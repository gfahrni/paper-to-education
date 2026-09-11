#!/usr/bin/env python3
"""build_pptx.py — Étape 2b : storyboard.json -> presentation.pptx.

Lit `llm-output/storyboard.json` (produit par `llm-process.py`) et génère un
PowerPoint 16:9. Chaque slide reçoit son titre, ses puces, son éventuelle image
(chemin résolu depuis la racine du projet) et son voiceover en notes du
présentateur.

Avec `--audio`, un fichier audio TTS est généré depuis le voiceover de chaque
slide et intégré au PPT en **lecture automatique** : en diaporama, avancer ou
reculer déclenche le voiceover de la slide affichée.

Le TTS utilise `say` (macOS, gratuit, hors-ligne) puis `ffmpeg` pour convertir
en mp3. Le placement de l'icône audio est hors-écran.

Usage :
    python build_pptx.py [--in llm-output] [--out llm-output/presentation.pptx]
                         [--audio] [--voice Thomas] [--rate 180]
                         [--audio-dir llm-output/audio] [--keep-audio]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
ACCENT = RGBColor(0x1F, 0x3A, 0x5F)
GREY = RGBColor(0x44, 0x44, 0x44)


def load_storyboard(path: Path) -> dict:
    text = path.read_text(encoding="utf-8").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Voiceover TTS + lecture automatique
# ---------------------------------------------------------------------------

def synthesize(text: str, dest: Path, voice: str, rate: int) -> Path | None:
    """Génère `dest` (mp3) depuis `text` via `say` + `ffmpeg`."""
    if not text.strip():
        return None
    if not shutil.which("say"):
        raise SystemExit("TTS indisponible : la commande macOS 'say' est requise.")
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg est requis pour convertir l'audio en mp3.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        aiff = Path(tmp) / "vo.aiff"
        subprocess.run(
            ["say", "-v", voice, "-r", str(rate), "-o", str(aiff), text], check=True
        )
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
             "-ac", "1", "-b:a", "64k", str(dest)],
            check=True,
        )
    return dest


def set_autoplay(shape) -> None:
    """Passe le média de la forme en lecture automatique (delay=0).

    Voir https://github.com/scanny/python-pptx/issues/427 — python-pptx
    n'expose pas ce réglage, on édite le nœud de timing.
    """
    pic = shape._element
    cNvPr = pic.find(".//" + qn("p:cNvPr"))
    if cNvPr is None:
        return
    spid = cNvPr.get("id")
    root = pic.getroottree().getroot()
    for tgt in root.iter(qn("p:spTgt")):
        if tgt.get("spid") != spid:
            continue
        cmedia = tgt.getparent().getparent()
        cond = cmedia.find(".//" + qn("p:cond"))
        if cond is not None:
            cond.set("delay", "0")
        return


def embed_audio(slide, mp3: Path) -> None:
    shape = slide.shapes.add_movie(
        str(mp3), Inches(-2), Inches(0), Inches(1), Inches(1), mime_type="audio/mpeg"
    )
    set_autoplay(shape)


# ---------------------------------------------------------------------------
# Rendu des slides
# ---------------------------------------------------------------------------

def add_title(slide, text: str) -> None:
    box = slide.shapes.add_textbox(Inches(0.6), Inches(0.35), SLIDE_W - Inches(1.2), Inches(0.9))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = text
    run.font.size = Pt(30)
    run.font.bold = True
    run.font.color.rgb = ACCENT
    line = slide.shapes.add_shape(1, Inches(0.6), Inches(1.18), SLIDE_W - Inches(1.2), Pt(2))
    line.fill.solid()
    line.fill.fore_color.rgb = ACCENT
    line.line.fill.background()


def add_bullets(slide, bullets: list[str], left, top, width, height, size: int) -> None:
    if not bullets:
        return
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    for i, b in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(10)
        run = p.add_run()
        run.text = f"•  {b}"
        run.font.size = Pt(size)
        run.font.color.rgb = GREY


def add_image(slide, img_path: Path, left, top, max_w, max_h) -> bool:
    if not img_path.is_file():
        print(f"  image introuvable, ignorée : {img_path}")
        return False
    with Image.open(img_path) as im:
        ratio = im.width / im.height
    w, h = max_w, int(max_w / ratio)
    if h > max_h:
        h, w = max_h, int(max_h * ratio)
    slide.shapes.add_picture(
        str(img_path), int(left + (max_w - w) / 2), int(top + (max_h - h) / 2), width=w, height=h
    )
    return True


def add_caption(slide, text: str, left, top, width) -> None:
    box = slide.shapes.add_textbox(left, top, width, Inches(0.6))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = text
    run.font.size = Pt(12)
    run.font.italic = True
    run.font.color.rgb = GREY


def add_notes(slide, voiceover: str) -> None:
    if voiceover:
        slide.notes_slide.notes_text_frame.text = voiceover


def build(data: dict, out_path: Path, root: Path, audio_cfg: dict | None = None) -> int:
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    blank = prs.slide_layouts[6]

    slides = data.get("slides", [])
    for i, s in enumerate(slides, start=1):
        layout = s.get("layout", "content")
        slide = prs.slides.add_slide(blank)

        if layout == "title":
            box = slide.shapes.add_textbox(Inches(0.8), Inches(2.4), SLIDE_W - Inches(1.6), Inches(1.6))
            tf = box.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            run = p.add_run()
            run.text = s.get("title", "")
            run.font.size = Pt(40)
            run.font.bold = True
            run.font.color.rgb = ACCENT
            sub = slide.shapes.add_textbox(Inches(0.8), Inches(4.1), SLIDE_W - Inches(1.6), Inches(1.4))
            stf = sub.text_frame
            stf.word_wrap = True
            for j, line in enumerate([data.get("source"), data.get("audience")]):
                if not line:
                    continue
                p = stf.paragraphs[0] if j == 0 else stf.add_paragraph()
                p.alignment = PP_ALIGN.CENTER
                r = p.add_run()
                r.text = line
                r.font.size = Pt(18)
                r.font.color.rgb = GREY
        else:
            add_title(slide, s.get("title", ""))
            bullets = s.get("bullets") or []
            image = s.get("image")
            if image:
                add_bullets(
                    slide, bullets, Inches(0.6), Inches(1.6), Inches(5.6), Inches(5.2),
                    size=16 if len(bullets) > 5 else 18,
                )
                add_image(slide, root / image, Inches(6.5), Inches(1.5), Inches(6.3), Inches(5.0))
                if s.get("image_caption"):
                    add_caption(slide, s["image_caption"], Inches(6.5), Inches(6.6), Inches(6.3))
            else:
                add_bullets(
                    slide, bullets, Inches(0.8), Inches(1.6), SLIDE_W - Inches(1.6), Inches(5.2),
                    size=18 if len(bullets) <= 6 else 15,
                )

        voiceover = s.get("voiceover", "")
        add_notes(slide, voiceover)

        if audio_cfg and voiceover:
            mp3 = audio_cfg["dir"] / f"slide_{i:02d}.mp3"
            if audio_cfg.get("keep") and mp3.is_file():
                pass
            else:
                print(f"  TTS slide {i}…")
                synthesize(voiceover, mp3, audio_cfg["voice"], audio_cfg["rate"])
            if mp3.is_file():
                embed_audio(slide, mp3)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    return len(slides)


def main() -> None:
    ap = argparse.ArgumentParser(description="storyboard.json -> presentation.pptx")
    ap.add_argument("--in", dest="indir", type=Path, default=Path("llm-output"))
    ap.add_argument("--out", dest="outfile", type=Path, default=None)
    ap.add_argument("--audio", action="store_true",
                    help="génère un voiceover TTS par slide en lecture automatique")
    ap.add_argument("--voice", default="Thomas", help="voix TTS macOS (say -v)")
    ap.add_argument("--rate", type=int, default=180, help="débit TTS (mots/minute)")
    ap.add_argument("--audio-dir", type=Path, default=None,
                    help="dossier des mp3 (défaut : <in>/audio)")
    ap.add_argument("--keep-audio", action="store_true",
                    help="réutilise les mp3 existants au lieu de les régénérer")
    args = ap.parse_args()

    root = Path.cwd()
    indir = args.indir if args.indir.is_absolute() else root / args.indir
    storyboard = indir / "storyboard.json"
    if not storyboard.is_file():
        raise SystemExit(f"Introuvable : {storyboard}")

    data = load_storyboard(storyboard)
    outfile = args.outfile or (indir / "presentation.pptx")
    if not outfile.is_absolute():
        outfile = root / outfile

    audio_cfg = None
    if args.audio:
        audio_dir = args.audio_dir or (indir / "audio")
        if not audio_dir.is_absolute():
            audio_dir = root / audio_dir
        audio_cfg = {
            "dir": audio_dir,
            "voice": args.voice,
            "rate": args.rate,
            "keep": args.keep_audio,
        }

    n = build(data, outfile, root, audio_cfg)
    print(f"{n} slides -> {outfile}")
    if audio_cfg:
        print(f"voiceover -> {audio_cfg['dir']} (lecture automatique intégrée)")


if __name__ == "__main__":
    main()
