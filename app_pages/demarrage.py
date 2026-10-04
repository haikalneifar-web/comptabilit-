"""Première ouverture : reprise de l'historique depuis le classeur Excel."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app_utils import choix_classeur, get_conn, montant
from compta import store, xlsx_io
from compta.model import date_longue

conn = get_conn()

st.title("Reprise de l'historique", anchor=False)
st.write(
    "Avant la première saisie, l'app recopie le contenu du classeur dans son "
    "propre registre. Le classeur n'est pas modifié par cette étape."
)

chemin = choix_classeur(conn, "demarrage")
infos = xlsx_io.infos_classeur(chemin)

if not infos["existe"]:
    st.error(f"Classeur introuvable : `{chemin}`\n\nIndiquez le bon fichier ci-dessus.")
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
        rapport = xlsx_io.importer(conn, chemin, progress=lambda p: barre.progress(
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
        # gardé au registre : sans ça, le constat repart avec la page
        "postes_sans_tarif": [
            dict(p, premiere=p["premiere"].isoformat(),
                 derniere=p["derniere"].isoformat(),
                 tarifs={str(t): n for t, n in p["tarifs"].items()})
            for p in rapport["postes_sans_tarif"]
        ],
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

    if rapport["postes_sans_tarif"]:
        postes = rapport["postes_sans_tarif"]
        st.warning(
            f"**Des actes comptés sans montant en face.** Sur "
            f"{sum(p['journees'] for p in postes)} journées, un compteur est rempli "
            "alors que sa colonne de montant est **vide — pas à zéro, sans formule "
            "du tout**. Le classeur ne les valorise nulle part : la colonne `U` "
            "additionne une cellule vide, ils ne sont donc dans aucun total, ni "
            "ici ni dans le fichier.",
            icon=":material/money_off:",
        )
        st.dataframe(
            pd.DataFrame([
                {
                    "Poste": p["libelle"],
                    "Colonnes": f"{p['compteur']} → {p['colonne']}",
                    "Journées": p["journees"],
                    "Actes": p["actes"],
                    "Période": f"{p['premiere']:%m/%Y} → {p['derniere']:%m/%Y}",
                    "Tarif voisin": " / ".join(
                        f"{t:g}" for t in sorted(p["tarifs"]) if t is not None),
                    "Manque au CA": montant(p["montant"]),
                }
                for p in postes
            ]),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "Les tarifs ci-dessus sont ceux des lignes voisines, et c'est celui-là "
            "que le registre retient pour ces journées — pas le tarif d'aujourd'hui. "
            "Les montants du classeur, eux, ne sont pas touchés : décider si ces "
            "actes doivent être portés au CA est une rectification, à faire journée "
            "par journée avec son motif."
        )

    t = store.totaux(conn)
    cols = st.columns(4)
    cols[0].metric("Recettes cumulées", montant(t["recettes"] or 0))
    cols[1].metric("CA déclaré", montant(t["ca_declare"] or 0))
    cols[2].metric("Patients", f"{int(t['patients'] or 0):,}".replace(",", " "))
    cols[3].metric("Journées actives", f"{int(t['jours_actifs'] or 0)}")

    # La navigation de ce passage-ci n'a qu'une page : les autres ne s'ouvrent
    # qu'avec `import_fait`, que l'import vient tout juste de poser. Un lien
    # direct vers la saisie échouerait donc ici même. Ce bouton relance l'app,
    # qui s'ouvrira sur le mois à saisir — et laisse lire ce qui précède.
    if st.button("Commencer la saisie", icon=":material/arrow_forward:",
                 type="primary"):
        st.rerun()
