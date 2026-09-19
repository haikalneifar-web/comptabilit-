"""Ressources partagées entre les pages Streamlit."""

from __future__ import annotations

import calendar
import copy
import datetime as dt
import sqlite3

import pandas as pd
import streamlit as st

from compta import export, store
from compta.config import LIBELLES_CHAMPS, MOIS_FR
from compta.model import (CALCULES, CHAMPS_SAISIE, COMPTEURS, MONTANTS,
                          date_longue, tnd)


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


# Libellés courts des colonnes de saisie : le nom entier du poste ne tient pas
# dans une colonne de grille, il reste dans l'infobulle. Partagés par les deux
# grilles mensuelles — celle de la saisie et celle des rectifications — pour
# qu'elles se ressemblent.
COURTS_GRILLE = {
    "pay_n": "Payant", "remb_n": "Remb.", "apci_n": "APCI",
    "tp_n": "Tiers payant", "star_n": "Assurance", "cat_cnam_n": "Cat. CNAM",
    "cat_pay_n": "Cat. payante", "laser_dec": "Laser décl.",
    "laser_nd": "Laser n.d.", "divers": "Divers", "depenses": "Dépenses",
}


def config_grille(champs: list, libelles: dict) -> dict:
    """Les colonnes d'une grille mensuelle : largeurs en pixels, noms courts.

    Les largeurs sont posées plutôt que laissées au calcul automatique : à douze
    colonnes, celui-ci rogne les en-têtes. Un test vérifie que leur somme tient
    dans la page.
    """
    return {
        **{c: st.column_config.NumberColumn(
            COURTS_GRILLE.get(c, libelles[c]), min_value=0, step=1,
            format="%d", width=94, help=libelles[c])
           for c in champs if c not in MONTANTS},
        **{c: st.column_config.NumberColumn(
            COURTS_GRILLE.get(c, libelles[c]), min_value=0.0, step=10.0,
            format="%.0f", width=106, help=f"{libelles[c]} — en TND")
           for c in champs if c in MONTANTS},
        "Date": st.column_config.DateColumn(format="ddd DD/MM", width=100),
    }


def mois_affiche(conn, annee: int, mois: int, corrige: bool,
                 tarifs: dict) -> dict:
    """Le mois entier, du 1er au dernier jour, indexé par date.

    Le tableau se construit sur le calendrier, pas sur les lignes du registre :
    au-delà de la dernière ligne du classeur (23/01/2027) les journées se créent
    à l'enregistrement, mais le mois se travaille quand même.
    """
    debut = dt.date(annee, mois, 1)
    fin = dt.date(annee, mois, calendar.monthrange(annee, mois)[1])
    connues = {r["date"]: r for r in store.journal(conn, debut, fin,
                                                   corrige=corrige)}
    lignes = [
        connues.get(d.isoformat()) or store.ligne_vide(d, tarifs)
        for d in (debut + dt.timedelta(days=n) for n in range((fin - debut).days + 1))
    ]
    return {dt.date.fromisoformat(r["date"]): r
            for r in sorted(lignes, key=lambda x: x["date"])}


def calculs_du_mois(par_date: dict, tarifs: dict, frontiere,
                    brouillon: dict | None = None) -> tuple[list, list]:
    """Les journées du mois et leurs colonnes calculées.

    `brouillon` — `{(position, champ): valeur}`, tel que l'éditeur le conserve —
    applique la saisie **en attente**, celle qui n'est pas encore enregistrée.
    C'est ce qui permet à l'écran de saisie et à la page des totaux de dire la
    même chose : on tape sur l'un, l'autre suit, avant tout enregistrement.

    Le calcul vit ici, en un seul endroit, parce que deux copies finiraient par
    diverger — et ce sont les formules du classeur qu'elles reproduisent.
    """
    journees, calculees = [], []
    for position, date in enumerate(par_date):
        ligne = par_date[date]
        journee = store.vers_journee(ligne, tarifs, frontiere)
        for champ in CHAMPS_SAISIE:
            if brouillon and (position, champ) in brouillon:
                valeur = brouillon[(position, champ)]
                setattr(journee, champ,
                        float(valeur) if champ in MONTANTS else int(valeur))
        journees.append(journee)
        # les seize colonnes calculées du classeur, pas une sélection : la liste
        # vient de `model.CALCULES`, que le test tient à jour face au classeur
        calculees.append({
            "Date": date,
            "État": ("Rectifiée" if ligne["rectifiee"] else
                     "Clôturée" if ligne["cloture"] else "Ouverte"),
            **{libelle: getattr(journee, attribut)
               for _, libelle, attribut, _ in CALCULES},
            "Δ en attente": journee.recettes - ligne["recettes"],
        })
    return journees, calculees


def brouillon_du_mois(annee: int, mois: int) -> dict:
    """La saisie en attente sur la grille d'un mois, s'il y en a une.

    Elle vit dans l'état de session, pas en base : elle survit au changement de
    page et se perd à la fermeture de l'app.
    """
    return st.session_state.get("_brouillons", {}).get(f"grille_{annee}_{mois}", {})


# la colonne AB compte des patients, la AD porte des centimes : les autres sont
# des dinars ronds
_TUILES_ENTIERES = {"patients"}
_TUILES_CENTIMES = {"tva_deduite"}


def tuiles_calculees(colonnes: list, journees: list,
                     reference: list | None = None, par_ligne: int = 5) -> None:
    """Un total de mois par colonne calculée, en tuiles.

    `colonnes` est une tranche de `model.CALCULES` — la liste qui répond des
    seize colonnes du classeur. `reference`, le registre avant la saisie en
    attente, fait apparaître sous chaque tuile ce qu'elle changerait.
    """
    somme = lambda attribut, source: sum(getattr(j, attribut) for j in source)  # noqa: E731

    for depart in range(0, len(colonnes), par_ligne):
        tranche = colonnes[depart:depart + par_ligne]
        for col, (lettre, libelle, attribut, _) in zip(st.columns(par_ligne),
                                                       tranche):
            total = somme(attribut, journees)
            if attribut in _TUILES_ENTIERES:
                valeur = f"{int(total)}"
            elif attribut in _TUILES_CENTIMES:
                valeur = f"{tnd(total, 2)} TND"
            else:
                valeur = montant(total)

            delta = None
            if reference is not None:
                ecart = total - somme(attribut, reference)
                if abs(ecart) > 0.005:
                    delta = (f"{ecart:+,.0f}".replace(",", " ")
                             + ("" if attribut in _TUILES_ENTIERES else " TND"))

            col.metric(libelle, valeur, delta=delta, border=True,
                       help=f"Colonne {lettre} du classeur")


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
