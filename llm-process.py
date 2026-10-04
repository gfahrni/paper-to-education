#!/usr/bin/env python3
"""llm-process.py — Étape 2 : interprétation LLM de l'extraction PDF.

Prend le dossier `paper-processed/` produit par `extract.py` et demande à une
session opencode non-interactive (modèle `opencode-go/deepseek-v4.1-flash`, avec
repli sur d'autres modèles) de produire :

    llm-output/storyboard.json   plan du PowerPoint (slides, images, voix off)
    llm-output/voiceover.md      texte de commentaire par slide

Deux axes paramètrent le rendu :

    --mode  journal | course    article (journal club) ou cours de formation
    --depth summary | extensive résumé borné, ou explicatif exhaustif (sans
                                plafond de slides ; une passe « plan » est
                                d'abord générée dans llm-output/plan.md)

Le prompt final est composé : prompt de base (`prompts/llm-process.md`) +
fragment de mode + fragment de profondeur (`prompts/fragments/`). Le contexte
d'exécution (sources, sortie) est injecté en tête.

La session a accès aux outils (lecture/écriture de fichiers) et lit elle-même
`paper-processed/` pour comprendre le contenu.

Prérequis : le binaire `opencode` doit être dans le PATH, et
`paper-processed/` doit avoir été généré par `extract.py`.

Usage :
    python llm-process.py [--paper paper-processed] [--out llm-output]
                          [--mode journal|course] [--depth summary|extensive]
                          [--prompt prompts/llm-process.md] [--config config.json]
                          [--model opencode-go/deepseek-v4.1-flash] [--model ...]
                          [--timeout 1800] [--build] [--dry-run]

    --config    config locale (modèles + clés API), ignorée par Git
    --build     lance aussi build_pptx.py pour générer llm-output/presentation.pptx
    --audio     avec --build : ajoute un voiceover TTS en lecture automatique
    --tts       say (macOS, défaut) ou mlx (serveur local)
    --voice     voix macOS (--tts say) ou voix locale (--tts mlx)
    --serve-tts avec --tts mlx : démarre/arrête le serveur local si besoin
    --speed     vitesse de lecture (défaut 1.0)
    --advance   en diaporama, avance à la fin du voiceover de chaque slide
    --dry-run   affiche la commande et le prompt composé sans exécuter la session

Choix du modèle / de l'API :
    Copie `config.example.json` en `config.json` (gitignoré), puis renseigne
    `models` (liste, le premier disponible gagne) et, si tu utilises un
    provider payant, ses clés dans `env`. Alternative sans fichier :
    `opencode auth login` puis `--model provider/model`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

DEFAULT_MODELS = [
    "opencode-go/deepseek-v4.1-flash",
    "deepseek/deepseek-flash",
    "opencode/big-pickle",
]

SCRIPT_DIR = Path(__file__).resolve().parent
FRAGMENTS_DIR = SCRIPT_DIR / "prompts" / "fragments"


def load_config(path: Path) -> dict:
    """Charge la config locale (modèles + variables d'environnement)."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        sys.exit(f"Config invalide ({path}) : {exc}")
    if not isinstance(data, dict):
        sys.exit(f"Config invalide ({path}) : objet JSON attendu.")
    return data


def find_opencode() -> str:
    exe = shutil.which("opencode")
    if not exe:
        sys.exit(
            "opencode introuvable dans le PATH.\n"
            "Installe-le : https://opencode.ai/docs/ (ou ajoute son dossier au PATH)."
        )
    return exe


def build_command(opencode: str, model: str, prompt: str) -> list[str]:
    # opencode >= 2.x : `run` n'a plus de flag --dir ; le dossier de travail
    # est imposé via cwd dans run_session().
    return [
        opencode,
        "run",
        "--model",
        model,
        "--auto",
        "--title",
        "pdf-to-education : storyboard + voiceover",
        prompt,
    ]


def run_session(cmd: list[str], log_path: Path, timeout: int,
                extra_env: dict[str, str] | None = None,
                cwd: Path | None = None) -> int:
    """Exécute la session en streamant la sortie vers la console et un log."""
    print("→", " ".join(cmd[:8]), "...")
    env = {**os.environ, **(extra_env or {})}
    with log_path.open("w", encoding="utf-8") as log:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                cwd=str(cwd) if cwd else None,
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


def load_fragment(name: str) -> str:
    """Charge un fragment de prompt (prompts/fragments/<name>.md)."""
    path = FRAGMENTS_DIR / f"{name}.md"
    if not path.is_file():
        sys.exit(f"Fragment de prompt introuvable : {path}")
    return path.read_text(encoding="utf-8").strip()


def load_sources(paper: Path) -> list[dict]:
    """Lit `metadata/sources.json`, avec repli sur l'ancienne structure plate."""
    index = paper / "metadata" / "sources.json"
    if index.is_file():
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        sources = data.get("sources") if isinstance(data, dict) else None
        if sources:
            return sources
    return [{
        "id": paper.name,
        "filename": paper.name,
        "title": None,
        "page_count": None,
        "dir": "",
        "text": "text/full_text.md",
        "metadata": "metadata/extraction.json",
    }]


def display_path(path: Path, session_dir: Path) -> str:
    """Chemin relatif au dossier de session si possible, sinon absolu."""
    path = path.resolve()
    try:
        return str(path.relative_to(session_dir))
    except ValueError:
        return str(path)


def build_header(
    paper: Path,
    out: Path,
    session_dir: Path,
    sources: list[dict],
    mode: str,
    depth: str,
    plan_path: Path | None = None,
) -> str:
    """Préambule de contexte injecté en tête du prompt."""
    lines = [
        "<!-- Contexte d'exécution",
        f"     dossier de travail opencode : {session_dir}",
        f"     mode : {mode} | profondeur : {depth}",
        f"     extraction : {display_path(paper, session_dir)}",
        f"     sources ({len(sources)}) :",
    ]
    for s in sources:
        title = s.get("title") or s.get("filename") or s.get("id") or "?"
        pages = f", {s['page_count']} p." if s.get("page_count") else ""
        kind = s.get("kind")
        kind_txt = f" [{kind}]" if kind else ""
        lines.append(f"       [{s.get('id', '?')}]{kind_txt} {title}{pages}")
        if s.get("text"):
            lines.append(
                f"            texte : {display_path(paper / s['text'], session_dir)}"
            )
        if s.get("metadata"):
            lines.append(
                f"            index : {display_path(paper / s['metadata'], session_dir)}"
            )
        if s.get("figures") or s.get("tables"):
            lines.append(
                f"            figures/tables : {s.get('figures', 0)}/"
                f"{s.get('tables', 0)}"
            )
        if s.get("pages_dir"):
            lines.append(
                f"            rendus de page : "
                f"{display_path(paper / s['pages_dir'], session_dir)} "
                f"({s.get('pages_count', 0)})"
            )
        if s.get("images_dir"):
            lines.append(
                f"            images (contexte dans *.txt) : "
                f"{display_path(paper / s['images_dir'], session_dir)} "
                f"({s.get('images_count', 0)})"
            )
    lines.append(f"     sortie : {display_path(out, session_dir)}")
    lines.append(
        f"     livrables : {display_path(out / 'storyboard.json', session_dir)}, "
        f"{display_path(out / 'voiceover.md', session_dir)}"
    )
    if plan_path is not None:
        lines.append(f"     plan détaillé : {display_path(plan_path, session_dir)}")
    lines.append("-->")
    return "\n".join(lines)


def compose_prompt(header: str, *blocks: str) -> str:
    """Assemble le contexte puis les blocs de prompt, séparés par une ligne vide."""
    parts = [header.strip()]
    parts += [b.strip() for b in blocks if b and b.strip()]
    return "\n\n".join(parts) + "\n"


def run_models(
    opencode: str,
    models: list[str],
    prompt: str,
    log_path: Path,
    timeout: int,
    extra_env: dict[str, str] | None,
    session_dir: Path,
    check,
) -> str | None:
    """Essaie chaque modèle jusqu'à ce que `check()` ne renvoie plus de problème."""
    for i, model in enumerate(models, start=1):
        print(f"\n=== Tentative {i}/{len(models)} avec {model} ===")
        cmd = build_command(opencode, model, prompt)
        code = run_session(cmd, log_path, timeout, extra_env, session_dir)
        # On vérifie toujours les livrables : `opencode run` peut sortir avec un
        # code non nul après une erreur de stream transitoire alors que les
        # fichiers ont bien été écrits. Le vrai critère de succès est `check()`.
        problems = check()
        if not problems:
            if code != 0:
                print(
                    f"  session terminée avec le code {code}, "
                    f"mais livrables présents — on continue."
                )
            print(f"\nOK — livrables générés par {model}.")
            return model
        if code != 0:
            print(f"  session terminée avec le code {code}, modèle suivant.")
        print("  livrables incomplets :")
        for p in problems:
            print(f"    - {p}")
    return None


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Étape 2 : storyboard PowerPoint + voiceover via opencode."
    )
    ap.add_argument("--paper", type=Path, default=Path("paper-processed"))
    ap.add_argument("--out", type=Path, default=Path("llm-output"))
    ap.add_argument("--prompt", type=Path, default=SCRIPT_DIR / "prompts/llm-process.md")
    ap.add_argument("--mode", choices=["journal", "course"], default="journal",
                    help="registre : journal club (article) ou cours (défaut : journal)")
    ap.add_argument("--depth", choices=["summary", "extensive"], default="summary",
                    help="profondeur : résumé borné ou explicatif exhaustif "
                         "(défaut : summary)")
    ap.add_argument("--config", type=Path, default=SCRIPT_DIR / "config.json",
                    help="config locale (modèles, clés API) — ignorée par Git")
    ap.add_argument(
        "--model",
        action="append",
        dest="models",
        help="modèle à utiliser (répétable) ; le premier dispo gagne",
    )
    ap.add_argument("--timeout", type=int, default=1800, help="délai max par session (s)")
    ap.add_argument("--build", action="store_true", help="génère aussi le .pptx")
    ap.add_argument("--audio", action="store_true",
                    help="avec --build : voiceover TTS en lecture automatique par slide")
    ap.add_argument("--tts", choices=["say", "mlx"], default="say",
                    help="moteur TTS (défaut : say macOS)")
    ap.add_argument("--voice", default=None,
                    help="voix macOS (--tts say) ou voix locale (--tts mlx)")
    ap.add_argument("--tts-model", default=None,
                    help="id Hugging Face du modèle TTS local (--tts mlx)")
    ap.add_argument("--tts-url", default=None,
                    help="URL du serveur TTS local compatible OpenAI (--tts mlx)")
    ap.add_argument("--tts-lang", default=None,
                    help="code langue du serveur local (--tts mlx, ex. fr)")
    ap.add_argument("--tts-config", type=Path, default=None,
                    help="config du serveur TTS local (défaut build_pptx : tts.json)")
    ap.add_argument("--serve-tts", action="store_true",
                    help="avec --tts mlx : démarre/arrête le serveur local si besoin")
    ap.add_argument("--rate", type=int, default=180, help="débit say (mots/minute)")
    ap.add_argument("--speed", type=float, default=None,
                    help="vitesse de lecture (défaut 1.0)")
    ap.add_argument("--advance", action="store_true",
                    help="en diaporama, avance à la slide suivante à la fin du voiceover")
    ap.add_argument("--dry-run", action="store_true", help="n'exécute pas la session")
    args = ap.parse_args()

    root = Path.cwd()
    paper = (root / args.paper).resolve() if not args.paper.is_absolute() else args.paper
    out = (root / args.out).resolve() if not args.out.is_absolute() else args.out
    prompt_file = (
        (root / args.prompt).resolve() if not args.prompt.is_absolute() else args.prompt
    )
    # Dossier de session opencode : doit contenir paper ET out pour que les
    # chemins relatifs du prompt (paper-processed/, llm-output/) se résolvent.
    # Via pdf-to-education.command, cwd == WORK (= parent commun). En manuel
    # avec des chemins absolus disparates, on prend le plus proche ancêtre
    # commun au lieu de cwd.
    try:
        session_dir = Path(os.path.commonpath([str(paper), str(out)]))
    except ValueError:
        session_dir = Path.cwd()
    # Si paper/out sont relatifs (cas Makefile), on garde cwd.
    if not args.paper.is_absolute() and not args.out.is_absolute():
        session_dir = root

    if not paper.is_dir():
        sys.exit(f"Dossier d'extraction introuvable : {paper}\nLance d'abord extract.py.")
    if not prompt_file.is_file():
        sys.exit(f"Prompt introuvable : {prompt_file}")
    out.mkdir(parents=True, exist_ok=True)

    opencode = find_opencode()
    config_file = (
        (root / args.config).resolve() if not args.config.is_absolute() else args.config
    )
    config = load_config(config_file)
    models = args.models or config.get("models") or DEFAULT_MODELS
    env_extra = {k: str(v) for k, v in (config.get("env") or {}).items() if v}
    log_path = out / "llm-session.log"

    base_prompt = prompt_file.read_text(encoding="utf-8")
    mode_fragment = load_fragment(args.mode)
    depth_fragment = load_fragment(args.depth)
    sources = load_sources(paper)
    plan_path = out / "plan.md" if args.depth == "extensive" else None
    header = build_header(
        paper, out, session_dir, sources, args.mode, args.depth, plan_path
    )
    full_prompt = compose_prompt(header, base_prompt, mode_fragment, depth_fragment)

    print(f"paper    : {paper}")
    print(f"output   : {out}")
    print(f"session  : {session_dir} (--dir opencode)")
    print(f"mode     : {args.mode} / {args.depth} ({len(sources)} source(s))")
    print(f"config   : {config_file if config else '(aucune)'}")
    print(f"modèles  : {', '.join(models)}")
    if env_extra:
        print(f"clés API : {', '.join(env_extra)} (depuis la config)")

    if args.dry_run:
        if args.depth == "extensive":
            plan_prompt = compose_prompt(
                build_header(
                    paper, out, session_dir, sources, args.mode, args.depth, plan_path
                ),
                load_fragment("plan"),
            )
            print("\n[dry-run] passe 1/2 — plan.md :\n")
            print(plan_prompt)
        print("\n[dry-run] commande :")
        cmd = build_command(opencode, models[0], "<prompt>")
        print(" ".join(cmd))
        print("\n[dry-run] passe 2/2 — storyboard + voiceover :\n")
        print(full_prompt)
        return

    if args.depth == "extensive":
        print("\n=== Passe 1/2 : plan détaillé ===")
        if plan_path.is_file() and plan_path.read_text(encoding="utf-8").strip():
            print(f"  plan existant réutilisé : {plan_path}")
        else:
            plan_prompt = compose_prompt(
                build_header(
                    paper, out, session_dir, sources, args.mode, args.depth, plan_path
                ),
                load_fragment("plan"),
            )
            plan_log = out / "plan-session.log"

            def check_plan() -> list[str]:
                if not plan_path.is_file():
                    return [f"manquant : {plan_path}"]
                if not plan_path.read_text(encoding="utf-8").strip():
                    return ["plan.md vide"]
                return []

            plan_model = run_models(
                opencode, models, plan_prompt, plan_log, args.timeout,
                env_extra, session_dir, check_plan,
            )
            if plan_model is None:
                sys.exit(
                    "\nAucun modèle n'a produit plan.md.\n"
                    f"Voir le log : {plan_log}"
                )
        print("\n=== Passe 2/2 : storyboard + voiceover ===")

    main_model = run_models(
        opencode, models, full_prompt, log_path, args.timeout,
        env_extra, session_dir, lambda: validate(out),
    )
    if main_model is None:
        sys.exit(
            "\nAucun modèle n'a produit les livrables attendus.\n"
            f"Voir le log : {log_path}"
        )

    if args.build:
        print("\n=== Génération du PowerPoint ===")
        build_cmd = [
            sys.executable, str(SCRIPT_DIR / "build_pptx.py"), "--in", str(out),
            "--tts", args.tts,
        ]
        if args.tts_model:
            build_cmd += ["--tts-model", args.tts_model]
        if args.tts_url:
            build_cmd += ["--tts-url", args.tts_url]
        if args.tts_lang:
            build_cmd += ["--tts-lang", args.tts_lang]
        if args.tts_config:
            build_cmd += ["--tts-config", str(args.tts_config)]
        if args.serve_tts:
            build_cmd += ["--serve-tts"]
        if args.voice:
            build_cmd += ["--voice", args.voice]
        if args.audio:
            build_cmd += ["--audio", "--rate", str(args.rate)]
        if args.speed is not None:
            build_cmd += ["--speed", str(args.speed)]
        if args.advance:
            build_cmd += ["--advance"]
        code = subprocess.run(build_cmd, env={**os.environ, **env_extra}).returncode
        if code != 0:
            sys.exit("Échec de build_pptx.py")
        print(f"PowerPoint : {out / 'presentation.pptx'}")
        if args.audio:
            print(f"Voiceover  : {out / 'audio'} ({args.tts}, lecture automatique)")


if __name__ == "__main__":
    main()
