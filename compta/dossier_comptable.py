"""Le dossier mensuel du comptable : où ranger un bordereau, et ce qui y est déjà.

`F:\\comptabilité\\<année>\\<mois> <année>\\` — seize années de dossiers mensuels,
un classeur par mois, transmis au comptable. Ce module fait deux choses :

1. **retrouver le dossier d'un mois** pour y ranger le bordereau. Les noms sont
   irréguliers — `juin2016`, `juuillet 2014`, `ocobre 2024`, `aout` sans année,
   `fevrier  2016` avec deux espaces — alors on compare sur un nom normalisé, à
   une faute de frappe près, et on crée le dossier seulement si rien ne convient ;

2. **lire ce qui a déjà été transmis**, pour le porter à l'historique. Ces
   fichiers **ne sont pas le registre** : ce sont les chiffres qui sont partis
   chez le comptable, et ils en diffèrent. On les lit, on ne les corrige pas, et
   on ne s'en sert jamais comme source.

La forme des fichiers bouge d'une année à l'autre — le nombre de colonnes va de
S à BD — mais deux repères tiennent sur les seize années : **la date est en
colonne B**, et les totaux se retrouvent par le **texte de leur en-tête**
(`CA A DECLARER`, `TVA DED`, `patients à DECLARER`…), jamais par leur position.
Les valeurs lues sont celles qu'Excel a mises en cache en enregistrant : ces
fichiers ne sont jamais recalculés ici.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

from .config import XLSX_PATH

# le dossier du comptable est celui qui contient le classeur du cabinet
RACINE = XLSX_PATH.parent

# noms de mois tels qu'ils apparaissent dans les dossiers : sans accent
MOIS_DOSSIER = [
    "janvier", "fevrier", "mars", "avril", "mai", "juin",
    "juillet", "aout", "septembre", "octobre", "novembre", "decembre",
]

# un dossier de factures n'est pas un dossier de mois, même s'il en porte le nom
EXCLUS = ("facture", "retenu", "declaration", "steg", "telecom", "copie")


def sans_accent(texte) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(texte))
                   if unicodedata.category(c) != "Mn").lower()


def _normaliser(nom: str) -> str:
    """Un nom de dossier réduit à ce qui l'identifie : mots, sans accent ni année."""
    plat = sans_accent(nom).replace("_", " ").replace("-", " ")
    plat = re.sub(r"\b(19|20)\d{2}\b", " ", plat)     # l'année s'enlève
    return re.sub(r"\s+", " ", plat).strip()


def _distance(a: str, b: str) -> int:
    """Levenshtein, borné à ce dont on a besoin : repérer une faute de frappe."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 2:
        return 99
    precedente = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        courante = [i]
        for j, cb in enumerate(b, start=1):
            courante.append(min(precedente[j] + 1, courante[j - 1] + 1,
                                precedente[j - 1] + (ca != cb)))
        precedente = courante
    return precedente[-1]


def mois_du_nom(nom: str) -> int | None:
    """Le numéro de mois que porte un nom de dossier, à une faute près.

    `juuillet 2014` → 7, `ocobre 2024` → 10, `juin2016` → 6, `aout` → 8.
    Retourne None pour `factures avril 2019`, `STEG`, `2015_03_16`.
    """
    plat = _normaliser(nom)
    if not plat or any(mot in plat for mot in EXCLUS):
        return None
    tete = plat.split()[0]
    for numero, mois in enumerate(MOIS_DOSSIER, start=1):
        if tete == mois or _distance(tete, mois) <= 1:
            return numero
    # `juin2016` : l'année collée au mois, que `_normaliser` n'a pas détachée
    for numero, mois in enumerate(MOIS_DOSSIER, start=1):
        if re.fullmatch(rf"{mois}\d*", tete):
            return numero
    return None


def nom_dossier(annee: int, mois: int) -> str:
    """Le nom qu'on donnerait au dossier d'un mois : `septembre 2026`."""
    return f"{MOIS_DOSSIER[mois - 1]} {annee}"


def dossier_du_mois(annee: int, mois: int, racine: Path | None = None,
                    creer: bool = False) -> Path | None:
    """Le dossier du comptable pour ce mois, tel qu'il existe ou tel qu'il faut.

    On ne crée rien sans `creer=True` : la page doit pouvoir dire « ce dossier
    n'existe pas encore » avant d'y écrire quoi que ce soit.
    """
    racine = Path(racine) if racine else RACINE
    annuel = racine / str(annee)

    if annuel.is_dir():
        exact = annuel / nom_dossier(annee, mois)
        if exact.is_dir():
            return exact
        # à défaut du nom canonique, celui qui désigne le même mois
        for candidat in sorted(annuel.iterdir()):
            if candidat.is_dir() and mois_du_nom(candidat.name) == mois:
                return candidat

    if not creer:
        return None
    cible = annuel / nom_dossier(annee, mois)
    cible.mkdir(parents=True, exist_ok=True)
    return cible


# --- lecture des fichiers transmis -------------------------------------------

COL_DATE = 2        # la date est en colonne B dans les seize années

# libellé interne -> motif cherché dans l'en-tête, normalisé
POSTES = {
    "ca_declare": "ca a declarer",
    "tva_deduite": "tva ded",
    "patients": "patients a declarer",
    "recettes": "recettes",
    "banque": "a verser a la banque",
    "caisse": "caisse",
    "depenses": "depenses",
}


def entetes(ws) -> dict[int, str]:
    """Le texte d'en-tête de chaque colonne, fusions dépliées et accents ôtés.

    Sans déplier les fusions, `a verser à la banque` — étalé sur trois lignes et
    parfois fusionné — ne se lirait que depuis sa cellule de tête.
    """
    fusion: dict[tuple[int, int], object] = {}
    for plage in ws.merged_cells.ranges:
        valeur = ws.cell(row=plage.min_row, column=plage.min_col).value
        for r in range(plage.min_row, plage.max_row + 1):
            for c in range(plage.min_col, plage.max_col + 1):
                fusion[(r, c)] = valeur

    par_colonne: dict[int, str] = {}
    for c in range(1, ws.max_column + 1):
        morceaux = []
        for r in (1, 2, 3):
            valeur = ws.cell(row=r, column=c).value
            if valeur is None:
                valeur = fusion.get((r, c))
            if valeur is not None and str(valeur).strip():
                morceaux.append(str(valeur).strip())
        if morceaux:
            # une fusion répète le même mot sur ses colonnes : on ne le garde
            # qu'une fois, sinon « recettes recettes recettes »
            vus, propre = set(), []
            for mot in sans_accent(" ".join(morceaux)).split():
                if mot not in vus:
                    vus.add(mot)
                    propre.append(mot)
            par_colonne[c] = " ".join(propre)
    return par_colonne


def _colonne(tetes: dict[int, str], motif: str) -> int | None:
    """La colonne dont l'en-tête porte ce motif. La plus à droite l'emporte :
    `caisse` apparaît parfois en sous-titre avant sa vraie colonne."""
    trouvees = [c for c, texte in tetes.items() if motif in texte]
    return max(trouvees) if trouvees else None


def _somme(ws, colonne: int, lignes: list[int]) -> float | None:
    """Somme des valeurs d'une colonne sur les lignes de journée.

    `None` si la colonne ne porte aucun nombre : mieux vaut dire « non lu »
    qu'annoncer zéro.
    """
    total, vus = 0.0, 0
    for r in lignes:
        valeur = ws.cell(row=r, column=colonne).value
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
            total += float(valeur)
            vus += 1
    return total if vus else None


def lire(chemin: Path) -> dict | None:
    """Ce qu'un fichier transmis dit de son mois, ou None si ce n'en est pas un.

    Les valeurs sont celles qu'Excel a mises en cache : le fichier n'est ni
    ouvert en écriture, ni recalculé.
    """
    chemin = Path(chemin)
    try:
        wb = load_workbook(chemin, data_only=True, read_only=False)
    except Exception:   # noqa: BLE001 — fichier corrompu, protégé, ou pas un xlsx
        return None

    try:
        for ws in wb.worksheets:
            lignes, mois_vus = [], Counter()
            for r in range(1, ws.max_row + 1):
                valeur = ws.cell(row=r, column=COL_DATE).value
                if isinstance(valeur, dt.datetime):
                    lignes.append(r)
                    mois_vus[(valeur.year, valeur.month)] += 1
            # moins d'une semaine de dates : ce n'est pas une feuille mensuelle
            if len(lignes) < 7 or not mois_vus:
                continue

            (annee, mois), jours = mois_vus.most_common(1)[0]
            tetes = entetes(ws)
            totaux: dict[str, float | None] = {}
            for cle, motif in POSTES.items():
                colonne = _colonne(tetes, motif)
                totaux[cle] = _somme(ws, colonne, lignes) if colonne else None

            if totaux["ca_declare"] is None:
                continue        # sans CA à déclarer, le fichier ne nous dit rien

            etat = chemin.stat()
            return {
                "chemin": str(chemin),
                "feuille": ws.title,
                "mois": f"{annee}-{mois:02d}",
                "jours": jours,
                "lignes": len(lignes),
                "modifie_le": dt.datetime.fromtimestamp(etat.st_mtime)
                              .isoformat(timespec="seconds"),
                "taille": etat.st_size,
                "totaux": {k: v for k, v in totaux.items() if v is not None},
            }
        return None
    finally:
        wb.close()


# Nos propres bordereaux, posés dans le dossier du mois. Il faut les écarter de
# la lecture : ils portent les chiffres du registre, et le jour où l'un d'eux
# serait ouvert puis enregistré dans Excel — ce qui lui donnerait des valeurs en
# cache — il prendrait, étant le plus récent, la place du fichier réellement
# transmis dans la comparaison. On lirait alors le registre contre lui-même.
_NOTRE_BORDEREAU = re.compile(r"^bordereau-\d{4}-\d{2}-", re.IGNORECASE)


def est_notre_bordereau(nom: str) -> bool:
    return bool(_NOTRE_BORDEREAU.match(nom))


def fichiers(racine: Path | None = None,
             annees: list[int] | None = None) -> list[Path]:
    """Tous les classeurs rangés sous les dossiers d'année, les nôtres exceptés."""
    racine = Path(racine) if racine else RACINE
    if not racine.is_dir():
        return []
    trouves: list[Path] = []
    for annuel in sorted(racine.iterdir()):
        if not annuel.is_dir() or not re.fullmatch(r"(19|20)\d{2}", annuel.name):
            continue
        if annees and int(annuel.name) not in annees:
            continue
        trouves += [p for p in sorted(annuel.rglob("*.xlsx"))
                    if not p.name.startswith("~$")
                    and not est_notre_bordereau(p.name)]
    return trouves


def inventaire(racine: Path | None = None, annees: list[int] | None = None,
               progress=None) -> list[dict]:
    """Tous les fichiers mensuels lisibles, dans l'ordre des mois.

    Lent : une centaine de classeurs à ouvrir. La page passe par le cache du
    registre (`store.rafraichir_transmis`) et ne rappelle ceci qu'à la demande.
    """
    tous = fichiers(racine, annees)
    lus = []
    for i, chemin in enumerate(tous):
        if progress:
            progress((i + 1) / len(tous), chemin.name)
        fiche = lire(chemin)
        if fiche:
            lus.append(fiche)
    return sorted(lus, key=lambda f: (f["mois"], f["modifie_le"]))
