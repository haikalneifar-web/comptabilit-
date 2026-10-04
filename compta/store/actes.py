"""Saisie patient par patient : les actes d'une journée."""

from __future__ import annotations

import datetime as dt
import sqlite3

from .base import tarifs_courants
from .journees import ecrire_jour, lire_jour


# --- actes (saisie patient par patient) --------------------------------------

def ajouter_acte(conn, date: dt.date, cle: str, montant: float, note: str = "") -> None:
    """Ajoute un acte et incrémente le compteur de la journée."""
    j = lire_jour(conn, date, tarifs_courants(conn))
    setattr(j, cle, getattr(j, cle) + 1)
    conn.execute(
        "INSERT INTO actes(date, cle, montant, note) VALUES(?,?,?,?)",
        (date.isoformat(), cle, float(montant), note or None),
    )
    ecrire_jour(conn, j, commit=False)
    conn.commit()


def supprimer_acte(conn, acte_id: int) -> None:
    r = conn.execute("SELECT date, cle FROM actes WHERE id=?", (acte_id,)).fetchone()
    if not r:
        return
    date = dt.date.fromisoformat(r["date"])
    j = lire_jour(conn, date, tarifs_courants(conn))
    setattr(j, r["cle"], max(0, getattr(j, r["cle"]) - 1))
    conn.execute("DELETE FROM actes WHERE id=?", (acte_id,))
    ecrire_jour(conn, j, commit=False)
    conn.commit()


def retirer_dernier(conn, date: dt.date, cle: str) -> bool:
    """Retire le dernier acte de ce type ; à défaut décrémente le compteur."""
    r = conn.execute(
        "SELECT id FROM actes WHERE date=? AND cle=? ORDER BY id DESC LIMIT 1",
        (date.isoformat(), cle),
    ).fetchone()
    if r:
        supprimer_acte(conn, r["id"])
        return True
    j = lire_jour(conn, date, tarifs_courants(conn))
    if getattr(j, cle) <= 0:
        return False
    setattr(j, cle, getattr(j, cle) - 1)
    ecrire_jour(conn, j)
    return True


def actes_du_jour(conn, date: dt.date) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM actes WHERE date=? ORDER BY id DESC", (date.isoformat(),)
    ).fetchall()


def nb_actes(conn, date: dt.date) -> int:
    return conn.execute(
        "SELECT COUNT(*) n FROM actes WHERE date=?", (date.isoformat(),)
    ).fetchone()["n"]
