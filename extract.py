#!/usr/bin/env python3
"""extract.py — Fragmentation générique d'un PDF scientifique.

Objectif : produire une extraction BRUTE et traçable, sans chercher à
interpréter. L'interprétation (sections, résumé, storyboard...) est laissée
au LLM en aval.

Chaque PDF est classé automatiquement « article » ou « non_article » :

- **article** (légendes « Figure N » / « Table N ») : figures et tables
  extraites et appariées à leur légende.
- **non_article** (diaporama, procédure, guideline…) : chaque page est rendue
  en image (`pages/page_NN.png`, auto-descriptif) et les images sans légende
  sont exportées dans `images/` avec un fichier de contexte (page + texte
  voisin).

Sorties (dossier `paper-processed/` par défaut) :

Un seul PDF (structure plate) :
    text/full_text.md              texte dans l'ordre de lecture, <!-- page N -->
    figures/<label>.png            figure appariée à une légende (article)
    captions/<label>.txt           légende associée
    tables/<label>.png             table rendue en image (article)
    tables/<label>.md              table en texte brut (best effort)
    pages/page_NN.png              rendu de page (non_article)
    images/<id>.png                image sans légende (non_article)
    images/<id>.txt                contexte de cette image (page + texte voisin)
    metadata/extraction.json       index complet (page, bbox, méthode, type…)

Un dossier de plusieurs PDF (structure multi-sources) :
    sources/<NN-slug>/…            une arborescence complète par PDF
    metadata/sources.json          index agrégé des sources (+ type détecté)

Dans les deux cas, `metadata/sources.json` liste chaque source avec son texte,
son type et ses visuels : c'est le point d'entrée pour l'étape LLM.

Dépendances : PyMuPDF, Pillow. Optionnel : pdfplumber (meilleures tables).

Usage :
    python extract.py [article.pdf | dossier/] [--in input-pdf]
                      [--out paper-processed] [--dpi 300]
                      [--kind auto|article|non_article] [--render-dpi 150]

Sans argument, les PDF de `input-pdf/` sont utilisés : un seul -> structure
plate, plusieurs -> structure multi-sources.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import re
import sys
from pathlib import Path

import pymupdf
from PIL import Image

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

# ---------------------------------------------------------------------------
# Réglages génériques (fractions de page, pas de coordonnées absolues)
# ---------------------------------------------------------------------------

TOP_BAND = 0.08        # marge haute : en-têtes
BOTTOM_BAND = 0.05     # marge basse : pieds de page
SIDE_BAND = 0.055      # marges latérales : filigranes / étiquettes
REPEAT_FRAC = 0.35     # texte répété sur >= 35% des pages = boilerplate
MIN_IMG_PX_W = 300     # filtre logos / puces
MIN_IMG_PX_H = 200
CAPTION_LOOKAHEAD = 0.45   # hauteur max (fraction de page) d'une figure/table
PAGE_BG_FRAC = 0.85        # image couvrant la page = fond (couverte par le rendu)
IMG_CONTEXT_CHARS = 240    # longueur du contexte textuel attaché à une image
ARTICLE_CAPTION_MIN = 2    # légendes numérotées min. pour classer « article »

FIGURE_RE = re.compile(r"^\s*(Figure|Fig\.?)\s+([A-Za-z]?\d+[A-Za-z]?)\b")
TABLE_RE = re.compile(r"^\s*(Table|Tab\.?)\s*\.?\s*([A-Za-z]?\d+[A-Za-z]?)?\b")


# ---------------------------------------------------------------------------
# Utilitaires texte
# ---------------------------------------------------------------------------

def clean(text: str) -> str:
    text = text.replace("\xad", "")
    text = "".join(ch if ch == "\n" or ch >= " " else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def norm_key(text: str) -> str:
    text = clean(text).lower()
    return re.sub(r"\d", "#", text)


def join_lines(lines: list[str]) -> str:
    """Recolle les lignes : \\xad = césure (sans espace), '-' = composé gardé."""
    out = ""
    prev_soft = prev_hard = False
    for raw in lines:
        stripped = raw.rstrip()
        line = clean(raw)
        if not line:
            continue
        if not out:
            out = line
        elif prev_soft:
            out += line
        elif prev_hard:
            out += line
        else:
            out += " " + line
        prev_soft = stripped.endswith("\xad")
        prev_hard = stripped.endswith("-")
    return out


def block_text(block: dict) -> str:
    return join_lines(
        "".join(sp["text"] for sp in ln["spans"]) for ln in block.get("lines", [])
    )


# ---------------------------------------------------------------------------
# Lecture des blocs et filtrage du boilerplate
# ---------------------------------------------------------------------------

def page_blocks(page) -> list[dict]:
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        text = block_text(b)
        if text:
            out.append({"bbox": tuple(b["bbox"]), "text": text, "raw": b})
    return out


def in_margin(bbox, w: float, h: float) -> bool:
    x0, y0, x1, y1 = bbox
    if y1 <= TOP_BAND * h or y0 >= (1 - BOTTOM_BAND) * h:
        return True
    if x1 <= SIDE_BAND * w or x0 >= (1 - SIDE_BAND) * w:
        return True
    return False


def detect_boilerplate(doc) -> set[str]:
    """Chaînes normalisées répétées dans les marges de nombreuses pages."""
    counts: dict[str, int] = {}
    for page in doc:
        w, h = page.rect.width, page.rect.height
        seen = set()
        for b in page_blocks(page):
            if not in_margin(b["bbox"], w, h):
                continue
            key = norm_key(b["text"])
            if len(key) >= 4 and key not in seen:
                counts[key] = counts.get(key, 0) + 1
                seen.add(key)
    threshold = max(2, int(REPEAT_FRAC * doc.page_count))
    return {k for k, c in counts.items() if c >= threshold}


def visible_blocks(page, boilerplate: set[str]) -> list[dict]:
    w, h = page.rect.width, page.rect.height
    out = []
    for b in page_blocks(page):
        if in_margin(b["bbox"], w, h):
            continue
        if norm_key(b["text"]) in boilerplate:
            continue
        out.append(b)
    return out


# ---------------------------------------------------------------------------
# Détection des colonnes + ordre de lecture
# ---------------------------------------------------------------------------

def detect_split(blocks: list[dict], w: float):
    """Renvoie l'abscisse de séparation des colonnes, ou None si 1 colonne.

    On cherche une bande verticale peu couverte au centre : tolérance de 1
    bloc traversant (titre centré, filet...)."""
    narrow = [b["bbox"] for b in blocks if (b["bbox"][2] - b["bbox"][0]) < 0.5 * w]
    if len(narrow) < 2:
        return None
    bins = int(w) + 2
    counts = [0] * bins
    for x0, _, x1, _ in narrow:
        for x in range(max(0, int(x0)), min(bins, int(x1) + 1)):
            counts[x] += 1
    lo, hi = int(0.25 * w), int(0.75 * w)
    best_w, best_x, run = 0, None, None
    for x in range(lo, hi):
        if counts[x] <= 1:
            run = x if run is None else run
        elif run is not None:
            if x - run > best_w:
                best_w, best_x = x - run, (run + x) // 2
            run = None
    if run is not None and hi - run > best_w:
        best_w, best_x = hi - run, (run + hi) // 2
    return best_x if best_w >= max(8.0, 0.018 * w) else None


def order_blocks(blocks: list[dict], split_x) -> list[dict]:
    if split_x is None:
        return merge_drop_caps(
            sorted(blocks, key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))
        )

    def crosses(b):
        x0, _, x1, _ = b["bbox"]
        return x0 < split_x < x1

    def center(b):
        return (b["bbox"][0] + b["bbox"][2]) / 2

    full = sorted([b for b in blocks if crosses(b)], key=lambda b: b["bbox"][1])
    cols = [b for b in blocks if not crosses(b)]
    ordered: list[dict] = []
    used: set[int] = set()

    def flush(upto_y):
        band = [c for c in cols if id(c) not in used and c["bbox"][1] < upto_y]
        left = sorted([c for c in band if center(c) < split_x], key=lambda c: c["bbox"][1])
        right = sorted([c for c in band if center(c) >= split_x], key=lambda c: c["bbox"][1])
        for c in left + right:
            used.add(id(c))
            ordered.append(c)

    for f in full:
        flush(f["bbox"][1])
        used.add(id(f))
        ordered.append(f)
    flush(float("inf"))
    return merge_drop_caps(ordered)


def merge_drop_caps(blocks: list[dict]) -> list[dict]:
    """Recolle une lettrine isolée (ex. 'T') avec le paragraphe suivant."""
    out: list[dict] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if (
            re.fullmatch(r"[A-Z]", b["text"].strip())
            and i + 1 < len(blocks)
            and blocks[i + 1]["text"][:1].islower()
        ):
            nxt = dict(blocks[i + 1])
            nxt["text"] = b["text"].strip() + nxt["text"]
            out.append(nxt)
            i += 2
            continue
        out.append(b)
        i += 1
    return out


# ---------------------------------------------------------------------------
# Classification article / non-article (déterministe, sans LLM)
# ---------------------------------------------------------------------------

def classify(doc) -> tuple[str, str]:
    """Classe un PDF en « article » ou « non_article » (et motive le choix).

    Signaux : légendes numérotées « Figure N » / « Table N », structure
    d'article (abstract / references), format des pages (diaporama).
    """
    fig = tbl = 0
    landscape = 0
    texts: list[str] = []
    for page in doc:
        w, h = page.rect.width, page.rect.height
        if w > h:
            landscape += 1
        for b in page_blocks(page):
            t = b["text"]
            texts.append(t)
            if FIGURE_RE.match(t):
                fig += 1
            if TABLE_RE.match(t):
                tbl += 1

    text = " ".join(texts).lower()
    captions = fig + tbl
    has_abstract = "abstract" in text
    has_refs = ("references" in text or "bibliograph" in text
                or "références" in text)
    landscape_frac = landscape / doc.page_count if doc.page_count else 0.0

    if captions >= ARTICLE_CAPTION_MIN:
        return "article", f"{captions} légende(s) numérotée(s)"
    if captions >= 1 and has_abstract and has_refs:
        return "article", f"{captions} légende(s) + structure d'article"
    if captions == 0 and landscape_frac >= 0.6:
        return "non_article", "format diaporama, aucune légende numérotée"
    return "non_article", f"{captions} légende(s), pas de structure d'article"


# ---------------------------------------------------------------------------
# Détection et extraction des figures
# ---------------------------------------------------------------------------

def large_images(page) -> list[dict]:
    out = []
    for im in page.get_images(full=True):
        xref, wpx, hpx = im[0], im[2], im[3]
        if wpx < MIN_IMG_PX_W or hpx < MIN_IMG_PX_H:
            continue
        try:
            bbox = tuple(page.get_image_bbox(im))
        except Exception:
            continue
        out.append({"xref": xref, "bbox": bbox, "wpx": wpx, "hpx": hpx})
    return out


def drawing_rects(page) -> list[tuple]:
    rects = []
    for d in page.get_drawings():
        r = d.get("rect")
        if r is not None and r.width > 1 and r.height > 1:
            rects.append(tuple(r))
    return rects


def rect_distance(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    dx = max(ax0 - bx1, bx0 - ax1, 0)
    dy = max(ay0 - by1, by0 - ay1, 0)
    return (dx * dx + dy * dy) ** 0.5


def save_native(doc, xref: int, dest: Path) -> tuple[int, int]:
    info = doc.extract_image(xref)
    img = Image.open(io.BytesIO(info["image"]))
    img.save(dest, "PNG")
    return img.width, img.height


def save_crop(page, clip, dest: Path, dpi: int) -> tuple[int, int]:
    pix = page.get_pixmap(clip=pymupdf.Rect(clip), dpi=dpi)
    pix.save(dest)
    return pix.width, pix.height


def match_caption(text: str, kind: str):
    """Retourne (label, texte) si le bloc est une légende, sinon None."""
    rx = FIGURE_RE if kind == "figure" else TABLE_RE
    m = rx.match(text)
    if not m:
        return None
    label = m.group(2)
    rest = text[m.end():]
    if rest[:1].islower():
        return None
    return label, text


# ---------------------------------------------------------------------------
# Documents non-article : rendus de page + images non légendées avec contexte
# ---------------------------------------------------------------------------

def save_page(page, dest: Path, dpi: int) -> tuple[int, int]:
    """Rend une page entière en PNG (auto-descriptif pour un diaporama)."""
    pix = page.get_pixmap(dpi=dpi)
    pix.save(dest)
    return pix.width, pix.height


def nearest_context(blocks: list[dict], bbox) -> str:
    """Texte du bloc le plus proche d'une image (pseudo-légende par proximité)."""
    if not blocks:
        return ""
    block = min(blocks, key=lambda b: rect_distance(b["bbox"], bbox))
    return clean(block["text"])[:IMG_CONTEXT_CHARS]


def export_uncaptioned_images(
    doc, page, page_no: int, out: Path,
    used_hashes: set[str], used_names: dict[str, int], blocks: list[dict],
) -> list[dict]:
    """Exporte les images sans légende, dédoublonnées, avec un fichier contexte."""
    page_area = page.rect.width * page.rect.height
    exported: list[dict] = []
    page_title = clean(blocks[0]["text"]) if blocks else ""
    for im in large_images(page):
        x0, y0, x1, y1 = im["bbox"]
        if page_area and (x1 - x0) * (y1 - y0) > PAGE_BG_FRAC * page_area:
            continue  # image de fond : déjà couverte par le rendu de page
        info = doc.extract_image(im["xref"])
        digest = hashlib.md5(info["image"]).hexdigest()
        if digest in used_hashes:
            continue
        used_hashes.add(digest)

        name = unique_name(f"p{page_no:02d}-image", used_names)
        img_path = out / "images" / f"{name}.png"
        pw, ph = save_native(doc, im["xref"], img_path)
        context = nearest_context(blocks, im["bbox"])
        ctx_path = out / "images" / f"{name}.txt"
        ctx_path.write_text(
            f"Source : page {page_no}\n"
            f"Titre de page : {page_title}\n"
            f"Contexte : {context}\n",
            encoding="utf-8",
        )
        exported.append({
            "id": name,
            "page": page_no,
            "method": "native_image",
            "image": str(img_path.relative_to(out)),
            "context_file": str(ctx_path.relative_to(out)),
            "context": context,
            "page_title": page_title,
            "pixel_size": [pw, ph],
            "source_bbox": [round(v, 2) for v in im["bbox"]],
        })
    return exported


# ---------------------------------------------------------------------------
# Région d'une table (image + texte)
# ---------------------------------------------------------------------------

def table_region(page, cap_bbox, w: float, h: float, blocks: list[dict]):
    cap = pymupdf.Rect(cap_bbox)
    rects = drawing_rects(page)
    texts = [b["bbox"] for b in blocks if b["bbox"][1] > cap.y1 - 4]

    def horiz_overlap(r):
        return r[2] > SIDE_BAND * w and r[0] < (1 - SIDE_BAND) * w

    below = [r for r in rects if r[1] >= cap.y1 - 6]
    above = [r for r in rects if r[3] <= cap.y0 + 6]
    elements = below if sum((r[2]-r[0])*(r[3]-r[1]) for r in below) >= \
        sum((r[2]-r[0])*(r[3]-r[1]) for r in above) else above

    region = pymupdf.Rect(cap)
    pool = sorted(elements + [t for t in texts if horiz_overlap(t)],
                  key=lambda r: abs(r[1] - cap.y1))
    for r in pool:
        rr = pymupdf.Rect(r)
        if rr.y0 - region.y1 > 0.04 * h or region.y0 - rr.y1 > 0.04 * h:
            continue
        if not horiz_overlap(r):
            continue
        region |= rr
    return tuple(region)


def table_text(page, region) -> str:
    rows: dict[int, list[tuple[float, str]]] = {}
    data = page.get_text("dict", clip=pymupdf.Rect(region))
    for block in data["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            txt = clean("".join(sp["text"] for sp in line["spans"]))
            if not txt:
                continue
            rows.setdefault(round(line["bbox"][1] / 3), []).append((line["bbox"][0], txt))
    out = []
    for y in sorted(rows):
        cells = [t for _, t in sorted(rows[y])]
        out.append(" | ".join(cells))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Pipeline d'extraction
# ---------------------------------------------------------------------------

def unique_name(base: str, used: dict[str, int]) -> str:
    used[base] = used.get(base, 0) + 1
    return base if used[base] == 1 else f"{base}_{used[base]}"


def safe_slug(text: str) -> str:
    """Slug lisible et sûr pour un nom de dossier de source."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._")
    return (slug[:60] or "source").lower()


def resolve_sources(explicit: Path | None, indir: Path) -> tuple[list[Path], bool]:
    """Détermine les PDF à traiter et le mode d'organisation.

    Renvoie `(pdfs, multi)` : `multi=True` -> une arborescence par source sous
    `sources/`, `multi=False` -> structure plate (un seul PDF).
    """
    if explicit is not None:
        if explicit.is_dir():
            pdfs = sorted(explicit.glob("*.pdf"))
            if not pdfs:
                sys.exit(f"Aucun PDF dans {explicit}/ — dépose des fichiers .pdf.")
            return pdfs, True
        if explicit.is_file():
            return [explicit], False
        sys.exit(f"Chemin introuvable : {explicit}")

    pdfs = sorted(indir.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"Aucun PDF dans {indir}/ — dépose un fichier .pdf ou passe son chemin.")
    return pdfs, len(pdfs) > 1


def source_entry(meta: dict, pdf: Path, sid: str, sdir_rel: str) -> dict:
    """Entrée d'index pour `metadata/sources.json` (chemins posix relatifs)."""
    def rel(name: str) -> str:
        return f"{sdir_rel}/{name}" if sdir_rel else name

    entry = {
        "id": sid,
        "pdf": meta.get("source_pdf") or str(pdf.resolve()),
        "filename": pdf.name,
        "title": meta.get("title") or pdf.stem,
        "page_count": meta.get("page_count"),
        "kind": meta.get("kind", "article"),
        "dir": sdir_rel,
        "text": rel("text/full_text.md"),
        "metadata": rel("metadata/extraction.json"),
        "figures": len(meta.get("figures", [])),
        "tables": len(meta.get("tables", [])),
    }
    if meta.get("kind_reason"):
        entry["kind_reason"] = meta["kind_reason"]
    n_pages = len(meta.get("pages", []))
    n_images = len(meta.get("images", []))
    if n_pages:
        entry["pages_dir"] = rel("pages")
        entry["pages_count"] = n_pages
    if n_images:
        entry["images_dir"] = rel("images")
        entry["images_count"] = n_images
    return entry


def write_sources_index(out: Path, entries: list[dict]) -> None:
    (out / "metadata").mkdir(parents=True, exist_ok=True)
    index = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source_count": len(entries),
        "sources": entries,
    }
    (out / "metadata" / "sources.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )



def run(pdf: Path, out: Path, dpi: int, render_dpi: int = 150,
        forced_kind: str = "auto") -> dict:
    for sub in ["text", "figures", "tables", "captions", "metadata",
                "pages", "images"]:
        (out / sub).mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf)
    kind, kind_reason = (classify(doc) if forced_kind == "auto"
                         else (forced_kind, "forcé"))
    boilerplate = detect_boilerplate(doc)

    paragraphs: list[str] = []
    figures, tables, unlabeled = [], [], []
    pages_meta, images_meta = [], []
    used_hashes: set[str] = set()
    used_names: dict[str, int] = {}
    fig_n = tbl_n = 0

    for page_no, page in enumerate(doc, start=1):
        w, h = page.rect.width, page.rect.height
        blocks = visible_blocks(page, boilerplate)
        split = detect_split(blocks, w)
        ordered = order_blocks(blocks, split)

        paragraphs.append(f"<!-- page {page_no} -->")
        for b in ordered:
            paragraphs.append(b["text"])

        images = large_images(page)
        caps_fig, caps_tbl = [], []
        for b in ordered:
            hit_f = match_caption(b["text"], "figure")
            hit_t = match_caption(b["text"], "table")
            if hit_f:
                caps_fig.append((hit_f[0], b))
            elif hit_t:
                caps_tbl.append((hit_t[0], b))

        used_images: set[int] = set()
        for label, b in caps_fig:
            fig_n += 1
            base = f"figure_{label}" if label else f"figure_{fig_n}"
            name = unique_name(base, used_names)
            cap_path = out / "captions" / f"{name}.txt"
            cap_path.write_text(b["text"] + "\n", encoding="utf-8")
            entry = {
                "id": name,
                "label": f"Figure {label}" if label else "Figure",
                "page": page_no,
                "caption": b["text"],
                "caption_file": str(cap_path.relative_to(out)),
                "caption_bbox": [round(v, 2) for v in b["bbox"]],
            }
            candidates = [im for im in images if id(im) not in used_images]
            chosen = min(candidates, key=lambda im: rect_distance(im["bbox"], b["bbox"])) \
                if candidates else None
            img_path = out / "figures" / f"{name}.png"
            if chosen is not None:
                used_images.add(id(chosen))
                pw, ph = save_native(doc, chosen["xref"], img_path)
                entry.update({
                    "method": "native_image",
                    "image": str(img_path.relative_to(out)),
                    "pixel_size": [pw, ph],
                    "source_bbox": [round(v, 2) for v in chosen["bbox"]],
                })
            else:
                clip = (SIDE_BAND * w, max(0.0, b["bbox"][1] - CAPTION_LOOKAHEAD * h),
                        (1 - SIDE_BAND) * w, b["bbox"][1] - 2)
                pw, ph = save_crop(page, clip, img_path, dpi)
                entry.update({
                    "method": "page_crop",
                    "image": str(img_path.relative_to(out)),
                    "pixel_size": [pw, ph],
                    "source_bbox": [round(v, 2) for v in clip],
                })
            figures.append(entry)

        for label, b in caps_tbl:
            tbl_n += 1
            base = f"table_{label}" if label else f"table_{tbl_n}"
            name = unique_name(base, used_names)
            cap_path = out / "captions" / f"{name}.txt"
            cap_path.write_text(b["text"] + "\n", encoding="utf-8")
            region = table_region(page, b["bbox"], w, h, blocks)
            img_path = out / "tables" / f"{name}.png"
            txt_path = out / "tables" / f"{name}.md"
            pw, ph = save_crop(page, region, img_path, dpi)
            txt_path.write_text(table_text(page, region) + "\n", encoding="utf-8")
            tables.append({
                "id": name,
                "label": f"Table {label}" if label else "Table",
                "page": page_no,
                "method": "region_crop",
                "image": str(img_path.relative_to(out)),
                "text_file": str(txt_path.relative_to(out)),
                "pixel_size": [pw, ph],
                "source_bbox": [round(v, 2) for v in region],
                "caption": b["text"],
                "caption_file": str(cap_path.relative_to(out)),
            })

        for im in images:
            if id(im) in used_images:
                continue
            unlabeled.append({
                "page": page_no,
                "xref": im["xref"],
                "bbox": [round(v, 2) for v in im["bbox"]],
                "pixel_size": [im["wpx"], im["hpx"]],
            })

        if kind == "non_article":
            pg_path = out / "pages" / f"page_{page_no:02d}.png"
            pw, ph = save_page(page, pg_path, render_dpi)
            pages_meta.append({
                "page": page_no,
                "image": str(pg_path.relative_to(out)),
                "pixel_size": [pw, ph],
            })
            images_meta.extend(export_uncaptioned_images(
                doc, page, page_no, out, used_hashes, used_names, ordered
            ))

    (out / "text" / "full_text.md").write_text("\n\n".join(paragraphs) + "\n",
                                               encoding="utf-8")

    metadata = {
        "source_pdf": str(pdf.resolve()),
        "page_count": doc.page_count,
        "title": doc.metadata.get("title"),
        "kind": kind,
        "kind_reason": kind_reason,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "engine": {"pymupdf": getattr(pymupdf, "__version__", "?"),
                   "pdfplumber": pdfplumber is not None},
        "text": "text/full_text.md",
        "figures": figures,
        "tables": tables,
        "pages": pages_meta,
        "images": images_meta,
        "unlabeled_images": unlabeled,
    }
    (out / "metadata" / "extraction.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extraction générique PDF -> texte/figures/tables "
                    "(un PDF, ou un dossier de PDF en multi-sources)"
    )
    ap.add_argument("pdf", type=Path, nargs="?",
                    help="PDF source ou dossier de PDF (défaut : --in)")
    ap.add_argument("--in", dest="indir", type=Path, default=Path("input-pdf"),
                    help="Dossier des PDF d'entrée")
    ap.add_argument("--out", type=Path, default=Path("paper-processed"))
    ap.add_argument("--dpi", type=int, default=300,
                    help="résolution des recadrages de figure/table (défaut 300)")
    ap.add_argument("--render-dpi", type=int, default=150,
                    help="résolution des rendus de page pour les documents "
                         "non-article (défaut 150)")
    ap.add_argument("--kind", choices=["auto", "article", "non_article"],
                    default="auto",
                    help="type de document ; « auto » détecte par PDF (défaut)")
    args = ap.parse_args()

    sources, multi = resolve_sources(args.pdf, args.indir)
    args.out.mkdir(parents=True, exist_ok=True)

    entries = []
    for i, pdf in enumerate(sources, start=1):
        if multi:
            sid = f"{i:02d}-{safe_slug(pdf.stem)}"
            sdir = args.out / "sources" / sid
            sdir_rel = f"sources/{sid}"
        else:
            sid = safe_slug(pdf.stem)
            sdir = args.out
            sdir_rel = ""
        meta = run(pdf, sdir, args.dpi, args.render_dpi, args.kind)
        entries.append(source_entry(meta, pdf, sid, sdir_rel))

    write_sources_index(args.out, entries)

    if multi:
        print(f"sources  -> {len(entries)}")
        for e in entries:
            extra = ""
            if e.get("pages_count"):
                extra += f", {e['pages_count']} rendus de page"
            if e.get("images_count"):
                extra += f", {e['images_count']} images"
            print(f"  - {e['filename']} [{e['kind']}] : {e['figures']} figures, "
                  f"{e['tables']} tables{extra}, {e['page_count']} p. -> {e['dir']}/")
    else:
        meta = entries[0]
        print(f"type     -> {meta['kind']} ({meta.get('kind_reason', '')})")
        print(f"texte    -> {args.out / 'text' / 'full_text.md'}")
        print(f"figures  -> {meta['figures']}")
        print(f"tables   -> {meta['tables']}")
        if meta.get("pages_count"):
            print(f"pages    -> {meta['pages_count']} rendus de page")
        if meta.get("images_count"):
            print(f"images   -> {meta['images_count']} images non légendées")
    print(f"index    -> {args.out / 'metadata' / 'sources.json'}")


if __name__ == "__main__":
    main()
