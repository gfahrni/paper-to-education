#!/usr/bin/env python3
"""build_pptx.py — Étape 2b : storyboard.json -> presentation.pptx.

Lit `llm-output/storyboard.json` (produit par `llm-process.py`) et génère un
PowerPoint 16:9. Chaque slide reçoit son titre, ses puces, son éventuelle image
(chemin résolu depuis la racine du projet) et son voiceover en notes du
présentateur.

Avec `--audio`, un fichier audio TTS est généré depuis le voiceover de chaque
slide et intégré au PPT en **lecture automatique** : en diaporama, avancer ou
reculer déclenche le voiceover de la slide affichée.

Moteurs TTS (`--tts`) :

- `say` (défaut) : commande macOS, gratuit et hors-ligne, puis `ffmpeg` pour
  convertir en mp3. Voix via `--voice` (ex. `Thomas`, `Amélie`).
- `mlx` : serveur TTS local compatible OpenAI (`mlx_audio.server`), gratuit et
  hors-ligne. Modèle via `--tts-model`, voix via `--voice`, langue via
  `--tts-lang`, URL via `--tts-url`. Ex. Voxtral FR : `--tts mlx
  --tts-model mlx-community/Voxtral-4B-TTS-2603-mlx-bf16 --voice fr_female`.
  `--serve-tts` démarre/arrête le serveur local si nécessaire.

Usage :
    python build_pptx.py [--in llm-output] [--out llm-output/presentation.pptx]
                         [--audio] [--tts say|mlx] [--voice Thomas]
                         [--speed 1.0] [--rate 180]
                         [--audio-dir llm-output/audio]
                         [--keep-audio] [--tts-config tts.json] [--serve-tts]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
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

SAY_VOICE = "Thomas"
LOCAL_TTS_URL = "http://127.0.0.1:8000/v1/audio/speech"
LOCAL_TTS_MODEL = "mlx-community/Voxtral-4B-TTS-2603-mlx-bf16"
LOCAL_TTS_VOICE = "fr_female"
LOCAL_TTS_LANG = "fr"
TTS_CONFIG_DEFAULT = Path("tts.json")
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
SERVER_COMMAND = ["mlx_audio.server", "--host", "{host}", "--port", "{port}"]
SERVER_STARTUP_TIMEOUT = 180


def load_storyboard(path: Path) -> dict:
    text = path.read_text(encoding="utf-8").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Voiceover TTS + lecture automatique
# ---------------------------------------------------------------------------

def synthesize_say(text: str, dest: Path, voice: str, rate: int) -> Path | None:
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


def synthesize_mlx(
    text: str, dest: Path, url: str, voice: str, model_id: str, lang_code: str
) -> Path | None:
    """Génère `dest` (mp3) via un serveur TTS local compatible OpenAI (mlx-audio)."""
    if not text.strip():
        return None
    payload = {
        "model": model_id,
        "input": text,
        "voice": voice,
        "lang_code": lang_code,
        "response_format": "mp3",
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"TTS local HTTP {exc.code} : {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Serveur TTS local injoignable ({url}) : {exc.reason}\n"
            "Démarre-le, ex. : mlx_audio.server --host 127.0.0.1 --port 8000"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(audio)
    return dest


def synthesize(text: str, dest: Path, cfg: dict) -> Path | None:
    """Dispatch TTS selon `cfg['tts']`."""
    if not text.strip():
        return None
    if cfg["tts"] == "mlx":
        return synthesize_mlx(
            text, dest, cfg["url"], cfg["voice"], cfg["model_id"], cfg["lang"]
        )
    return synthesize_say(text, dest, cfg["voice"], cfg["rate"])


# ---------------------------------------------------------------------------
# Cycle de vie du serveur TTS local (mlx_audio.server)
# ---------------------------------------------------------------------------

def load_tts_config(path: Path) -> dict:
    """Lit la config du serveur TTS local (tts.json), sans échouer si absent."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"Config TTS invalide ({path}) : {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"Config TTS invalide ({path}) : objet JSON attendu.")
    return data


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Vrai si un serveur écoute déjà sur host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_server(host: str, port: int, timeout: int, proc) -> bool:
    """Attend que le port s'ouvre ; abandonne si le process meurt."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open(host, port):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.5)
    return False


def start_local_server(
    host: str, port: int, command: list[str], timeout: int, log_path: Path
):
    """Démarre le serveur TTS local et attend qu'il écoute. Renvoie le Popen."""
    exe = shutil.which(command[0])
    if not exe:
        raise SystemExit(
            f"Commande TTS introuvable : « {command[0]} ».\n"
            "Installe-le : uv tool install --force 'mlx-audio[server,tts]' "
            "--with misaki --with phonemizer-fork --with espeakng-loader"
        )
    argv = [exe] + [a.format(host=host, port=port) for a in command[1:]]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    print(f"  démarrage du serveur TTS : {' '.join(argv)}")
    try:
        proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
    except OSError as exc:
        log.close()
        raise SystemExit(f"Échec du démarrage du serveur TTS : {exc}")
    if not wait_for_server(host, port, timeout, proc):
        stop_local_server(proc)
        raise SystemExit(
            f"Le serveur TTS n'écoute pas sur {host}:{port} après {timeout}s.\n"
            f"Voir le log : {log_path}"
        )
    return proc


def stop_local_server(proc) -> None:
    """Arrête proprement le serveur TTS lancé par le script."""
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def atempo_filter(speed: float) -> str:
    """Filtres ffmpeg atempo pour une vitesse arbitraire (hauteur conservée)."""
    parts = []
    s = speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def apply_speed(path: Path, speed: float) -> None:
    """Accélère/ralentit un mp3 sans changer la voix (ffmpeg atempo)."""
    if abs(speed - 1.0) < 1e-3:
        return
    if not shutil.which("ffmpeg"):
        print("  ffmpeg absent : vitesse non appliquée.")
        return
    tmp = path.with_name(path.stem + ".speed" + path.suffix)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
         "-filter:a", atempo_filter(speed), "-b:a", "128k", str(tmp)],
        check=True,
    )
    tmp.replace(path)


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


def audio_duration_ms(path: Path) -> int | None:
    """Durée d'un mp3 en millisecondes via ffprobe (None si indisponible)."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return int(float(out) * 1000)
    except (subprocess.CalledProcessError, ValueError):
        return None


def set_advance_after(slide, ms: int) -> None:
    """Pose « avancer après N ms » sur la slide (transition p:transition/advTm).

    python-pptx n'expose pas les transitions ; on insère l'élément au bon
    endroit du XML (après cSld/clrMapOvr, avant p:timing).
    """
    sld = slide._element
    for old in sld.findall(qn("p:transition")):
        sld.remove(old)
    transition = sld.makeelement(qn("p:transition"), {})
    transition.set("advTm", str(int(ms)))
    transition.set("advClick", "1")
    timing = sld.find(qn("p:timing"))
    if timing is not None:
        timing.addprevious(transition)
    else:
        sld.append(transition)


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
                print(f"  TTS slide {i} ({audio_cfg['tts']})…")
                if synthesize(voiceover, mp3, audio_cfg):
                    apply_speed(mp3, audio_cfg["speed"])
            if mp3.is_file():
                embed_audio(slide, mp3)
                if audio_cfg.get("advance"):
                    ms = audio_duration_ms(mp3)
                    if ms:
                        set_advance_after(slide, ms + audio_cfg.get("advance_buffer", 600))
                    else:
                        print("  durée audio illisible (ffprobe manquant ?) : avance auto ignorée.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    return len(slides)


def main() -> None:
    ap = argparse.ArgumentParser(description="storyboard.json -> presentation.pptx")
    ap.add_argument("--in", dest="indir", type=Path, default=Path("llm-output"))
    ap.add_argument("--out", dest="outfile", type=Path, default=None)
    ap.add_argument("--audio", action="store_true",
                    help="génère un voiceover TTS par slide en lecture automatique")
    ap.add_argument("--tts", choices=["say", "mlx"], default="say",
                    help="moteur TTS (défaut : say macOS)")
    ap.add_argument("--voice", default=None,
                    help="voix : voix macOS (--tts say) ou voix du serveur local "
                         "(--tts mlx, ex. fr_female)")
    ap.add_argument("--tts-model", default=None,
                    help="id Hugging Face du modèle TTS local (--tts mlx)")
    ap.add_argument("--tts-url", default=None,
                    help="URL du serveur TTS local compatible OpenAI (--tts mlx)")
    ap.add_argument("--tts-lang", default=None,
                    help="code langue du serveur local (--tts mlx, ex. fr)")
    ap.add_argument("--tts-config", type=Path, default=TTS_CONFIG_DEFAULT,
                    help="config du serveur TTS local (défaut : tts.json)")
    ap.add_argument("--serve-tts", action="store_true",
                    help="avec --tts mlx : démarre le serveur local s'il est absent "
                         "et l'arrête à la fin (un serveur déjà lancé est conservé)")
    ap.add_argument("--serve-tts-timeout", type=int, default=None,
                    help=f"délai max d'attente du serveur TTS (s, "
                         f"défaut {SERVER_STARTUP_TIMEOUT})")
    ap.add_argument("--rate", type=int, default=180, help="débit say (mots/minute)")
    ap.add_argument("--speed", type=float, default=None,
                    help="vitesse de lecture (1.0 = normal)")
    ap.add_argument("--audio-dir", type=Path, default=None,
                    help="dossier des mp3 (défaut : <in>/audio)")
    ap.add_argument("--keep-audio", action="store_true",
                    help="réutilise les mp3 existants au lieu de les régénérer")
    ap.add_argument("--advance", action="store_true",
                    help="en diaporama, avance à la slide suivante à la fin du voiceover")
    ap.add_argument("--advance-buffer", type=int, default=600,
                    help="délai après l'audio avant d'avancer (ms, défaut 600)")
    args = ap.parse_args()

    root = Path.cwd()
    indir = args.indir if args.indir.is_absolute() else root / args.indir

    tts_config_path = (
        args.tts_config if args.tts_config.is_absolute() else root / args.tts_config
    )
    tts_cfg = load_tts_config(tts_config_path)

    tts_url = args.tts_url or tts_cfg.get("url") or LOCAL_TTS_URL
    tts_model = args.tts_model or tts_cfg.get("model") or LOCAL_TTS_MODEL
    tts_lang = args.tts_lang or tts_cfg.get("lang") or LOCAL_TTS_LANG
    cfg_voice = tts_cfg.get("voice") or LOCAL_TTS_VOICE

    server_host = str(tts_cfg.get("host", SERVER_HOST))
    server_port = int(tts_cfg.get("port", SERVER_PORT))
    server_cmd = tts_cfg.get("server_command") or SERVER_COMMAND
    serve_tts = args.tts == "mlx" and (args.serve_tts or bool(tts_cfg.get("serve")))
    serve_tts_timeout = args.serve_tts_timeout or int(
        tts_cfg.get("startup_timeout", SERVER_STARTUP_TIMEOUT)
    )

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
        voice = args.voice or (cfg_voice if args.tts == "mlx" else SAY_VOICE)
        speed = args.speed if args.speed is not None else 1.0
        audio_cfg = {
            "tts": args.tts,
            "dir": audio_dir,
            "voice": voice,
            "rate": args.rate,
            "speed": speed,
            "keep": args.keep_audio,
            "model_id": tts_model,
            "url": tts_url,
            "lang": tts_lang,
            "advance": args.advance,
            "advance_buffer": args.advance_buffer,
        }

    server_proc = None
    if serve_tts and not args.audio:
        print("  --serve-tts ignoré : ajoute --audio pour générer le voiceover.")
    if serve_tts and args.audio:
        if port_open(server_host, server_port):
            print(f"  serveur TTS déjà en écoute sur {server_host}:{server_port} "
                  "— conservé tel quel.")
        else:
            server_proc = start_local_server(
                server_host, server_port, server_cmd,
                serve_tts_timeout, indir / "tts-server.log",
            )
            print(f"  serveur TTS démarré (pid {server_proc.pid}).")

    try:
        n = build(data, outfile, root, audio_cfg)
    finally:
        if server_proc is not None:
            stop_local_server(server_proc)
            print("  serveur TTS arrêté.")

    print(f"{n} slides -> {outfile}")
    if audio_cfg:
        extra = ", avance auto en fin de voix" if audio_cfg.get("advance") else ""
        print(f"voiceover -> {audio_cfg['dir']} "
              f"({audio_cfg['tts']}, voix {audio_cfg['voice']}, lecture automatique{extra})")


if __name__ == "__main__":
    main()
