"""Registre de recettes — cabinet d'ophtalmologie.

Saisie quotidienne adossée au classeur « compta jdid .xlsx ».
Lancement :  streamlit run streamlit_app.py
"""

from __future__ import annotations

import streamlit as st

from app_utils import badge_export, get_conn
from compta import store

st.set_page_config(
    page_title="Registre du cabinet",
    page_icon=":material/visibility:",
    layout="wide",
)

conn = get_conn()

st.session_state.setdefault("date_saisie", None)
st.session_state.setdefault("mode_saisie", "Patient par patient")
# vue par défaut : le registre corrigé, c'est-à-dire le réel plus les
# rectifications motivées. « Réel » montre les valeurs d'origine, intactes.
st.session_state.setdefault("registre", "Corrigé")
# mois ouvert dans le tableau ; résolu au premier affichage sur le mois qui
# reste à saisir, puis mémorisé d'une page à l'autre
st.session_state.setdefault("mois_travail", None)

if not store.meta_get(conn, "import_fait", False):
    pages = [
        st.Page("app_pages/demarrage.py", title="Démarrage",
                icon=":material/rocket_launch:", default=True)
    ]
else:
    en_attente = badge_export(conn)
    titre_excel = "Classeur Excel" if not en_attente else f"Classeur Excel ({en_attente})"
    nb_rectifs = store.nb_rectifications(conn)
    titre_rectifs = "Rectifications" if not nb_rectifs else f"Rectifications ({nb_rectifs})"

    # une saisie en cours ailleurs doit rester visible depuis n'importe quel onglet
    brouillons = st.session_state.get("_brouillons", {})
    en_cours = sum(
        len({position for position, _ in v})
        for c, v in brouillons.items()
        if c.startswith("grille_") and isinstance(v, dict) and v
    )
    titre_mois = "Mois comptable" if not en_cours else f"Mois comptable ● {en_cours}"
    # La saisie se fait en fin de mois comptable : le tableau du mois est
    # l'écran de travail, la saisie au jour le jour ne sert qu'en appoint.
    pages = [
        st.Page("app_pages/journal.py", title=titre_mois,
                icon=":material/calendar_month:", default=True),
        # juste après la saisie : ce que les formules en tirent, que l'écran de
        # saisie ne montre plus
        st.Page("app_pages/totaux.py", title="Totaux du mois",
                icon=":material/functions:"),
        st.Page("app_pages/rectifications.py", title=titre_rectifs,
                icon=":material/edit_note:"),
        st.Page("app_pages/saisie.py", title="Saisie du jour",
                icon=":material/add_circle:"),
        st.Page("app_pages/bordereaux.py", title="Bordereaux",
                icon=":material/description:"),
        st.Page("app_pages/tableau_bord.py", title="Tableau de bord",
                icon=":material/insights:"),
        st.Page("app_pages/excel.py", title=titre_excel,
                icon=":material/table_view:"),
        st.Page("app_pages/tarifs.py", title="Tarifs",
                icon=":material/sell:"),
    ]

page = st.navigation(pages, position="top")
page.run()
