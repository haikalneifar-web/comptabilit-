"""Première ouverture : reprise de l'historique depuis le classeur Excel."""

from __future__ import annotations

import streamlit as st

from app_utils import get_conn, montant
from compta import store, xlsx_io
from compta.config import XLSX_PATH
from compta.model import date_longue

conn = get_conn()

st.title("Reprise de l'historique", anchor=False)
st.write(
    "Avant la première saisie, l'app recopie le contenu du classeur dans son "
    "propre registre. Le classeur n'est pas modifié par cette étape."
)

infos = xlsx_io.infos_classeur()

if not infos["existe"]:
    st.error(
        f"Classeur introuvable : `{XLSX_PATH}`\n\n"
        "Corrigez le chemin dans `compta/config.py`, ou définissez la variable "
        "d'environnement `COMPTA_XLSX`, puis rechargez la page."
    )
    st.stop()

with st.container(border=True):
    st.subheader("Classeur source", anchor=False)
    st.table(
        {
            ":material/description: Fichier": f"`{infos['chemin']}`",
            ":material/database: Taille": f"{infos['taille'] / 1_048_576:.1f} Mo",
            ":material/schedule: Dernière modification":
                infos["modifie"].strftime("%d/%m/%Y à %H:%M"),
        },
        border="horizontal",
        width="content",
    )

st.info(
    "L'import lit les 4 673 lignes de la feuille et en extrait les compteurs, "
    "les tarifs inscrits dans chaque formule et les totaux calculés. "
    "Les dates en double sont ignorées : seule la première occurrence est retenue.",
    icon=":material/info:",
)

if st.button("Importer l'historique", icon=":material/download:", type="primary"):
    barre = st.progress(0.0, text="Lecture du classeur…")
    try:
        rapport = xlsx_io.importer(conn, progress=lambda p: barre.progress(
            min(p, 1.0), text=f"Lecture du classeur… {p:.0%}"))
    except Exception as err:  # noqa: BLE001
        barre.empty()
        st.error(f"Import interrompu : {err}")
        st.stop()

    barre.progress(1.0, text="Import terminé")
    store.meta_set(conn, "import_fait", True)
    store.meta_set(conn, "import_rapport", {
        "lignes": rapport["lignes"],
        "doublons": [[r, d.isoformat()] for r, d in rapport["doublons"]],
        "premiere": rapport["premiere"].isoformat() if rapport["premiere"] else None,
        "derniere": rapport["derniere"].isoformat() if rapport["derniere"] else None,
    })

    st.success(
        f"{rapport['lignes']} journées reprises, "
        f"du {date_longue(rapport['premiere'])} au {date_longue(rapport['derniere'])}.",
        icon=":material/check_circle:",
    )

    if rapport["doublons"]:
        dates = sorted({d for _, d in rapport["doublons"]})
        st.warning(
            f"{len(rapport['doublons'])} lignes en double ignorées "
            f"({dates[0]:%d/%m/%Y} → {dates[-1]:%d/%m/%Y}). "
            "Elles restent dans le classeur : l'app n'en tient pas compte.",
            icon=":material/content_copy:",
        )

    if rapport["ab_divergents"]:
        st.warning(
            f"Sur {len(rapport['ab_divergents'])} lignes, la colonne AB du classeur "
            "compte les patients avec la formule `=C+E+H`, qui oublie les assurances "
            "et le payant. L'app retient le compte réel `=C+E+H+J+L`. Le nombre de "
            "patients affiché ici est donc supérieur à celui du classeur.",
            icon=":material/calculate:",
        )

    t = store.totaux(conn)
    cols = st.columns(4)
    cols[0].metric("Recettes cumulées", montant(t["recettes"] or 0))
    cols[1].metric("CA déclaré", montant(t["ca_declare"] or 0))
    cols[2].metric("Patients", f"{int(t['patients'] or 0):,}".replace(",", " "))
    cols[3].metric("Journées actives", f"{int(t['jours_actifs'] or 0)}")

    st.page_link("app_pages/saisie.py", label="Commencer la saisie",
                 icon=":material/arrow_forward:")
