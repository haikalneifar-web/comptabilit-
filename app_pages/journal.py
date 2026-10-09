"""Le mois comptable : la grille de saisie, et rien d'autre.

C'est l'écran de travail principal, la saisie se faisant en fin de mois. Il ne
porte **que les colonnes de saisie du classeur** — c'est la secrétaire qui le
remplit, et elle n'a pas à lire ce que les formules en tirent : les totaux du
mois sont en tuiles sous le tableau, le détail journée par journée est sur la
page « Totaux du mois ». On y travaille sur le registre corrigé ; le registre
réel, lui, ne s'édite pas.
"""

from __future__ import annotations

import calendar
import datetime as dt

import pandas as pd
import streamlit as st

from app_utils import (COURTS_TARIFS, bandeau_mois, barre_export,
                       brouillon_du_mois, calculs_du_mois, config_grille, editeur_persistant,
                       get_conn, memoriser, mois_affiche, oublier,
                       selecteur_mois, totaux_registre)
from compta import bordereau, store, xlsx_io
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
par_date = mois_affiche(conn, annee, mois, corrige, tarifs)
dates = list(par_date)
lignes = list(par_date.values())

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

# --- tarifs du mois ----------------------------------------------------------

# La règle est de régler le tarif avant de saisir : une journée enregistrée fige
# celui qu'elle porte. L'écran de saisie doit donc le montrer, au-dessus de la
# grille, tel que chaque journée le prendra — pas le tarif courant en général.
appliques = [store.vers_journee(par_date[d], tarifs, frontiere) for d in dates]
releve = bordereau.tarifs_du_mois(appliques)
# ce que la formule du classeur porte encore, quand l'app va la réaligner
realignes = {
    cle: sorted({float(par_date[d][cle]) for d, j in zip(dates, appliques)
                 if abs(float(par_date[d][cle]) - j.tarifs[cle]) > 0.005})
    for cle in releve
}
realignes = {cle: anciens for cle, anciens in realignes.items() if anciens}
modifiable = fin >= frontiere


def prix(cle: str) -> str:
    valeurs = "/".join(f"{v:g}" for v in releve[cle])
    if cle in realignes:
        anciens = "/".join(f"{v:g}" for v in realignes[cle])
        return f"{COURTS_TARIFS.get(cle, cle)} ~~{anciens}~~ **{valeurs}**"
    return f"{COURTS_TARIFS.get(cle, cle)} **{valeurs}**"


with st.container(horizontal=True, vertical_alignment="center", key="tarifs_mois"):
    st.caption(
        ":material/sell: Tarifs de ce mois — "
        + " · ".join(prix(cle) for cle in releve)
        + (" — barré : le prix encore inscrit dans la formule du classeur, "
           "remis à jour à l'écriture" if realignes else "")
        + (" — un poste porte deux prix dans le mois"
           if any(len(v) > 1 for v in releve.values()) else "")
        + ("" if modifiable else
           " — mois déjà travaillé : ses journées gardent leur tarif")
    )
    if modifiable:
        st.page_link("app_pages/tarifs.py", label="Régler les tarifs",
                     icon=":material/tune:")

# --- tableau du mois ---------------------------------------------------------

champs = [a.cle for a in TOUS_ACTES] + [c for c, _ in MONTANTS_DIRECTS]
libelles = {a.cle: a.libelle for a in TOUS_ACTES} | dict(MONTANTS_DIRECTS)

st.subheader(f"Tableau de {mois_long(annee, mois)}", anchor=False)

cle_grille = f"grille_{annee}_{mois}"
cle_motif = f"motif_{annee}_{mois}"

base = pd.DataFrame(
    [{"Date": d, **{c: par_date[d][c] for c in champs}} for d in dates]
).set_index("Date")

config_saisie = config_grille(champs, libelles)

HAUTEUR = 560      # les tuiles de totaux restent visibles sous la grille

# La page de saisie ne porte qu'une chose : la grille du mois, en pleine
# largeur. Les colonnes calculées n'y sont plus à côté — c'est la secrétaire qui
# remplit cet écran, et elle n'a pas à lire ce que les formules en tirent. Les
# totaux du mois se lisent sous le tableau, et le détail par journée reste à un
# clic, replié.
st.caption("**Ce qui se saisit** — colonnes C, E, H, J, L, N, P, R, S, T, V")
# Le tableau prend la hauteur de la fenêtre : la molette fait défiler les dates
# dans le tableau, dont la ligne de titres reste fixe, et non la page entière.
st.markdown(
    "<style>.st-key-zone_grille [data-testid=\"stDataFrame\"] "
    "{ height: calc(100vh - 8rem) !important; min-height: 420px; }</style>",
    unsafe_allow_html=True,
)
# Les deux gestes de fin de saisie, à portée de main au-dessus du tableau ; la
# barre se remplit plus bas, une fois les modifications connues.
barre_actions = st.container(horizontal=True, vertical_alignment="center",
                             key="barre_actions")
with st.container(key="zone_grille"):
    if corrige:
        edite, ecarts = editeur_persistant(base, cle_grille, MONTANTS,
                                           config_saisie, height=HAUTEUR)
    else:
        st.dataframe(base, column_config=config_saisie, height=HAUTEUR)
        edite, ecarts = base, []
zone_export_saisie = st.container()

# --- ce que la saisie donne, pour les tuiles ---------------------------------

# Le calcul est celui de la page « Totaux du mois » — un seul code pour les
# deux écrans, sinon ils finiraient par ne plus dire la même chose. Il relit la
# saisie en attente là où l'éditeur la conserve.
journees, _ = calculs_du_mois(par_date, tarifs, frontiere,
                              brouillon_du_mois(annee, mois) if corrige else {})

periode = mois_long(annee, mois)
registre_dit = "registre corrigé" if corrige else "registre réel"

with zone_export_saisie:
    barre_export(
        edite, f"saisie_{annee}-{mois:02d}", f"Saisie de {periode}",
        cle=f"saisie_{annee}_{mois}", libelles=libelles,
        totaux=totaux_registre(journees),
        sous_titre=f"Cabinet d'ophtalmologie · {registre_dit} · "
                   "colonnes de saisie du classeur",
    )

# --- les totaux du mois, sous le tableau -------------------------------------

bandeau_mois(
    journees,
    reference=appliques if ecarts else None,
)

# Le détail par journée est sur la page d'à côté : cet écran-ci ne sert qu'à
# saisir.
with st.container(horizontal=True, vertical_alignment="center"):
    st.page_link("app_pages/totaux.py",
                 label="Voir ce que les formules en tirent, jour par jour",
                 icon=":material/functions:")
    st.caption("Les seize colonnes calculées du classeur — la saisie en "
               "attente y est comprise.")


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

# journées du mois que le registre a enregistrées mais que le classeur n'a pas
# encore reçues
pour_classeur = [d for d in store.jours_a_exporter(conn) if debut <= d <= fin]
motif_saisi = st.session_state.get(cle_motif, "")
desaccord = sync["connu"] and not sync["a_jour"]

with barre_actions:
    enregistrer = st.button(
        "Enregistrer les modifications" + (f" ({len(modifs)})" if modifs else ""),
        icon=":material/save:", type="primary", key="enregistrer_mois",
        disabled=not modifs or (bool(a_rectifier) and not motif_saisi.strip()),
        help=("Motif obligatoire pour rectifier une journée clôturée "
              "(en bas de page)." if a_rectifier and not motif_saisi.strip()
              else "Garde la saisie dans le registre de l'app."),
    )
    ecrire_classeur = st.button(
        "Enregistrer dans le classeur"
        + (f" ({len(pour_classeur)})" if pour_classeur else ""),
        icon=":material/table_view:", key="classeur_mois",
        disabled=bool(modifs) or not pour_classeur or desaccord,
        help=("Enregistrez d'abord les modifications en attente." if modifs
              else "Le classeur a été modifié hors de l'app : passez par la "
                   "page Classeur Excel." if desaccord
              else "Rien à écrire : le classeur est à jour." if not pour_classeur
              else "Écrit les journées du mois dans le classeur Excel (copie de "
                   "sauvegarde avant) et les clôture."),
    )
    abandonner = st.button("Tout abandonner", icon=":material/undo:",
                           type="tertiary", key="abandon_mois",
                           disabled=not modifs)

if ecrire_classeur:
    journees_a_ecrire = [store.lire_jour_corrige(conn, d, tarifs)
                         for d in pour_classeur]
    try:
        with st.spinner("Écriture dans le classeur…"):
            rapport = xlsx_io.exporter(conn, journees_a_ecrire,
                                       tarifs_nouveaux=tarifs)
    except PermissionError:
        st.error("Le classeur est ouvert dans Excel. Fermez-le puis réessayez.",
                 icon=":material/lock:")
    except Exception as err:  # noqa: BLE001
        st.error(f"Écriture interrompue : {err}")
    else:
        store.marquer_exporte(
            conn, [d for d, _, etat in rapport["lignes"] if etat == "écrite"])
        st.toast(f"{rapport['ecrites']} journée(s) écrite(s) dans le classeur.",
                 icon=":material/check:")
        st.rerun()

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
        "Aucune. Modifiez une cellule du tableau : les totaux sous la grille "
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
