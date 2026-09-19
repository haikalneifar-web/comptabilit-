"""Registre SQLite : source de travail de l'app.

Le classeur Excel reste le document de référence pour le comptable ; cette base
est le carnet dans lequel on saisit, corrige et consulte avant d'écrire dans le
classeur. Chaque journée modifiée est marquée « à exporter ».

Deux registres, un seul jeu de données :

* le **registre réel** — la table `jours` — porte les valeurs d'origine, telles
  qu'importées du classeur ou saisies au fil de la journée. Une journée
  *clôturée* n'y est plus modifiable ;
* le **registre corrigé** — `jours` + la table `rectifications` — est ce que le
  registre aurait dû dire. Chaque écart entre les deux est une ligne motivée et
  horodatée, jamais un écrasement.

On ne supprime pas une rectification : on en passe une autre qui revient à la
valeur précédente. La valeur en vigueur pour un champ est donc simplement la
dernière rectification enregistrée.
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import sqlite3
from dataclasses import replace

from .config import DB_PATH
from .model import CHAMPS_SAISIE, COMPTEURS, MONTANTS, TARIFS_DEFAUT, Journee

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


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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


# --- agrégats ----------------------------------------------------------------

_SOMMES = """
    SUM(recettes) recettes, SUM(ca_declare) ca_declare, SUM(caisse) caisse,
    SUM(charge_cnam) charge_cnam, SUM(banque) banque, SUM(tva_deduite) tva_deduite,
    SUM(patients) patients, SUM(actes_chirurgie) actes_chirurgie,
    SUM(cat_cnam_n) cat_cnam_n, SUM(cat_pay_n) cat_pay_n,
    SUM(pay_n*t_pay) pay_m, SUM(remb_n*t_remb) remb_m,
    SUM(apci_n*t_apci) apci_m, SUM(star_n*t_star) star_m,
    SUM(cat_cnam_n*t_cat_cnam) cat_cnam_m, SUM(cat_pay_n*t_cat_pay) cat_pay_m,
    COUNT(*) jours, SUM(CASE WHEN recettes>0 THEN 1 ELSE 0 END) jours_actifs
"""


def _metriques(j: Journee) -> dict[str, float]:
    """Les mêmes grandeurs que `_SOMMES`, pour une journée."""
    return {
        "recettes": j.recettes, "ca_declare": j.ca_declare, "caisse": j.caisse,
        "charge_cnam": j.charge_cnam, "banque": j.banque,
        "tva_deduite": j.tva_deduite,
        "patients": float(j.patients), "actes_chirurgie": float(j.actes_chirurgie),
        "cat_cnam_n": float(j.cat_cnam_n), "cat_pay_n": float(j.cat_pay_n),
        "pay_m": j.pay_m, "remb_m": j.remb_m, "apci_m": j.apci_m, "star_m": j.star_m,
        "cat_cnam_m": j.cat_cnam_m, "cat_pay_m": j.cat_pay_m,
        "jours": 0.0, "jours_actifs": float(j.recettes > 0),
    }


def ecarts_rectifications(conn) -> dict[str, dict[str, float]]:
    """Écart réel → corrigé, journée par journée.

    Les rectifications sont peu nombreuses au regard du registre : on recalcule
    les seules journées touchées et on ajoute l'écart aux agrégats SQL.
    """
    ecarts: dict[str, dict[str, float]] = {}
    for date_iso, champs in rectifs_actives(conn).items():
        reel = lire_jour(conn, dt.date.fromisoformat(date_iso))
        m_reel, m_corrige = _metriques(reel), _metriques(_appliquer(reel, champs))
        ecarts[date_iso] = {k: m_corrige[k] - m_reel[k] for k in m_reel}
    return ecarts


def _corriger(conn, lignes, cle: str | None) -> list[dict]:
    """Ajoute l'écart des rectifications aux agrégats. `cle` est le nom de la
    colonne de période ('mois', 'annee') ou None pour un total unique."""
    ecarts = ecarts_rectifications(conn)
    lignes = [dict(r) for r in lignes]
    if not ecarts:
        return lignes
    taille = {"mois": 7, "annee": 4}.get(cle, 0)
    par_periode: dict[str, dict[str, float]] = {}
    for date_iso, ecart in ecarts.items():
        cumul = par_periode.setdefault(date_iso[:taille], {})
        for k, v in ecart.items():
            cumul[k] = cumul.get(k, 0.0) + v
    for ligne in lignes:
        for k, v in par_periode.get(ligne[cle] if cle else "", {}).items():
            if ligne.get(k) is not None:
                ligne[k] = ligne[k] + v
    return lignes


def agregat_mensuel(conn, depuis: str | None = None,
                    corrige: bool = False) -> list[dict]:
    where = "WHERE date >= ?" if depuis else ""
    args = (depuis,) if depuis else ()
    lignes = conn.execute(
        f"SELECT substr(date,1,7) mois, {_SOMMES} FROM jours {where} "
        f"GROUP BY mois ORDER BY mois", args
    ).fetchall()
    return _corriger(conn, lignes, "mois") if corrige else [dict(r) for r in lignes]


def agregat_annuel(conn, corrige: bool = False) -> list[dict]:
    lignes = conn.execute(
        f"SELECT substr(date,1,4) annee, {_SOMMES} FROM jours "
        f"GROUP BY annee ORDER BY annee"
    ).fetchall()
    return _corriger(conn, lignes, "annee") if corrige else [dict(r) for r in lignes]


def totaux(conn, corrige: bool = False) -> dict:
    ligne = conn.execute(f"SELECT {_SOMMES} FROM jours").fetchone()
    return _corriger(conn, [ligne], None)[0] if corrige else dict(ligne)


def journal(conn, debut: dt.date, fin: dt.date,
            corrige: bool = False) -> list[dict]:
    lignes = conn.execute(
        "SELECT * FROM jours WHERE date BETWEEN ? AND ? ORDER BY date DESC",
        (debut.isoformat(), fin.isoformat()),
    ).fetchall()
    # les journées rectifiées se signalent dans les deux vues ; seule la vue
    # corrigée applique les valeurs
    actives = rectifs_actives(conn, debut, fin)
    sortie = []
    for r in lignes:
        champs = actives.get(r["date"])
        if not champs or not corrige:
            sortie.append(dict(r) | {"rectifiee": bool(champs)})
            continue
        j = _appliquer(_vers_journee(r), champs)
        sortie.append(
            dict(r)
            | {c: getattr(j, c) for c in CHAMPS_SAISIE}
            | {c: getattr(j, c) for c in _CALCULES}
            | {"rectifiee": True}
        )
    return sortie


def dernier_jour_rempli(conn) -> dt.date | None:
    """Dernière journée qui porte des chiffres — la fin du travail déjà fait."""
    r = conn.execute(
        f"SELECT MAX(date) d FROM jours WHERE ({' + '.join(CHAMPS_SAISIE)}) > 0"
    ).fetchone()
    return dt.date.fromisoformat(r["d"]) if r and r["d"] else None


def mois_a_saisir(conn) -> tuple[int, int]:
    """Le mois par lequel reprendre : celui qui suit la dernière journée
    renseignée, ou le mois courant si la saisie est à jour."""
    dernier = dernier_jour_rempli(conn)
    aujourdhui = dt.date.today()
    if dernier is None:
        return aujourdhui.year, aujourdhui.month
    suivant = (dt.date(dernier.year, dernier.month, 1) + dt.timedelta(days=32)).replace(day=1)
    if suivant > aujourdhui:
        return dernier.year, dernier.month
    return suivant.year, suivant.month


def ligne_vide(date: dt.date, tarifs: dict[str, float]) -> dict:
    """Une journée absente du registre, sous la même forme qu'une ligne lue.

    Le classeur s'arrête au 23/01/2027 : au-delà, le mois se travaille quand
    même, et les journées se créent à l'enregistrement.
    """
    return (
        {c: 0 for c in COMPTEURS}
        | {c: 0.0 for c in MONTANTS}
        | {t: float(tarifs.get(t, TARIFS_DEFAUT[t])) for t in _TARIF_CLES}
        | {c: 0.0 for c in _CALCULES}
        | {
            "date": date.isoformat(), "source": "app", "a_exporter": 0,
            "cloture": 0, "ligne_xlsx": None, "rectifiee": False,
            "updated_at": None, "absente": True,
        }
    )


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
    from . import dossier_comptable

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


def bornes(conn) -> tuple[dt.date | None, dt.date | None]:
    r = conn.execute("SELECT MIN(date) a, MAX(date) b FROM jours").fetchone()
    if not r or not r["a"]:
        return None, None
    return dt.date.fromisoformat(r["a"]), dt.date.fromisoformat(r["b"])
