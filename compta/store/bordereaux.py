"""Bordereaux mensuels et ce qui a été transmis au comptable."""

from __future__ import annotations

import calendar
import datetime as dt
import json
import sqlite3

from ..model import Journee
from .base import meta_set, tarifs_courants
from .journees import frontiere_tarifs, vers_journee
from .agregats import journal, ligne_vide


# --- bordereaux mensuels -----------------------------------------------------

def mois_en_journees(conn, annee: int, mois: int, corrige: bool = True,
                     tarifs: dict[str, float] | None = None) -> list[Journee]:
    """Le mois entier en journées calculables, du 1er au dernier jour.

    Le mois se construit sur le calendrier, pas sur les lignes du registre : une
    journée absente — le classeur s'arrête au 23/01/2027 — devient une journée à
    zéro, pour que le bordereau ait autant de lignes que le mois a de jours.
    """
    tarifs = tarifs or tarifs_courants(conn)
    depuis = frontiere_tarifs(conn)
    debut = dt.date(annee, mois, 1)
    fin = dt.date(annee, mois, calendar.monthrange(annee, mois)[1])

    connues = {r["date"]: r for r in journal(conn, debut, fin, corrige=corrige)}
    return [
        vers_journee(connues.get(d.isoformat()) or ligne_vide(d, tarifs),
                     tarifs, depuis)
        for d in (debut + dt.timedelta(days=n) for n in range((fin - debut).days + 1))
    ]


def enregistrer_bordereau(conn, annee: int, mois: int, registre: str,
                          empreinte: str, totaux_mois: dict,
                          fichier: str | None = None) -> int:
    """Consigne une édition de bordereau. Rien ne remplace une édition passée."""
    cur = conn.execute(
        "INSERT INTO bordereaux(mois, registre, fichier, empreinte, totaux, edite_le) "
        "VALUES(?,?,?,?,?,?)",
        (f"{annee}-{mois:02d}", registre, fichier, empreinte,
         json.dumps(totaux_mois),
         dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return int(cur.lastrowid)


def _vers_bordereau(r: sqlite3.Row) -> dict:
    return dict(r) | {"totaux": json.loads(r["totaux"])}


def bordereaux_du_mois(conn, annee: int, mois: int) -> list[dict]:
    """Les éditions d'un mois, de la plus récente à la plus ancienne."""
    return [
        _vers_bordereau(r)
        for r in conn.execute(
            "SELECT * FROM bordereaux WHERE mois=? ORDER BY id DESC",
            (f"{annee}-{mois:02d}",),
        )
    ]


def liste_bordereaux(conn, limite: int | None = None) -> list[dict]:
    """Toutes les éditions, la plus récente d'abord."""
    borne = f" LIMIT {int(limite)}" if limite else ""
    return [
        _vers_bordereau(r)
        for r in conn.execute(f"SELECT * FROM bordereaux ORDER BY id DESC{borne}")
    ]


def derniers_bordereaux_par_mois(conn) -> dict[str, dict]:
    """La dernière édition de chaque mois, indexée par `AAAA-MM`.

    C'est cette vue qui sert à suivre l'évolution : un mois réédité ne compte
    qu'une fois, avec ses chiffres les plus récents.
    """
    lignes = conn.execute("""
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY mois ORDER BY id DESC) rang
            FROM bordereaux
        ) WHERE rang = 1 ORDER BY mois
    """).fetchall()
    return {r["mois"]: _vers_bordereau(r) for r in lignes}


# --- ce qui a été transmis au comptable --------------------------------------

def rafraichir_transmis(conn, racine=None, annees: list[int] | None = None,
                        progress=None) -> dict:
    """Relit le dossier du comptable et met le cache à jour.

    Un classeur n'est rouvert que si sa date ou sa taille a changé : la centaine
    de fichiers ne se relit entièrement qu'une fois. Les lignes dont le fichier
    a disparu s'en vont.
    """
    from .. import dossier_comptable

    connus = {
        r["chemin"]: (r["modifie_le"], r["taille"])
        for r in conn.execute("SELECT chemin, modifie_le, taille FROM transmis")
    }
    presents = dossier_comptable.fichiers(racine, annees)
    rapport = {"vus": len(presents), "inchanges": 0, "relus": 0,
               "nouveaux": 0, "ignores": 0, "disparus": 0}

    for i, chemin in enumerate(presents):
        if progress:
            progress((i + 1) / max(len(presents), 1), chemin.name)
        etat = chemin.stat()
        signature = (dt.datetime.fromtimestamp(etat.st_mtime)
                     .isoformat(timespec="seconds"), etat.st_size)
        if connus.get(str(chemin)) == signature:
            rapport["inchanges"] += 1
            continue

        fiche = dossier_comptable.lire(chemin)
        if fiche is None:
            # pas une feuille mensuelle : on retient qu'on l'a regardée, pour ne
            # pas la rouvrir à chaque passage
            conn.execute(
                "INSERT INTO transmis(chemin, mois, feuille, jours, modifie_le, "
                "taille, totaux) VALUES(?,NULL,NULL,0,?,?,'{}') "
                "ON CONFLICT(chemin) DO UPDATE SET mois=NULL, jours=0, "
                "modifie_le=excluded.modifie_le, taille=excluded.taille, "
                "totaux='{}', lu_le=datetime('now')",
                (str(chemin), signature[0], signature[1]),
            )
            rapport["ignores"] += 1
            continue

        rapport["nouveaux" if str(chemin) not in connus else "relus"] += 1
        conn.execute(
            "INSERT INTO transmis(chemin, mois, feuille, jours, modifie_le, "
            "taille, totaux, lu_le) VALUES(?,?,?,?,?,?,?,datetime('now')) "
            "ON CONFLICT(chemin) DO UPDATE SET mois=excluded.mois, "
            "feuille=excluded.feuille, jours=excluded.jours, "
            "modifie_le=excluded.modifie_le, taille=excluded.taille, "
            "totaux=excluded.totaux, lu_le=datetime('now')",
            (str(chemin), fiche["mois"], fiche["feuille"], fiche["jours"],
             fiche["modifie_le"], fiche["taille"], json.dumps(fiche["totaux"])),
        )

    vivants = {str(p) for p in presents}
    partis = [c for c in connus if c not in vivants]
    for chemin in partis:
        conn.execute("DELETE FROM transmis WHERE chemin=?", (chemin,))
    rapport["disparus"] = len(partis)

    conn.commit()
    meta_set(conn, "transmis_lu_le",
             dt.datetime.now().isoformat(timespec="seconds"))
    return rapport


def transmis_par_mois(conn) -> dict[str, dict]:
    """Le fichier retenu pour chaque mois : le plus récemment modifié.

    Un mois porte parfois plusieurs classeurs — une copie, un brouillon, une
    version rangée dans un sous-dossier. Le dernier modifié est celui qui a été
    transmis.
    """
    lignes = conn.execute("""
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY mois ORDER BY modifie_le DESC, chemin DESC) rang
            FROM transmis WHERE mois IS NOT NULL
        ) WHERE rang = 1 ORDER BY mois
    """).fetchall()
    return {r["mois"]: dict(r) | {"totaux": json.loads(r["totaux"])}
            for r in lignes}


def transmis_du_mois(conn, annee: int, mois: int) -> list[dict]:
    """Tous les classeurs trouvés pour un mois, le plus récent d'abord."""
    return [
        dict(r) | {"totaux": json.loads(r["totaux"])}
        for r in conn.execute(
            "SELECT * FROM transmis WHERE mois=? ORDER BY modifie_le DESC",
            (f"{annee}-{mois:02d}",),
        )
    ]
