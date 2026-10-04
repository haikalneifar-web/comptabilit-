"""Le journal des rectifications motivées et le registre corrigé."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace

from ..model import CHAMPS_SAISIE, COMPTEURS, MONTANTS, Journee
from .journees import existe, lire_jour


# --- rectifications ----------------------------------------------------------

def _appliquer(j: Journee, champs: dict[str, float]) -> Journee:
    """Copie de la journée avec les rectifications en vigueur appliquées."""
    corrige = replace(j, tarifs=dict(j.tarifs))
    for champ, valeur in champs.items():
        if champ in COMPTEURS:
            setattr(corrige, champ, int(round(float(valeur))))
        elif champ in MONTANTS:
            setattr(corrige, champ, float(valeur))
    return corrige


def rectifs_actives(conn, debut: dt.date | None = None,
                    fin: dt.date | None = None) -> dict[str, dict[str, float]]:
    """Valeur en vigueur par journée et par champ : la dernière rectification.

    Retourne `{date_iso: {champ: valeur}}`. Les journées sans rectification
    n'y figurent pas.
    """
    where, args = "", []
    if debut and fin:
        where = "WHERE date BETWEEN ? AND ?"
        args = [debut.isoformat(), fin.isoformat()]
    lignes = conn.execute(f"""
        SELECT date, champ, nouvelle FROM (
            SELECT date, champ, nouvelle,
                   ROW_NUMBER() OVER (PARTITION BY date, champ ORDER BY id DESC) rang
            FROM rectifications {where}
        ) WHERE rang = 1
    """, args).fetchall()
    actives: dict[str, dict[str, float]] = {}
    for r in lignes:
        actives.setdefault(r["date"], {})[r["champ"]] = float(r["nouvelle"])
    return actives


def lire_jour_corrige(conn, date: dt.date,
                      tarifs_defaut: dict[str, float] | None = None) -> Journee:
    """La journée telle que le registre corrigé la donne."""
    j = lire_jour(conn, date, tarifs_defaut)
    champs = rectifs_actives(conn, date, date).get(date.isoformat())
    return _appliquer(j, champs) if champs else j


def ajouter_rectification(conn, date: dt.date, champ: str, nouvelle: float,
                          motif: str, annule_id: int | None = None) -> int:
    """Enregistre une correction motivée sur une journée du registre.

    L'ancienne valeur retenue est celle du registre corrigé au moment de la
    saisie, pour que la suite des rectifications d'un champ se lise de proche
    en proche.
    """
    motif = (motif or "").strip()
    if not motif:
        raise ValueError("Une rectification doit dire pourquoi. Motif obligatoire.")
    if champ not in CHAMPS_SAISIE:
        raise ValueError(f"Champ non rectifiable : {champ}.")
    if not existe(conn, date):
        raise ValueError(f"Aucune journée au registre le {date:%d/%m/%Y}.")

    courant = lire_jour_corrige(conn, date)
    ancienne = float(getattr(courant, champ))
    nouvelle = float(nouvelle)
    if champ in COMPTEURS:
        nouvelle = float(int(round(nouvelle)))
    if nouvelle < 0:
        raise ValueError("Une valeur rectifiée ne peut pas être négative.")
    if abs(nouvelle - ancienne) < 0.005:
        raise ValueError("Cette valeur est déjà celle du registre corrigé.")

    cur = conn.execute(
        "INSERT INTO rectifications(date, champ, ancienne, nouvelle, motif, annule_id) "
        "VALUES(?,?,?,?,?,?)",
        (date.isoformat(), champ, ancienne, nouvelle, motif, annule_id),
    )
    # la correction doit atteindre le classeur
    conn.execute("UPDATE jours SET a_exporter=1 WHERE date=?", (date.isoformat(),))
    conn.commit()
    return int(cur.lastrowid)


def annuler_rectification(conn, rectif_id: int, motif: str) -> int:
    """Revient à la valeur qui précédait une rectification, par une autre
    rectification : rien n'est effacé du journal."""
    r = conn.execute(
        "SELECT * FROM rectifications WHERE id=?", (rectif_id,)
    ).fetchone()
    if not r:
        raise ValueError("Rectification introuvable.")
    return ajouter_rectification(
        conn, dt.date.fromisoformat(r["date"]), r["champ"], r["ancienne"],
        motif, annule_id=rectif_id,
    )


def liste_rectifications(conn, debut: dt.date | None = None,
                         fin: dt.date | None = None) -> list[dict]:
    """Journal des rectifications, de la plus récente à la plus ancienne.

    Chaque ligne porte `en_vigueur` : la dernière rectification d'un champ est
    celle qui compte, les précédentes ne sont plus que de l'historique.
    """
    where, args = "", []
    if debut and fin:
        where = "WHERE date BETWEEN ? AND ?"
        args = [debut.isoformat(), fin.isoformat()]
    lignes = conn.execute(f"""
        SELECT *, ROW_NUMBER() OVER (PARTITION BY date, champ ORDER BY id DESC) rang
        FROM rectifications {where} ORDER BY id DESC
    """, args).fetchall()
    return [dict(r) | {"en_vigueur": r["rang"] == 1} for r in lignes]


def rectifications_du_jour(conn, date: dt.date) -> list[dict]:
    return liste_rectifications(conn, date, date)


def nb_rectifications(conn) -> int:
    return conn.execute("SELECT COUNT(*) n FROM rectifications").fetchone()["n"]


def dates_rectifiees(conn) -> list[dt.date]:
    return [
        dt.date.fromisoformat(r["date"])
        for r in conn.execute(
            "SELECT DISTINCT date FROM rectifications ORDER BY date"
        )
    ]
