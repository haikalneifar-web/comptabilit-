"""Tarifs unitaires appliqués aux nouvelles journées."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app_utils import get_conn, memoriser, oublier
from compta import store
from compta.model import CHAMPS_SAISIE, LIBELLES_TARIFS, TARIFS_DEFAUT, tnd

conn = get_conn()
courants = store.tarifs_courants(conn)

st.header("Tarifs", anchor=False)
st.write(
    "Ces tarifs s'appliquent à **toute journée qui ne porte pas encore de "
    "chiffres**, y compris les lignes déjà présentes dans le classeur mais "
    "vides — celui-ci est pré-rempli jusqu'au 23/01/2027 avec le tarif qui "
    "avait cours quand ces lignes ont été préparées. Une journée qui porte des "
    "chiffres, ou qui est clôturée, garde le sien : modifier cette page ne "
    "réécrit jamais le passé."
)
st.caption(
    "À l'écriture dans le classeur, la constante de la formule d'une journée "
    "ouverte est remise à jour si elle a vieilli, pour qu'Excel calcule le même "
    "montant que l'app."
)

# --- écart entre les tarifs en vigueur et ceux des lignes vides à venir -------

vides = conn.execute(f"""
    SELECT {', '.join(f'MIN({t}) min_{t}, MAX({t}) max_{t}' for t in LIBELLES_TARIFS)},
           COUNT(*) n, MIN(date) debut, MAX(date) fin
    FROM jours
    WHERE cloture=0 AND ({' + '.join(CHAMPS_SAISIE)}) = 0 AND date >= date('now')
""").fetchone()

if vides and vides["n"]:
    perimes = [
        (LIBELLES_TARIFS[t], vides[f"min_{t}"], courants[t])
        for t in LIBELLES_TARIFS
        if abs((vides[f"min_{t}"] or 0) - courants[t]) > 0.005
        or abs((vides[f"max_{t}"] or 0) - courants[t]) > 0.005
    ]
    if perimes:
        st.warning(
            f"{vides['n']} journées à venir attendent au registre "
            f"({vides['debut']} → {vides['fin']}) avec un tarif dépassé :\n\n"
            + "\n".join(f"- {libelle} : {tnd(ancien)} → **{tnd(nouveau)}** TND"
                        for libelle, ancien, nouveau in perimes)
            + "\n\nElles prendront le tarif ci-dessus à la saisie, et la formule "
              "du classeur sera alignée à l'écriture.",
            icon=":material/sell:",
        )

# les tarifs en cours de frappe survivent au changement d'onglet
for cle in LIBELLES_TARIFS:
    champ = f"tarif_{cle}"
    if not memoriser(champ) and champ not in st.session_state:
        st.session_state[champ] = float(courants[cle])

with st.form("tarifs"):
    saisis = {}
    cols = st.columns(3)
    for i, (cle, libelle) in enumerate(LIBELLES_TARIFS.items()):
        saisis[cle] = cols[i % 3].number_input(
            libelle, min_value=0.0, step=1.0, format="%.2f", key=f"tarif_{cle}",
        )
    with st.container(horizontal=True):
        enregistrer = st.form_submit_button("Enregistrer", icon=":material/save:",
                                            type="primary")
        reinitialiser = st.form_submit_button("Valeurs du classeur",
                                              icon=":material/restart_alt:")

champs = [f"tarif_{c}" for c in LIBELLES_TARIFS]

if enregistrer:
    store.enregistrer_tarifs(conn, saisis)
    oublier(*champs)
    st.toast("Tarifs enregistrés.", icon=":material/check:")
    st.rerun()

if reinitialiser:
    store.enregistrer_tarifs(conn, TARIFS_DEFAUT)
    oublier(*champs)
    st.toast("Tarifs remis aux valeurs relevées en juillet 2026.",
             icon=":material/restart_alt:")
    st.rerun()

st.divider()

# --- historique des tarifs effectivement appliqués ---------------------------

st.subheader("Tarifs appliqués par année", anchor=False)
st.caption("Relevés dans les formules du classeur, année par année.")

lignes = conn.execute("""
    SELECT substr(date,1,4) annee,
           ROUND(AVG(NULLIF(t_pay,0)),2)       t_pay,
           ROUND(AVG(NULLIF(t_remb,0)),2)      t_remb,
           ROUND(AVG(NULLIF(t_apci,0)),2)      t_apci,
           ROUND(AVG(NULLIF(t_tp_recu,0)),2)   t_tp_recu,
           ROUND(AVG(NULLIF(t_tp_reste,0)),2)  t_tp_reste,
           ROUND(AVG(NULLIF(t_star,0)),2)      t_star,
           ROUND(AVG(NULLIF(t_cat_cnam,0)),2)  t_cat_cnam,
           ROUND(AVG(NULLIF(t_cat_pay,0)),2)   t_cat_pay
    FROM jours GROUP BY annee ORDER BY annee
""").fetchall()

if lignes:
    df = pd.DataFrame([dict(r) for r in lignes]).rename(
        columns={"annee": "Année", **LIBELLES_TARIFS})
    st.dataframe(df, hide_index=True)
    st.caption(
        "Une valeur intermédiaire (par ex. 39,65) signale un changement de tarif "
        "en cours d'année, pas une erreur."
    )

with st.expander("À quoi sert le complément tiers payant (colonne W)",
                 icon=":material/help:"):
    st.write(
        f"""
La colonne **W** du classeur vaut `= E × {tnd(courants['t_tva_tp'], 2)}`, soit un
montant par patient en tiers payant qui s'ajoute aux recettes (colonne U) sans
apparaître dans aucun poste de consultation.

C'est ce qui explique les écarts de réconciliation de 11 TND par patient observés
sur les années 2017 à 2019. Le montant est repris tel quel par l'app : il entre
dans les recettes et dans la caisse, mais pas dans le CA à déclarer.
        """
    )
