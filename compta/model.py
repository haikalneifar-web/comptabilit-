"""Miroir Python des formules du classeur.

Chaque colonne calculée d'Excel est reproduite ici à l'identique, pour que
l'app affiche les mêmes totaux que le fichier sans attendre un recalcul
d'Excel. Les formules sont celles des lignes récentes du classeur :

    D = C×t_apci        F = E×t_tp_recu     G = E×t_tp_reste
    I = H×t_remb        K = J×t_star        M = L×t_pay
    O = N×t_cat_cnam    Q = P×t_cat_pay     W = E×t_tva_tp
    U (recettes)     = D+F+I+K+M+O+Q+S+T+R+W
    X (caisse)       = F+I+M+T+W − V
    Z (dû CNAM)      = D+G+O
    AA (banque)      = F+I+K+M+O/2
    AB (patients)    = C+E+H+J+L
    AC (CA déclaré)  = D+F+G+I+K+M+O+R
    AD (TVA déduite) = AC − AC/1,06
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, asdict

from .config import JOURS_FR, MOIS_FR

# Tarifs en vigueur, relevés sur les dernières lignes du classeur (juillet 2026).
# Modifiables depuis la page « Tarifs » ; servent aux journées nouvellement créées.
TARIFS_DEFAUT: dict[str, float] = {
    "t_apci": 72.0,
    "t_tp_recu": 20.0,
    "t_tp_reste": 21.0,
    "t_remb": 70.0,
    "t_star": 70.0,
    "t_pay": 70.0,
    "t_cat_cnam": 700.0,
    "t_cat_pay": 750.0,
    "t_tva_tp": 11.0,
}

LIBELLES_TARIFS: dict[str, str] = {
    "t_apci": "APCI — consultation chronique",
    "t_tp_recu": "Tiers payant — part patient",
    "t_tp_reste": "Tiers payant — part CNAM",
    "t_remb": "Remboursement",
    "t_star": "Assurance / STAR",
    "t_pay": "Payant comptant",
    "t_cat_cnam": "Cataracte CNAM",
    "t_cat_pay": "Cataracte payante",
    "t_tva_tp": "Complément tiers payant (colonne W)",
}

COMPTEURS = ["apci_n", "tp_n", "remb_n", "star_n", "pay_n", "cat_cnam_n", "cat_pay_n"]
MONTANTS = ["laser_dec", "laser_nd", "divers", "depenses"]
CHAMPS_SAISIE = COMPTEURS + MONTANTS


@dataclass
class Journee:
    """Une journée du registre : les saisies, les tarifs, et tout le calculé."""

    date: dt.date

    # compteurs
    apci_n: int = 0
    tp_n: int = 0
    remb_n: int = 0
    star_n: int = 0
    pay_n: int = 0
    cat_cnam_n: int = 0
    cat_pay_n: int = 0

    # montants saisis directement
    laser_dec: float = 0.0
    laser_nd: float = 0.0
    divers: float = 0.0
    depenses: float = 0.0

    tarifs: dict[str, float] = field(default_factory=lambda: dict(TARIFS_DEFAUT))

    source: str = "app"          # "xlsx" (importé) ou "app" (saisi ici)
    a_exporter: bool = False     # modifié depuis le dernier export Excel
    cloture: bool = False        # figée : ne se modifie plus que par rectification
    ligne_xlsx: int | None = None

    # ---- montants calculés --------------------------------------------------
    @property
    def apci_m(self) -> float:
        return self.apci_n * self.tarifs["t_apci"]

    @property
    def tp_recu(self) -> float:
        return self.tp_n * self.tarifs["t_tp_recu"]

    @property
    def tp_reste(self) -> float:
        return self.tp_n * self.tarifs["t_tp_reste"]

    @property
    def remb_m(self) -> float:
        return self.remb_n * self.tarifs["t_remb"]

    @property
    def star_m(self) -> float:
        return self.star_n * self.tarifs["t_star"]

    @property
    def pay_m(self) -> float:
        return self.pay_n * self.tarifs["t_pay"]

    @property
    def cat_cnam_m(self) -> float:
        return self.cat_cnam_n * self.tarifs["t_cat_cnam"]

    @property
    def cat_pay_m(self) -> float:
        return self.cat_pay_n * self.tarifs["t_cat_pay"]

    @property
    def tva_tp(self) -> float:
        return self.tp_n * self.tarifs["t_tva_tp"]

    # ---- agrégats (colonnes U, X, Z, AA, AB, AC, AD) ------------------------
    @property
    def recettes(self) -> float:
        return (self.apci_m + self.tp_recu + self.remb_m + self.star_m + self.pay_m
                + self.cat_cnam_m + self.cat_pay_m + self.laser_nd + self.divers
                + self.laser_dec + self.tva_tp)

    @property
    def caisse(self) -> float:
        return (self.tp_recu + self.remb_m + self.pay_m + self.divers
                + self.tva_tp - self.depenses)

    @property
    def charge_cnam(self) -> float:
        return self.apci_m + self.tp_reste + self.cat_cnam_m

    @property
    def banque(self) -> float:
        return (self.tp_recu + self.remb_m + self.star_m + self.pay_m
                + self.cat_cnam_m / 2)

    @property
    def patients(self) -> int:
        return self.apci_n + self.tp_n + self.remb_n + self.star_n + self.pay_n

    @property
    def ca_declare(self) -> float:
        return (self.apci_m + self.tp_recu + self.tp_reste + self.remb_m
                + self.star_m + self.pay_m + self.cat_cnam_m + self.laser_dec)

    @property
    def tva_deduite(self) -> float:
        return self.ca_declare - self.ca_declare / 1.06

    @property
    def non_declare(self) -> float:
        return self.recettes - self.ca_declare

    @property
    def actes_chirurgie(self) -> int:
        return self.cat_cnam_n + self.cat_pay_n

    @property
    def vide(self) -> bool:
        return all(getattr(self, c) == 0 for c in CHAMPS_SAISIE)

    @property
    def nom_jour(self) -> str:
        return JOURS_FR[self.date.weekday()]

    def resume(self) -> dict[str, float]:
        return {
            "recettes": self.recettes,
            "ca_declare": self.ca_declare,
            "non_declare": self.non_declare,
            "caisse": self.caisse,
            "charge_cnam": self.charge_cnam,
            "banque": self.banque,
            "tva_deduite": self.tva_deduite,
            "patients": self.patients,
            "actes_chirurgie": self.actes_chirurgie,
        }

    def to_row(self) -> dict:
        d = asdict(self)
        d.pop("tarifs")
        d["date"] = self.date.isoformat()
        d.update({k: float(v) for k, v in self.tarifs.items()})
        return d


def date_longue(d: dt.date) -> str:
    return f"{JOURS_FR[d.weekday()].capitalize()} {d.day} {MOIS_FR[d.month - 1]} {d.year}"


def mois_long(annee: int, mois: int) -> str:
    return f"{MOIS_FR[mois - 1]} {annee}"


def tnd(v: float, decimales: int = 0) -> str:
    """Formate un montant à la française : 1 234 TND."""
    s = f"{v:,.{decimales}f}".replace(",", " ").replace(".", ",")
    return s
