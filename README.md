# Registre de recettes — cabinet d'ophtalmologie

Application de saisie quotidienne adossée au classeur `compta jdid .xlsx`.

## Lancer

```powershell
streamlit run "F:\projets claude\claude comptabilite\streamlit_app.py"
```

L'app s'ouvre sur <http://localhost:8501>.

Dépendances : `streamlit`, `pandas`, `altair`, `openpyxl` (lecture et écriture du
classeur) et `reportlab` (export PDF).

```powershell
pip install streamlit pandas altair openpyxl reportlab
```

## Le rythme de travail

La saisie se fait **en fin de mois comptable**, pas au jour le jour. L'app
s'ouvre donc sur le tableau du mois, positionné sur **le mois qui reste à
reprendre** — celui qui suit la dernière journée renseignée. Le parcours normal :

1. remplir le mois dans le tableau, ligne par ligne ;
2. vérifier les colonnes calculées en regard ;
3. écrire le mois dans le classeur — ce qui clôture les journées.

Le mois choisi suit d'une page à l'autre : *Mois comptable* et *Rectifications*
travaillent toujours sur la même période. Les flèches passent au mois précédent
ou suivant, changement d'année compris, et le choix des années court jusqu'à
cinq ans au-delà de l'année en cours — le registre ne s'arrête pas à la dernière
ligne pré-remplie du classeur.

Le tableau affiche **tous les jours du mois**, y compris ceux qui n'existent pas
encore au registre : le classeur s'arrête au 23/01/2027, au-delà les journées se
créent à l'enregistrement. La page *Saisie du jour* reste là pour les journées
saisies à l'unité.

## Les six pages

| Page | À quoi elle sert |
|---|---|
| **Mois comptable** | L'écran de travail : à gauche les colonnes de saisie, éditables ; à droite les colonnes calculées, qui suivent la frappe. C'est là qu'on saisit, qu'on corrige et qu'on rectifie. |
| **Saisie du jour** | En appoint : un bouton par acte au fil de la journée, ou les totaux du jour d'un coup. |
| **Rectifications** | Deux tableaux côte à côte : à gauche le registre réel, non modifiable ; à droite le corrigé, qu'on modifie. L'écart devient une rectification motivée. Suivent le journal des corrections du mois et leur effet sur les totaux. |
| **Tableau de bord** | Évolution mensuelle, composition des recettes, volume de cataractes, récapitulatif annuel. |
| **Classeur Excel** | Écrit les journées saisies dans le `.xlsx`, signale si le fichier a changé sans l'app, liste les sauvegardes, permet de réimporter. |
| **Tarifs** | Tarifs unitaires des nouvelles journées, et historique des tarifs relevés dans le classeur. |

## Quand un tarif change

**Un changement de tarif ne vaut que pour la suite.** Il s'applique aux journées
sans chiffres du **mois en cours de saisie et des mois qui le suivent** — y
compris les lignes déjà présentes dans le classeur mais vides. Une journée qui
porte des chiffres, ou qui est clôturée, garde le tarif sous lequel elle a été
saisie : le passé ne se réécrit pas.

La frontière est le premier jour du mois à reprendre, pas la date du jour : la
saisie se faisant en fin de mois, les journées qu'on remplit sont toujours
passées. Elle ne bouge pas pendant qu'on remplit le mois. Une journée **oubliée
d'un mois déjà travaillé** est vide sans être à venir : elle garde le tarif que
le classeur a inscrit dans sa formule, celui de ses voisines. Sans cette borne,
saisir un jour retrouvé de 2019 le compterait au prix d'aujourd'hui.

Le point à connaître : le classeur est pré-rempli jusqu'au 23/01/2027, et ces
lignes portent dans leurs formules le tarif qui avait cours quand elles ont été
préparées (`=C123*72`). Y écrire seulement les compteurs ferait dire à Excel
autre chose qu'à l'app dès le premier changement de prix. À l'écriture, la
constante de ces formules — et d'elles seules, sur des journées ouvertes dont
tous les montants valent zéro — est donc remise à jour, et le rapport
d'écriture dit exactement ce qui a changé.

La page Tarifs signale d'elle-même combien de journées à venir attendent au
registre avec un tarif dépassé.

## Deux registres, un seul jeu de données

Le **registre réel** porte les valeurs d'origine : celles importées du classeur,
celles saisies au fil de la journée. Il ne s'écrase pas.

Le **registre corrigé** est le registre réel plus le journal des rectifications.
C'est lui qui part dans le classeur et chez le comptable.

Une journée est **ouverte** tant qu'elle n'a pas de chiffres acquis : elle se
saisit et se corrige librement. Elle se **clôture** dès qu'elle est écrite dans
le classeur, ou à la main depuis la page de saisie. À partir de là, elle ne bouge
plus que par une **rectification** :

- elle porte sur un compteur ou un montant saisi d'une journée précise ;
- son **motif est obligatoire**, et reste attaché à la correction ;
- l'ancienne valeur, la nouvelle, la date de saisie sont conservées ;
- rien ne se supprime : revenir en arrière, c'est une rectification de plus, et
  les deux restent au journal.

C'est le principe comptable ordinaire — on ne gomme pas une écriture, on passe
une écriture de correction motivée. Le basculement **Réel / Corrigé** du Journal
et du Tableau de bord montre les deux à tout moment.

### Où se fait quoi

| Ce que vous voulez faire | Où |
|---|---|
| Saisir un mois, corriger une journée pas encore écrite au classeur | **Mois comptable** |
| Corriger une journée déjà écrite au classeur | **Rectifications** |

Une journée se clôture à l'écriture dans le classeur. Avant, elle se corrige
librement ; après, elle se rectifie — avec un motif, et sans que la valeur
d'origine disparaisse. La page *Rectifications* montre les deux registres l'un
à côté de l'autre : le réel à gauche en lecture seule, le corrigé à droite,
modifiable. Ce qui les sépare devient une rectification datée.

### Comment on saisit et corrige un mois

La page **Mois comptable** affiche le mois comme la feuille du classeur, en deux tableaux
alignés : **ce qui se saisit** (C, E, H, J, L, N, P, R, S, T, V) à gauche,
éditable ; **ce que les formules en tirent** (U, X, Z, AB, AC) à droite, avec une
colonne `Δ en attente` qui chiffre l'effet de la modification en cours avant tout
enregistrement.

Chaque tableau porte ses totaux juste au-dessus, calculés sur ce qu'il affiche —
modifications en attente comprises. Sur la page *Rectifications*, le bandeau du
registre corrigé chiffre en plus l'écart au registre réel : on voit l'effet
d'une correction avant de l'enregistrer.

Sous chaque tableau, trois boutons l'emportent en **PDF**, **Excel** ou **CSV** :
le PDF se transmet, le classeur se retravaille, le CSV se relit partout. Les
trois contiennent la même chose — titre, totaux affichés, puis le tableau — et
sont produits en mémoire à la demande : rien n'est écrit sur le disque, et le
classeur du cabinet n'est pas touché. Le CSV emploie les conventions
francophones (`;` en séparateur, virgule décimale, BOM) pour s'ouvrir
directement dans Excel.

En modifiant une cellule, la liste des changements s'affiche sous le tableau,
chacun étiqueté selon son traitement :

- journée **ouverte** → saisie directe, aucun motif ;
- journée **clôturée** → rectification motivée, une par poste modifié.

Le motif n'est demandé que si au moins une journée clôturée est touchée, et le
bouton d'enregistrement reste bloqué tant qu'il est vide. Le tableau n'est
éditable que sur la vue **Corrigé** : le registre réel ne s'édite jamais.

Une saisie de fin de mois ne touche donc que des journées ouvertes et ne produit
aucune rectification. Les rectifications n'apparaissent que sur un mois déjà
écrit dans le classeur.

### Ce qui est saisi sans être enregistré

Une saisie en cours **tient le temps de la session** : elle survit au passage
d'un onglet à l'autre et au retour. Rien n'est écrit en base tant qu'on
n'enregistre pas, et tout se perd à la fermeture de l'app — c'est un filet, pas
une sauvegarde. Le bouton *Tout abandonner* efface la saisie en attente, et
l'onglet *Mois comptable* porte un repère `●` suivi du nombre de journées
modifiées non enregistrées, visible depuis n'importe quelle page.

Le motif en cours de frappe et les tarifs tapés sans être validés se conservent
de la même façon.

> Une rectification corrige une erreur constatée : patient compté deux fois,
> tarif erroné, encaissement porté au mauvais jour. Les deux registres sont donc
> censés converger. Un écart qui grandit sans erreur derrière n'est pas une
> correction.

À l'import, une ligne du classeur qui porte des chiffres arrive clôturée
(2 903 journées) ; les lignes pré-remplies à zéro jusqu'au 23/01/2027 sont des
emplacements de saisie et restent ouvertes (1 227).

## Ce que l'app écrit dans le classeur

Uniquement les **colonnes de saisie** :

- compteurs : `C` APCI, `E` tiers payant, `H` remboursement, `J` assurance, `L` payant, `N` cataracte CNAM, `P` cataracte payante
- montants : `R` laser déclaré, `S` laser non déclaré, `T` divers, `V` dépenses

Toutes les colonnes de montants et de totaux (`D`, `F`, `G`, `I`, `K`, `M`, `O`, `Q`, `U`, `W`, `X`, `Z`, `AA`, `AB`, `AC`, `AD`) restent des **formules Excel**. Le fichier se recalcule à son ouverture.

Une seule exception, décrite plus bas : sur une journée **encore ouverte**, la constante de tarif inscrite dans la formule (`=C123*72`) est remise à jour si le tarif a changé. La formule reste une formule, et une journée clôturée n'est jamais touchée.

Une **copie horodatée** du classeur est déposée dans `sauvegardes/` avant chaque écriture. Si le classeur est ouvert dans Excel au moment de l'écriture, l'app le signale et n'écrit rien.

### Quand le classeur bouge sans l'app

L'app n'est pas seule à écrire dans le fichier : il s'ouvre aussi dans Excel.
Elle relève donc l'état du classeur — date de modification et taille — chaque
fois que les deux sont mis d'accord, c'est-à-dire après chaque import et après
chaque écriture.

Si le fichier a changé depuis ce relevé, la page **Classeur Excel** le dit en
rouge avec les deux dates, et *Mois comptable* porte le même avertissement : ce
qui est affiché peut être en retard sur le fichier. L'écriture reste possible,
mais demande alors de cocher une case — écrire des journées sur un classeur plus
récent que le registre les clôturerait sur des chiffres peut-être dépassés.

Le remède est le **réimport**, en bas de la page Classeur Excel.

Au-delà du 23/01/2027 — dernière ligne pré-remplie du classeur — l'app crée les lignes manquantes en recopiant le style et les formules de la dernière ligne existante, avec les tarifs de la page **Tarifs**.

## Organisation

```
streamlit_app.py      navigation
app_utils.py          connexion partagée, bandeau de totaux, formulaire de rectification
app_pages/            une page par écran
compta/
  config.py           chemins, colonnes du classeur, postes
  model.py            miroir Python des formules Excel
  store.py            registre SQLite : journées, clôture, rectifications
  xlsx_io.py          import et écriture du classeur
  export.py           un tableau en PDF, Excel ou CSV
data/compta.db        registre de travail
sauvegardes/          copies du classeur avant écriture
tests/                tests, sur une copie de la base — jamais sur l'originale
```

Les tests se lancent directement :

```powershell
python tests\test_rectifications.py   # registre figé, journal des corrections
python tests\test_tarifs.py           # changement de prix, jusqu'à l'écriture Excel
python tests\test_export.py           # PDF, Excel et CSV relus et vérifiés
python tests\test_synchronisation.py  # le classeur modifié en dehors de l'app
python tests\test_pages.py            # rendu des six pages, sans navigateur
```

Ils travaillent tous sur des **copies** de la base et du classeur ; les
originaux ne sont jamais ouverts en écriture.

Le chemin du classeur se change dans `compta/config.py`, ou par la variable
d'environnement `COMPTA_XLSX`.

## Ce que l'import a relevé dans le classeur

- **4 130 journées** reprises, du 01/10/2015 au 23/01/2027.
- **31 lignes en double** ignorées : décembre 2022 est saisi deux fois (lignes 2994–3024). Elles restent dans le fichier ; l'app ne les compte pas.
- **897 lignes** où la colonne `AB` utilise `=C+E+H` au lieu de `=C+E+H+J+L`, ce qui oublie les assurances et le payant. L'app retient le compte réel : 51 341 patients contre 38 809 affichés par le classeur.
- La colonne `W` (`=E×11`) ajoute un montant par patient en tiers payant qui n'apparaît dans aucun poste de consultation. Il entre dans les recettes et la caisse, pas dans le CA à déclarer.
- La colonne `AC` (CA à déclarer) **exclut la colonne `Q`** (cataracte payante) : c'est ce qui produit l'écart de 254 572 TND entre recettes et CA déclaré sur l'ensemble de la période.
- La colonne `V` (dépenses) est vide sur toutes les lignes : le classeur ne mesure aucun résultat, seulement un chiffre d'affaires.
- **Deux journées** (21/03/2019 et 23/05/2019) portent une cataracte payante — 1 et 3 actes — pour des recettes nulles : sur ces lignes, la colonne `U` ne reprend pas `Q`. Candidates à rectification.
- La dernière journée qui porte des chiffres est le **31/07/2026** ; tout ce qui suit dans le classeur est pré-rempli à zéro.
