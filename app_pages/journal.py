"""Le mois comptable : son tableau, ses colonnes calculées, ses corrections.

C'est l'écran de travail principal, la saisie se faisant en fin de mois. Le
tableau reprend la feuille mensuelle du classeur : à gauche ce qui se saisit, à
droite ce que les formules en tirent. On y travaille sur le registre corrigé ;
le registre réel, lui, ne s'édite pas.
"""

from __future__ import annotations

import calendar
import datetime as dt

import pandas as pd
import streamlit as st

from app_utils import (bandeau_mois, barre_export, editeur_persistant,
                       get_conn, memoriser, oublier, selecteur_mois,
                       totaux_registre)
from compta import store, xlsx_io
from compta.config import MONTANTS_DIRECTS, TOUS_ACTES
from compta.model import MONTANTS, mois_long

conn = get_conn()
tarifs = store.tarifs_courants(conn)
# un changement de tarif ne vaut que pour la suite : calculé une fois pour tout
# le mois affiché, pas à chaque ligne
frontiere = store.frontiere_tarifs(conn)
premiere, derniere = store.bornes(conn)

st.header("Mois comptable", anchor=False)

# Le classeur s'ouvre aussi dans Excel : si des journées y ont été saisies
# directement, ce tableau est en retard sur le fichier et rien ne le dirait.
sync = xlsx_io.etat_synchronisation(conn)
if sync["connu"] and not sync["a_jour"]:
    st.warning(
        f"Le classeur a été modifié le **{sync['modifie_le']:%d/%m/%Y à %H:%M}**, "
        f"après sa dernière lecture par l'app le "
        f"{sync['lu_le']:%d/%m/%Y à %H:%M}. Ce que vous voyez ici peut être en "
        "retard sur le fichier — réimportez depuis **Classeur Excel**.",
        icon=":material/sync_problem:",
    )

if premiere is None:
    st.info("Aucune journée enregistrée.", icon=":material/inbox:")
    st.stop()

# --- choix du mois et du registre --------------------------------------------

# La saisie se fait en fin de mois comptable : on ouvre sur le mois qui reste à
# reprendre, pas sur la date du jour.
if st.session_state.mois_travail is None:
    st.session_state.mois_travail = store.mois_a_saisir(conn)

# le mois et le registre sur une seule ligne : c'est la barre de réglage de
# l'écran, elle n'a pas à occuper deux rangées
choix_mois, choix_registre = st.columns([3, 1], vertical_alignment="bottom")
with choix_mois:
    annee, mois = selecteur_mois(premiere, derniere)
with choix_registre:
    vue = st.segmented_control(
        "Registre", ["Corrigé", "Réel"], default=st.session_state.registre,
        key="registre_journal",
    )
if vue:
    st.session_state.registre = vue
corrige = st.session_state.registre == "Corrigé"

debut = dt.date(annee, mois, 1)
fin = dt.date(annee, mois, calendar.monthrange(annee, mois)[1])

# Le mois se travaille en entier, y compris au-delà de la dernière ligne du
# classeur : les journées absentes du registre se créent à l'enregistrement.
connues = {r["date"]: r for r in store.journal(conn, debut, fin, corrige=corrige)}
lignes = [
    connues.get(d.isoformat()) or store.ligne_vide(d, tarifs)
    for d in (debut + dt.timedelta(days=n) for n in range((fin - debut).days + 1))
]

# --- totaux du mois ----------------------------------------------------------

actifs = sum(1 for r in lignes if r["recettes"] > 0)
rectifiees = [r for r in lignes if r["rectifiee"]]
absentes = [r for r in lignes if r.get("absente")]

# une seule ligne d'état plutôt que quatre légendes empilées : chacune disait
# une chose vraie, mais ensemble elles repoussaient les tableaux vers le bas
etat = [f"**{actifs} jour(s) renseigné(s)** sur les {len(lignes)} du mois"]
if rectifiees:
    etat.append(
        f"{len(rectifiees)} journée(s) rectifiée(s) — valeurs "
        + ("du registre corrigé" if corrige else "d'origine, avant rectification")
    )
if absentes:
    etat.append(f"{len(absentes)} journée(s) encore absente(s) du registre, "
                "créée(s) à l'enregistrement")
if actifs and len(lignes) - actifs > 8:
    etat.append(f"{len(lignes) - actifs} journées à zéro")
st.caption(" · ".join(etat))

dernier_rempli = store.dernier_jour_rempli(conn)
if actifs == 0 and dernier_rempli and fin > dernier_rempli:
    st.warning(
        f"{mois_long(annee, mois).capitalize()} n'est pas encore saisi. "
        f"Dernière journée renseignée : {dernier_rempli:%d/%m/%Y}.",
        icon=":material/edit_calendar:",
    )

# --- tableau du mois ---------------------------------------------------------

champs = [a.cle for a in TOUS_ACTES] + [c for c, _ in MONTANTS_DIRECTS]
libelles = {a.cle: a.libelle for a in TOUS_ACTES} | dict(MONTANTS_DIRECTS)

triees = sorted(lignes, key=lambda x: x["date"])
par_date = {dt.date.fromisoformat(r["date"]): r for r in triees}
dates = list(par_date)

st.subheader(f"Tableau de {mois_long(annee, mois)}", anchor=False)

cle_grille = f"grille_{annee}_{mois}"
cle_motif = f"motif_{annee}_{mois}"

base = pd.DataFrame(
    [{"Date": d, **{c: par_date[d][c] for c in champs}} for d in dates]
).set_index("Date")

# Largeurs en pixels plutôt que « small » : avec onze colonnes dans la grille
# de gauche, la largeur automatique rognait les en-têtes — « Rembo », « Catarac »,
# « Laser d ». Les libellés sont raccourcis pour la grille, le nom entier reste
# dans l'infobulle.
COURTS = {
    "pay_n": "Payant", "remb_n": "Remb.", "apci_n": "APCI", "tp_n": "Tiers p.",
    "star_n": "Assur.", "cat_cnam_n": "Cat. CNAM", "cat_pay_n": "Cat. pay.",
    "laser_dec": "Laser décl.", "laser_nd": "Laser n.d.", "divers": "Divers",
    "depenses": "Dépenses",
}

config_saisie = {
    **{c: st.column_config.NumberColumn(COURTS.get(c, libelles[c]), min_value=0,
                                        step=1, format="%d", width=64,
                                        help=libelles[c])
       for c in champs if c not in MONTANTS},
    **{c: st.column_config.NumberColumn(COURTS.get(c, libelles[c]), min_value=0.0,
                                        step=10.0, format="%.0f", width=74,
                                        help=f"{libelles[c]} — en TND")
       for c in champs if c in MONTANTS},
    "Date": st.column_config.DateColumn(format="ddd DD/MM", width=86),
}

HAUTEUR = 620      # de quoi montrer un mois entier sans faire défiler

# 1,85 contre 1 : la grille de saisie demande 836 px pour ses douze colonnes,
# le tableau calculé 454 pour ses six. Le partage est calculé sur ces largeurs,
# pas choisi à vue — c'est ce qui évite les en-têtes rognés.
bandeau = st.container()          # les totaux, une fois la saisie connue
gauche, droite = st.columns([1.85, 1], gap="medium")

with gauche:
    st.caption("**Ce qui se saisit** — colonnes C, E, H, J, L, N, P, R, S, T, V")
    if corrige:
        edite, ecarts = editeur_persistant(base, cle_grille, MONTANTS,
                                           config_saisie, height=HAUTEUR)
    else:
        st.dataframe(base, column_config=config_saisie, height=HAUTEUR)
        edite, ecarts = base, []
    zone_export_saisie = st.container()

# --- colonnes calculées, à partir de ce qui est affiché à gauche -------------

# accès par position : l'index du tableau peut être converti par pandas, l'ordre
# des lignes, lui, est celui de `dates`
journees, calculees = [], []
for i, d in enumerate(dates):
    j = store.vers_journee(par_date[d], tarifs, frontiere)
    for c in champs:
        valeur = edite[c].iloc[i]
        valeur = 0 if pd.isna(valeur) else valeur
        setattr(j, c, float(valeur) if c in MONTANTS else int(valeur))
    journees.append(j)
    calculees.append({
        "Date": d,
        "État": ("Rectifiée" if par_date[d]["rectifiee"] else
                 "Clôturée" if par_date[d]["cloture"] else "Ouverte"),
        "Patients": j.patients,
        "Recettes": j.recettes,
        "CA déclaré": j.ca_declare,
        "Caisse": j.caisse,
        "Dû CNAM": j.charge_cnam,
        "Δ en attente": j.recettes - par_date[d]["recettes"],
    })

periode = mois_long(annee, mois)
registre_dit = "registre corrigé" if corrige else "registre réel"

with bandeau:
    bandeau_mois(
        journees,
        reference=[store.vers_journee(par_date[d], tarifs, frontiere)
                   for d in dates] if ecarts else None,
    )

with zone_export_saisie:
    barre_export(
        edite, f"saisie_{annee}-{mois:02d}", f"Saisie de {periode}",
        cle=f"saisie_{annee}_{mois}", libelles=libelles,
        totaux=totaux_registre(journees),
        sous_titre=f"Cabinet d'ophtalmologie · {registre_dit} · "
                   "colonnes de saisie du classeur",
    )

with droite:
    st.caption("**Ce que les formules en tirent** — colonnes U, AB, AC")
    # Caisse et Dû CNAM ont quitté ce tableau : ils sont au bandeau du haut, et
    # leur place ici obligeait six colonnes à se partager la moitié de l'espace
    # de gauche. Les noms de colonnes ne bougent pas — seuls leurs libellés se
    # raccourcissent.
    st.dataframe(
        pd.DataFrame(calculees).set_index("Date"),
        height=HAUTEUR,
        column_order=["État", "Patients", "Recettes", "CA déclaré",
                      "Δ en attente"],
        column_config={
            "Date": st.column_config.DateColumn(format="ddd DD/MM", width=86),
            "État": st.column_config.TextColumn(width=78),
            "Patients": st.column_config.NumberColumn("Patients", format="%d",
                                                      width=66),
            "Recettes": st.column_config.NumberColumn("Recettes", format="%.0f",
                                                      width=86),
            "CA déclaré": st.column_config.NumberColumn("CA décl.", format="%.0f",
                                                        width=82,
                                                        help="CA à déclarer — "
                                                             "colonne AC"),
            "Δ en attente": st.column_config.NumberColumn(
                "Δ", format="%+.0f", width=56,
                help="Ce que la modification en cours changerait aux recettes "
                     "de la journée, avant enregistrement."),
        },
    )
    barre_export(
        pd.DataFrame(calculees).set_index("Date").drop(columns=["Δ en attente"]),
        f"totaux_{annee}-{mois:02d}", f"Totaux de {periode}",
        cle=f"calcul_{annee}_{mois}", totaux=totaux_registre(journees),
        sous_titre=f"Cabinet d'ophtalmologie · {registre_dit} · "
                   "colonnes calculées du classeur",
    )


def lien_classeur() -> None:
    """Fin du mois comptable : renvoyer vers l'écriture dans le classeur."""
    en_attente = [d for d in store.jours_a_exporter(conn) if debut <= d <= fin]
    if not en_attente:
        return
    st.divider()
    with st.container(horizontal=True, vertical_alignment="center"):
        st.page_link(
            "app_pages/excel.py",
            label=f"Écrire les {len(en_attente)} journées du mois dans le classeur",
            icon=":material/table_view:",
        )
        st.caption("L'écriture clôture les journées : sauvegarde du classeur avant, "
                   "rectification motivée après.")


if not corrige:
    st.info(
        "Vue du registre réel : les valeurs d'origine ne s'éditent pas. Passez "
        "sur « Corrigé » pour saisir ou rectifier.",
        icon=":material/lock:",
    )
    lien_classeur()
    st.stop()

# --- ce qui a changé ---------------------------------------------------------

modifs = [
    {"date": dates[position], "champ": champ, "avant": avant, "apres": apres,
     "cloture": bool(par_date[dates[position]]["cloture"])}
    for position, champ, avant, apres in ecarts
]

a_rectifier = [m for m in modifs if m["cloture"]]
a_ecrire = [m for m in modifs if not m["cloture"]]

st.divider()
st.subheader("Modifications en attente", anchor=False)

if modifs:
    st.caption(
        ":material/history: Rien n'est encore enregistré. Ces modifications sont "
        "reprises de votre session : elles survivent au changement d'onglet, et "
        "se perdent à la fermeture de l'app."
    )

if not modifs:
    st.caption(
        "Aucune. Modifiez une cellule du tableau : les colonnes calculées "
        "suivent, et le détail de ce qui change s'affiche ici."
    )
    lien_classeur()
    st.stop()

st.dataframe(
    pd.DataFrame([
        {
            "Journée": m["date"],
            "Poste": libelles[m["champ"]],
            "Avant": m["avant"],
            "Après": m["apres"],
            "Écart": float(m["apres"]) - float(m["avant"]),
            "Traitement": "Rectification motivée" if m["cloture"] else "Saisie directe",
        }
        for m in modifs
    ]),
    hide_index=True,
    column_config={
        "Journée": st.column_config.DateColumn(format="DD/MM/YYYY"),
        "Écart": st.column_config.NumberColumn(format="%+.0f"),
    },
)

if a_ecrire and not a_rectifier:
    st.caption(
        f"{len(a_ecrire)} modification(s) sur des journées encore ouvertes : "
        "elles s'enregistrent directement, sans rectification."
    )

motif = ""
if a_rectifier:
    jours_touches = sorted({m["date"] for m in a_rectifier})
    st.caption(
        f"{len(a_rectifier)} modification(s) portent sur "
        f"{len(jours_touches)} journée(s) clôturée(s) : chacune devient une "
        "rectification distincte au journal, avec ce motif."
    )
    memoriser(cle_motif)  # le motif en cours de frappe survit au changement d'onglet
    motif = st.text_area(
        "Motif des rectifications",
        placeholder="Ce qui s'est réellement passé : patients comptés deux fois, "
                    "tarif erroné, encaissement porté au mauvais jour…",
        height=90, key=cle_motif,
    )

with st.container(horizontal=True, vertical_alignment="center"):
    enregistrer = st.button(
        f"Enregistrer {len(modifs)} modification{'s' if len(modifs) > 1 else ''}",
        icon=":material/save:", type="primary",
        disabled=bool(a_rectifier) and not motif.strip(),
    )
    abandonner = st.button("Tout abandonner", icon=":material/undo:",
                           type="tertiary", key="abandon_mois")
    if a_rectifier and not motif.strip():
        st.caption(":material/edit_note: Le motif est obligatoire pour rectifier "
                   "une journée clôturée.")

if abandonner:
    oublier(cle_grille, cle_motif)
    st.toast("Modifications abandonnées.", icon=":material/undo:")
    st.rerun()

if enregistrer:
    # journées ouvertes : écriture directe, poste par poste regroupé par jour
    for d in sorted({m["date"] for m in a_ecrire}):
        j = store.lire_jour(conn, d, tarifs)
        for m in (x for x in a_ecrire if x["date"] == d):
            setattr(j, m["champ"],
                    float(m["apres"]) if m["champ"] in MONTANTS else int(m["apres"]))
        store.ecrire_jour(conn, j, commit=False)
    conn.commit()

    # journées clôturées : une rectification motivée par poste modifié
    refus = []
    for m in a_rectifier:
        try:
            store.ajouter_rectification(conn, m["date"], m["champ"], m["apres"], motif)
        except ValueError as err:
            refus.append(f"{m['date']:%d/%m} {libelles[m['champ']]} : {err}")

    oublier(cle_grille, cle_motif)
    if refus:
        st.warning("Non enregistré — " + " · ".join(refus), icon=":material/warning:")
    st.toast(
        f"{len(modifs) - len(refus)} modification(s) enregistrée(s)"
        + (f", dont {len(a_rectifier) - len(refus)} rectification(s)"
           if a_rectifier else "") + ".",
        icon=":material/check:",
    )
    st.rerun()

lien_classeur()
