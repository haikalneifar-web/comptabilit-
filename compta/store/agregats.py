"""Agrégats mensuels et annuels, journal, mois à saisir."""

from __future__ import annotations

import datetime as dt

from ..model import CHAMPS_SAISIE, COMPTEURS, MONTANTS, TARIFS_DEFAUT, Journee
from .base import _CALCULES, _TARIF_CLES
from .journees import _vers_journee, lire_jour
from .rectifications import _appliquer, rectifs_actives


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
    clôturée, ou le mois courant si la saisie est à jour.

    Clôturée, pas seulement renseignée : un mois n'est fini qu'une fois écrit
    dans le classeur. La saisie se fait après coup — septembre se remplit en
    octobre — et compter la dernière journée enregistrée ferait passer au mois
    suivant dès la première journée sauvée. Le reste du mois tomberait alors
    derrière `frontiere_tarifs` et retrouverait l'ancien tarif.
    """
    r = conn.execute(
        f"SELECT MAX(date) d FROM jours WHERE cloture=1 "
        f"AND ({' + '.join(CHAMPS_SAISIE)}) > 0"
    ).fetchone()
    dernier = dt.date.fromisoformat(r["d"]) if r and r["d"] else None
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


def bornes(conn) -> tuple[dt.date | None, dt.date | None]:
    r = conn.execute("SELECT MIN(date) a, MAX(date) b FROM jours").fetchone()
    if not r or not r["a"]:
        return None, None
    return dt.date.fromisoformat(r["a"]), dt.date.fromisoformat(r["b"])
