"""Ce que les formules tirent du mois — les colonnes calculées, jour par jour.

L'écran de saisie ne porte que la grille : c'est la secrétaire qui le remplit.
Les **seize colonnes** que le classeur calcule se lisent ici, sur la page d'à
côté, en deux tableaux — ce que chaque poste rapporte (D, F, G, I, K, M, O, Q,
W), puis ce que le classeur en tire (U, X, Z, AA, AB, AC, AD). Dix-neuf
colonnes d'un seul tenant déborderaient de la page ; la liste, elle, est
complète, et `model.CALCULES` en répond face au classeur.

Rien ne s'y saisit. Et rien n'y est recalculé d'une autre façon : les journées
et leurs totaux viennent de `app_utils.calculs_du_mois`, le même code que celui
qui alimente les tuiles de l'écran de saisie. **La saisie en attente est
comprise** : ce qui est tapé sur la grille et pas encore enregistré se voit ici
aussi, et la colonne « Δ en attente » dit ce qu'elle changerait.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app_utils import (barre_export, brouillon_du_mois, calculs_du_mois,
                       get_conn, mois_affiche, selecteur_mois, totaux_registre,
                       tuiles_calculees)
from compta import store
from compta.model import CALCULES_POSTE, CALCULES_TOTAL, mois_long

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
    f"**{mois_long(annee, mois).capitalize()}** — les **seize colonnes** que le "
    "classeur calcule, journée par journée. Rien ne se saisit sur cette page ; "
    "la saisie se fait sur **Mois comptable**."
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

tableau = pd.DataFrame(calculees).set_index("Date")

# Dix-neuf colonnes dans un seul tableau déborderaient de la page et se
# liraient au défilement horizontal. Deux groupes, donc, dans l'ordre du
# classeur : ce que chaque poste rapporte, puis ce que le classeur en tire.
# Chacun donne d'abord ses totaux du mois en tuiles, puis son détail.
DATE = st.column_config.DateColumn(format="ddd DD/MM", width=100)


def montants(colonnes, largeur):
    return {libelle: st.column_config.NumberColumn(
        libelle,
        format="%d" if attribut == "patients"
        else "%.2f" if attribut == "tva_deduite" else "%.0f",
        width=largeur, help=f"Colonne {lettre} du classeur")
        for lettre, libelle, attribut, _ in colonnes}


st.markdown("##### Ce que chaque poste rapporte")
st.caption("Colonnes D, F, G, I, K, M, O, Q et W — le compteur de la journée "
           "multiplié par son tarif.")
tuiles_calculees(CALCULES_POSTE, journees, reference, par_ligne=5)
st.dataframe(
    tableau[[libelle for _, libelle, _, _ in CALCULES_POSTE]],
    height=420,
    column_config={"Date": DATE} | montants(CALCULES_POSTE, 108),
)

st.markdown("##### Ce que le classeur en tire")
st.caption("Colonnes U, X, Z, AA, AB, AC et AD — les totaux que les formules "
           "construisent à partir des précédentes.")
tuiles_calculees(CALCULES_TOTAL, journees, reference, par_ligne=4)

# « Δ en attente » n'a de sens qu'avec une saisie en attente : sans elle, c'est
# une colonne de zéros sur un écran qui ne montre que du calculé.
colonnes_tirees = [libelle for _, libelle, _, _ in CALCULES_TOTAL]
if brouillon:
    colonnes_tirees.append("Δ en attente")
st.dataframe(
    tableau[colonnes_tirees],
    height=420,
    column_config={
        "Date": DATE,
        **montants(CALCULES_TOTAL, 120),
        "Δ en attente": st.column_config.NumberColumn(
            "Δ en attente", format="%+.0f", width=118,
            help="Ce que la saisie en attente changerait aux recettes de la "
                 "journée, avant enregistrement."),
    },
)

registre_dit = "registre corrigé" if corrige else "registre réel"
barre_export(
    tableau.drop(columns=["Δ en attente"]),
    f"totaux_{annee}-{mois:02d}", f"Totaux de {mois_long(annee, mois)}",
    cle=f"calcul_{annee}_{mois}", totaux=totaux_registre(journees),
    sous_titre=f"Cabinet d'ophtalmologie · {registre_dit} · "
               "les seize colonnes calculées du classeur",
)
st.caption(":material/download: L'export reprend les seize colonnes d'un seul "
           "tenant, les deux tableaux réunis.")

with st.container(horizontal=True, vertical_alignment="center"):
    st.page_link("app_pages/journal.py", label="Retour à la saisie du mois",
                 icon=":material/calendar_month:")
    st.caption("Les modifications se font là-bas ; cette page les reflète.")
