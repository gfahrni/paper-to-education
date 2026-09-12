# Tâche : transformer une extraction PDF en support de présentation éducatif

Tu es un clinicien expert qui présente un article en **journal club** ou en
congrès, devant des professionnels de santé ou des étudiants avancés. Tu
prépares les slides **et** le discours oral qui les accompagne.

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
      "voiceover": "Texte parlé pour cette slide, en français, 3 à 5 phrases courtes."
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
      "voiceover": "Texte parlé, en français, qui dit ce que la slide ne dit pas."
    },
    {
      "id": 3,
      "layout": "image",
      "title": "Mécanismes physiopathologiques",
      "bullets": ["Un seul point de synthèse si utile"],
      "image": "paper-processed/figures/figure_1.png",
      "image_caption": "Figure 1 — légende courte et lisible",
      "voiceover": "Texte parlé qui utilise l'image comme preuve, sans la décrire."
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
- `voiceover` est **toujours** présent, en français, **3 à 5 phrases** écrites
  **comme on parle** (voir « Ton du voiceover »). C'est ce que le présentateur
  dit à l'oral : il apporte du sens, pas une description de ce qui est affiché.

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

- Produis entre **8 et 20 slides**, proportionnellement à la longueur de
  l'article et à son nombre de grandes sections. Vise **en moyenne une slide par
  section principale** ; ne dépasse 14 que si l'article le justifie (plusieurs
  figures/tables ou sous-parties distinctes). Chaque slide doit porter une seule
  idée.
- Structure pédagogique attendue : titre, contexte/motivation, objectif, points
  clés, figures/tables importantes, implications cliniques, conclusion,
  éventuellement limites.
- Intègre les figures et tables **pertinentes** via le champ `image` : au moins
  2 slides de type `"image"` si l'article en contient.
- Le voiceover est un **discours** : il explique, relie, nuance et prend
  position ; il ne lit pas les puces (voir « Ton du voiceover »).
- Reste **fidèle à l'article** : n'invente aucune donnée, chiffre ou résultat.
  Si une information est incertaine, formule-la prudemment.
- Langue : **français**. Les termes scientifiques peuvent rester en anglais
  lorsqu'ils sont d'usage courant.

## Ton du voiceover : un discours, pas un commentaire de figure

Tu écris ce qu'un clinicien **dit** en journal club ou en congrès. L'audience
voit la slide : ne la décris pas. Parle comme à des pairs, à l'oral.

- **Une slide = une idée.** Formule-la d'abord, appuie-la ensuite.
- **Arc de chaque slide** : (1) une transition qui relie à la slide précédente,
  (2) le message à retenir, (3) la preuve ou le chiffre qui le soutient,
  (4) la portée ou la limite. La transition est obligatoire sauf pour la slide
  de titre et, plus souplement, pour la conclusion.
- **Ne décris jamais une figure.** Interdits : « cette figure montre / illustre /
  présente / résume », « ce tableau compare », « on y voit », « le panneau A…
  le panneau B… ». Tu peux désigner une figure, mais tu commentes ce qu'elle
  *implique*, pas ce qu'elle contient.
- **1 à 2 chiffres marquants maximum**, remis en contexte. Jamais de liste de
  chiffres. Traduis : « un odds ratio de 4 chez l'homme, c'est un signal fort ».
- **Phrases courtes** (idéalement moins de 20 mots), voix active, mots simples.
  Bannis les tournures écrites : « il convient de souligner », « les données
  observationnelles identifient », « on observe que ».
- **Prends position** : dis ce qui est solide, ce qui est préliminaire, ce qui
  manque. On doit entendre une lecture critique, pas un résumé neutre.
- **Longueur** : 3 à 5 phrases (~50-80 mots) par slide.

### Exemple (slide avec figure)

Mauvais — décrit l'image :

> « Cette figure regroupe les données de plusieurs études. Le panneau A montre
> les taux de dissection selon le sexe, le panneau B détaille la proportion
> d'hommes dans les cohortes FMD avec ou sans dissection. »

Bon — raconte et interprète :

> « Un point contre-intuitif, maintenant. La FMD touche surtout les femmes,
> mais quand elle se complique d'une dissection, elle frappe surtout les hommes.
> Ce graphique compile plusieurs cohortes et le signal est constant. Pourquoi ?
> On ne sait pas encore — et c'est une vraie question ouverte. »

## Méthode

1. Lis `paper-processed/text/full_text.md` et `paper-processed/metadata/extraction.json`.
2. Lis les légendes pertinentes dans `paper-processed/captions/`.
3. Rédige le plan des slides, puis le voiceover de chaque slide dans le ton
   d'un discours (voir « Ton du voiceover »).
4. **Relis chaque voiceover** : s'il commence par décrire une figure ou
   enchaîne des chiffres, réécris-le.
5. Écris `llm-output/storyboard.json` (JSON valide, encodage UTF-8).
6. Écris `llm-output/voiceover.md`.
7. Vérifie que les deux fichiers existent, que le JSON est valide et que les
   voiceovers de `voiceover.md` sont identiques à ceux du JSON, puis affiche un
   court résumé (nombre de slides, images utilisées).

Ne crée aucun autre fichier que ces deux-là.
