"""Schéma SQLite, table `meta` (réglages) et tarifs courants."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3

from ..model import CHAMPS_SAISIE, COMPTEURS, MONTANTS, TARIFS_DEFAUT

_TARIF_CLES = list(TARIFS_DEFAUT)

_CALCULES = [
    "recettes", "ca_declare", "caisse", "charge_cnam",
    "banque", "tva_deduite", "patients", "actes_chirurgie",
]


class JourCloture(Exception):
    """Tentative d'écrasement d'une journée clôturée."""

    def __init__(self, date: dt.date):
        self.date = date
        super().__init__(
            f"La journée du {date:%d/%m/%Y} est clôturée : elle ne se modifie "
            "plus que par une rectification motivée."
        )


def init_db(conn: sqlite3.Connection) -> None:
    cols = (
        [f"{c} INTEGER NOT NULL DEFAULT 0" for c in COMPTEURS]
        + [f"{c} REAL NOT NULL DEFAULT 0" for c in MONTANTS]
        + [f"{t} REAL NOT NULL DEFAULT {TARIFS_DEFAUT[t]}" for t in _TARIF_CLES]
        + [f"{c} REAL NOT NULL DEFAULT 0" for c in _CALCULES]
    )
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS jours (
            date TEXT PRIMARY KEY,
            {', '.join(cols)},
            source TEXT NOT NULL DEFAULT 'app',
            a_exporter INTEGER NOT NULL DEFAULT 0,
            cloture INTEGER NOT NULL DEFAULT 0,
            ligne_xlsx INTEGER,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS actes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            cle TEXT NOT NULL,
            montant REAL NOT NULL DEFAULT 0,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Journal des rectifications : une ligne par correction motivée, jamais
    # supprimée. `annule_id` renseigne la rectification sur laquelle on revient.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rectifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            champ TEXT NOT NULL,
            ancienne REAL NOT NULL,
            nouvelle REAL NOT NULL,
            motif TEXT NOT NULL,
            annule_id INTEGER REFERENCES rectifications(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Journal des bordereaux édités : une ligne par édition, jamais écrasée.
    # Rééditer un mois après une rectification ajoute une ligne, et l'écart
    # entre deux éditions se lit dans leurs totaux.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bordereaux (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mois TEXT NOT NULL,
            registre TEXT NOT NULL,
            fichier TEXT,
            empreinte TEXT NOT NULL,
            totaux TEXT NOT NULL,
            edite_le TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bordereaux_mois ON bordereaux(mois)")
    # Cache de ce qui a été transmis au comptable : un fichier mensuel par ligne,
    # relu seulement s'il a bougé. Ce n'est pas une source — le registre reste le
    # registre — c'est l'observation de fichiers extérieurs, qu'on ne modifie pas.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transmis (
            chemin TEXT PRIMARY KEY,
            mois TEXT,
            feuille TEXT,
            jours INTEGER,
            modifie_le TEXT NOT NULL,
            taille INTEGER NOT NULL,
            totaux TEXT NOT NULL,
            lu_le TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transmis_mois ON transmis(mois)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_actes_date ON actes(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jours_export ON jours(a_exporter)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rectif_date ON rectifications(date, champ)")
    conn.execute("CREATE TABLE IF NOT EXISTS meta (cle TEXT PRIMARY KEY, valeur TEXT)")

    # migration des bases créées avant l'ajout de la clôture : les journées du
    # classeur qui portent des chiffres sont acquises ; ses lignes pré-remplies
    # à zéro sont de simples emplacements de saisie, qui restent ouverts.
    colonnes = {r["name"] for r in conn.execute("PRAGMA table_info(jours)")}
    if "cloture" not in colonnes:
        conn.execute("ALTER TABLE jours ADD COLUMN cloture INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            f"UPDATE jours SET cloture=1 WHERE source='xlsx' "
            f"AND ({' + '.join(CHAMPS_SAISIE)}) > 0"
        )

    conn.commit()


# --- meta --------------------------------------------------------------------

def meta_get(conn, cle: str, defaut=None):
    r = conn.execute("SELECT valeur FROM meta WHERE cle=?", (cle,)).fetchone()
    return json.loads(r["valeur"]) if r else defaut


def meta_set(conn, cle: str, valeur) -> None:
    conn.execute(
        "INSERT INTO meta(cle,valeur) VALUES(?,?) "
        "ON CONFLICT(cle) DO UPDATE SET valeur=excluded.valeur",
        (cle, json.dumps(valeur)),
    )
    conn.commit()


def tarifs_courants(conn) -> dict[str, float]:
    stockes = meta_get(conn, "tarifs", {}) or {}
    return {k: float(stockes.get(k, v)) for k, v in TARIFS_DEFAUT.items()}


def enregistrer_tarifs(conn, tarifs: dict[str, float]) -> None:
    meta_set(conn, "tarifs", {k: float(v) for k, v in tarifs.items()})
