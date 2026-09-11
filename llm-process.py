#!/usr/bin/env python3
"""llm-process.py — Étape 2 : interprétation LLM de l'extraction PDF.

Prend le dossier `paper-processed/` produit par `extract.py` et demande à une
session opencode non-interactive (modèle gratuit `opencode/big-pickle`, avec
repli sur d'autres modèles gratuits) de produire :

    llm-output/storyboard.json   plan du PowerPoint (slides, images, voix off)
    llm-output/voiceover.md      texte de commentaire par slide

La session a accès aux outils (lecture/écriture de fichiers) et lit elle-même
`paper-processed/` pour comprendre l'article.

Prérequis : le binaire `opencode` doit être dans le PATH, et
`paper-processed/` doit avoir été généré par `extract.py`.

Usage :
    python llm-process.py [--paper paper-processed] [--out llm-output]
                          [--prompt prompts/llm-process.md]
                          [--model opencode/big-pickle] [--model ...]
                          [--timeout 1800] [--build] [--dry-run]

    --build     lance aussi build_pptx.py pour générer llm-output/presentation.pptx
    --dry-run   affiche la commande sans exécuter la session (test rapide)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
from pathlib import Path

DEFAULT_MODELS = [
    "opencode/big-pickle",
    "opencode/mimo-v2.5-free",
    "opencode/nemotron-3-ultra-free",
    "opencode/ling-3.0-flash-fin-free",
]


def find_opencode() -> str:
    exe = shutil.which("opencode")
    if not exe:
        sys.exit(
            "opencode introuvable dans le PATH.\n"
            "Installe-le : https://opencode.ai/docs/ (ou ajoute son dossier au PATH)."
        )
    return exe


def build_command(opencode: str, model: str, prompt: str, root: Path) -> list[str]:
    return [
        opencode,
        "run",
        "--model",
        model,
        "--dir",
        str(root),
        "--auto",
        "--title",
        "pdf-to-education : storyboard + voiceover",
        prompt,
    ]


def run_session(cmd: list[str], log_path: Path, timeout: int) -> int:
    """Exécute la session en streamant la sortie vers la console et un log."""
    print("→", " ".join(cmd[:8]), "...")
    with log_path.open("w", encoding="utf-8") as log:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            print(f"  échec du lancement : {exc}")
            return 1
        assert proc.stdout is not None
        timed_out = threading.Event()

        def watchdog() -> None:
            timed_out.set()
            proc.kill()

        timer = threading.Timer(timeout, watchdog)
        timer.daemon = True
        timer.start()
        try:
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log.write(line)
            code = proc.wait()
            if timed_out.is_set():
                print(f"  délai dépassé ({timeout}s), session interrompue.")
                return 124
            return code
        except KeyboardInterrupt:
            proc.kill()
            print("\n  interrompu par l'utilisateur.")
            raise
        finally:
            timer.cancel()


def validate(out: Path) -> list[str]:
    """Vérifie les livrables attendus, renvoie la liste des problèmes."""
    problems = []
    storyboard = out / "storyboard.json"
    voiceover = out / "voiceover.md"
    if not storyboard.is_file():
        problems.append(f"manquant : {storyboard}")
    else:
        import json

        try:
            data = json.loads(storyboard.read_text(encoding="utf-8"))
            slides = data.get("slides", [])
            if not slides:
                problems.append("storyboard.json : aucune slide")
            else:
                print(f"  storyboard : {len(slides)} slides")
                imgs = [s for s in slides if s.get("image")]
                print(f"  images intégrées : {len(imgs)}")
        except (json.JSONDecodeError, OSError) as exc:
            problems.append(f"storyboard.json invalide : {exc}")
    if not voiceover.is_file():
        problems.append(f"manquant : {voiceover}")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Étape 2 : storyboard PowerPoint + voiceover via opencode."
    )
    ap.add_argument("--paper", type=Path, default=Path("paper-processed"))
    ap.add_argument("--out", type=Path, default=Path("llm-output"))
    ap.add_argument("--prompt", type=Path, default=Path("prompts/llm-process.md"))
    ap.add_argument(
        "--model",
        action="append",
        dest="models",
        help="modèle à utiliser (répétable) ; le premier dispo gagne",
    )
    ap.add_argument("--timeout", type=int, default=1800, help="délai max par session (s)")
    ap.add_argument("--build", action="store_true", help="génère aussi le .pptx")
    ap.add_argument("--dry-run", action="store_true", help="n'exécute pas la session")
    args = ap.parse_args()

    root = Path.cwd()
    paper = (root / args.paper).resolve() if not args.paper.is_absolute() else args.paper
    out = (root / args.out).resolve() if not args.out.is_absolute() else args.out
    prompt_file = (
        (root / args.prompt).resolve() if not args.prompt.is_absolute() else args.prompt
    )

    if not paper.is_dir():
        sys.exit(f"Dossier d'extraction introuvable : {paper}\nLance d'abord extract.py.")
    if not prompt_file.is_file():
        sys.exit(f"Prompt introuvable : {prompt_file}")
    out.mkdir(parents=True, exist_ok=True)

    opencode = find_opencode()
    prompt = prompt_file.read_text(encoding="utf-8")
    models = args.models or DEFAULT_MODELS
    log_path = out / "llm-session.log"

    print(f"paper    : {paper}")
    print(f"output   : {out}")
    print(f"modèles  : {', '.join(models)}")

    if args.dry_run:
        cmd = build_command(opencode, models[0], prompt, root)
        print("\n[dry-run] commande :")
        print(" ".join(cmd[:8]), "<prompt>")
        print("\nPrompt :")
        print(prompt)
        return

    for i, model in enumerate(models, start=1):
        print(f"\n=== Tentative {i}/{len(models)} avec {model} ===")
        cmd = build_command(opencode, model, prompt, root)
        code = run_session(cmd, log_path, args.timeout)
        if code != 0:
            print(f"  session terminée avec le code {code}, modèle suivant.")
            continue
        problems = validate(out)
        if not problems:
            print(f"\nOK — livrables générés par {model}.")
            break
        print("  livrables incomplets :")
        for p in problems:
            print(f"    - {p}")
    else:
        sys.exit(
            "\nAucun modèle n'a produit les livrables attendus.\n"
            f"Voir le log : {log_path}"
        )

    if args.build:
        print("\n=== Génération du PowerPoint ===")
        code = subprocess.run(
            [sys.executable, str(root / "build_pptx.py"), "--in", str(out)]
        ).returncode
        if code != 0:
            sys.exit("Échec de build_pptx.py")
        print(f"PowerPoint : {out / 'presentation.pptx'}")


if __name__ == "__main__":
    main()
