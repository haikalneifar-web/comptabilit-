"""Ce que les formules tirent du mois — les colonnes calculées, jour par jour.

L'écran de saisie ne porte que la grille : c'est la secrétaire qui le remplit.
Les colonnes que le classeur calcule — recettes, caisse, dû CNAM, patients, CA
à déclarer — se lisent ici, sur la page d'à côté.

Rien ne s'y saisit. Et rien n'y est recalculé d'une autre façon : les journées
et leurs totaux viennent de `app_utils.calculs_du_mois`, le même code que celui
qui alimente les tuiles de l'écran de saisie. **La saisie en attente est
comprise** : ce qui est tapé sur la grille et pas encore enregistré se voit ici
aussi, et la colonne « Δ en attente » dit ce qu'elle changerait.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app_utils import (bandeau_mois, barre_export, brouillon_du_mois,
                       calculs_du_mois, get_conn, mois_affiche,
                       selecteur_mois, totaux_registre)
from compta import store
from compta.model import mois_long

conn = get_conn()
tarifs = store.tarifs_courants(conn)
frontiere = store.frontiere_tarifs(conn)
premiere, derniere = store.bornes(conn)

st.header("Totaux du mois", anchor=False)

if premiere is None:
    st.info("Aucune journée enregistrée.", icon=":material/inbox:")
    st.stop()

if st.session_state.mois_travail is None:
    st.session_state.mois_travail = store.mois_a_saisir(conn)

choix_mois, choix_registre = st.columns([3, 1], vertical_alignment="bottom")
with choix_mois:
    annee, mois = selecteur_mois(premiere, derniere)
with choix_registre:
    vue = st.segmented_control(
        "Registre", ["Corrigé", "Réel"], default=st.session_state.registre,
        key="registre_totaux",
    )
if vue:
    st.session_state.registre = vue
corrige = st.session_state.registre == "Corrigé"

par_date = mois_affiche(conn, annee, mois, corrige, tarifs)
# la saisie en attente ne vaut que pour le registre corrigé : le réel montre
# les valeurs d'origine, et il ne s'édite pas
brouillon = brouillon_du_mois(annee, mois) if corrige else {}
journees, calculees = calculs_du_mois(par_date, tarifs, frontiere, brouillon)

st.caption(
    f"**{mois_long(annee, mois).capitalize()}** — colonnes U, X, Z, AB, AC du "
    "classeur, calculées journée par journée. Rien ne se saisit sur cette "
    "page ; la saisie se fait sur **Mois comptable**."
)

if brouillon:
    positions = {position for position, _ in brouillon}
    st.info(
        f"**{len(brouillon)} modification(s) en attente** sur "
        f"{len(positions)} journée(s), tapées sur l'écran de saisie et pas "
        "encore enregistrées. Elles sont comprises dans ce qui s'affiche ici.",
        icon=":material/edit_note:",
    )

reference = (calculs_du_mois(par_date, tarifs, frontiere)[0]
             if brouillon else None)
bandeau_mois(journees, reference=reference)

st.dataframe(
    pd.DataFrame(calculees).set_index("Date"),
    height=620,
    column_config={
        "Date": st.column_config.DateColumn(format="ddd DD/MM", width=110),
        "État": st.column_config.TextColumn(width=100),
        "Patients": st.column_config.NumberColumn(format="%d", width=100,
                                                  help="Colonne AB"),
        "Recettes": st.column_config.NumberColumn(format="%.0f", width=120,
                                                  help="Colonne U"),
        "CA déclaré": st.column_config.NumberColumn(format="%.0f", width=120,
                                                    help="Colonne AC"),
        "Caisse": st.column_config.NumberColumn(format="%.0f", width=110,
                                                help="Colonne X"),
        "Dû CNAM": st.column_config.NumberColumn(format="%.0f", width=110,
                                                 help="Colonne Z"),
        "Δ en attente": st.column_config.NumberColumn(
            "Δ en attente", format="%+.0f", width=130,
            help="Ce que la saisie en attente changerait aux recettes de la "
                 "journée, avant enregistrement."),
    },
)

registre_dit = "registre corrigé" if corrige else "registre réel"
barre_export(
    pd.DataFrame(calculees).set_index("Date").drop(columns=["Δ en attente"]),
    f"totaux_{annee}-{mois:02d}", f"Totaux de {mois_long(annee, mois)}",
    cle=f"calcul_{annee}_{mois}", totaux=totaux_registre(journees),
    sous_titre=f"Cabinet d'ophtalmologie · {registre_dit} · "
               "colonnes calculées du classeur",
)

with st.container(horizontal=True, vertical_alignment="center"):
    st.page_link("app_pages/journal.py", label="Retour à la saisie du mois",
                 icon=":material/calendar_month:")
    st.caption("Les modifications se font là-bas ; cette page les reflète.")
