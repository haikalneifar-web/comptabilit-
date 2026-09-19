"""Chemins, colonnes du classeur et définition des postes.

Le classeur « compta jdid .xlsx » est entièrement piloté par des formules :
seules les colonnes de saisie ci-dessous contiennent des valeurs. Tout le
reste (montants, recettes, caisse, TVA) est recalculé par Excel.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# --- chemins -----------------------------------------------------------------

# Monté en exe (PyInstaller), le code est déplié dans un dossier temporaire que
# Windows efface à la fermeture : y ranger le registre le ferait disparaître à
# chaque sortie. Le ranger à côté de l'exe ne vaut pas mieux — déplacer l'exe,
# ou le lancer depuis un raccourci posé ailleurs, repartirait sur un registre
# vide et redemanderait tout l'historique. Le registre a donc **une adresse
# fixe**, celle des données applicatives de l'utilisateur, et l'exe la retrouve
# où qu'il soit.
if getattr(sys, "frozen", False):
    _donnees = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    PROJECT_DIR = Path(_donnees or Path.home()) / "Registre du cabinet"
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
else:
    PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
BACKUP_DIR = PROJECT_DIR / "sauvegardes"
# Les bordereaux mensuels produits par l'app. `archives/` garde les éditions
# précédentes d'un mois : on ne réécrit jamais un bordereau par-dessus un autre
# sans en conserver la trace.
BORDEREAUX_DIR = PROJECT_DIR / "bordereaux"
ARCHIVES_DIR = BORDEREAUX_DIR / "archives"
DB_PATH = DATA_DIR / "compta.db"

XLSX_PATH = Path(os.environ.get("COMPTA_XLSX", r"F:\comptabilité\compta jdid .xlsx"))
SHEET_NAME = "Feuil1"

DATA_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)
ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)


# --- colonnes de saisie (les seules que l'app écrit) --------------------------
# clé interne -> lettre de colonne Excel
SAISIE_COLS: dict[str, str] = {
    "apci_n": "C",
    "tp_n": "E",
    "remb_n": "H",
    "star_n": "J",
    "pay_n": "L",
    "cat_cnam_n": "N",
    "cat_pay_n": "P",
    "laser_dec": "R",
    "laser_nd": "S",
    "divers": "T",
    "depenses": "V",
}

COL_JOUR = "A"
COL_DATE = "B"

# colonnes calculées par Excel -> formule miroir (voir model.py)
CALC_COLS: dict[str, str] = {
    "apci_m": "D",
    "tp_recu": "F",
    "tp_reste": "G",
    "remb_m": "I",
    "star_m": "K",
    "pay_m": "M",
    "cat_cnam_m": "O",
    "cat_pay_m": "Q",
    "recettes": "U",
    "tva_tp": "W",
    "caisse": "X",
    "charge_cnam": "Z",
    "banque": "AA",
    "patients": "AB",
    "ca_declare": "AC",
    "tva_deduite": "AD",
}

# tarif unitaire -> (colonne montant, colonne compteur)
TARIF_COLS: dict[str, tuple[str, str]] = {
    "t_apci": ("D", "C"),
    "t_tp_recu": ("F", "E"),
    "t_tp_reste": ("G", "E"),
    "t_remb": ("I", "H"),
    "t_star": ("K", "J"),
    "t_pay": ("M", "L"),
    "t_cat_cnam": ("O", "N"),
    "t_cat_pay": ("Q", "P"),
    "t_tva_tp": ("W", "E"),
}


# --- postes de consultation (saisie patient par patient) ----------------------
class Acte:
    __slots__ = ("cle", "libelle", "tarif", "famille", "icone")

    def __init__(self, cle: str, libelle: str, tarif: str, famille: str, icone: str):
        self.cle = cle
        self.libelle = libelle
        self.tarif = tarif
        self.famille = famille
        self.icone = icone


CONSULTATIONS: list[Acte] = [
    Acte("pay_n", "Payant", "t_pay", "Consultation", ":material/payments:"),
    Acte("remb_n", "Remboursement", "t_remb", "CNAM", ":material/receipt_long:"),
    Acte("apci_n", "APCI", "t_apci", "CNAM", ":material/health_and_safety:"),
    Acte("tp_n", "Tiers payant", "t_tp_recu", "CNAM", ":material/credit_card:"),
    Acte("star_n", "Assurance", "t_star", "Assurance", ":material/shield:"),
]

CHIRURGIE: list[Acte] = [
    Acte("cat_cnam_n", "Cataracte CNAM", "t_cat_cnam", "Chirurgie", ":material/visibility:"),
    Acte("cat_pay_n", "Cataracte payante", "t_cat_pay", "Chirurgie", ":material/visibility:"),
]

TOUS_ACTES: list[Acte] = CONSULTATIONS + CHIRURGIE
ACTES_PAR_CLE: dict[str, Acte] = {a.cle: a for a in TOUS_ACTES}

# montants saisis directement (pas de compteur)
MONTANTS_DIRECTS = [
    ("laser_dec", "Laser déclaré"),
    ("laser_nd", "Laser non déclaré"),
    ("divers", "Divers"),
    ("depenses", "Dépenses"),
]

# tout ce qui se saisit, donc tout ce qui se rectifie
LIBELLES_CHAMPS: dict[str, str] = (
    {a.cle: a.libelle for a in TOUS_ACTES} | dict(MONTANTS_DIRECTS)
)

JOURS_FR = ["LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI", "SAMEDI", "DIMANCHE"]
MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
