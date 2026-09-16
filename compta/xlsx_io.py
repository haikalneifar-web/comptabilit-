"""Lecture et écriture du classeur « compta jdid .xlsx ».

Règle de sécurité : l'app n'écrit QUE dans les colonnes de saisie
(C, E, H, J, L, N, P, R, S, T, V). Toutes les colonnes de montants et de
totaux restent des formules Excel, intactes. Une sauvegarde horodatée est
créée avant chaque écriture.
"""

from __future__ import annotations

import datetime as dt
import re
import shutil
from copy import copy
from pathlib import Path

import openpyxl
from openpyxl.utils import column_index_from_string

from .config import (BACKUP_DIR, COL_DATE, COL_JOUR, JOURS_FR, SAISIE_COLS,
                     SHEET_NAME, TARIF_COLS, XLSX_PATH)
from .model import COMPTEURS, MONTANTS, TARIFS_DEFAUT, Journee
from .store import ecrire_jour, meta_get, meta_set

_RE_TARIF = re.compile(r"^=\s*[A-Z]{1,3}\d+\s*\*\s*([0-9]+(?:[.,][0-9]+)?)\s*$")
_IDX = {cle: column_index_from_string(col) for cle, col in SAISIE_COLS.items()}
_IDX_TARIF = {cle: (column_index_from_string(m), column_index_from_string(c))
              for cle, (m, c) in TARIF_COLS.items()}
_IDX_DATE = column_index_from_string(COL_DATE)
_IDX_JOUR = column_index_from_string(COL_JOUR)

# colonnes calculées lues depuis le cache d'Excel à l'import
_IDX_CALC = {
    "recettes": "U", "caisse": "X", "charge_cnam": "Z",
    "banque": "AA", "patients": "AB", "ca_declare": "AC", "tva_deduite": "AD",
}
_IDX_CALC = {k: column_index_from_string(v) for k, v in _IDX_CALC.items()}


def _nombre(v) -> float:
    if isinstance(v, bool) or v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(" ", "").replace(",", "."))
        except ValueError:
            return 0.0
    return 0.0


def _tarif_depuis_formule(valeur, montant_cache, compteur) -> float | None:
    """Extrait le tarif unitaire d'une formule `=C123*72`, sinon le déduit."""
    if isinstance(valeur, str):
        m = _RE_TARIF.match(valeur.strip())
        if m:
            return float(m.group(1).replace(",", "."))
    if compteur:
        montant = _nombre(montant_cache)
        if montant:
            return montant / compteur
    return None


def sauvegarder(chemin: Path = XLSX_PATH) -> Path:
    """Copie horodatée du classeur avant toute écriture."""
    horo = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    cible = BACKUP_DIR / f"{chemin.stem}_{horo}{chemin.suffix}"
    shutil.copy2(chemin, cible)
    return cible


# --- synchronisation registre / classeur --------------------------------------
#
# L'app n'est pas seule à écrire dans le classeur : il s'ouvre aussi dans Excel.
# En août 2026, un mois entier y a été saisi à la main sans que le registre en
# sache rien — il est resté un mois en retard sans le moindre signal. On relève
# donc l'état du fichier à chaque fois que les deux sont mis d'accord, pour
# pouvoir dire ensuite qu'il a bougé depuis.

_META_SOURCE = "xlsx_source"


def _empreinte(chemin: Path) -> dict:
    st = chemin.stat()
    return {
        "mtime": st.st_mtime,
        "taille": st.st_size,
        "releve_le": dt.datetime.now().isoformat(timespec="seconds"),
    }


def marquer_synchronise(conn, chemin: Path = XLSX_PATH) -> None:
    """Registre et classeur viennent d'être mis d'accord : on note l'état du
    fichier. Appelé après un import comme après une écriture."""
    if chemin.exists():
        meta_set(conn, _META_SOURCE, _empreinte(chemin))


def etat_synchronisation(conn, chemin: Path = XLSX_PATH) -> dict:
    """Le classeur a-t-il changé depuis que le registre l'a lu ?

    `connu` est faux tant qu'aucun relevé n'a été pris — registre importé avant
    la mise en place de ce contrôle. Dans ce cas on ne prétend rien.
    """
    if not chemin.exists():
        return {"connu": False, "absent": True, "a_jour": False}
    releve = meta_get(conn, _META_SOURCE)
    if not releve:
        return {"connu": False, "absent": False, "a_jour": False}
    actuel = _empreinte(chemin)
    # une seconde de tolérance : les systèmes de fichiers n'ont pas tous la
    # même résolution sur les dates de modification
    bouge = (abs(actuel["mtime"] - releve["mtime"]) > 1
             or actuel["taille"] != releve["taille"])
    return {
        "connu": True,
        "absent": False,
        "a_jour": not bouge,
        "lu_le": dt.datetime.fromisoformat(releve["releve_le"]),
        "modifie_le": dt.datetime.fromtimestamp(actuel["mtime"]),
        "taille_lue": releve["taille"],
        "taille_actuelle": actuel["taille"],
    }


# --- import ------------------------------------------------------------------

def importer(conn, chemin: Path = XLSX_PATH, progress=None) -> dict:
    """Charge tout l'historique du classeur dans la base.

    Retourne un rapport : lignes lues, doublons ignorés, bornes de dates.
    """
    wb_f = openpyxl.load_workbook(chemin, data_only=False)
    wb_v = openpyxl.load_workbook(chemin, data_only=True)
    ws_f, ws_v = wb_f[SHEET_NAME], wb_v[SHEET_NAME]

    vues: dict[dt.date, int] = {}
    doublons: list[tuple[int, dt.date]] = []
    ab_divergents: list[int] = []
    importees = 0
    total = ws_f.max_row

    for r in range(1, total + 1):
        if progress and r % 400 == 0:
            progress(r / total)
        brut = ws_f.cell(row=r, column=_IDX_DATE).value
        if not isinstance(brut, dt.datetime):
            continue
        date = brut.date()
        if date in vues:
            doublons.append((r, date))
            continue
        vues[date] = r

        j = Journee(date=date, source="xlsx", ligne_xlsx=r)
        for cle in COMPTEURS:
            j.__setattr__(cle, int(_nombre(ws_f.cell(row=r, column=_IDX[cle]).value)))
        for cle in MONTANTS:
            j.__setattr__(cle, _nombre(ws_f.cell(row=r, column=_IDX[cle]).value))

        tarifs = dict(TARIFS_DEFAUT)
        for cle, (ic, icnt) in _IDX_TARIF.items():
            compteur = _nombre(ws_f.cell(row=r, column=icnt).value)
            t = _tarif_depuis_formule(
                ws_f.cell(row=r, column=ic).value,
                ws_v.cell(row=r, column=ic).value,
                compteur,
            )
            if t is not None:
                tarifs[cle] = t
        j.tarifs = tarifs

        # Une ligne qui porte des chiffres est un fait acquis : elle arrive
        # clôturée et ne se corrigera plus que par rectification motivée. Le
        # classeur est en revanche pré-rempli de lignes vides jusqu'au
        # 23/01/2027 : ce sont des emplacements de saisie, pas des journées.
        j.cloture = not j.vide

        # Montants : on reprend le cache d'Excel, pour rester fidèle au classeur
        # même là où d'anciennes lignes utilisent une variante de formule.
        calc = {}
        for cle, ic in _IDX_CALC.items():
            v = ws_v.cell(row=r, column=ic).value
            calc[cle] = _nombre(v) if isinstance(v, (int, float)) else float(getattr(j, cle))
        calc["actes_chirurgie"] = j.actes_chirurgie

        # Exception : le nombre de patients. La colonne AB existe en deux versions
        # dans le classeur (`=C+E+H+J+L` et `=C+E+H`) ; la seconde oublie les
        # assurances et le payant. On retient toujours le compte réel.
        if abs(calc["patients"] - j.patients) > 0.5:
            ab_divergents.append(r)
        calc["patients"] = float(j.patients)

        ecrire_jour(conn, j, calc=calc, marquer=False, commit=False, force=True)
        importees += 1

    conn.commit()
    marquer_synchronise(conn, chemin)
    dates = sorted(vues)
    return {
        "lignes": importees,
        "doublons": doublons,
        "ab_divergents": ab_divergents,
        "premiere": dates[0] if dates else None,
        "derniere": dates[-1] if dates else None,
        "derniere_ligne": max(vues.values()) if vues else 0,
    }


# --- export ------------------------------------------------------------------

def _index_dates(ws) -> dict[dt.date, int]:
    idx: dict[dt.date, int] = {}
    for r in range(1, ws.max_row + 1):
        v = ws.cell(row=r, column=_IDX_DATE).value
        if isinstance(v, dt.datetime) and v.date() not in idx:
            idx[v.date()] = r
    return idx


def _fmt(t: float) -> str:
    return str(int(t)) if float(t).is_integer() else str(t)


def _creer_ligne(ws, r: int, date: dt.date, modele: int, tarifs: dict[str, float]) -> None:
    """Crée une nouvelle ligne de journée en copiant le style du modèle."""
    for c in range(1, 31):
        src = ws.cell(row=modele, column=c)
        dst = ws.cell(row=r, column=c)
        if src.has_style:
            dst._style = copy(src._style)

    ws.cell(row=r, column=_IDX_JOUR).value = JOURS_FR[date.weekday()]
    cell_date = ws.cell(row=r, column=_IDX_DATE)
    cell_date.value = dt.datetime(date.year, date.month, date.day)
    cell_date.number_format = ws.cell(row=modele, column=_IDX_DATE).number_format

    for cle in COMPTEURS:
        ws.cell(row=r, column=_IDX[cle]).value = 0

    t = tarifs
    ws[f"D{r}"] = f"=C{r}*{_fmt(t['t_apci'])}"
    ws[f"F{r}"] = f"=E{r}*{_fmt(t['t_tp_recu'])}"
    ws[f"G{r}"] = f"=E{r}*{_fmt(t['t_tp_reste'])}"
    ws[f"I{r}"] = f"=H{r}*{_fmt(t['t_remb'])}"
    ws[f"K{r}"] = f"=J{r}*{_fmt(t['t_star'])}"
    ws[f"M{r}"] = f"=L{r}*{_fmt(t['t_pay'])}"
    ws[f"O{r}"] = f"=N{r}*{_fmt(t['t_cat_cnam'])}"
    ws[f"Q{r}"] = f"=P{r}*{_fmt(t['t_cat_pay'])}"
    ws[f"W{r}"] = f"=E{r}*{_fmt(t['t_tva_tp'])}"
    ws[f"U{r}"] = f"=D{r}+F{r}+I{r}+K{r}+M{r}+O{r}+Q{r}+S{r}+T{r}+R{r}+W{r}"
    ws[f"X{r}"] = f"=SUM(F{r},I{r},M{r},T{r},W{r})-V{r}"
    ws[f"Z{r}"] = f"=SUM(D{r},G{r},O{r})"
    ws[f"AA{r}"] = f"=SUM(F{r},I{r},K{r},M{r},O{r}/2)"
    ws[f"AB{r}"] = f"=C{r}+E{r}+H{r}+J{r}+L{r}"
    ws[f"AC{r}"] = f"=D{r}+F{r}+G{r}+I{r}+K{r}+M{r}+O{r}+R{r}"
    ws[f"AD{r}"] = f"=AC{r}-(AC{r}/1.06)"


def _aligner_tarifs(ws, r: int, tarifs: dict[str, float]) -> list[tuple[str, float, float]]:
    """Remet le tarif en vigueur dans les formules d'une ligne encore ouverte.

    Le classeur est pré-rempli de lignes à zéro jusqu'au 23/01/2027, avec le
    tarif qui avait cours quand elles ont été préparées. Y écrire seulement les
    compteurs ferait dire à Excel autre chose qu'à l'app : `=C123*72` quand le
    tarif est passé à 74.

    On ne touche qu'à une formule de la forme `=C123*72`, et seulement à sa
    constante — la formule reste une formule. Réservé aux journées ouvertes,
    dont tous les montants valent zéro : aucun montant historique ne change.
    """
    changements = []
    for cle, (col_montant, col_compteur) in TARIF_COLS.items():
        valeur = ws[f"{col_montant}{r}"].value
        m = _RE_TARIF.match(valeur.strip()) if isinstance(valeur, str) else None
        if not m:
            continue
        ancien = float(m.group(1).replace(",", "."))
        nouveau = float(tarifs[cle])
        if abs(ancien - nouveau) < 0.005:
            continue
        ws[f"{col_montant}{r}"] = f"={col_compteur}{r}*{_fmt(nouveau)}"
        changements.append((col_montant, ancien, nouveau))
    return changements


def exporter(conn, journees: list[Journee], chemin: Path = XLSX_PATH,
             tarifs_nouveaux: dict[str, float] | None = None) -> dict:
    """Écrit les journées données dans le classeur. Retourne un rapport."""
    if not journees:
        return {"ecrites": 0, "creees": 0, "sauvegarde": None, "lignes": [],
                "tarifs_alignes": []}

    sauvegarde = sauvegarder(chemin)
    wb = openpyxl.load_workbook(chemin, data_only=False)
    ws = wb[SHEET_NAME]
    index = _index_dates(ws)

    derniere_date = max(index) if index else None
    derniere_ligne = index[derniere_date] if derniere_date else 4
    tarifs_nouveaux = tarifs_nouveaux or dict(TARIFS_DEFAUT)

    ecrites, creees, detail = 0, 0, []
    tarifs_alignes: list[tuple[dt.date, str, float, float]] = []

    for j in sorted(journees, key=lambda x: x.date):
        r = index.get(j.date)
        if r is None:
            # prolonge le classeur jour par jour pour rester continu
            if derniere_date is None or j.date <= derniere_date:
                detail.append((j.date, None, "ignorée — ligne introuvable"))
                continue
            modele = derniere_ligne
            curseur = derniere_date
            ligne = derniere_ligne
            while curseur < j.date:
                curseur += dt.timedelta(days=1)
                ligne += 1
                _creer_ligne(ws, ligne, curseur, modele, tarifs_nouveaux)
                index[curseur] = ligne
                creees += 1
            derniere_date, derniere_ligne = j.date, ligne
            r = ligne

        # une ligne encore ouverte peut porter un tarif périmé dans ses formules
        if not j.cloture:
            for col, ancien, nouveau in _aligner_tarifs(ws, r, j.tarifs):
                tarifs_alignes.append((j.date, col, ancien, nouveau))

        for cle in COMPTEURS:
            ws.cell(row=r, column=_IDX[cle]).value = int(getattr(j, cle))
        for cle in MONTANTS:
            v = float(getattr(j, cle))
            ws.cell(row=r, column=_IDX[cle]).value = v if v else 0
        ecrites += 1
        detail.append((j.date, r, "écrite"))

    if wb.calculation is not None:
        wb.calculation.fullCalcOnLoad = True
    wb.save(chemin)
    # c'est l'app qui vient d'écrire : le fichier a changé sans désaccord
    marquer_synchronise(conn, chemin)

    return {
        "ecrites": ecrites,
        "creees": creees,
        "sauvegarde": sauvegarde,
        "lignes": detail,
        "tarifs_alignes": tarifs_alignes,
    }


def infos_classeur(chemin: Path = XLSX_PATH) -> dict:
    if not chemin.exists():
        return {"existe": False}
    st = chemin.stat()
    return {
        "existe": True,
        "taille": st.st_size,
        "modifie": dt.datetime.fromtimestamp(st.st_mtime),
        "chemin": str(chemin),
    }
