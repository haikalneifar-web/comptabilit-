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

### En un exe, sans rien installer

```powershell
pip install pyinstaller
pyinstaller registre.spec --noconfirm
```

Sort `dist\Registre du cabinet.exe`, **95 Mo**, qui contient Python, Streamlit et
l'app. Un double-clic ouvre **une fenêtre d'application** — pas d'onglets, pas de
barre d'adresse, son propre bouton dans la barre des tâches — et la fermer arrête
le serveur. Comptez une trentaine de secondes au premier écran : l'exe se déplie
dans un dossier temporaire à chaque lancement.

Streamlit est un framework web : son interface est nécessairement une page,
servie en local sur `localhost`. Ce que fait `lancer.py`, c'est la montrer dans
Edge (ou Chrome) en **mode application**, ce qui en retire tout l'habillage de
navigateur. Ni l'un ni l'autre n'étant installé, on retombe sur le navigateur par
défaut, et il faut alors arrêter le logiciel à la main.

Le logiciel n'a pas de console : une panne au démarrage s'affiche en boîte de
dialogue et s'écrit dans `erreur_demarrage.txt`, à côté de l'exe. Lancé deux
fois, il ouvre simplement une fenêtre de plus sur l'instance déjà en place.

**Où vit le registre.** À une adresse fixe, indépendante de l'endroit où se
trouve l'exe :

```
%LOCALAPPDATA%\Registre du cabinet\data\compta.db
```

L'historique ne se reprend donc **qu'une fois**. Déplacer l'exe, le lancer depuis
un raccourci ou le refabriquer ne change rien : il retrouve le même registre.
C'est aussi le fichier à sauvegarder. Lancé depuis les sources (`streamlit run`
ou `python lancer.py`), c'est en revanche le `data\` du projet qui sert — les
deux registres sont distincts.

Le classeur, lui, est toujours lu là où `COMPTA_XLSX` ou `compta/config.py` le
désigne.

`lancer.py` est le point d'entrée de l'exe, et marche aussi depuis les sources
(`python lancer.py`) : c'est le même démarrage que `streamlit run`, en passant
par le bootstrap de Streamlit plutôt que par la ligne de commande.

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

## Les huit pages

| Page | À quoi elle sert |
|---|---|
| **Mois comptable** | L'écran de saisie, ouvert sur le mois à reprendre : une grille pleine largeur, une ligne par journée, et les totaux du mois en tuiles sous le tableau. C'est là qu'on saisit, qu'on corrige et qu'on rectifie. |
| **Totaux du mois** | Les **seize colonnes** que le classeur calcule, journée par journée, en deux tableaux : ce que chaque poste rapporte, puis ce que le classeur en tire. Rien ne s'y saisit ; la saisie en attente sur l'écran précédent y est comprise. |
| **Saisie du jour** | En appoint : un bouton par acte au fil de la journée, ou les totaux du jour d'un coup. |
| **Bordereaux** | Édite le bordereau du mois — le mois du registre dans un classeur autonome, montants en formules — le range, en garde l'historique et montre l'évolution. |
| **Rectifications** | Deux tableaux côte à côte : à gauche le registre réel, non modifiable ; à droite le corrigé, qu'on modifie. L'écart devient une rectification motivée. Suivent le journal des corrections du mois et leur effet sur les totaux. |
| **Tableau de bord** | Évolution mensuelle, composition des recettes, volume de cataractes, récapitulatif annuel. |
| **Classeur Excel** | Écrit les journées saisies dans le `.xlsx`, signale si le fichier a changé sans l'app, liste les sauvegardes, permet de réimporter. |
| **Tarifs** | Tarifs unitaires des nouvelles journées, et historique des tarifs relevés dans le classeur. |

### La mise en page de l'écran de saisie

**C'est un écran de saisie, et rien d'autre** : la secrétaire y remplit le mois,
elle n'a pas à lire ce que les formules en tirent. La page porte donc une seule
grille, en pleine largeur — les onze colonnes de saisie du classeur, une ligne
par journée.

**Sous le tableau**, un bandeau de six tuiles donne les totaux du mois :
patients, chirurgie, recettes, CA déclaré, caisse, dû CNAM ; puis une ligne de
détail (cataractes, laser, divers, dépenses). Quand une modification est en
attente, chaque tuile affiche en plus ce qu'elle changerait.

Le **détail par journée** est sur la page suivante, **Totaux du mois**, avec son
export. Les deux écrans partagent le même calcul (`app_utils.calculs_du_mois`) :
deux copies finiraient par diverger, et ce sont les formules du classeur qu'elles
reproduisent. La **saisie en attente** — tapée, pas encore enregistrée — y est
comprise : elle vit dans l'état de session et suit d'une page à l'autre.

### Les seize colonnes calculées

Le classeur calcule seize colonnes, et la page des totaux les montre **toutes**
— et rien d'autre. Chaque groupe donne **ses totaux du mois en tuiles** ; seul
le second donne aussi son détail journée par journée, celui du premier
reprendrait la grille de saisie de la page précédente, au tarif près :

- **ce que chaque poste rapporte** — D (APCI), F et G (tiers payant reçu et
  reste), I (remboursement), K (assurance), M (payant), O et Q (cataractes),
  W (TVA tiers payant) : le compteur de la journée multiplié par son tarif ;
- **ce que le classeur en tire** — U (recettes), X (caisse), Z (dû CNAM),
  AA (à verser à la banque), AB (patients), AC (CA à déclarer), AD (TVA
  déduite).

La page ne porte rien d'autre : ni colonne de saisie, ni état de la journée. La
colonne « Δ en attente » n'apparaît que s'il y a une saisie en attente — sans
elle, ce serait une colonne de zéros sur un écran qui ne montre que du calculé.

**L'export, lui, sort les seize colonnes jour par jour** — y compris celles qui
ne sont à l'écran qu'en tuiles.

La liste vit à un seul endroit, `model.CALCULES`, et **des tests imposent**
qu'elle couvre `config.CALC_COLS` exactement, que chacune de ses entrées soit
réellement à l'écran — en tuile ou en colonne —, que **chaque tuile porte bien
le total du mois de sa colonne** recalculé depuis le registre, et que le calcul
dont l'export est tiré les porte toutes. Sans ces garde-fous, une colonne
calculée peut rester hors de l'écran sans que rien ne le signale : c'est arrivé
à « à verser à la banque » sur les bordereaux, puis à elle et dix autres ici.

Les **largeurs de colonnes sont posées en pixels**, pas laissées au calcul
automatique : à douze colonnes, les en-têtes se faisaient rogner (« Rembo »,
« Catarac », « Laser d »). Le nom entier du poste reste dans l'infobulle.

Trois choses sont **tenues par des tests** : chaque colonne affichée a une
largeur posée, la somme de ces largeurs tient dans la page, et l'ordre de
l'écran — la grille, puis les tuiles — est vérifié sur l'arbre de rendu.
Ajouter une colonne sans rééquilibrer, ou remonter les tuiles au-dessus du
tableau, fait échouer la suite. Un test vérifie aussi qu'aucune colonne
calculée ne s'est glissée dans la grille de saisie.

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

Encore faut-il qu'il y ait une formule à lire. Quelques centaines de cellules de
montant du classeur sont **vides — pas à zéro, sans formule du tout** : il n'y a
alors aucun tarif inscrit nulle part. L'import prend celui de la ligne lisible la
plus proche, celle d'avant à égalité de distance, plutôt que de retomber sur le
tarif d'aujourd'hui. Là où le compteur en face est rempli, ce sont des actes que
le classeur ne valorise pas : l'import les signale poste par poste, voir plus bas.

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

## Le bordereau mensuel

Le bordereau, c'est **un mois du registre extrait dans un classeur autonome** :
colonnes A→AD, en-tête sur trois lignes, journées à partir de la ligne 4 — la
feuille du classeur, sur un seul mois et dans un fichier neuf. Une deuxième
feuille, *Récapitulatif*, dit d'où il vient, ce qu'il totalise et à quels tarifs.

Le point qui fait tout : **les montants restent des formules**. Seuls les
compteurs et les montants saisis sont écrits en valeur — C, E, H, J, L, N, P puis
R, S, T, V ; D, F, G, I, K, M, O, Q, U, W, X, Y, Z, AA, AB, AC et AD sont les
formules du classeur, réécrites au numéro de ligne du bordereau, et la dernière
ligne les additionne. Corriger un compteur dans le bordereau met ses totaux à
jour tout seul. Les totaux du récapitulatif sont eux-mêmes des renvois vers cette
ligne de total, jamais des nombres recopiés.

**Chaque journée porte son tarif**, celui que le registre lui connaît : une
journée de 2019 s'écrit au prix de 2019, visible à l'œil nu dans la formule
(`=C12*52`). Le récapitulatif signale un tarif qui a changé en cours de mois
plutôt que d'en choisir un.

Une seule liberté prise sur le modèle : la colonne **Y — « à la charge STAR »**,
que le classeur annonce en en-tête mais ne remplit plus depuis 2016. Le bordereau
la remplit (`=K{ligne}`) ; aucun total n'en dépend, ni ici ni dans le classeur.

**Il rejoint le dossier du mois.** Le cabinet range déjà ses mois dans
`F:\comptabilité\<année>\<mois> <année>\` ; le bordereau y est déposé sous le nom
`bordereau-<année>-<mois>-<mois>.xlsx`, qui ne ressemble à aucun de ceux qui s'y
trouvent — **il ne recouvre jamais un fichier existant**. Les noms de dossiers
sont irréguliers (`juin2016`, `juuillet 2014`, `ocobre 2024`, `aout` sans année) :
l'app les reconnaît à une faute de frappe près, et ne crée un dossier que si
aucun ne convient. Faute de dossier d'année, elle retombe sur `bordereaux/<année>/`
dans le projet.

**Rien ne s'écrase.** Un mois a toujours un bordereau courant, au même chemin,
c'est lui qu'on envoie. Rééditer pousse l'ancien dans `bordereaux/archives/` du
projet — les archives restent chez nous, le dossier du comptable ne garde que le
bordereau en cours — et **ajoute une ligne au journal des éditions** : la page
montre l'écart entre deux éditions du même mois, et la courbe d'évolution marque
d'un point les mois déjà édités.

Le classeur du cabinet n'est jamais ouvert pour ça : le bordereau se fabrique à
partir du registre de l'app.

## Ce qui a été transmis au comptable

Les classeurs mensuels rangés dans `F:\comptabilité\<année>\<mois>\` sont les
chiffres **partis chez le comptable**. Ils diffèrent du registre. L'app les lit
pour l'historique — et seulement pour ça : elle ne les modifie pas, ne s'en sert
jamais comme source, et le bordereau continue de sortir avec les chiffres du
registre.

Leur forme bouge d'une année à l'autre — de S à BD colonnes, les totaux glissant
de place — mais deux repères tiennent sur les seize années : **la date est en
colonne B**, et les totaux se retrouvent par le **texte de leur en-tête**
(`CA A DECLARER`, `TVA DED`, `patients à DECLARER`), jamais par leur position.
Un poste absent du fichier est rapporté « non lu », pas zéro. Les valeurs lues
sont celles qu'Excel a mises en cache : rien n'est recalculé.

Une centaine de classeurs, une dizaine de secondes — d'où un cache dans la table
`transmis`, relu **seulement pour les fichiers qui ont bougé** (date et taille).
Nos propres bordereaux sont exclus de cette lecture : déposés dans le même
dossier, et enregistrés un jour depuis Excel, ils prendraient la place du fichier
réellement transmis et on comparerait le registre à lui-même.

La page montre alors, pour le mois choisi, le CA, la TVA et les patients
transmis face à ceux du registre, et la courbe d'évolution gagne une troisième
série.

## Ce que l'app écrit dans le classeur

Uniquement les **colonnes de saisie** :

- compteurs : `C` APCI, `E` tiers payant, `H` remboursement, `J` assurance, `L` payant, `N` cataracte CNAM, `P` cataracte payante
- montants : `R` laser déclaré, `S` laser non déclaré, `T` divers, `V` dépenses

Toutes les colonnes de montants et de totaux (`D`, `F`, `G`, `I`, `K`, `M`, `O`, `Q`, `U`, `W`, `X`, `Z`, `AA`, `AB`, `AC`, `AD`) restent des **formules Excel**. Le fichier se recalcule à son ouverture.

Deux exceptions, toutes deux réservées aux journées **encore ouvertes** — celles dont tous les montants valent zéro, où rien d'historique ne peut donc changer. Une journée clôturée n'est jamais touchée.

1. La constante de tarif inscrite dans la formule (`=C123*72`) est remise à jour si le tarif a changé. La formule reste une formule.
2. Une colonne de montant **sans aucune formule** en reçoit une (`=J123*70`), au tarif que porte la journée. Sans ça, écrire le compteur en face ferait disparaître la recette : la colonne `U` additionnerait une cellule vide. C'est ce qui a coûté 97 actes entre 2018 et 2019, et la seule façon que ça se reproduise serait de saisir aujourd'hui une de ces journées restées vides. Si le cas se présente sur une journée **acquise**, l'app n'y touche pas et le signale dans le rapport d'écriture.

Le rapport d'écriture dit exactement ce qui a été posé ou réaligné, colonne par colonne.

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
lancer.py             point d'entrée de l'exe (et de `python lancer.py`)
registre.spec         recette PyInstaller
app_pages/            une page par écran
compta/
  config.py           chemins, colonnes du classeur, postes
  model.py            miroir Python des formules Excel
  store.py            registre SQLite : journées, clôture, rectifications, bordereaux
  xlsx_io.py          import et écriture du classeur
  bordereau.py        le mois du registre en classeur autonome, formules comprises
  dossier_comptable.py  où ranger un bordereau, et lecture de ce qui a été transmis
  export.py           un tableau en PDF, Excel ou CSV
data/compta.db        registre de travail
sauvegardes/          copies du classeur avant écriture
bordereaux/           bordereaux mensuels édités, `archives/` pour les éditions passées
tests/                tests, sur une copie de la base — jamais sur l'originale
```

Les tests se lancent directement :

```powershell
python tests\test_rectifications.py   # registre figé, journal des corrections
python tests\test_tarifs.py           # changement de prix, jusqu'à l'écriture Excel
python tests\test_export.py           # PDF, Excel et CSV relus et vérifiés
python tests\test_synchronisation.py  # le classeur modifié en dehors de l'app
python tests\test_import_tarifs.py    # actes comptés sans montant, tarifs hérités
python tests\test_bordereau.py        # bordereau : formules, tarifs, dossier du comptable
python tests\test_pages.py            # rendu des huit pages, sans navigateur
```

Ils travaillent tous sur des **copies** de la base et du classeur — ou sur un
classeur fabriqué pour l'occasion ; les originaux ne sont jamais ouverts en
écriture.

Le chemin du classeur se change dans `compta/config.py`, ou par la variable
d'environnement `COMPTA_XLSX`.

## Ce que l'import a relevé dans le classeur

- **4 130 journées** reprises, du 01/10/2015 au 23/01/2027.
- **31 lignes en double** ignorées : décembre 2022 est saisi deux fois (lignes 2994–3024). Elles restent dans le fichier ; l'app ne les compte pas.
- **897 lignes** où la colonne `AB` utilise `=C+E+H` au lieu de `=C+E+H+J+L`, ce qui oublie les assurances et le payant. L'app retient le compte réel : 51 341 patients contre 38 809 affichés par le classeur.
- La colonne `W` (`=E×11`) ajoute un montant par patient en tiers payant qui n'apparaît dans aucun poste de consultation. Il entre dans les recettes et la caisse, pas dans le CA à déclarer.
- La colonne `AC` (CA à déclarer) **exclut la colonne `Q`** (cataracte payante) : c'est ce qui produit l'écart de 254 572 TND entre recettes et CA déclaré sur l'ensemble de la période.
- La colonne `V` (dépenses) est vide sur toutes les lignes : le classeur ne mesure aucun résultat, seulement un chiffre d'affaires.
- **97 actes comptés sans montant en face, ≈ 12 015 TND jamais portés au CA.** Sur 76 journées de 2018–2019, un compteur est rempli alors que sa cellule de montant est **vide — pas à zéro, sans formule du tout**. La colonne `U` additionne alors une cellule vide : ces actes ne sont dans aucun total, ni dans le classeur ni ici.
  - `P` → `Q` cataracte payante : **8 journées, 15 actes**, du 21/02/2019 au 18/07/2019, soit 9 000 TND au tarif voisin de 600. Deux de ces journées (21/03/2019 et 23/05/2019) affichent des recettes strictement nulles alors qu'elles portent 1 et 3 cataractes.
  - `J` → `K` assurance : **68 journées, 82 actes**, du 04/06/2018 au 31/07/2019, soit 3 015 TND aux tarifs voisins (30 puis 45).
  - L'import les signale et **hérite du tarif des lignes voisines** au lieu de retomber sur le tarif d'aujourd'hui — sans quoi ces actes seraient valorisés à 70 et 750 le jour où l'une de ces journées serait rectifiée. Les montants du classeur, eux, ne sont pas touchés : les porter au CA est une rectification, journée par journée, avec son motif.
  - Ce sont des **oublis de saisie**. Pour qu'ils ne se reproduisent pas, l'écriture pose la formule manquante sur toute journée ouverte avant d'y écrire un compteur (voir plus haut). Les **145 journées à partir du 01/09/2026 sont intactes** : toutes leurs formules sont en place, la saisie des mois à venir ne risque rien.
- La dernière journée qui porte des chiffres est le **31/08/2026** ; tout ce qui suit dans le classeur est pré-rempli à zéro.
