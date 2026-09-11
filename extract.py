#!/usr/bin/env python3
"""extract.py — Fragmentation générique d'un PDF scientifique.

Objectif : produire une extraction BRUTE et traçable, sans chercher à
interpréter. L'interprétation (sections, résumé, storyboard...) est laissée
au LLM en aval.

Sorties (dossier `paper-processed/` par défaut) :
    text/full_text.md              texte dans l'ordre de lecture, avec
                                   marqueurs de page <!-- page N -->
    figures/<label>.png            une image par figure (nom = n° réel)
    captions/<label>.txt           légende associée
    tables/<label>.png             table rendue en image
    tables/<label>.md              table en texte brut (best effort)
    metadata/extraction.json       index complet (page, bbox, méthode...)

Dépendances : PyMuPDF, Pillow. Optionnel : pdfplumber (meilleures tables).

Usage :
    python extract.py [article.pdf] [--in input-pdf] [--out paper-processed] [--dpi 300]

Si le PDF n'est pas fourni, l'unique PDF de `input-pdf/` est utilisé.
"""

from __future__ import annotations

import argparse
import datetime as dt
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


def run(pdf: Path, out: Path, dpi: int) -> dict:
    for sub in ["text", "figures", "tables", "captions", "metadata"]:
        (out / sub).mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf)
    boilerplate = detect_boilerplate(doc)

    paragraphs: list[str] = []
    figures, tables, unlabeled = [], [], []
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

    (out / "text" / "full_text.md").write_text("\n\n".join(paragraphs) + "\n",
                                               encoding="utf-8")

    metadata = {
        "source_pdf": str(pdf.resolve()),
        "page_count": doc.page_count,
        "title": doc.metadata.get("title"),
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "engine": {"pymupdf": getattr(pymupdf, "__version__", "?"),
                   "pdfplumber": pdfplumber is not None},
        "text": "text/full_text.md",
        "figures": figures,
        "tables": tables,
        "unlabeled_images": unlabeled,
    }
    (out / "metadata" / "extraction.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return metadata


def find_pdf(indir: Path) -> Path:
    pdfs = sorted(indir.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"Aucun PDF dans {indir}/ — dépose un fichier .pdf ou passe son chemin.")
    if len(pdfs) > 1:
        names = ", ".join(p.name for p in pdfs)
        sys.exit(f"Plusieurs PDF dans {indir}/ : {names}\nPrécise lequel en argument.")
    return pdfs[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="Extraction générique PDF -> texte/figures/tables")
    ap.add_argument("pdf", type=Path, nargs="?", help="PDF source (défaut : unique PDF de --in)")
    ap.add_argument("--in", dest="indir", type=Path, default=Path("input-pdf"),
                    help="Dossier des PDF d'entrée")
    ap.add_argument("--out", type=Path, default=Path("paper-processed"))
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args()

    pdf = args.pdf if args.pdf is not None else find_pdf(args.indir)
    if not pdf.is_file():
        sys.exit(f"PDF introuvable : {pdf}")

    meta = run(pdf, args.out, args.dpi)
    print(f"texte    -> {args.out / 'text' / 'full_text.md'}")
    print(f"figures  -> {len(meta['figures'])}")
    print(f"tables   -> {len(meta['tables'])}")
    print(f"images non labellisées -> {len(meta['unlabeled_images'])}")
    print(f"index    -> {args.out / 'metadata' / 'extraction.json'}")


if __name__ == "__main__":
    main()
