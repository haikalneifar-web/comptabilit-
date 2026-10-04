"""Un cabinet fictif pour les tests : un classeur fabriqué et son registre importé.

Les tests n'ont besoin ni du classeur réel (`F:\\...`) ni de `data/compta.db`, qui
est du côté de la machine du cabinet et jamais dans le dépôt. On fabrique ici un
classeur qui a la même forme — A→AD, journées à partir de la ligne 4, formules
`=C4*72` — et on l'importe dans une base neuve.

Ce qu'il contient, et sur quoi les tests s'appuient :

* une ligne par jour du 01/10/2015 au 23/01/2027, comme le classeur du cabinet ;
* des chiffres jusqu'au 31/08/2026 (dimanches à zéro) : ces journées arrivent
  clôturées ; tout ce qui suit est pré-rempli à zéro, donc ouvert ;
* trois époques de tarifs : 2018 (payant à 40), 2019-2024 (payant à 60), puis
  les tarifs d'aujourd'hui (APCI 72, payant 70…), que portent aussi les lignes
  pré-remplies du futur ;
* quelques cataractes, pour que les colonnes N, O, P et Q servent.

Usage, avant tout `import compta` :

    import atelier
    CLASSEUR, BASE = atelier.installer()

`CLASSEUR` est déjà désigné par `COMPTA_XLSX`. `BASE` est le registre importé, à
copier pour chaque test — jamais à ouvrir en écriture.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJET = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJET))

# à changer dès que la fabrication change : le cache est rebâti
VERSION = "2"
CACHE = Path(tempfile.gettempdir()) / f"registre_tests_cabinet_v{VERSION}"

DEBUT = dt.date(2015, 10, 1)
DERNIERE_LIGNE = dt.date(2027, 1, 23)
DERNIERE_SAISIE = dt.date(2026, 8, 31)

_COMPTEUR_DE = {"D": "C", "F": "E", "G": "E", "I": "H", "K": "J", "M": "L",
                "O": "N", "Q": "P", "W": "E"}

_ANCIENS = {"D": 52, "F": 9, "G": 21, "I": 40, "K": 30, "M": 40,
            "O": 600, "Q": 600, "W": 11}
_MOYENS = {"D": 60, "F": 15, "G": 21, "I": 60, "K": 60, "M": 60,
           "O": 650, "Q": 700, "W": 11}
_RECENTS = {"D": 72, "F": 20, "G": 21, "I": 70, "K": 70, "M": 70,
            "O": 700, "Q": 750, "W": 11}


def _tarifs(jour: dt.date) -> dict[str, int]:
    if jour.year < 2019:
        return _ANCIENS
    if jour.year < 2025:
        return _MOYENS
    return _RECENTS


def _compteurs(jour: dt.date) -> dict[str, int]:
    """Une journée de travail : tout à zéro le dimanche."""
    if jour > DERNIERE_SAISIE or jour.weekday() == 6:
        return {}
    c = {"C": 2, "E": 1 + jour.day % 3, "H": 1, "J": 1, "L": 5 + jour.day % 4}
    if jour.day % 10 == 0:
        c["N"] = 1
    if jour.day % 15 == 0:
        c["P"] = 1
    return c


def fabriquer_classeur(chemin: Path) -> None:
    import openpyxl

    from compta.config import SHEET_NAME

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws["A1"] = "Registre de recettes (classeur fabriqué pour les tests)"

    jour, r = DEBUT, 4
    while jour <= DERNIERE_LIGNE:
        ws[f"A{r}"] = jour.strftime("%A").upper()
        ws[f"B{r}"] = dt.datetime(jour.year, jour.month, jour.day)
        compteurs = _compteurs(jour)
        for col in "CEHJLNP":
            ws[f"{col}{r}"] = compteurs.get(col, 0)
        for col in "RSTV":
            ws[f"{col}{r}"] = 0
        for col, t in _tarifs(jour).items():
            ws[f"{col}{r}"] = f"={_COMPTEUR_DE[col]}{r}*{t}"
        ws[f"U{r}"] = f"=D{r}+F{r}+I{r}+K{r}+M{r}+O{r}+Q{r}+S{r}+T{r}+R{r}+W{r}"
        ws[f"X{r}"] = f"=F{r}+I{r}+M{r}+T{r}+W{r}-V{r}"
        ws[f"Z{r}"] = f"=D{r}+G{r}+O{r}"
        ws[f"AA{r}"] = f"=F{r}+I{r}+K{r}+M{r}+O{r}/2"
        ws[f"AB{r}"] = f"=C{r}+E{r}+H{r}+J{r}+L{r}"
        ws[f"AC{r}"] = f"=D{r}+F{r}+G{r}+I{r}+K{r}+M{r}+O{r}+R{r}"
        ws[f"AD{r}"] = f"=AC{r}-AC{r}/1.06"
        jour += dt.timedelta(days=1)
        r += 1
    wb.save(chemin)


def _bâtir() -> None:
    """Fabrique le classeur et le registre importé dans `CACHE`."""
    from compta import store, xlsx_io

    tmp = Path(tempfile.mkdtemp(dir=CACHE.parent))
    classeur, base = tmp / "cabinet.xlsx", tmp / "cabinet.db"
    fabriquer_classeur(classeur)

    ancienne = store.DB_PATH
    store.DB_PATH = base
    try:
        conn = store.connect()
        store.init_db(conn)
        xlsx_io.importer(conn, chemin=classeur)
        # la page de démarrage a déjà passé : sans cela l'app n'ouvre que Démarrage
        store.meta_set(conn, "import_fait", True)
        conn.close()
    finally:
        store.DB_PATH = ancienne

    try:
        tmp.rename(CACHE)
    except OSError:                 # un autre test l'a bâti entre-temps
        shutil.rmtree(tmp, ignore_errors=True)


def installer() -> tuple[Path, Path]:
    """Désigne le classeur fabriqué (COMPTA_XLSX) et rend (classeur, base)."""
    # `compta.config` lit COMPTA_XLSX à l'import : on la pose d'abord, quitte à
    # bâtir ensuite avec un chemin qui n'existe pas encore.
    os.environ["COMPTA_XLSX"] = str(CACHE / "cabinet.xlsx")
    if not (CACHE / "cabinet.db").exists():
        _bâtir()
    return CACHE / "cabinet.xlsx", CACHE / "cabinet.db"
