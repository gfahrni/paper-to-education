# pdf-to-education

Transformer un PDF d'article scientifique en **présentation pédagogique
PowerPoint avec voix off**.

Le projet prend un PDF en entrée et produit un `.pptx` prêt à présenter :
texte résumé par un LLM, figures et tables conservées en image, et un voiceover
TTS en lecture automatique par slide. La chaîne va de bout en bout :

```text
input-pdf/article.pdf
        │  extract.py
        ▼
paper-processed/        texte, figures, tables, légendes (brut et traçable)
        │  llm-process.py (session opencode)
        ▼
llm-output/             storyboard.json + voiceover.md
        │  build_pptx.py (+ TTS)
        ▼
llm-output/presentation.pptx   slides + images + voiceover
```

## Ce que le projet sait faire

- **Extraction fidèle** : texte reconstruit dans l'ordre de lecture (colonnes,
  césures, lettrines), figures extraites en image, tables rendues en image +
  texte brut, légendes appariées, index JSON de traçabilité.
- **Storyboard généré par LLM** : une session opencode non-interactive lit
  l'extraction et écrit un plan de slides (titres, puces, image associée) et un
  commentaire oral par slide.
- **PowerPoint 16:9** : mise en page automatique (titre, puces, image, légende),
  voiceover en notes du présentateur.
- **Voiceover intégré** : audio TTS par slide, en lecture automatique, avec
  moteur local (`mlx-audio`, voix humaines FR) ou `say` macOS (hors-ligne).
  Une **barre de progression** reste visible en bas de chaque slide et se met
  en pause avec `S` (pause du diaporama) ; les contrôles média PowerPoint et
  l'icône audio restent aussi accessibles au survol/clic.
- **Modèles gratuits par défaut** avec repli automatique, ou provider payant via
  `config.json` / `opencode auth login`.

## Modules

| Script | Rôle | Sortie |
| --- | --- | --- |
| `extract.py` | fragmente le PDF sans l'interpréter | `paper-processed/` |
| `llm-process.py` | pilote la session LLM (opencode) | `llm-output/storyboard.json`, `voiceover.md` |
| `build_pptx.py` | construit le PPT (+ TTS) | `llm-output/presentation.pptx`, `audio/` |

Le prompt qui pilote le LLM est versionné dans `prompts/llm-process.md`.

## Prérequis

| Composant | Utile pour | Obligatoire |
| --- | --- | --- |
| **Python 3.10+** | tout le pipeline | oui |
| **opencode** + un provider | génération du storyboard | oui |
| **ffmpeg** | convertir / accélérer l'audio | oui pour le voiceover |
| **macOS sur Apple Silicon** | TTS local (`mlx`) et `say` | seulement pour le voiceover |
| **uv** | installer le serveur TTS local | oui pour `--tts mlx` |
| **Homebrew** | installer `ffmpeg`, `uv`, `opencode` | recommandé (macOS) |

> ⚠️ Le voiceover repose sur **MLX** (`mlx-audio`) et sur `say`, tous deux
> **macOS / Apple Silicon**. Sur Linux, Windows ou Mac Intel, l'extraction PDF
> et la génération du storyboard fonctionnent, mais **pas l'audio**.

## Installation

### 1. Outils système (macOS)

```bash
brew install ffmpeg uv

# opencode
curl -fsSL https://opencode.ai/install | bash   # ou : brew install anomalyco/tap/opencode
```

### 2. Environnement Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# optionnel : meilleure détection des tables
pip install pdfplumber
```

### 3. Fournisseur LLM (opencode)

Connecte un provider une fois (`opencode auth login`, ou `/connect` dans le TUI
opencode), puis vérifie :

```bash
opencode models | grep big-pickle
```

Le script utilise par défaut des modèles **gratuits** et bascule automatiquement
sur les suivants si le premier est indisponible.

### 4. Serveur TTS local (voiceover, optionnel)

```bash
uv tool install --force 'mlx-audio[server,tts]' \
    --with misaki --with phonemizer-fork --with espeakng-loader

cp tts.example.json tts.json   # ajuste ensuite voix / modèle si besoin
```

`uv tool` expose `mlx_audio.*` dans `~/.local/bin` sans toucher à ton Python.
Détails (modèles, voix, cycle de vie du serveur) : [Voiceover](#voiceover).

## Utilisation

### Raccourcis (Makefile)

Les opérations courantes sont encapsulées dans le `Makefile` (voix locale
Voxtral `fr_female`, serveur TTS démarré/arrêté automatiquement) :

```bash
make            # affiche l'aide
make install    # crée .venv + installe les dépendances Python
make extract    # PDF -> paper-processed/
make storyboard # paper-processed/ -> llm-output/ (storyboard + voiceover)
make pptx       # llm-output/ -> presentation.pptx + voiceover local
make serve-tts  # démarre le serveur TTS local en manuel (127.0.0.1:8000)

make pptx VOICE=fr_male   # surcharge la voix
make pptx SPEED=1.1       # vitesse de lecture
make pptx TTS=say         # repli sur la voix macOS (hors-ligne, robotique)
make pptx ADVANCE=0       # pas d'avance auto (clic pour changer de slide)
```

### Pipeline manuel

Dépose le PDF dans `input-pdf/`, puis :

```bash
# 1. extraction PDF
python extract.py [article.pdf] [--in input-pdf] [--out paper-processed] [--dpi 300]

# 2. storyboard + voiceover (session LLM) + PPT (+ audio)
python llm-process.py --build --audio

# ou seulement le PowerPoint depuis un storyboard existant
python build_pptx.py --in llm-output
```

Sans argument, `extract.py` prend l'unique PDF de `input-pdf/`.

#### `extract.py`

| Option | Défaut | Description |
| --- | --- | --- |
| `pdf` (positionnel) | unique PDF de `input-pdf/` | PDF source |
| `--in` | `input-pdf` | Dossier du PDF |
| `--out` | `paper-processed` | Dossier de sortie |
| `--dpi` | `300` | Résolution des recadrages de page |

#### `llm-process.py`

| Option | Défaut | Description |
| --- | --- | --- |
| `--paper` | `paper-processed` | Dossier d'extraction |
| `--out` | `llm-output` | Dossier de sortie |
| `--prompt` | `prompts/llm-process.md` | Prompt envoyé à la session |
| `--config` | `config.json` | Config locale (modèles, clés API) |
| `--model` | `opencode/big-pickle` | Modèle (répétable, dans l'ordre) |
| `--timeout` | `1800` | Délai max par session (s) |
| `--build` | — | Génère aussi `presentation.pptx` |
| `--audio` | — | Avec `--build` : voiceover TTS (lecture auto) |
| `--tts` | `say` | Moteur : `say` (macOS), `mlx` (serveur local) |
| `--tts-config` | `tts.json` | Config du serveur TTS local |
| `--serve-tts` | — | Avec `--tts mlx` : démarre/arrête le serveur si besoin |
| `--tts-url` | depuis `tts.json` | URL du serveur TTS local |
| `--tts-lang` | depuis `tts.json` | Code langue du serveur local (`fr`) |
| `--voice` | selon `--tts` | Voix locale (`fr_female`) ou voix macOS |
| `--dry-run` | — | Affiche la commande sans exécuter la session |

Exemple complet :

```bash
python extract.py
python llm-process.py --build --audio
```

Pour tester sans consommer de modèle :

```bash
python llm-process.py --dry-run
```

### Choisir le modèle / connecter une API

Par défaut, le script utilise les modèles **gratuits** d'OpenCode Zen, sans
configuration. Pour utiliser un autre provider (payant), il y a deux méthodes —
**ne mets jamais une clé API dans le script**.

**a) Via `opencode auth login`** (le plus simple) : la clé est stockée par
opencode dans `~/.local/share/opencode/auth.json`, puis :

```bash
python llm-process.py --model anthropic/claude-sonnet-4-5
```

**b) Via `config.json`** (gitignoré) : copie l'exemple et remplis-le.

```bash
cp config.example.json config.json
```

```json
{
  "models": ["anthropic/claude-sonnet-4-5", "opencode/big-pickle"],
  "env": {
    "ANTHROPIC_API_KEY": "sk-ant-..."
  }
}
```

- `models` : liste essayée dans l'ordre, le premier qui répond gagne. Le dernier
  peut rester un modèle gratuit comme filet de sécurité.
- `env` : variables d'environnement passées à la session opencode (noms des
  clés selon le provider : `OPENAI_API_KEY`, `OPENROUTER_API_KEY`,
  `DEEPSEEK_API_KEY`, `MISTRAL_API_KEY`…).

`config.json` et `.env` sont **ignorés par Git** ; seul `config.example.json`
est versionné.

## Voiceover

Avec `--audio`, un fichier TTS est généré depuis le `voiceover` de chaque slide
et intégré au `.pptx` en **lecture automatique** : en diaporama, avancer ou
reculer déclenche le voiceover de la slide affichée (et donc le rejoue si tu
reviens en arrière).

Une **barre de progression** est dessinée en bas de chaque slide : elle se
remplit de gauche à droite sur la durée exacte de l'audio, toujours visible
(pas seulement au survol), et suit le rythme du voiceover. En diaporama, la
touche `S` met le diaporama en pause (audio + barre + minuteur d'avance), et
une seconde pression reprend exactement où on s'était arrêté.

En complément, PowerPoint affiche sa **barre de contrôle média** (play/pause +
progression) au survol/clic : l'option « Show media controls » est activée dans
le fichier et l'icône audio est laissée visible. `--no-progress-bar` /
`--no-media-controls` désactivent l'un ou l'autre.

Par défaut (`make pptx`), la slide avance automatiquement à la fin du
voiceover (`--advance`). Pour plutôt rester sur la slide et avancer au clic,
utilise `make pptx ADVANCE=0`.

Moteurs disponibles via `--tts` :

| `--tts` | Qualité | Dépendances | Voix |
| --- | --- | --- | --- |
| `mlx` | voix humaines, FR natif | serveur local `mlx-audio` | `fr_female`, `fr_male`… |
| `say` | robotique | macOS `say` + `ffmpeg` | `Thomas`, `Amélie`… (`say -v '?'`) |

```bash
# Voix locale Voxtral (recommandé)
python llm-process.py --build --audio --tts mlx --serve-tts

# Sur un storyboard existant
python build_pptx.py --in llm-output --audio --tts mlx --advance

# Repli voix macOS (gratuit, hors-ligne, moins naturel)
python llm-process.py --build --audio --tts say
```

### Serveur TTS local (`mlx-audio`)

Le moteur `mlx` appelle un **serveur local compatible OpenAI**
(`mlx_audio.server`), gratuit et hors-ligne, qui fait tourner
[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), Voxtral, Kokoro, etc. sur
Apple Silicon.

Installation (une fois) :

```bash
brew install ffmpeg
uv tool install --force 'mlx-audio[server,tts]' \
    --with misaki --with phonemizer-fork --with espeakng-loader
```

> `uv tool` expose les commandes dans `~/.local/bin` sans polluer ton Python.
> `misaki` + `phonemizer-fork` + `espeakng-loader` sont requis pour le français.

La configuration vit dans **`tts.json`** (racine, gitignoré ; copie
`tts.example.json`) :

```json
{
  "url": "http://127.0.0.1:8000/v1/audio/speech",
  "host": "127.0.0.1",
  "port": 8000,
  "model": "mlx-community/Voxtral-4B-TTS-2603-mlx-bf16",
  "voice": "fr_female",
  "lang": "fr",
  "serve": true,
  "startup_timeout": 180,
  "server_command": ["mlx_audio.server", "--host", "{host}", "--port", "{port}"]
}
```

Priorité : **options CLI > `tts.json` > défauts**.

Avec `serve: true` (ou `--serve-tts`), `build_pptx.py` gère le cycle de vie :

- serveur **déjà en écoute** → conservé tel quel (jamais arrêté) ;
- serveur **absent** → démarré, attente de disponibilité, génération, puis
  **arrêt automatique** (même en cas d'erreur).

Pour le lancer/le garder en manuel : `make serve-tts`.

### Options de `build_pptx.py`

| Option | Défaut | Description |
| --- | --- | --- |
| `--in` | `llm-output` | Dossier du `storyboard.json` |
| `--out` | `<in>/presentation.pptx` | Fichier `.pptx` de sortie |
| `--audio` | — | Génère et intègre le voiceover TTS (lecture auto) |
| `--tts` | `say` | `mlx` (serveur local) ou `say` (macOS) |
| `--tts-config` | `tts.json` | Config du serveur TTS local |
| `--serve-tts` | — | Démarre/arrête le serveur local si nécessaire |
| `--serve-tts-timeout` | `180` | Attente max du serveur (s) |
| `--tts-url` | `tts.json` | URL du serveur TTS local |
| `--tts-model` | `tts.json` | Modèle (id Hugging Face) |
| `--voice` | `fr_female` | Voix locale (ex. `fr_female`, `fr_male`) |
| `--tts-lang` | `fr` | Code langue du serveur local |
| `--rate` | `180` | Débit `say` (mots/minute) |
| `--speed` | `1.0` | Vitesse de lecture (hauteur conservée) |
| `--audio-dir` | `<in>/audio` | Dossier des mp3 |
| `--keep-audio` | — | Réutilise les mp3 existants (pas de régénération) |
| `--advance` | — | En diaporama, avance à la fin du voiceover de la slide |
| `--advance-buffer` | `600` | Délai après l'audio avant d'avancer (ms) |
| `--no-media-controls` | — | Ne pas afficher la barre de contrôle média (play/pause, progression) |
| `--no-progress-bar` | — | Ne pas afficher la barre de progression audio en bas des slides |

La vitesse (`--speed`) est appliquée par ffmpeg (`atempo`) sans modifier la
hauteur de la voix (défaut `1.0`).

Avec `--advance`, la durée de chaque mp3 (mesurée par `ffprobe`) est inscrite
dans la transition de la slide (« avancer après N ms ») : en diaporama, le
voiceover se lance puis la slide suivante s'affiche automatiquement à la fin
(+ `--advance-buffer` ms de marge). `make pptx` l'active par défaut ;
`make pptx ADVANCE=0` le désactive (la slide ne change alors qu'au clic).

Limite : le découpage reste **par slide** ; sauter à un paragraphe précis du
voiceover n'est pas géré nativement par PowerPoint. Changer de voix ou de
modèle régénère tout l'audio (sauf `--keep-audio`).

## Dossiers et sorties

```text
input-pdf/        PDF source déposé à la main            (gitignoré)
paper-processed/  extraction brute                       (gitignoré)
llm-output/       storyboard, voiceover, audio, .pptx    (gitignoré)
```

```text
paper-processed/
├── text/full_text.md          # texte complet, ordre de lecture, <!-- page N -->
├── figures/<label>.png        # une image par figure (nom = n° réel)
├── tables/<label>.png         # table rendue en image
├── tables/<label>.md          # table en texte brut (best effort)
├── captions/<label>.txt       # légende associée à la figure/table
└── metadata/extraction.json   # index complet (page, bbox, méthode…)

llm-output/
├── storyboard.json            # plan du PPT : slides, puces, image, voiceover
├── voiceover.md               # commentaire oral par slide
├── audio/slide_NN.mp3         # voiceover TTS (si --audio)
├── llm-session.log            # trace complète de la session
└── presentation.pptx          # généré par build_pptx.py
```

## Notes

- `input-pdf/`, `paper-processed/`, `llm-output/`, `config.json`, `tts.json`,
  `.env` et les PDF (`*.pdf`) sont ignorés par Git.
- L'extraction est déterministe et sans LLM ; le storyboard est génératif.
- Le serveur TTS local est sans clé API ; la voix est figée dans `tts.json`.
