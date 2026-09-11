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
├── audio/slide_NN.mp3         # voiceover TTS (si --audio)
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

### Raccourcis (Makefile)

Les étapes courantes sont encapsulées dans le `Makefile` (voix ElevenLabs
`George` par défaut) :

```bash
make            # affiche l'aide
make extract    # PDF -> paper-processed/
make storyboard # paper-processed/ -> llm-output/ (storyboard + voiceover)
make pptx       # llm-output/ -> presentation.pptx + voiceover ElevenLabs
make preview    # écoute un échantillon de la voix

make pptx VOICE=Alice       # surcharge la voix
make pptx SPEED=1.0         # vitesse normale
make pptx VOICE=Alice SPEED=1.1
```

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
| `--config` | `config.json` | Config locale (modèles, clés API) |
| `--model` | `opencode/big-pickle` | Modèle (répétable, dans l'ordre) |
| `--timeout` | `1800` | Délai max par session (s) |
| `--build` | — | Génère aussi `presentation.pptx` |
| `--audio` | — | Avec `--build` : voiceover TTS (lecture auto) |
| `--tts` | `say` | Moteur : `say` (macOS) ou `elevenlabs` |
| `--voice` | selon `--tts` | Voix ElevenLabs (nom/id) ou voix macOS |
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

Pour ne régénérer que le PowerPoint depuis un `storyboard.json` existant :

```bash
python build_pptx.py --in llm-output
```

### 3. Choisir le modèle / connecter une API

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

`config.json` et `.env` sont **ignorés par Git** ; seul
`config.example.json` est versionné.

### 4. Voiceover automatique dans le PPT

Avec `--audio`, un fichier TTS est généré depuis le `voiceover` de chaque slide
et intégré au `.pptx` en **lecture automatique** : en diaporama, avancer ou
reculer déclenche le voiceover de la slide affichée (et donc le rejoue si tu
reviens en arrière).

Deux moteurs, via `--tts` :

| `--tts` | Qualité | Dépendances | Voix |
| --- | --- | --- | --- |
| `say` (défaut) | robotique | macOS `say` + `ffmpeg` | `Thomas`, `Amélie`… (`say -v '?'`) |
| `elevenlabs` | voix humaines très naturelles | clé API ElevenLabs | nom ou id de voix |

```bash
# Voix macOS (gratuit, hors-ligne)
python llm-process.py --build --audio

# Voix humaines ElevenLabs (voix par défaut : George)
python llm-process.py --build --audio --tts elevenlabs

# Sur un storyboard existant
python build_pptx.py --in llm-output --audio --tts elevenlabs --voice George

# Raccourci équivalent (voir Makefile)
make pptx
```

#### Configurer ElevenLabs

1. Crée un compte sur elevenlabs.io, puis récupère ta clé API (Profil → API key).
2. Ajoute-la dans `config.json` (gitignoré) :

   ```json
   {
     "env": { "ELEVENLABS_API_KEY": "sk_..." }
   }
   ```

   ou exporte-la : `export ELEVENLABS_API_KEY=sk_...`.
3. Liste les voix de ton compte et écoute-les :

   ```bash
   # noms, ids et lien d'écoute fourni par ElevenLabs (gratuit)
   python build_pptx.py --tts elevenlabs --list-voices

   # échantillon en français de chaque voix, joué localement (consomme des crédits)
   python build_pptx.py --tts elevenlabs --preview

   # seulement quelques voix, avec ton propre texte
   python build_pptx.py --tts elevenlabs --voice "Alice,Matilda,River" \
       --preview "Voici comment j'explique un mécanisme physiopathologique."
   ```

   Les échantillons sont écrits dans `llm-output/voice-preview/` (réécoutables
   avec `afplay <fichier>`). Les voix natives françaises de la **Voice Library**
   donnent le meilleur résultat ; `--voice` accepte un nom ou un `voice_id`.

- Modèle par défaut : `eleven_multilingual_v2` (naturel). Pour économiser les
  crédits : `--tts-model eleven_flash_v2_5`.
- L'offre gratuite est limitée (≈ 10 000 caractères/mois) : un run complet de
  14 slides la consomme presque entièrement. Utilise `--keep-audio` pour ne pas
  régénérer les mp3 déjà présents.

| Option | Défaut | Description |
| --- | --- | --- |
| `--audio` | — | Génère et intègre le voiceover TTS (lecture auto) |
| `--tts` | `say` | `say` (macOS) ou `elevenlabs` |
| `--voice` | `Thomas` / `George` | Voix macOS ou nom/id ElevenLabs |
| `--tts-model` | `eleven_multilingual_v2` | Modèle ElevenLabs |
| `--rate` | `180` | Débit `say` (mots/minute) |
| `--speed` | `1.25` (ElevenLabs) / `1.0` | Vitesse de lecture (hauteur conservée) |
| `--audio-dir` | `llm-output/audio` | Dossier des mp3 |
| `--keep-audio` | — | Réutilise les mp3 existants (pas de régénération) |

La vitesse (`--speed`) est appliquée par ffmpeg (`atempo`) sans modifier la
hauteur de la voix ; ElevenLabs est à `1.25` par défaut, `say` à `1.0`
(utiliser `--rate` dans ce cas).

Limite : le découpage reste **par slide** ; sauter à un paragraphe précis du
voiceover n'est pas géré nativement par PowerPoint.

## Feuille de route

- [x] Extraction texte, figures, tables et légendes
- [x] Storyboard + voiceover via LLM (opencode)
- [x] Export PowerPoint (`.pptx`)
- [x] Voiceover TTS en lecture automatique par slide
- [x] Moteur TTS ElevenLabs (voix humaines) en plus de `say`
- [x] Choix du modèle / de la clé API via `config.json`
- [ ] Export vidéo MP4 (slides + voix off)
- [ ] Choix de l'agent opencode en argument

## Notes

- `input-pdf/`, `paper-processed/`, `llm-output/`, `config.json`, `.env` et les
  PDF (`*.pdf`) sont ignorés par Git.
- L'étape 1 est déterministe et sans LLM ; l'étape 2 est générative.
