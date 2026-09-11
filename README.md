# pdf-to-education

Transformer un PDF scientifique en matériel pédagogique.

## Vision

À terme, l'objectif est de générer automatiquement un **PowerPoint** ou une
**vidéo éducative** qui mélange :

- du **texte résumé** (généré par un LLM),
- des **figures et tables** conservées en **image**,
- une **voix off** (voiceover).

Pour y parvenir, la première brique — et l'état actuel du projet — est
l'**extraction brute et traçable** du PDF : texte dans l'ordre de lecture,
figures et tables isolées en images, légendes associées. L'interprétation
(sections, résumé, storyboard…) est volontairement laissée au LLM en aval.

## État actuel : extraction PDF

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

## Structure des sorties

Par défaut dans `paper/` :

```
paper/
├── text/full_text.md          # texte complet, ordre de lecture, <!-- page N -->
├── figures/<label>.png        # une image par figure (nom = n° réel)
├── tables/<label>.png         # table rendue en image
├── tables/<label>.md          # table en texte brut (best effort)
├── captions/<label>.txt       # légende associée à la figure/table
└── metadata/extraction.json   # index complet (page, bbox, méthode…)
```

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pymupdf pillow
```

`pdfplumber` est **optionnel** (meilleure détection de tables) :

```bash
pip install pdfplumber
```

## Utilisation

```bash
python extract.py article.pdf [--out paper] [--dpi 300]
```

| Option | Défaut | Description |
| --- | --- | --- |
| `pdf` | — | PDF source (positionnel) |
| `--out` | `paper` | Dossier de sortie |
| `--dpi` | `300` | Résolution des recadrages d'image |

Exemple :

```bash
python extract.py robberechts-et-al-2026-fibromuscular-dysplasia.pdf
```

## Feuille de route

- [x] Extraction texte, figures, tables et légendes
- [ ] Résumé et structuration par un LLM
- [ ] Génération d'un storyboard (slides / scènes)
- [ ] Export PowerPoint
- [ ] Export vidéo avec voiceover

## Notes

- Le dossier `paper/` et les PDF (`*.pdf`) sont ignorés par Git.
- Aucune dépendance à un LLM dans cette étape : le script reste générique et
  déterministe.
