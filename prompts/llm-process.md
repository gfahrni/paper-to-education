# Tâche : transformer une extraction PDF en support de présentation éducatif

Tu prépares un support de présentation pédagogique à partir d'un ou plusieurs
articles scientifiques. Ce support comporte des slides **et** le discours oral
qui les accompagne.

Le registre et la profondeur attendus sont précisés plus bas par les sections
« Mode » et « Profondeur ». **Lis-les avant de commencer.**

## Contexte

L'extraction est produite par `extract.py` et décrite en tête de ce prompt. Elle
peut contenir une seule étude (structure `text/`, `figures/`, `tables/`,
`captions/`, `metadata/`) ou plusieurs études regroupées sous `sources/`.

Commence toujours par lire `metadata/sources.json` : il liste chaque source, son
titre, son nombre de pages, son texte complet et son index de figures/tables.
Puis parcours, pour chaque source :

- `…/text/full_text.md` — texte complet dans l'ordre de lecture, avec des
  marqueurs `<!-- page N -->` ;
- `…/metadata/extraction.json` — index des figures et tables : `id`, `label`,
  `page`, `caption`, chemin `image`, `caption_file`, `pixel_size` ;
- `…/captions/*.txt` — légende associée à chaque figure/table ;
- `…/figures/*.png` et `…/tables/*.png` — images extraites.

**Lis ces fichiers toi-même** avant de produire quoi que ce soit.

## Livrables

Tu dois écrire **exactement deux fichiers** (trois en profondeur `extensive`,
voir « Profondeur »).

### 1. `storyboard.json`

Un JSON strict, sans commentaire, de cette forme :

```json
{
  "title": "Titre de la présentation",
  "source": "Référence bibliographique (auteurs, année, revue)",
  "audience": "Public visé",
  "slides": [
    {
      "id": 1,
      "layout": "title",
      "title": "Titre de la slide",
      "bullets": [],
      "image": null,
      "image_caption": null,
      "voiceover": "Texte parlé pour cette slide, en français."
    },
    {
      "id": 2,
      "layout": "content",
      "title": "Contexte",
      "bullets": ["Point clé 1", "Point clé 2"],
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

- `layout` vaut `"title"`, `"content"`, `"image"` ou `"section"`.
  `"section"` affiche un simple séparateur de chapitre (titre centré) ; utile
  surtout pour une présentation longue, pas obligatoire.
- `image` est un chemin **exact** vers un fichier existant (sous
  `paper-processed/figures/` ou `paper-processed/tables/`), ou `null`.
  N'invente jamais de chemin.
- `image_caption` est `null` quand `image` est `null`.
- `bullets` est une liste de chaînes courtes (max ~12 mots chacune).
- `voiceover` est **toujours** présent, en français, écrit **comme on parle**
  (voir « Ton du voiceover »). C'est ce que le présentateur dit à l'oral : il
  apporte du sens, pas une description de ce qui est affiché.

### 2. `voiceover.md`

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

## Règles communes

- **Fidélité absolue** : n'invente aucune donnée, chiffre ou résultat. Si une
  information est incertaine, formule-la prudemment.
- **Une slide = une idée.** Formule-la d'abord, appuie-la ensuite.
- Intègre les figures et tables **pertinentes** via le champ `image` (au moins
  2 slides de type `"image"` si le contenu en contient).
- Le voiceover est un **discours** : il explique, relie, nuance et prend
  position ; il ne lit pas les puces.
- **Langue : français.** Les termes scientifiques peuvent rester en anglais
  lorsqu'ils sont d'usage courant.

## Ton du voiceover : un discours, pas un commentaire de figure

Tu écris ce qu'un clinicien **dit** en présentant. L'audience voit la slide : ne
la décris pas. Parle comme à des pairs, à l'oral.

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

### Exemple (slide avec figure)

Mauvais — décrit l'image :

> « Cette figure regroupe les données de plusieurs études. Le panneau A montre
> les taux de dissection selon le sexe, le panneau B détaille la proportion
> d'hommes dans les cohortes. »

Bon — raconte et interprète :

> « Un point contre-intuitif, maintenant. La maladie touche surtout les femmes,
> mais quand elle se complique, elle frappe surtout les hommes. Ce graphique
> compile plusieurs cohortes et le signal est constant. Pourquoi ? On ne sait pas
> encore — et c'est une vraie question ouverte. »

## Méthode

1. Lis `metadata/sources.json`, puis le texte et l'index de chaque source.
2. Lis les légendes pertinentes et repère les figures/tables à réutiliser.
3. Rédige le plan des slides, puis le voiceover de chaque slide dans le ton
   d'un discours (voir « Ton du voiceover »), en respectant « Mode » et
   « Profondeur ».
4. **Relis chaque voiceover** : s'il commence par décrire une figure ou enchaîne
   des chiffres, réécris-le.
5. Écris `storyboard.json` (JSON valide, encodage UTF-8).
6. Écris `voiceover.md`.
7. Vérifie que les deux fichiers existent, que le JSON est valide et que les
   voiceovers de `voiceover.md` sont identiques à ceux du JSON, puis affiche un
   court résumé (nombre de slides, images utilisées).

Ne crée aucun autre fichier que ceux demandés.
