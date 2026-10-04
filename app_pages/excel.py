"""Écriture des journées saisies dans « compta jdid .xlsx »."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from app_utils import choix_classeur, get_conn, montant
from compta import store, xlsx_io
from compta.config import BACKUP_DIR
from compta.model import tnd

conn = get_conn()
tarifs = store.tarifs_courants(conn)

st.header("Classeur Excel", anchor=False)

chemin = choix_classeur(conn, "excel")
infos = xlsx_io.infos_classeur(chemin)
if not infos["existe"]:
    st.error(f"Classeur introuvable : `{chemin}`. Indiquez le bon fichier ci-dessus.")
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

# --- le classeur a-t-il bougé sans l'app ? -----------------------------------

sync = xlsx_io.etat_synchronisation(conn)

if not sync["connu"]:
    st.caption(
        ":material/help: L'app ne sait pas encore reconnaître une modification "
        "extérieure du classeur : le registre a été importé avant ce contrôle. "
        "Le prochain import — ou la prochaine écriture — le mettra en place."
    )
elif not sync["a_jour"]:
    st.error(
        "**Le classeur a changé depuis que le registre l'a lu.**\n\n"
        f"- lu par l'app le **{sync['lu_le']:%d/%m/%Y à %H:%M}**\n"
        f"- modifié depuis, le **{sync['modifie_le']:%d/%m/%Y à %H:%M}**"
        + (f" — taille {sync['taille_lue'] / 1_048_576:.1f} → "
           f"{sync['taille_actuelle'] / 1_048_576:.1f} Mo"
           if sync["taille_lue"] != sync["taille_actuelle"] else "")
        + "\n\nDes journées y ont peut-être été saisies directement dans Excel : "
          "le registre ne les connaît pas, et ce que l'app affiche est en retard "
          "sur le fichier. **Réimportez avant d'écrire** — en bas de cette page.",
        icon=":material/sync_problem:",
    )
else:
    st.success(
        f"Registre et classeur sont d'accord — dernier échange le "
        f"{sync['lu_le']:%d/%m/%Y à %H:%M}.",
        icon=":material/sync:",
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

    # écrire dans un fichier qu'on sait plus récent que le registre demande un
    # geste de plus : l'écriture ne clobbere pas les autres journées, mais elle
    # clôture les siennes sur des chiffres qui peuvent être dépassés
    desaccord = sync["connu"] and not sync["a_jour"]
    confirme = True
    if desaccord:
        confirme = st.checkbox(
            "J'ai vérifié : écrire malgré la modification extérieure du classeur",
            key="forcer_ecriture_desync",
        )

    if st.button("Écrire dans le classeur", icon=":material/save:", type="primary",
                 disabled=not confirme):
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

        posees = rapport.get("formules_posees") or []
        if posees:
            colonnes = {}
            for d, col in posees:
                colonnes.setdefault(col, []).append(d)
            st.info(
                "Formules de montant posées sur des journées ouvertes qui n'en "
                "avaient pas. Sans elles, la recette saisie n'entrait dans aucun "
                "total du classeur :\n\n"
                + "\n".join(
                    f"- colonne **{col}** sur {len(dates)} ligne(s), du "
                    f"{min(dates):%d/%m/%Y} au {max(dates):%d/%m/%Y}"
                    for col, dates in sorted(colonnes.items())
                ),
                icon=":material/function:",
            )

        absentes = rapport.get("formules_absentes") or []
        if absentes:
            st.warning(
                "**Des actes écrits sans montant en face.** Ces journées sont "
                "acquises : leur colonne de montant est vide, et l'app n'y touche "
                "pas — leur ligne porte déjà des totaux. Ces actes n'entrent donc "
                "dans aucun total du classeur.\n\n"
                + "\n".join(
                    f"- {d:%d/%m/%Y} : {n} en colonne **{compteur}**, "
                    f"montant **{montant_col}** absent"
                    for d, montant_col, compteur, n in absentes
                ),
                icon=":material/money_off:",
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
