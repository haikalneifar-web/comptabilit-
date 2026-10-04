"""Les journées du registre réel : lecture, écriture, clôture, export."""

from __future__ import annotations

import datetime as dt
import sqlite3

from ..model import COMPTEURS, MONTANTS, TARIFS_DEFAUT, Journee
from .base import JourCloture, _CALCULES, _TARIF_CLES


# --- journées ----------------------------------------------------------------

def _vers_journee(r: sqlite3.Row) -> Journee:
    j = Journee(date=dt.date.fromisoformat(r["date"]))
    for c in COMPTEURS:
        setattr(j, c, int(r[c]))
    for c in MONTANTS:
        setattr(j, c, float(r[c]))
    j.tarifs = {t: float(r[t]) for t in _TARIF_CLES}
    j.source = r["source"]
    j.a_exporter = bool(r["a_exporter"])
    j.cloture = bool(r["cloture"])
    j.ligne_xlsx = r["ligne_xlsx"]
    return j


def frontiere_tarifs(conn) -> dt.date:
    """Première journée qu'un changement de tarif peut encore régir.

    Un changement de tarif ne vaut que pour la suite. « La suite » commence au
    premier jour du mois en cours de saisie : les mois déjà travaillés sont
    clos, leurs trous compris. C'est `mois_a_saisir` qui fait foi, pour que la
    frontière ne bouge pas pendant qu'on remplit le mois.
    """
    # import tardif : `agregats` lit les journées, donc dépend de ce module
    from .agregats import mois_a_saisir
    annee, mois = mois_a_saisir(conn)
    return dt.date(annee, mois, 1)


def _tarifs_du_jour(j: Journee, tarifs_courants: dict[str, float] | None,
                    depuis: dt.date | None = None) -> Journee:
    """Aligne les tarifs d'une journée encore vierge sur les tarifs en vigueur.

    Le classeur est pré-rempli de lignes à zéro jusqu'au 23/01/2027, avec le
    tarif qui avait cours au moment où elles ont été préparées. Ces lignes ne
    sont pas des journées : tant qu'elles ne portent aucun chiffre, elles
    doivent suivre le tarif du jour. Dès qu'une journée porte des chiffres — ou
    qu'elle est clôturée — elle garde les siens, c'est son histoire.

    `depuis` — la frontière ci-dessus — borne le procédé au mois en cours et à
    ce qui le suit. Une journée oubliée d'un mois déjà travaillé est vide sans
    être à venir : elle garde le tarif que le classeur a inscrit dans sa
    formule, celui de ses voisines, et non le tarif d'aujourd'hui. Sans quoi
    saisir un jour retrouvé de 2019 le compterait au prix de 2026.
    """
    if (tarifs_courants and j.vide and not j.cloture
            and (depuis is None or j.date >= depuis)):
        j.tarifs = dict(tarifs_courants)
    return j


def vers_journee(ligne, tarifs_courants: dict[str, float] | None = None,
                 depuis: dt.date | None = None) -> Journee:
    """Une ligne du registre (Row ou dict) en journée calculable, avec ses
    propres tarifs — ceux de sa période, pas ceux d'aujourd'hui.

    `depuis` vient de `frontiere_tarifs` ; l'appelant qui boucle sur un mois le
    calcule une fois plutôt qu'à chaque ligne.
    """
    return _tarifs_du_jour(_vers_journee(ligne), tarifs_courants, depuis)


def lire_jour(conn, date: dt.date, tarifs_defaut: dict[str, float] | None = None) -> Journee:
    r = conn.execute("SELECT * FROM jours WHERE date=?", (date.isoformat(),)).fetchone()
    if r:
        depuis = frontiere_tarifs(conn) if tarifs_defaut else None
        return _tarifs_du_jour(_vers_journee(r), tarifs_defaut, depuis)
    # absente du registre : au-delà de la dernière ligne du classeur, donc à venir
    j = Journee(date=date)
    j.tarifs = dict(tarifs_defaut or TARIFS_DEFAUT)
    return j


def existe(conn, date: dt.date) -> bool:
    return conn.execute(
        "SELECT 1 FROM jours WHERE date=?", (date.isoformat(),)
    ).fetchone() is not None


def ecrire_jour(conn, j: Journee, calc: dict | None = None, marquer: bool = True,
                commit: bool = True, force: bool = False) -> None:
    """Enregistre une journée dans le registre réel.

    `calc` force les valeurs calculées (import Excel). Une journée clôturée ne
    se modifie plus que par rectification : l'écriture est refusée, sauf
    `force=True` réservé à la relecture complète du classeur.
    """
    if not force and est_cloture(conn, j.date):
        raise JourCloture(j.date)
    valeurs = {c: int(getattr(j, c)) for c in COMPTEURS}
    valeurs |= {c: float(getattr(j, c)) for c in MONTANTS}
    valeurs |= {t: float(j.tarifs[t]) for t in _TARIF_CLES}
    calcules = calc if calc is not None else {c: float(getattr(j, c)) for c in _CALCULES}
    valeurs |= {c: float(calcules.get(c, 0.0)) for c in _CALCULES}
    valeurs |= {
        "date": j.date.isoformat(),
        "source": j.source,
        "a_exporter": int(marquer or j.a_exporter),
        "cloture": int(j.cloture),
        "ligne_xlsx": j.ligne_xlsx,
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    champs = list(valeurs)
    maj = ", ".join(f"{c}=excluded.{c}" for c in champs if c != "date")
    conn.execute(
        f"INSERT INTO jours ({', '.join(champs)}) VALUES ({', '.join('?' * len(champs))}) "
        f"ON CONFLICT(date) DO UPDATE SET {maj}",
        [valeurs[c] for c in champs],
    )
    if commit:
        conn.commit()


# --- clôture -----------------------------------------------------------------

def est_cloture(conn, date: dt.date) -> bool:
    r = conn.execute(
        "SELECT cloture FROM jours WHERE date=?", (date.isoformat(),)
    ).fetchone()
    return bool(r and r["cloture"])


def cloturer(conn, dates: list[dt.date], commit: bool = True) -> int:
    """Fige des journées : elles ne se modifient plus que par rectification."""
    cur = conn.executemany(
        "UPDATE jours SET cloture=1 WHERE date=?",
        [(d.isoformat(),) for d in dates],
    )
    if commit:
        conn.commit()
    return cur.rowcount


def jours_ouverts(conn, debut: dt.date, fin: dt.date) -> list[dt.date]:
    return [
        dt.date.fromisoformat(r["date"])
        for r in conn.execute(
            "SELECT date FROM jours WHERE cloture=0 AND date BETWEEN ? AND ? ORDER BY date",
            (debut.isoformat(), fin.isoformat()),
        )
    ]


def nb_ouverts(conn) -> int:
    return conn.execute("SELECT COUNT(*) n FROM jours WHERE cloture=0").fetchone()["n"]


# --- export ------------------------------------------------------------------

def jours_a_exporter(conn) -> list[dt.date]:
    return [
        dt.date.fromisoformat(r["date"])
        for r in conn.execute(
            "SELECT date FROM jours WHERE a_exporter=1 ORDER BY date"
        ).fetchall()
    ]


def marquer_exporte(conn, dates: list[dt.date]) -> None:
    """Écrite dans le classeur : la journée est aussi clôturée, elle ne se
    modifie plus que par rectification."""
    conn.executemany(
        "UPDATE jours SET a_exporter=0, cloture=1 WHERE date=?",
        [(d.isoformat(),) for d in dates],
    )
    conn.commit()
