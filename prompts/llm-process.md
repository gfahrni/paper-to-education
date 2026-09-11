# Tâche : transformer une extraction PDF en support de présentation éducatif

Tu es un expert en vulgarisation scientifique médicale. Tu prépares une
présentation de congrès destinée à des professionnels de santé ou des
étudiants avancés, à partir d'un article scientifique.

## Contexte

Le dossier `paper-processed/` contient l'extraction **brute** d'un article, produite par
`extract.py` :

- `paper-processed/text/full_text.md` — texte complet dans l'ordre de lecture, avec des
  marqueurs `<!-- page N -->`.
- `paper-processed/metadata/extraction.json` — index des figures et tables : `id`,
  `label`, `page`, `caption`, chemin `image`, `caption_file`, `pixel_size`.
- `paper-processed/captions/*.txt` — légende associée à chaque figure/table.
- `paper-processed/figures/*.png` et `paper-processed/tables/*.png` — images extraites.

**Lis ces fichiers toi-même** avant de produire quoi que ce soit. Commence par
`paper-processed/text/full_text.md` et `paper-processed/metadata/extraction.json`. Parcours ensuite
les légendes pour comprendre le contenu des figures et tables.

## Livrables

Tu dois écrire **exactement deux fichiers**.

### 1. `llm-output/storyboard.json`

Un JSON strict, sans commentaire, de cette forme :

```json
{
  "title": "Titre de la présentation",
  "source": "Référence bibliographique de l'article (auteurs, année, revue)",
  "audience": "Public visé",
  "slides": [
    {
      "id": 1,
      "layout": "title",
      "title": "Titre de la slide",
      "bullets": [],
      "image": null,
      "image_caption": null,
      "voiceover": "Texte parlé pour cette slide, en français, 3 à 6 phrases."
    },
    {
      "id": 2,
      "layout": "content",
      "title": "Contexte",
      "bullets": [
        "Point clé 1",
        "Point clé 2"
      ],
      "image": null,
      "image_caption": null,
      "voiceover": "Texte parlé, en français, qui développe ce qui est affiché."
    },
    {
      "id": 3,
      "layout": "image",
      "title": "Mécanismes physiopathologiques",
      "bullets": ["Un seul point de synthèse si utile"],
      "image": "paper-processed/figures/figure_1.png",
      "image_caption": "Figure 1 — légende courte et lisible",
      "voiceover": "Texte parlé qui explique l'image en détail."
    }
  ]
}
```

Règles du schéma :

- `layout` vaut `"title"`, `"content"` ou `"image"`.
- `image` est un chemin **exact** vers un fichier existant de `paper-processed/figures/`
  ou `paper-processed/tables/`, ou `null`. N'invente jamais de chemin.
- `image_caption` est `null` quand `image` est `null`.
- `bullets` est une liste de chaînes courtes (max ~12 mots chacune).
- `voiceover` est **toujours** présent, en français, et plus détaillé que la
  slide : c'est ce que le présentateur dit à l'oral pour expliquer le contenu.

### 2. `llm-output/voiceover.md`

Le même contenu oral, en clair, un bloc par slide :

```markdown
# Voiceover — Titre de la présentation

## Slide 1 — Titre de la slide
Texte parlé de la slide 1.

## Slide 2 — Contexte
Texte parlé de la slide 2.
```

Les textes de `voiceover.md` doivent être identiques à ceux du champ
`voiceover` de `storyboard.json`.

## Consignes de fond

- Produis entre **8 et 14 slides**.
- Structure pédagogique attendue : titre, contexte/motivation, objectif, points
  clés, figures/tables importantes, implications cliniques, conclusion,
  éventuellement limites.
- Intègre les figures et tables **pertinentes** via le champ `image` : au moins
  2 slides de type `"image"` si l'article en contient.
- Le voiceover explique, relie et nuance ; il ne se contente pas de lire les
  puces.
- Reste **fidèle à l'article** : n'invente aucune donnée, chiffre ou résultat.
  Si une information est incertaine, formule-la prudemment.
- Langue : **français**. Les termes scientifiques peuvent rester en anglais
  lorsqu'ils sont d'usage courant.

## Méthode

1. Lis `paper-processed/text/full_text.md` et `paper-processed/metadata/extraction.json`.
2. Lis les légendes pertinentes dans `paper-processed/captions/`.
3. Rédige le plan des slides, puis le voiceover de chaque slide.
4. Écris `llm-output/storyboard.json` (JSON valide, encodage UTF-8).
5. Écris `llm-output/voiceover.md`.
6. Vérifie que les deux fichiers existent et que le JSON est valide, puis
   affiche un court résumé (nombre de slides, images utilisées).

Ne crée aucun autre fichier que ces deux-là.
