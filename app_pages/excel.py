"""Écriture des journées saisies dans « compta jdid .xlsx »."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from app_utils import get_conn, montant
from compta import store, xlsx_io
from compta.config import BACKUP_DIR
from compta.model import tnd

conn = get_conn()
tarifs = store.tarifs_courants(conn)

st.header("Classeur Excel", anchor=False)

infos = xlsx_io.infos_classeur()
if not infos["existe"]:
    st.error("Classeur introuvable. Vérifiez le chemin dans `compta/config.py`.")
    st.stop()

st.table(
    {
        ":material/description: Fichier": f"`{infos['chemin']}`",
        ":material/schedule: Dernière modification":
            infos["modifie"].strftime("%d/%m/%Y à %H:%M"),
        ":material/database: Taille": f"{infos['taille'] / 1_048_576:.1f} Mo",
    },
    border="horizontal",
    width="content",
)

st.info(
    "L'app n'écrit que les colonnes de saisie — C, E, H, J, L, N, P (compteurs) et "
    "R, S, T, V (montants). Les colonnes de montants et de totaux restent des "
    "formules Excel : elles se recalculent à l'ouverture du fichier.",
    icon=":material/shield:",
)
st.caption(
    ":material/edit_note: C'est le **registre corrigé** qui part dans le classeur : "
    "les valeurs d'origine plus les rectifications motivées. Une journée écrite "
    "est clôturée — elle ne se modifiera plus que par une nouvelle rectification."
)
st.caption(
    ":material/sell: Seule exception à la règle des formules : sur une journée "
    "**encore ouverte**, si la formule du classeur porte un tarif périmé "
    "(`=C123*72` quand le tarif est passé à 74), sa constante est remise à jour. "
    "La formule reste une formule, et jamais sur une journée clôturée."
)

en_attente = store.jours_a_exporter(conn)

if not en_attente:
    st.success("Le classeur est à jour : aucune journée en attente.",
               icon=":material/check_circle:")
else:
    st.subheader(f"{len(en_attente)} journée{'s' if len(en_attente) > 1 else ''} "
                 "en attente", anchor=False)

    apercu = pd.DataFrame([
        {
            "Date": d,
            "Patients": j.patients,
            "Chirurgie": j.actes_chirurgie,
            "Recettes": j.recettes,
            "CA déclaré": j.ca_declare,
            "Rectifiée": bool(store.rectifications_du_jour(conn, d)),
            # colonne homogène : Arrow refuse un mélange d'entiers et de texte
            "Ligne": str(j.ligne_xlsx) if j.ligne_xlsx else "à créer",
        }
        for d, j in ((d, store.lire_jour_corrige(conn, d, tarifs)) for d in en_attente)
    ])
    st.dataframe(
        apercu, hide_index=True,
        column_config={
            "Date": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Recettes": st.column_config.NumberColumn(format="%.0f TND"),
            "CA déclaré": st.column_config.NumberColumn(format="%.0f TND"),
            "Rectifiée": st.column_config.CheckboxColumn(width="small"),
        },
    )

    futures = [d for d in en_attente if d > dt.date(2027, 1, 23)]
    if futures:
        st.caption(
            ":material/add_row_below: Le classeur s'arrête au 23/01/2027 ; "
            f"les lignes manquantes jusqu'au {max(futures):%d/%m/%Y} seront créées "
            "avec les tarifs courants."
        )

    st.caption("Une copie horodatée du classeur est créée avant chaque écriture.")

    if st.button("Écrire dans le classeur", icon=":material/save:", type="primary"):
        journees = [store.lire_jour_corrige(conn, d, tarifs) for d in en_attente]
        try:
            with st.spinner("Écriture en cours…"):
                rapport = xlsx_io.exporter(conn, journees, tarifs_nouveaux=tarifs)
        except PermissionError:
            st.error(
                "Le classeur est ouvert dans Excel. Fermez-le puis relancez l'écriture.",
                icon=":material/lock:",
            )
            st.stop()
        except Exception as err:  # noqa: BLE001
            st.error(f"Écriture interrompue : {err}")
            st.stop()

        ecrites = [d for d, r, etat in rapport["lignes"] if etat == "écrite"]
        store.marquer_exporte(conn, ecrites)

        st.success(
            f"{rapport['ecrites']} journées écrites"
            + (f", {rapport['creees']} lignes créées" if rapport["creees"] else "")
            + ".",
            icon=":material/check_circle:",
        )
        st.caption(f"Sauvegarde : `{rapport['sauvegarde']}`")

        alignes = rapport.get("tarifs_alignes") or []
        if alignes:
            postes = {}
            for d, col, ancien, nouveau in alignes:
                postes.setdefault((col, ancien, nouveau), []).append(d)
            st.info(
                "Tarifs remis à jour dans les formules de journées ouvertes :\n\n"
                + "\n".join(
                    f"- colonne **{col}** : {tnd(ancien)} → **{tnd(nouveau)}** TND "
                    f"sur {len(dates)} ligne(s), du {min(dates):%d/%m/%Y} au "
                    f"{max(dates):%d/%m/%Y}"
                    for (col, ancien, nouveau), dates in sorted(postes.items())
                ),
                icon=":material/sell:",
            )

        ignorees = [(d, etat) for d, r, etat in rapport["lignes"] if etat != "écrite"]
        if ignorees:
            st.warning(
                "Journées non écrites : "
                + ", ".join(f"{d:%d/%m/%Y} ({etat})" for d, etat in ignorees),
                icon=":material/warning:",
            )
        st.rerun()

st.divider()

# --- sauvegardes -------------------------------------------------------------

st.subheader("Sauvegardes", anchor=False)
copies = sorted(BACKUP_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)

if not copies:
    st.caption("Aucune sauvegarde pour l'instant.")
else:
    st.dataframe(
        pd.DataFrame([
            {
                "Fichier": p.name,
                "Créée le": dt.datetime.fromtimestamp(p.stat().st_mtime),
                "Taille": f"{p.stat().st_size / 1_048_576:.1f} Mo",
            }
            for p in copies[:15]
        ]),
        hide_index=True,
        column_config={"Créée le": st.column_config.DatetimeColumn(
            format="DD/MM/YYYY HH:mm")},
    )
    st.caption(f"Dossier : `{BACKUP_DIR}` · {len(copies)} copies conservées.")

with st.expander("Réimporter depuis le classeur", icon=":material/warning:"):
    st.write(
        "Relit le classeur et écrase le registre réel de l'app. À n'utiliser que si "
        "le classeur a été corrigé directement dans Excel. **Les journées en attente "
        "d'écriture seront perdues.** Le journal des rectifications, lui, est "
        "conservé et continue de s'appliquer par-dessus les valeurs relues."
    )
    confirmation = st.text_input(
        "Tapez REIMPORTER pour confirmer", key="confirm_reimport",
        placeholder="REIMPORTER",
    )
    if st.button("Réimporter", icon=":material/refresh:",
                 disabled=confirmation.strip().upper() != "REIMPORTER"):
        barre = st.progress(0.0, text="Lecture du classeur…")
        rapport = xlsx_io.importer(
            conn, progress=lambda p: barre.progress(min(p, 1.0)))
        barre.empty()
        st.success(f"{rapport['lignes']} journées relues.",
                   icon=":material/check_circle:")
        st.rerun()
