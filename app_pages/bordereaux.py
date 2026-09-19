"""Bordereaux mensuels : générer le mois, en garder la trace, suivre l'évolution.

Un bordereau est le mois du registre extrait dans un classeur autonome, montants
en formules vivantes — voir `compta/bordereau.py`. Cette page le fabrique, le
range, et consigne chaque édition : rééditer un mois après une rectification
n'efface pas l'édition précédente, il s'ajoute une ligne à l'historique et
l'écart entre les deux se lit.
"""

from __future__ import annotations

import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

from app_utils import get_conn, montant, selecteur_mois
from compta import bordereau, store, xlsx_io
from compta.config import BORDEREAUX_DIR
from compta.model import mois_long

conn = get_conn()
tarifs = store.tarifs_courants(conn)
premiere, derniere = store.bornes(conn)

st.header("Bordereaux mensuels", anchor=False)

if premiere is None:
    st.info("Aucune journée enregistrée.", icon=":material/inbox:")
    st.stop()

# Un bordereau édité sur un registre en retard sur le classeur serait faux sans
# que rien ne le dise.
sync = xlsx_io.etat_synchronisation(conn)
if sync["connu"] and not sync["a_jour"]:
    st.warning(
        f"Le classeur a été modifié le **{sync['modifie_le']:%d/%m/%Y à %H:%M}**, "
        f"après sa dernière lecture par l'app le "
        f"{sync['lu_le']:%d/%m/%Y à %H:%M}. Un bordereau édité maintenant "
        "porterait les chiffres que l'app connaît, pas ceux du fichier — "
        "réimportez depuis **Classeur Excel**.",
        icon=":material/sync_problem:",
    )

# --- choix du mois et du registre --------------------------------------------

if st.session_state.mois_travail is None:
    st.session_state.mois_travail = store.mois_a_saisir(conn)

annee, mois = selecteur_mois(premiere, derniere)

vue = st.segmented_control(
    "Registre", ["Corrigé", "Réel"], default=st.session_state.registre,
    key="registre_bordereau", label_visibility="collapsed",
)
if vue:
    st.session_state.registre = vue
corrige = st.session_state.registre == "Corrigé"
nom_registre = "corrigé" if corrige else "réel"

cle_mois = f"{annee}-{mois:02d}"
journees = store.mois_en_journees(conn, annee, mois, corrige=corrige, tarifs=tarifs)
totaux = bordereau.totaux(journees)

# --- le mois, et son évolution -----------------------------------------------

agregats = {r["mois"]: r for r in store.agregat_mensuel(conn, corrige=corrige)}


def _precedent(pas_mois: int) -> dict | None:
    """Le mois situé `pas_mois` en arrière, s'il est au registre."""
    a, m = divmod(annee * 12 + (mois - 1) - pas_mois, 12)
    return agregats.get(f"{a}-{m + 1:02d}")


mois_avant, an_avant = _precedent(1), _precedent(12)


def _delta(champ: str, reference: dict | None) -> str | None:
    if not reference or not reference.get(champ):
        return None
    ecart = totaux[champ] - float(reference[champ])
    return f"{ecart:+,.0f}".replace(",", " ") + " TND"


cols = st.columns(5)
cols[0].metric("Recettes", montant(totaux["recettes"]),
               delta=_delta("recettes", mois_avant))
cols[1].metric("CA à déclarer", montant(totaux["ca_declare"]),
               delta=_delta("ca_declare", mois_avant))
cols[2].metric("Caisse", montant(totaux["caisse"]),
               delta=_delta("caisse", mois_avant))
cols[3].metric("À la charge CNAM", montant(totaux["charge_cnam"]),
               delta=_delta("charge_cnam", mois_avant))
cols[4].metric("Patients", f"{int(totaux['patients'])}",
               delta=(f"{int(totaux['patients']) - int(mois_avant['patients']):+d}"
                      if mois_avant and mois_avant.get("patients") else None))

st.caption(
    f"{int(totaux['jours_actifs'])} jour(s) renseigné(s) sur "
    f"{int(totaux['jours'])} · {int(totaux['actes_chirurgie'])} acte(s) de "
    "chirurgie · écarts calculés sur le mois précédent"
    + (f" · même mois l'an dernier : {montant(float(an_avant['recettes'] or 0))} "
       "de recettes" if an_avant else "")
)

if totaux["jours_actifs"] == 0:
    st.warning(
        f"{mois_long(annee, mois).capitalize()} ne porte aucun chiffre. Un "
        "bordereau de ce mois serait une feuille à zéro — saisissez le mois "
        "depuis **Mois comptable** avant de l'éditer.",
        icon=":material/edit_calendar:",
    )

st.divider()

# --- générer ------------------------------------------------------------------

st.subheader(f"Bordereau de {mois_long(annee, mois)}", anchor=False)

st.caption(
    ":material/function: Le fichier reprend la feuille du classeur — colonnes "
    "A→AD, en-tête sur trois lignes, journées à partir de la ligne 4. **Seuls "
    "les compteurs et les montants saisis sont des valeurs** ; D, F, G, I, K, M, "
    "O, Q, U, W, X, Y, Z, AA, AB, AC et AD restent les formules du classeur, et "
    "la dernière ligne les additionne. Une seconde feuille récapitule la "
    "provenance, les totaux et les tarifs appliqués."
)
COURTS = {
    "t_apci": "APCI", "t_tp_recu": "TP reçu", "t_tp_reste": "TP reste",
    "t_remb": "remb", "t_star": "assurance", "t_pay": "payant",
    "t_cat_cnam": "cataracte CNAM", "t_cat_pay": "cataracte payante",
    "t_tva_tp": "TVA TP",
}
releve = bordereau.tarifs_du_mois(journees)
st.caption(
    ":material/sell: Chaque journée garde **son** tarif : une journée de 2019 "
    "s'écrit au prix de 2019. Tarifs de ce mois — "
    + " · ".join(
        f"{COURTS.get(cle, cle)} **{'/'.join(f'{v:.0f}' for v in valeurs)}**"
        for cle, valeurs in releve.items()
    )
    + (" — un poste porte deux prix dans le mois, le récapitulatif le signale."
       if any(len(v) > 1 for v in releve.values()) else "")
)

editions = store.bordereaux_du_mois(conn, annee, mois)
if editions:
    derniere_edition = editions[0]
    edite_le = dt.datetime.fromisoformat(derniere_edition["edite_le"])
    ecart = totaux["recettes"] - float(derniere_edition["totaux"].get("recettes", 0))
    if abs(ecart) > 0.005:
        depuis = (" — le registre dit aujourd'hui **"
                  + f"{ecart:+,.0f}".replace(",", " ")
                  + " TND** de recettes de plus")
    else:
        depuis = " — les chiffres n'ont pas bougé depuis"
    st.info(
        f"Ce mois a déjà été édité **{len(editions)} fois**, la dernière le "
        f"{edite_le:%d/%m/%Y à %H:%M} sur le registre "
        f"{derniere_edition['registre']}{depuis}.",
        icon=":material/history:",
    )

cle_produit = f"bordereau_produit_{cle_mois}"

with st.container(horizontal=True, vertical_alignment="center"):
    generer = st.button(
        "Générer le bordereau", icon=":material/description:", type="primary",
        disabled=totaux["jours_actifs"] == 0,
    )
    st.caption(f"Il sera rangé dans `{BORDEREAUX_DIR / str(annee)}`. Une "
               "édition précédente du même mois part dans `archives/`.")

if generer:
    contenu = bordereau.construire(journees, annee, mois, registre=nom_registre)
    chemin, archive = bordereau.enregistrer(contenu, annee, mois)
    store.enregistrer_bordereau(
        conn, annee, mois, nom_registre, bordereau.empreinte(contenu), totaux,
        fichier=str(chemin),
    )
    st.session_state[cle_produit] = {
        "contenu": contenu, "chemin": str(chemin),
        "archive": str(archive) if archive else None,
    }
    st.rerun()

produit = st.session_state.get(cle_produit)
if produit:
    st.success(f"Bordereau enregistré : `{produit['chemin']}`",
               icon=":material/check_circle:")
    if produit["archive"]:
        st.caption(f":material/inventory_2: Édition précédente conservée : "
                   f"`{produit['archive']}`")
    st.download_button(
        "Télécharger le bordereau", data=produit["contenu"],
        file_name=bordereau.nom_fichier(annee, mois),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:", key=f"dl_{cle_mois}",
    )

# --- le détail du mois --------------------------------------------------------

with st.expander(f"Les {len(journees)} journées telles qu'elles partiront",
                 icon=":material/table_rows:"):
    st.dataframe(
        pd.DataFrame([
            {
                "Date": j.date,
                "Jour": j.nom_jour.capitalize(),
                "APCI": j.apci_n, "TP": j.tp_n, "Remb": j.remb_n,
                "Assurance": j.star_n, "Payant": j.pay_n,
                "Cat. CNAM": j.cat_cnam_n, "Cat. payante": j.cat_pay_n,
                "Recettes": j.recettes, "CA à déclarer": j.ca_declare,
                "Caisse": j.caisse, "Patients": j.patients,
            }
            for j in journees
        ]),
        hide_index=True,
        column_config={
            "Date": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Recettes": st.column_config.NumberColumn(format="%.0f"),
            "CA à déclarer": st.column_config.NumberColumn(format="%.0f"),
            "Caisse": st.column_config.NumberColumn(format="%.0f"),
        },
        height=420,
    )

st.divider()

# --- historique des éditions --------------------------------------------------

st.subheader("Historique", anchor=False)

if editions:
    st.caption(
        f"**Éditions de {mois_long(annee, mois)}** — de la plus récente à la "
        "plus ancienne. L'écart est calculé sur l'édition qui précède."
    )
    lignes = []
    for i, e in enumerate(editions):
        avant = editions[i + 1]["totaux"] if i + 1 < len(editions) else None
        lignes.append({
            "Édité le": dt.datetime.fromisoformat(e["edite_le"]),
            "Registre": e["registre"],
            "Recettes": e["totaux"].get("recettes", 0.0),
            "CA à déclarer": e["totaux"].get("ca_declare", 0.0),
            "Patients": int(e["totaux"].get("patients", 0)),
            "Δ recettes": (e["totaux"].get("recettes", 0.0)
                           - avant.get("recettes", 0.0)) if avant else None,
            "Empreinte": e["empreinte"],
        })
    st.dataframe(
        pd.DataFrame(lignes), hide_index=True,
        column_config={
            "Édité le": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
            "Recettes": st.column_config.NumberColumn(format="%.0f TND"),
            "CA à déclarer": st.column_config.NumberColumn(format="%.0f TND"),
            "Δ recettes": st.column_config.NumberColumn(
                format="%+.0f",
                help="Écart de recettes avec l'édition précédente du même mois."),
        },
    )
else:
    st.caption(f"{mois_long(annee, mois).capitalize()} n'a pas encore été édité.")

# --- évolution ----------------------------------------------------------------

edites = store.derniers_bordereaux_par_mois(conn)

periodes = {"24 derniers mois": 24, "5 dernières années": 60, "Tout l'historique": None}
choix = st.segmented_control("Période", list(periodes), default="24 derniers mois",
                             key="periode_bordereaux", label_visibility="collapsed")
serie = list(agregats.values())
limite = periodes.get(choix)
if limite:
    serie = serie[-limite:]

df = pd.DataFrame([
    {
        "Mois": pd.Period(r["mois"], freq="M").to_timestamp(),
        "Recettes": r["recettes"] or 0.0,
        "CA à déclarer": r["ca_declare"] or 0.0,
        "Édité": r["mois"] in edites,
    }
    for r in serie
])

if df.empty:
    st.stop()

long = df.melt(id_vars=["Mois", "Édité"], value_vars=["Recettes", "CA à déclarer"],
               var_name="Série", value_name="Montant")
couleurs = alt.Scale(domain=["Recettes", "CA à déclarer"],
                     range=["#2a78d6", "#eb6834"])
base_graphe = alt.Chart(long).encode(
    x=alt.X("Mois:T", title=None),
    y=alt.Y("Montant:Q", title="TND"),
    color=alt.Color("Série:N", title=None, scale=couleurs),
    tooltip=[alt.Tooltip("Mois:T", format="%m/%Y"), "Série:N",
             alt.Tooltip("Montant:Q", format=",.0f"), "Édité:N"],
)
st.altair_chart(
    (base_graphe.mark_line(strokeWidth=2)
     + base_graphe.transform_filter(alt.datum["Édité"]).mark_point(
         size=70, filled=True, opacity=1))
    .properties(height=320)
)
st.caption(
    ":material/circle: Les points marquent les mois dont un bordereau a été "
    f"édité — {len(edites)} mois à ce jour. La courbe, elle, vient du registre "
    f"{nom_registre}."
)

if edites:
    st.caption("**Tous les mois édités**, dernière édition de chacun.")
    st.dataframe(
        pd.DataFrame([
            {
                "Mois": pd.Period(m, freq="M").to_timestamp(),
                "Éditions": len(store.bordereaux_du_mois(conn, *map(int, m.split("-")))),
                "Dernière édition": dt.datetime.fromisoformat(e["edite_le"]),
                "Registre": e["registre"],
                "Recettes": e["totaux"].get("recettes", 0.0),
                "CA à déclarer": e["totaux"].get("ca_declare", 0.0),
                "Patients": int(e["totaux"].get("patients", 0)),
                "Fichier": e["fichier"] or "",
            }
            for m, e in sorted(edites.items(), reverse=True)
        ]),
        hide_index=True,
        column_config={
            "Mois": st.column_config.DateColumn(format="MM/YYYY"),
            "Dernière édition": st.column_config.DatetimeColumn(
                format="DD/MM/YYYY HH:mm"),
            "Recettes": st.column_config.NumberColumn(format="%.0f TND"),
            "CA à déclarer": st.column_config.NumberColumn(format="%.0f TND"),
        },
    )
