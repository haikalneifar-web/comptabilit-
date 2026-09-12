"""Saisie d'une journée : acte par acte, ou totaux directs.

Tant qu'une journée est ouverte, elle se saisit et se corrige librement. Une
fois clôturée — écrite dans le classeur, ou figée à la main — elle ne bouge
plus que par une rectification motivée.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from app_utils import (demander_rectification, get_conn, montant, recap_journee,
                       rectification_en_attente, valeur_champ)
from compta import store
from compta.config import (ACTES_PAR_CLE, CHIRURGIE, CONSULTATIONS,
                           LIBELLES_CHAMPS, MONTANTS_DIRECTS)
from compta.model import MONTANTS, date_longue, tnd

conn = get_conn()
tarifs = store.tarifs_courants(conn)

# --- choix de la journée -----------------------------------------------------

if st.session_state.date_saisie is None:
    st.session_state.date_saisie = dt.date.today()

st.header("Saisie du jour", anchor=False)

with st.container(horizontal=True, vertical_alignment="bottom"):
    date = st.date_input(
        "Journée", value=st.session_state.date_saisie, format="DD/MM/YYYY",
        key="choix_date", width=200,
    )
    if st.button("Aujourd'hui", icon=":material/today:"):
        st.session_state.date_saisie = dt.date.today()
        st.rerun()
    if st.button("Hier", icon=":material/history:"):
        st.session_state.date_saisie = dt.date.today() - dt.timedelta(days=1)
        st.rerun()

if date != st.session_state.date_saisie:
    st.session_state.date_saisie = date

journee = store.lire_jour_corrige(conn, date, tarifs)
st.caption(date_longue(date) + ("  ·  importée du classeur" if journee.source == "xlsx" else ""))

if date > dt.date.today():
    st.warning("Cette journée est dans le futur.", icon=":material/schedule:")

recap_journee(journee)

if journee.a_exporter:
    st.caption(":material/pending: Modifiée — en attente d'écriture dans le classeur.")

st.divider()


# --- journée clôturée : lecture seule, rectification motivée -----------------

if journee.cloture:
    st.info(
        "Journée clôturée. Elle ne se modifie plus directement : une correction "
        "passe par une rectification, qui garde la valeur d'origine, le motif "
        "et la date de la correction.",
        icon=":material/lock:",
    )

    st.subheader("Ce que dit le registre", anchor=False)
    postes = {
        LIBELLES_CHAMPS[a.cle]: valeur_champ(a.cle, getattr(journee, a.cle))
        for a in CONSULTATIONS + CHIRURGIE
    } | {
        libelle: valeur_champ(cle, getattr(journee, cle))
        for cle, libelle in MONTANTS_DIRECTS
    }
    st.table({k: v for k, v in postes.items() if v not in ("0", "0 TND")}
             or {"Journée sans activité": "—"},
             border="horizontal", width="content")

    st.button("Rectifier cette journée", icon=":material/edit_note:",
              type="primary", on_click=demander_rectification, args=(date,))

    corrections = store.rectifications_du_jour(conn, date)
    if corrections:
        st.subheader(f"{len(corrections)} rectification(s)", anchor=False)
        reel = store.lire_jour(conn, date, tarifs)
        for r in corrections:
            with st.container(border=True):
                st.markdown(
                    f"**{LIBELLES_CHAMPS.get(r['champ'], r['champ'])}** · "
                    f"{valeur_champ(r['champ'], r['ancienne'])} → "
                    f"{valeur_champ(r['champ'], r['nouvelle'])}"
                    + ("" if r["en_vigueur"] else "  ·  *remplacée depuis*")
                )
                st.caption(f"{r['motif']} — saisie le {r['created_at']}")
        st.caption(
            f"Valeurs d'origine au registre réel : recettes "
            f"{montant(reel.recettes)}, CA déclaré {montant(reel.ca_declare)}, "
            f"{reel.patients} patients."
        )

    rectification_en_attente(conn)
    st.stop()


# --- journée ouverte : saisie normale ----------------------------------------

mode = st.segmented_control(
    "Mode de saisie",
    ["Patient par patient", "Totaux de la journée"],
    default=st.session_state.mode_saisie,
    key="mode_saisie_widget",
    label_visibility="collapsed",
)
if mode:
    st.session_state.mode_saisie = mode

if st.session_state.mode_saisie == "Patient par patient":
    st.caption(
        "Tapez le nombre directement dans un compteur, ou utilisez `+` et `−` pour "
        "enregistrer les actes un par un avec leur horaire."
    )


# --- callbacks ---------------------------------------------------------------

def _cle_widget(cle: str) -> str:
    """Clé de widget propre à la journée affichée, pour que le champ se
    rafraîchisse quand on change de date."""
    return f"nb_{cle}_{st.session_state.date_saisie:%Y%m%d}"


def _ajouter(cle: str) -> None:
    acte = ACTES_PAR_CLE[cle]
    store.ajouter_acte(conn, st.session_state.date_saisie, cle, tarifs[acte.tarif])


def _retirer(cle: str) -> None:
    if not store.retirer_dernier(conn, st.session_state.date_saisie, cle):
        st.toast("Rien à retirer pour ce poste.", icon=":material/block:")


def _saisir(cle: str) -> None:
    """Nombre tapé directement dans le champ."""
    valeur = st.session_state.get(_cle_widget(cle))
    if valeur is None:
        return
    d = st.session_state.date_saisie
    j = store.lire_jour(conn, d, tarifs)
    nouvelle = max(0, int(valeur))
    if nouvelle == getattr(j, cle):
        return  # rien n'a changé : ne pas marquer la journée à exporter
    setattr(j, cle, nouvelle)
    store.ecrire_jour(conn, j)


def _cle_montant(cle: str) -> str:
    return f"mt_{cle}_{st.session_state.date_saisie:%Y%m%d}"


def _saisir_montant(cle: str) -> None:
    valeur = st.session_state.get(_cle_montant(cle))
    if valeur is None:
        return
    d = st.session_state.date_saisie
    j = store.lire_jour(conn, d, tarifs)
    nouveau = max(0.0, float(valeur))
    if abs(nouveau - getattr(j, cle)) < 0.005:
        return  # rien n'a changé : ne pas marquer la journée à exporter
    setattr(j, cle, nouveau)
    store.ecrire_jour(conn, j)


def _supprimer(acte_id: int, cle: str) -> None:
    store.supprimer_acte(conn, acte_id)


def _cloturer() -> None:
    store.cloturer(conn, [st.session_state.date_saisie])


def _compteur(acte, col) -> None:
    valeur = getattr(journee, acte.cle)
    # la base fait foi : on recale le champ à chaque rendu, sans passer `value=`
    # (ce qui déclencherait l'avertissement « default value + Session State »).
    st.session_state[_cle_widget(acte.cle)] = valeur
    with col.container(border=True):
        st.caption(acte.libelle)
        st.number_input(
            acte.libelle, min_value=0, step=1, format="%d",
            key=_cle_widget(acte.cle), on_change=_saisir, args=(acte.cle,),
            label_visibility="collapsed",
        )
        st.caption(f"{tnd(tarifs[acte.tarif])} TND × {valeur} = "
                   f"**{tnd(valeur * tarifs[acte.tarif])}**")
        with st.container(horizontal=True):
            st.button("−", key=f"moins_{acte.cle}", on_click=_retirer, args=(acte.cle,),
                      disabled=valeur <= 0, width="stretch")
            st.button("+", key=f"plus_{acte.cle}", on_click=_ajouter, args=(acte.cle,),
                      type="primary", width="stretch")


# --- mode acte par acte ------------------------------------------------------

if st.session_state.mode_saisie == "Patient par patient":
    st.subheader("Consultations", anchor=False)
    cols = st.columns(len(CONSULTATIONS))
    for acte, col in zip(CONSULTATIONS, cols):
        _compteur(acte, col)

    st.subheader("Chirurgie", anchor=False)
    cols = st.columns(len(CONSULTATIONS))
    for acte, col in zip(CHIRURGIE, cols[:2]):
        _compteur(acte, col)

    non_vides = any(getattr(journee, c) for c, _ in MONTANTS_DIRECTS)
    with st.expander("Laser, divers et dépenses", icon=":material/more_horiz:",
                     expanded=non_vides):
        st.caption("Montants en TND, enregistrés dès que vous quittez le champ.")
        cols = st.columns(len(MONTANTS_DIRECTS))
        for (cle, libelle), col in zip(MONTANTS_DIRECTS, cols):
            st.session_state[_cle_montant(cle)] = float(getattr(journee, cle))
            col.number_input(
                libelle, min_value=0.0, step=10.0, format="%.0f",
                key=_cle_montant(cle), on_change=_saisir_montant, args=(cle,),
            )

    actes = store.actes_du_jour(conn, date)
    if actes:
        st.subheader(f"Détail de la journée · {len(actes)} actes", anchor=False)
        for a in actes:
            libelle = ACTES_PAR_CLE[a["cle"]].libelle
            heure = (a["created_at"] or "")[-8:-3]
            with st.container(horizontal=True, vertical_alignment="center", border=True):
                st.markdown(f"**{libelle}**")
                st.caption(f"{tnd(a['montant'])} TND")
                st.caption(heure)
                st.button("Supprimer", key=f"del_{a['id']}", icon=":material/delete:",
                          type="tertiary", on_click=_supprimer,
                          args=(a["id"], a["cle"]))
    elif not journee.vide:
        st.caption(
            "Aucun acte détaillé pour cette journée : les compteurs viennent du "
            "classeur ou d'une saisie en totaux."
        )

# --- mode totaux -------------------------------------------------------------

else:
    st.subheader("Totaux de la journée", anchor=False)
    with st.form("totaux_jour", border=False):
        st.caption("Nombre de patients par poste")
        cols = st.columns(len(CONSULTATIONS))
        saisies = {}
        for acte, col in zip(CONSULTATIONS, cols):
            saisies[acte.cle] = col.number_input(
                acte.libelle, min_value=0, step=1,
                value=int(getattr(journee, acte.cle)), key=f"tot_{acte.cle}",
            )

        st.caption("Chirurgie")
        cols = st.columns(len(CONSULTATIONS))
        for acte, col in zip(CHIRURGIE, cols[:2]):
            saisies[acte.cle] = col.number_input(
                acte.libelle, min_value=0, step=1,
                value=int(getattr(journee, acte.cle)), key=f"tot_{acte.cle}",
            )

        st.caption("Montants saisis directement")
        cols = st.columns(len(MONTANTS_DIRECTS))
        for (cle, libelle), col in zip(MONTANTS_DIRECTS, cols):
            saisies[cle] = col.number_input(
                libelle, min_value=0.0, step=10.0, format="%.0f",
                value=float(getattr(journee, cle)), key=f"tot_{cle}",
            )

        if st.form_submit_button("Enregistrer la journée", icon=":material/save:",
                                 type="primary"):
            for cle, v in saisies.items():
                setattr(journee, cle, float(v) if cle in MONTANTS else int(v))
            store.ecrire_jour(conn, journee)
            st.toast(f"Journée du {date:%d/%m/%Y} enregistrée.", icon=":material/check:")
            st.rerun()

    nb = store.nb_actes(conn, date)
    if nb and nb != journee.patients + journee.actes_chirurgie:
        st.warning(
            f"{nb} actes détaillés sont enregistrés pour cette journée alors que les "
            "totaux en annoncent un nombre différent. Les totaux saisis ici font foi.",
            icon=":material/warning:",
        )

# --- clôture -----------------------------------------------------------------

st.divider()

with st.container(horizontal=True, vertical_alignment="center"):
    st.button("Clôturer la journée", icon=":material/lock:",
              on_click=_cloturer, disabled=journee.vide)
    st.caption(
        "Une journée clôturée est figée : elle ne se corrige plus que par une "
        "rectification motivée. L'écriture dans le classeur clôture aussi."
    )

# --- détail du calcul --------------------------------------------------------

with st.expander("Comment ce total est calculé", icon=":material/function:"):
    st.caption("Mêmes formules que le classeur, colonne par colonne.")
    lignes = {
        "APCI (D)": journee.apci_m,
        "Tiers payant — part patient (F)": journee.tp_recu,
        "Tiers payant — part CNAM (G)": journee.tp_reste,
        "Remboursement (I)": journee.remb_m,
        "Assurance / STAR (K)": journee.star_m,
        "Payant (M)": journee.pay_m,
        "Cataracte CNAM (O)": journee.cat_cnam_m,
        "Cataracte payante (Q)": journee.cat_pay_m,
        "Complément tiers payant (W)": journee.tva_tp,
        "Laser déclaré (R)": journee.laser_dec,
        "Laser non déclaré (S)": journee.laser_nd,
        "Divers (T)": journee.divers,
        "Dépenses (V)": -journee.depenses,
    }
    st.table({k: montant(v) for k, v in lignes.items() if v},
             border="horizontal", width="content")
    st.caption(
        f"Recettes {montant(journee.recettes)} · CA à déclarer "
        f"{montant(journee.ca_declare)} · non déclaré {montant(journee.non_declare)} "
        f"(cataracte payante, exclue de la colonne AC du classeur)."
    )
