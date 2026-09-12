"""Tableau de bord : évolution, composition, part non déclarée."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app_utils import get_conn, montant
from compta import store

conn = get_conn()

st.header("Tableau de bord", anchor=False)

vue = st.segmented_control(
    "Registre", ["Corrigé", "Réel"], default=st.session_state.registre,
    key="registre_bord",
)
if vue:
    st.session_state.registre = vue
corrige = st.session_state.registre == "Corrigé"

nb_rectifs = store.nb_rectifications(conn)
if nb_rectifs:
    st.caption(
        f":material/edit_note: {nb_rectifs} rectification(s) au journal. "
        + ("Les chiffres ci-dessous les intègrent."
           if corrige else "Les chiffres ci-dessous les ignorent : valeurs d'origine.")
    )

t = store.totaux(conn, corrige=corrige)
if not t or not t["jours"]:
    st.info("Aucune donnée à afficher.", icon=":material/inbox:")
    st.stop()

recettes = t["recettes"] or 0.0
declare = t["ca_declare"] or 0.0
ecart = recettes - declare
actifs = int(t["jours_actifs"] or 0)

cols = st.columns(5)
cols[0].metric("Recettes cumulées", montant(recettes))
cols[1].metric("CA déclaré", montant(declare),
               delta=f"{100 * declare / recettes:.1f} % des recettes".replace(".", ","),
               delta_color="off")
cols[2].metric("Non déclaré", montant(ecart),
               delta=f"{100 * ecart / recettes:.1f} %".replace(".", ","),
               delta_color="off")
cols[3].metric("Patients", f"{int(t['patients'] or 0):,}".replace(",", " "))
cols[4].metric("Recette / jour actif", montant(recettes / actifs if actifs else 0))

st.divider()

# --- évolution mensuelle -----------------------------------------------------

periodes = {"Tout l'historique": None, "5 dernières années": 60, "24 derniers mois": 24}
choix = st.segmented_control("Période", list(periodes), default="24 derniers mois",
                             key="periode_bord", label_visibility="collapsed")
mois = store.agregat_mensuel(conn, corrige=corrige)
limite = periodes.get(choix)
if limite:
    mois = mois[-limite:]

df_mois = pd.DataFrame([
    {
        "Mois": pd.Period(r["mois"], freq="M").to_timestamp(),
        "Recettes": r["recettes"] or 0.0,
        "CA déclaré": r["ca_declare"] or 0.0,
        "Non déclaré": (r["recettes"] or 0.0) - (r["ca_declare"] or 0.0),
        "Patients": int(r["patients"] or 0),
        "Jours actifs": int(r["jours_actifs"] or 0),
    }
    for r in mois
])

st.subheader("Évolution mensuelle", anchor=False)
long = df_mois.melt(id_vars="Mois", value_vars=["Recettes", "CA déclaré"],
                    var_name="Série", value_name="Montant")
courbe = (
    alt.Chart(long)
    .mark_line(strokeWidth=2, point=False)
    .encode(
        x=alt.X("Mois:T", title=None),
        y=alt.Y("Montant:Q", title="TND"),
        color=alt.Color("Série:N", title=None,
                        scale=alt.Scale(domain=["Recettes", "CA déclaré"],
                                        range=["#2a78d6", "#eb6834"])),
        tooltip=[alt.Tooltip("Mois:T", format="%m/%Y"), "Série:N",
                 alt.Tooltip("Montant:Q", format=",.0f")],
    )
    .properties(height=320)
)
st.altair_chart(courbe)

creux = df_mois[df_mois["Recettes"] == 0]
if not creux.empty:
    st.caption(
        ":material/report: Mois sans aucune saisie : "
        + ", ".join(creux["Mois"].dt.strftime("%m/%Y"))
    )

st.divider()

# --- vue annuelle ------------------------------------------------------------

annees = store.agregat_annuel(conn, corrige=corrige)
df_an = pd.DataFrame([
    {
        "Année": r["annee"],
        "Payant": r["pay_m"] or 0.0,
        "Remboursement CNAM": r["remb_m"] or 0.0,
        "Cataracte CNAM": r["cat_cnam_m"] or 0.0,
        "Cataracte payante": r["cat_pay_m"] or 0.0,
        "APCI": r["apci_m"] or 0.0,
        "Assurance": r["star_m"] or 0.0,
        "Recettes": r["recettes"] or 0.0,
        "CA déclaré": r["ca_declare"] or 0.0,
        "Non déclaré": (r["recettes"] or 0.0) - (r["ca_declare"] or 0.0),
        "Cataractes CNAM": int(r["cat_cnam_n"] or 0),
        "Cataractes payantes": int(r["cat_pay_n"] or 0),
        "Jours actifs": int(r["jours_actifs"] or 0),
    }
    for r in annees
])

gauche, droite = st.columns(2)

with gauche:
    st.subheader("Composition des recettes", anchor=False)
    postes = ["Payant", "Remboursement CNAM", "Cataracte CNAM",
              "Cataracte payante", "APCI", "Assurance"]
    empile = df_an.melt(id_vars="Année", value_vars=postes,
                        var_name="Poste", value_name="Montant")
    st.altair_chart(
        alt.Chart(empile)
        .mark_bar(size=22)
        .encode(
            x=alt.X("Année:N", title=None),
            y=alt.Y("Montant:Q", title="TND", stack="zero"),
            color=alt.Color("Poste:N", title=None,
                            scale=alt.Scale(domain=postes,
                                            range=["#2a78d6", "#eb6834", "#1baf7a",
                                                   "#eda100", "#e87ba4", "#9aa5af"]),
                            legend=alt.Legend(orient="bottom", columns=3)),
            tooltip=["Année:N", "Poste:N", alt.Tooltip("Montant:Q", format=",.0f")],
        )
        .properties(height=320)
    )

with droite:
    st.subheader("Volume de cataractes", anchor=False)
    chir = df_an.melt(id_vars="Année",
                      value_vars=["Cataractes CNAM", "Cataractes payantes"],
                      var_name="Type", value_name="Actes")
    st.altair_chart(
        alt.Chart(chir)
        .mark_bar()
        .encode(
            x=alt.X("Année:N", title=None),
            xOffset="Type:N",
            y=alt.Y("Actes:Q", title="actes"),
            color=alt.Color("Type:N", title=None,
                            scale=alt.Scale(domain=["Cataractes CNAM",
                                                    "Cataractes payantes"],
                                            range=["#1baf7a", "#eda100"]),
                            legend=alt.Legend(orient="bottom")),
            tooltip=["Année:N", "Type:N", "Actes:Q"],
        )
        .properties(height=320)
    )

st.subheader("Récapitulatif annuel", anchor=False)
st.dataframe(
    df_an[["Année", "Jours actifs", "Recettes", "CA déclaré", "Non déclaré",
           "Cataractes CNAM", "Cataractes payantes"]],
    hide_index=True,
    column_config={
        "Recettes": st.column_config.NumberColumn(format="%.0f TND"),
        "CA déclaré": st.column_config.NumberColumn(format="%.0f TND"),
        "Non déclaré": st.column_config.NumberColumn(format="%.0f TND"),
    },
)
st.caption(
    "« Non déclaré » = recettes moins la colonne AC du classeur. La formule AC "
    "exclut la colonne Q (cataracte payante) : c'est ce qui produit l'écart."
)
