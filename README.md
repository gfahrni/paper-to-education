# pdf-to-education

Transformer un PDF scientifique en matériel pédagogique.

## Vision

À terme, l'objectif est de générer automatiquement un **PowerPoint** ou une
**vidéo éducative** qui mélange :

- du **texte résumé** (généré par un LLM),
- des **figures et tables** conservées en **image**,
- une **voix off** (voiceover).

Le projet avance par étapes :

1. **Extraction PDF** — fragmente le PDF en texte, figures, tables et légendes
   de façon brute et traçable (`extract.py`).
2. **Interprétation LLM** — une session opencode lit l'extraction et produit un
   storyboard de slides + un voiceover (`llm-process.py`), puis un `.pptx`
   (`build_pptx.py`).
3. *(à venir)* export vidéo avec la voix off.

## Convention des dossiers

```
input-pdf/        PDF source déposé à la main
paper-processed/  extraction brute (étape 1)
llm-output/       storyboard, voiceover et .pptx (étape 2)
```

## Étape 1 — Extraction PDF (`extract.py`)

`extract.py` fragmente un PDF sans chercher à l'interpréter :

- **Texte** : reconstruit dans l'ordre de lecture (gestion des colonnes,
  recollage des césures, lettrines), avec des marqueurs `<!-- page N -->`.
- **Boilerplate** : en-têtes, pieds de page et filigranes répétés sont
  détectés et supprimés.
- **Figures** : extraites en image, soit l'image native du PDF, soit un
  recadrage de page en haute résolution (300 dpi par défaut).
- **Tables** : rendues en image + tentative d'extraction texte brute.
- **Légendes** : chaque figure/table est appariée à sa légende.
- **Traçabilité** : un index JSON recense page, bbox, méthode et fichiers
  produits pour chaque élément.

Sorties par défaut dans `paper-processed/` :

```
paper-processed/
├── text/full_text.md          # texte complet, ordre de lecture, <!-- page N -->
├── figures/<label>.png        # une image par figure (nom = n° réel)
├── tables/<label>.png         # table rendue en image
├── tables/<label>.md          # table en texte brut (best effort)
├── captions/<label>.txt       # légende associée à la figure/table
└── metadata/extraction.json   # index complet (page, bbox, méthode…)
```

## Étape 2 — Interprétation LLM (`llm-process.py`)

`llm-process.py` lance une **session opencode non-interactive** qui lit
`paper-processed/` et produit :

```
llm-output/
├── storyboard.json            # plan du PPT : slides, puces, image, voiceover
├── voiceover.md               # commentaire oral par slide
├── llm-session.log            # trace complète de la session
└── presentation.pptx          # généré par build_pptx.py
```

- Modèle par défaut : `opencode/big-pickle` (gratuit), avec **repli automatique**
  sur d'autres modèles gratuits si indisponible.
- La session a accès aux outils de lecture/écriture : elle lit elle-même
  `paper-processed/` et écrit `llm-output/`.
- Le prompt qui pilote la session est versionné dans
  `prompts/llm-process.md`.

## Prérequis

- **Python 3.10+**.
- **opencode** (pour l'étape 2) installé et disponible dans le `PATH` :

  ```bash
  curl -fsSL https://opencode.ai/install | bash   # macOS / Linux
  # ou
  brew install anomalyco/tap/opencode
  ```

- Un provider configuré dans opencode. Le script utilise par défaut des modèles
  **gratuits** ; connecte un provider une fois avec `opencode auth login` (ou
  `/connect` dans le TUI opencode), puis vérifie :

  ```bash
  opencode models | grep big-pickle
  ```

  Si le premier modèle est indisponible, `llm-process.py` bascule
  automatiquement sur les autres modèles gratuits.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pymupdf pillow python-pptx
```

`pdfplumber` est **optionnel** (meilleure détection de tables) :

```bash
pip install pdfplumber
```

## Utilisation

### 1. Extraire le PDF

Dépose le PDF dans `input-pdf/`, puis :

```bash
python extract.py [article.pdf] [--in input-pdf] [--out paper-processed] [--dpi 300]
```

Sans argument, le script prend l'unique PDF de `input-pdf/`.

### 2. Générer le storyboard + voiceover (et le PPT)

```bash
python llm-process.py [--paper paper-processed] [--out llm-output] [--build]
```

| Option | Défaut | Description |
| --- | --- | --- |
| `--paper` | `paper-processed` | Dossier d'extraction |
| `--out` | `llm-output` | Dossier de sortie |
| `--prompt` | `prompts/llm-process.md` | Prompt envoyé à la session |
| `--model` | `opencode/big-pickle` | Modèle (répétable, dans l'ordre) |
| `--timeout` | `1800` | Délai max par session (s) |
| `--build` | — | Génère aussi `presentation.pptx` |
| `--dry-run` | — | Affiche la commande sans exécuter la session |

Exemple complet :

```bash
python extract.py
python llm-process.py --build
```

Pour tester sans consommer de modèle :

```bash
python llm-process.py --dry-run
```

Pour ne régénérer que le PowerPoint depuis un `storyboard.json` existant :

```bash
python build_pptx.py --in llm-output
```

## Feuille de route

- [x] Extraction texte, figures, tables et légendes
- [x] Storyboard + voiceover via LLM (opencode)
- [x] Export PowerPoint (`.pptx`)
- [ ] Export vidéo avec voiceover
- [ ] Choix du modèle / de l'agent en argument de configuration

## Notes

- `input-pdf/`, `paper-processed/`, `llm-output/` et les PDF (`*.pdf`) sont
  ignorés par Git.
- L'étape 1 est déterministe et sans LLM ; l'étape 2 est générative.
