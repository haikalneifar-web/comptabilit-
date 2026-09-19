"""Ressources partagées entre les pages Streamlit."""

from __future__ import annotations

import copy
import datetime as dt
import sqlite3

import pandas as pd
import streamlit as st

from compta import export, store
from compta.config import LIBELLES_CHAMPS, MOIS_FR
from compta.model import CHAMPS_SAISIE, COMPTEURS, date_longue, tnd


@st.cache_resource
def get_conn() -> sqlite3.Connection:
    conn = store.connect()
    store.init_db(conn)
    return conn


def montant(v: float, suffixe: str = " TND") -> str:
    return tnd(v) + suffixe


def valeur_champ(champ: str, v: float) -> str:
    """Une valeur de saisie, lisible selon sa nature."""
    return f"{int(round(v))}" if champ in COMPTEURS else f"{tnd(v)} TND"


def recap_journee(j, colonnes: int = 5) -> None:
    """Bandeau de totaux d'une journée, identique aux colonnes du classeur."""
    cols = st.columns(colonnes)
    cols[0].metric("Recettes", montant(j.recettes))
    cols[1].metric("CA à déclarer", montant(j.ca_declare))
    cols[2].metric("Caisse", montant(j.caisse))
    cols[3].metric("Dû CNAM", montant(j.charge_cnam))
    cols[4].metric("Patients", f"{j.patients}")


def bandeau_registre(journees: list, reference: list | None = None) -> None:
    """Totaux d'un tableau, calculés sur ce qu'il affiche.

    `reference` — l'autre registre — fait apparaître l'écart sous chaque total.
    """
    somme = lambda champ, source: sum(getattr(j, champ) for j in source)  # noqa: E731
    postes = [("Recettes", "recettes"), ("CA déclaré", "ca_declare"),
              ("Caisse", "caisse"), ("Dû CNAM", "charge_cnam")]

    cols = st.columns(len(postes))
    for col, (libelle, champ) in zip(cols, postes):
        total = somme(champ, journees)
        delta = None
        if reference is not None:
            ecart = total - somme(champ, reference)
            if abs(ecart) > 0.005:
                delta = f"{ecart:+,.0f}".replace(",", " ") + " TND"
        col.metric(libelle, montant(total), delta=delta)

    patients = somme("patients", journees)
    chirurgie = somme("actes_chirurgie", journees)
    detail = f"{patients} patients · {chirurgie} actes de chirurgie"
    if reference is not None:
        ecart_p = patients - somme("patients", reference)
        ecart_c = chirurgie - somme("actes_chirurgie", reference)
        if ecart_p or ecart_c:
            detail += f"  ·  écart : {ecart_p:+d} patient(s), {ecart_c:+d} acte(s)"
    st.caption(detail)


def bandeau_mois(journees: list, reference: list | None = None) -> None:
    """Les totaux du mois en une seule rangée de tuiles, au-dessus des tableaux.

    Ce qui se compte et ce que les formules en tirent se lisent d'un coup.
    Auparavant deux bandeaux séparés surmontaient chacun son tableau, à des
    hauteurs différentes : les deux grilles ne démarraient pas à la même ligne,
    et le haut de l'écran passait entier en totaux.

    `reference` — le registre avant la saisie en cours — fait apparaître sous
    chaque tuile ce que la modification en attente changerait.
    """
    somme = lambda champ, source: sum(getattr(j, champ) for j in source)  # noqa: E731
    postes = [
        ("Patients", "patients", False),
        ("Chirurgie", "actes_chirurgie", False),
        ("Recettes", "recettes", True),
        ("CA déclaré", "ca_declare", True),
        ("Caisse", "caisse", True),
        ("Dû CNAM", "charge_cnam", True),
    ]

    for col, (libelle, champ, argent) in zip(st.columns(len(postes)), postes):
        total = somme(champ, journees)
        delta = None
        if reference is not None:
            ecart = total - somme(champ, reference)
            if abs(ecart) > 0.005:
                delta = (f"{ecart:+,.0f}".replace(",", " ")
                         + (" TND" if argent else ""))
        col.metric(libelle, montant(total) if argent else f"{int(total)}",
                   delta=delta, border=True)

    # ce qui ne mérite pas une tuile, mais qui manquerait à l'appel
    laser = somme("laser_dec", journees) + somme("laser_nd", journees)
    divers = somme("divers", journees)
    depenses = somme("depenses", journees)
    detail = [f"{int(somme('cat_cnam_n', journees))} cataracte(s) CNAM",
              f"{int(somme('cat_pay_n', journees))} payante(s)"]
    if laser:
        detail.append(f"{montant(laser)} de laser")
    if divers:
        detail.append(f"{montant(divers)} de divers")
    if depenses:
        detail.append(f"{montant(depenses)} de dépenses")
    st.caption(" · ".join(detail))


def barre_export(df: "pd.DataFrame", nom: str, titre: str, cle: str,
                 totaux: list[tuple[str, str]] | None = None,
                 sous_titre: str = "", libelles: dict | None = None) -> None:
    """Sous un tableau : le même contenu à emporter, en PDF, Excel ou CSV.

    Les fichiers sont produits en mémoire à la demande — rien n'est écrit sur le
    disque, et le classeur du cabinet n'est pas touché.
    """
    if df is None or df.empty:
        return
    exportable = df.rename(columns=libelles) if libelles else df

    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(":material/download: Exporter ce tableau :")
        for extension, (etiquette, type_mime, fabriquer) in export.FORMATS.items():
            if extension == "csv":
                contenu = fabriquer(exportable, totaux)
            else:
                contenu = fabriquer(exportable, titre, totaux, sous_titre)
            st.download_button(
                etiquette, data=contenu,
                file_name=f"{nom}.{extension}", mime=type_mime,
                key=f"export_{cle}_{extension}", icon=":material/description:",
            )


def totaux_registre(journees: list) -> list[tuple[str, str]]:
    """Les totaux d'un tableau, sous la forme attendue par les exports."""
    somme = lambda champ: sum(getattr(j, champ) for j in journees)  # noqa: E731
    return [
        ("Recettes", montant(somme("recettes"))),
        ("CA déclaré", montant(somme("ca_declare"))),
        ("Caisse", montant(somme("caisse"))),
        ("Dû CNAM", montant(somme("charge_cnam"))),
        ("Patients", f"{somme('patients')}"),
        ("Chirurgie", f"{somme('actes_chirurgie')}"),
    ]


def badge_export(conn) -> int:
    """Nombre de journées en attente d'écriture dans le classeur."""
    return len(store.jours_a_exporter(conn))


# --- brouillons : ce qui est saisi mais pas encore enregistré ----------------
#
# Streamlit purge l'état des widgets qui ne sont pas rendus : passer d'un onglet
# à l'autre efface une saisie en cours. On en garde une copie dans une clé
# ordinaire — elle, survit à la navigation — et on la restaure au retour. Ça ne
# dure que la session : rien n'est écrit en base tant qu'on n'enregistre pas.

def memoriser(cle: str) -> bool:
    """Rend un widget persistant d'un onglet à l'autre.

    À appeler avant de créer le widget. Retourne True si un brouillon vient
    d'être restauré.

    Ne convient qu'aux widgets dont la valeur peut être posée dans l'état de
    session — `st.data_editor` l'interdit, sa saisie en attente se conserve en
    réappliquant les valeurs aux données affichées (voir la page du mois).
    """
    brouillons = st.session_state.setdefault("_brouillons", {})
    if cle in st.session_state:
        brouillons[cle] = copy.deepcopy(st.session_state[cle])
        return False
    if cle in brouillons:
        st.session_state[cle] = copy.deepcopy(brouillons[cle])
        return True
    return False


def editeur_persistant(base: "pd.DataFrame", cle: str, montants: list[str],
                       config: dict, height: int = 560) -> tuple["pd.DataFrame", list]:
    """Tableau modifiable dont la saisie en attente survit au changement d'onglet.

    `st.data_editor` refuse qu'on lui repose son état : ce ne sont donc pas les
    frappes qu'on conserve mais les valeurs, réappliquées aux données affichées.
    Les modifications en attente et le brouillon conservé sont ainsi une seule
    et même chose, recalculée à chaque passage face à `base`.

    Retourne le tableau édité et la liste des écarts
    `(position, champ, avant, après)`.
    """
    brouillon = st.session_state.setdefault("_brouillons", {}).setdefault(cle, {})

    affichee = base.copy()
    for (position, champ), valeur in brouillon.items():
        affichee.iloc[position, affichee.columns.get_loc(champ)] = valeur

    edite = st.data_editor(affichee, key=cle, num_rows="fixed",
                           column_config=config, height=height)

    brouillon.clear()
    modifs = []
    for position in range(len(base)):
        for champ in base.columns:
            avant = base[champ].iloc[position]
            apres = edite[champ].iloc[position]
            apres = 0 if pd.isna(apres) else apres
            if champ in montants:
                apres = float(apres)
                change = abs(apres - float(avant)) > 0.005
            else:
                apres = int(apres)
                change = apres != int(avant)
            if change:
                brouillon[(position, champ)] = apres
                modifs.append((position, champ, avant, apres))
    return edite, modifs


def oublier(*cles: str) -> None:
    """Efface un brouillon : la saisie a été enregistrée, ou abandonnée."""
    brouillons = st.session_state.setdefault("_brouillons", {})
    for cle in cles:
        brouillons.pop(cle, None)
        try:
            del st.session_state[cle]
        except KeyError:
            pass


# --- choix du mois de travail ------------------------------------------------

def _decaler_mois(pas: int) -> None:
    annee, mois = st.session_state.mois_travail
    annee, mois = divmod(annee * 12 + (mois - 1) + pas, 12)
    st.session_state.mois_travail = (annee, mois + 1)


def selecteur_mois(premiere: dt.date, derniere: dt.date) -> tuple[int, int]:
    """Sélecteur de mois partagé par les pages qui travaillent au mois.

    La plage d'années ne s'arrête pas à la dernière ligne du classeur : les mois
    à venir se saisissent, leurs journées se créant à l'enregistrement.

    Le mois retenu vit dans `mois_travail`, pas dans l'état des widgets : celui-ci
    est purgé au changement de page, `mois_travail` suit d'une page à l'autre.
    """
    annee_defaut, mois_defaut = st.session_state.mois_travail
    horizon = max(derniere.year, dt.date.today().year, annee_defaut) + 5
    annees = list(range(premiere.year, horizon + 1))
    annee_defaut = min(max(annee_defaut, annees[0]), annees[-1])

    with st.container(horizontal=True, vertical_alignment="bottom"):
        annee = st.selectbox("Année", annees, index=annees.index(annee_defaut),
                             width=130)
        mois = st.selectbox(
            "Mois", list(range(1, 13)), index=mois_defaut - 1, width=170,
            format_func=lambda m: MOIS_FR[m - 1].capitalize(),
        )
        st.button("Mois précédent", icon=":material/chevron_left:",
                  on_click=_decaler_mois, args=(-1,), key="mois_precedent")
        st.button("Mois suivant", icon=":material/chevron_right:",
                  on_click=_decaler_mois, args=(1,), key="mois_suivant")

    st.session_state.mois_travail = (annee, mois)
    return annee, mois


# --- rectifications ----------------------------------------------------------

def demander_rectification(date: dt.date, champ: str | None = None) -> None:
    """Callback : demande l'ouverture du formulaire de rectification."""
    st.session_state["rectif_cible"] = (date, champ)


def rectification_en_attente(conn) -> None:
    """À appeler en fin de page : ouvre le formulaire si on l'a demandé."""
    cible = st.session_state.pop("rectif_cible", None)
    if cible:
        dialogue_rectification(conn, *cible)


@st.dialog("Rectifier une journée", width="large")
def dialogue_rectification(conn, date: dt.date, champ: str | None = None) -> None:
    """Une correction motivée sur une journée clôturée.

    Rien n'est écrasé : la valeur d'origine reste au registre réel, la
    rectification s'empile par-dessus avec son motif et son horodatage.
    """
    journee = store.lire_jour_corrige(conn, date)
    st.caption(date_longue(date))

    index = CHAMPS_SAISIE.index(champ) if champ in CHAMPS_SAISIE else 0
    choix = st.selectbox(
        "Poste à rectifier", CHAMPS_SAISIE, index=index,
        format_func=lambda c: LIBELLES_CHAMPS[c],
    )
    actuelle = float(getattr(journee, choix))

    gauche, droite = st.columns(2)
    with gauche:
        st.metric("Valeur en vigueur", valeur_champ(choix, actuelle))
    with droite:
        if choix in COMPTEURS:
            nouvelle = st.number_input(
                "Valeur rectifiée", min_value=0, step=1, format="%d",
                value=int(actuelle),
            )
        else:
            nouvelle = st.number_input(
                "Valeur rectifiée (TND)", min_value=0.0, step=10.0, format="%.0f",
                value=actuelle,
            )

    motif = st.text_area(
        "Motif de la rectification",
        placeholder="Ce qui s'est réellement passé : patient compté deux fois, "
                    "tarif erroné, encaissement porté au mauvais jour…",
        height=90,
    )
    st.caption(
        "Le motif est obligatoire et reste attaché à la correction. Une "
        "rectification qui ne corrige pas une erreur constatée n'en est pas une."
    )

    passees = store.rectifications_du_jour(conn, date)
    if passees:
        with st.expander(f"{len(passees)} rectification(s) déjà sur cette journée",
                         icon=":material/history:"):
            for r in passees:
                st.markdown(
                    f"**{LIBELLES_CHAMPS.get(r['champ'], r['champ'])}** · "
                    f"{valeur_champ(r['champ'], r['ancienne'])} → "
                    f"{valeur_champ(r['champ'], r['nouvelle'])}"
                    + ("" if r["en_vigueur"] else "  ·  *remplacée depuis*")
                )
                st.caption(f"{r['motif']} — {r['created_at']}")

    with st.container(horizontal=True):
        enregistrer = st.button(
            "Enregistrer la rectification", icon=":material/edit_note:",
            type="primary", disabled=not motif.strip(),
        )
        if st.button("Annuler", type="tertiary"):
            st.rerun()

    if enregistrer:
        try:
            store.ajouter_rectification(conn, date, choix, nouvelle, motif)
        except ValueError as err:
            st.error(str(err), icon=":material/error:")
            return
        st.toast(
            f"Rectification enregistrée sur le {date:%d/%m/%Y}.",
            icon=":material/check:",
        )
        st.rerun()
