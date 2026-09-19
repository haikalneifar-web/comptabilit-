"""Bordereaux mensuels : générer le mois, en garder la trace, suivre l'évolution.

Un bordereau est le mois du registre extrait dans un classeur autonome, montants
en formules vivantes — voir `compta/bordereau.py`. Cette page le fabrique, le
range, et consigne chaque édition : rééditer un mois après une rectification
n'efface pas l'édition précédente, il s'ajoute une ligne à l'historique et
l'écart entre les deux se lit.
"""

from __future__ import annotations

import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

from app_utils import get_conn, montant, selecteur_mois
from compta import bordereau, dossier_comptable, store, xlsx_io
from compta.config import ARCHIVES_DIR
from compta.model import mois_long

conn = get_conn()
tarifs = store.tarifs_courants(conn)
premiere, derniere = store.bornes(conn)

st.header("Bordereaux mensuels", anchor=False)

if premiere is None:
    st.info("Aucune journée enregistrée.", icon=":material/inbox:")
    st.stop()

# Un bordereau édité sur un registre en retard sur le classeur serait faux sans
# que rien ne le dise.
sync = xlsx_io.etat_synchronisation(conn)
if sync["connu"] and not sync["a_jour"]:
    st.warning(
        f"Le classeur a été modifié le **{sync['modifie_le']:%d/%m/%Y à %H:%M}**, "
        f"après sa dernière lecture par l'app le "
        f"{sync['lu_le']:%d/%m/%Y à %H:%M}. Un bordereau édité maintenant "
        "porterait les chiffres que l'app connaît, pas ceux du fichier — "
        "réimportez depuis **Classeur Excel**.",
        icon=":material/sync_problem:",
    )

# --- choix du mois et du registre --------------------------------------------

# On édite le bordereau d'un mois **terminé**, pas de celui qu'on s'apprête à
# saisir : arriver ici sur un mois vide n'offrirait qu'un bouton grisé. D'où un
# défaut différent de celui de la saisie — le mois de la dernière journée
# renseignée. Le choix fait ailleurs, lui, est respecté : `mois_travail` suit
# d'une page à l'autre, on ne le repositionne que s'il n'a jamais été résolu.
if st.session_state.mois_travail is None:
    dernier_rempli = store.dernier_jour_rempli(conn)
    st.session_state.mois_travail = (
        (dernier_rempli.year, dernier_rempli.month) if dernier_rempli
        else store.mois_a_saisir(conn)
    )

annee, mois = selecteur_mois(premiere, derniere)

vue = st.segmented_control(
    "Registre", ["Corrigé", "Réel"], default=st.session_state.registre,
    key="registre_bordereau", label_visibility="collapsed",
)
if vue:
    st.session_state.registre = vue
corrige = st.session_state.registre == "Corrigé"
nom_registre = "corrigé" if corrige else "réel"

cle_mois = f"{annee}-{mois:02d}"
journees = store.mois_en_journees(conn, annee, mois, corrige=corrige, tarifs=tarifs)
totaux = bordereau.totaux(journees)

# --- le mois, et son évolution -----------------------------------------------

agregats = {r["mois"]: r for r in store.agregat_mensuel(conn, corrige=corrige)}


def _precedent(pas_mois: int) -> dict | None:
    """Le mois situé `pas_mois` en arrière, s'il est au registre."""
    a, m = divmod(annee * 12 + (mois - 1) - pas_mois, 12)
    return agregats.get(f"{a}-{m + 1:02d}")


mois_avant, an_avant = _precedent(1), _precedent(12)


def _delta(champ: str, reference: dict | None) -> str | None:
    if not reference or not reference.get(champ):
        return None
    ecart = totaux[champ] - float(reference[champ])
    return f"{ecart:+,.0f}".replace(",", " ") + " TND"


# les six totaux que le classeur tire du mois, dans l'ordre de ses colonnes
cols = st.columns(6)
cols[0].metric("Recettes", montant(totaux["recettes"]),
               delta=_delta("recettes", mois_avant),
               help="Colonne U du classeur.")
cols[1].metric("CA à déclarer", montant(totaux["ca_declare"]),
               delta=_delta("ca_declare", mois_avant),
               help="Colonne AC.")
cols[2].metric("Caisse", montant(totaux["caisse"]),
               delta=_delta("caisse", mois_avant),
               help="Colonne X : ce qui reste en caisse, dépenses déduites.")
cols[3].metric("À la charge CNAM", montant(totaux["charge_cnam"]),
               delta=_delta("charge_cnam", mois_avant),
               help="Colonne Z : APCI, part CNAM du tiers payant, cataracte CNAM.")
cols[4].metric("À verser à la banque", montant(totaux["banque"]),
               delta=_delta("banque", mois_avant),
               help="Colonne AA : =SUM(F;I;K;M;O/2).")
cols[5].metric("Patients", f"{int(totaux['patients'])}",
               delta=(f"{int(totaux['patients']) - int(mois_avant['patients']):+d}"
                      if mois_avant and mois_avant.get("patients") else None),
               help="Colonne AB.")

st.caption(
    f"{int(totaux['jours_actifs'])} jour(s) renseigné(s) sur "
    f"{int(totaux['jours'])} · {int(totaux['actes_chirurgie'])} acte(s) de "
    "chirurgie · écarts calculés sur le mois précédent"
    + (f" · même mois l'an dernier : {montant(float(an_avant['recettes'] or 0))} "
       "de recettes" if an_avant else "")
)

# le reste de ce que le bordereau totalise : tout y passe, rien ne reste hors
# de vue sous prétexte que le bandeau ne tient que six chiffres
st.caption(
    "TVA déduite **" + montant(totaux["tva_deduite"]) + "** (AD) · "
    "non déclaré **" + montant(totaux["non_declare"]) + "** (U − AC) · "
    "laser **" + montant(totaux["laser_dec"] + totaux["laser_nd"]) + "** (R+S) · "
    "divers **" + montant(totaux["divers"]) + "** (T) · "
    "dépenses **" + montant(totaux["depenses"]) + "** (V) · "
    f"cataractes **{int(totaux['cat_cnam_n'])} CNAM / "
    f"{int(totaux['cat_pay_n'])} payantes** (N, P)"
)

if totaux["jours_actifs"] == 0:
    st.warning(
        f"{mois_long(annee, mois).capitalize()} ne porte aucun chiffre. Un "
        "bordereau de ce mois serait une feuille à zéro — saisissez le mois "
        "depuis **Mois comptable** avant de l'éditer.",
        icon=":material/edit_calendar:",
    )
    # Le mois de travail suit d'une page à l'autre, et l'accueil l'ouvre sur le
    # mois **à saisir** — vide par définition. Arriver ici par là ne doit pas
    # être un cul-de-sac : le dernier mois renseigné est à un clic.
    dernier_rempli = store.dernier_jour_rempli(conn)
    if dernier_rempli and (dernier_rempli.year, dernier_rempli.month) != (annee, mois):
        st.button(
            f"Aller à {mois_long(dernier_rempli.year, dernier_rempli.month)}, "
            "le dernier mois renseigné",
            icon=":material/history:",
            on_click=lambda: st.session_state.update(
                mois_travail=(dernier_rempli.year, dernier_rempli.month)),
            key="aller_dernier_mois",
        )

st.divider()

# --- générer ------------------------------------------------------------------

st.subheader(f"Bordereau de {mois_long(annee, mois)}", anchor=False)

st.caption(
    ":material/function: Le fichier reprend la feuille du classeur — colonnes "
    "A→AD, en-tête sur trois lignes, journées à partir de la ligne 4. **Seuls "
    "les compteurs et les montants saisis sont des valeurs** ; D, F, G, I, K, M, "
    "O, Q, U, W, X, Y, Z, AA, AB, AC et AD restent les formules du classeur, et "
    "la dernière ligne les additionne. Une seconde feuille récapitule la "
    "provenance, les totaux et les tarifs appliqués."
)
COURTS = {
    "t_apci": "APCI", "t_tp_recu": "TP reçu", "t_tp_reste": "TP reste",
    "t_remb": "remb", "t_star": "assurance", "t_pay": "payant",
    "t_cat_cnam": "cataracte CNAM", "t_cat_pay": "cataracte payante",
    "t_tva_tp": "TVA TP",
}
releve = bordereau.tarifs_du_mois(journees)
st.caption(
    ":material/sell: Chaque journée garde **son** tarif : une journée de 2019 "
    "s'écrit au prix de 2019. Tarifs de ce mois — "
    + " · ".join(
        f"{COURTS.get(cle, cle)} **{'/'.join(f'{v:.0f}' for v in valeurs)}**"
        for cle, valeurs in releve.items()
    )
    + (" — un poste porte deux prix dans le mois, le récapitulatif le signale."
       if any(len(v) > 1 for v in releve.values()) else "")
)

editions = store.bordereaux_du_mois(conn, annee, mois)
if editions:
    derniere_edition = editions[0]
    edite_le = dt.datetime.fromisoformat(derniere_edition["edite_le"])
    ecart = totaux["recettes"] - float(derniere_edition["totaux"].get("recettes", 0))
    if abs(ecart) > 0.005:
        depuis = (" — le registre dit aujourd'hui **"
                  + f"{ecart:+,.0f}".replace(",", " ")
                  + " TND** de recettes de plus")
    else:
        depuis = " — les chiffres n'ont pas bougé depuis"
    st.info(
        f"Ce mois a déjà été édité **{len(editions)} fois**, la dernière le "
        f"{edite_le:%d/%m/%Y à %H:%M} sur le registre "
        f"{derniere_edition['registre']}{depuis}.",
        icon=":material/history:",
    )

cle_produit = f"bordereau_produit_{cle_mois}"

cible = bordereau.destination(annee, mois)
dossier_existe = cible.is_dir()

with st.container(horizontal=True, vertical_alignment="center"):
    generer = st.button(
        "Générer le bordereau", icon=":material/description:", type="primary",
        disabled=totaux["jours_actifs"] == 0,
    )
    st.caption(
        f"Il rejoindra le dossier du mois : `{cible}`"
        + ("" if dossier_existe else " — **à créer**")
        + f". Son nom, `{bordereau.nom_fichier(annee, mois)}`, ne recouvre "
        "aucun fichier existant ; une édition précédente part dans "
        f"`{ARCHIVES_DIR}`."
    )

if dossier_existe:
    voisins = sorted(p.name for p in cible.glob("*.xlsx")
                     if p.name != bordereau.nom_fichier(annee, mois))
    if voisins:
        st.caption(
            f":material/folder: Déjà dans ce dossier : "
            + " · ".join(f"`{n}`" for n in voisins[:6])
            + (f" et {len(voisins) - 6} autre(s)" if len(voisins) > 6 else "")
        )

if generer:
    contenu = bordereau.construire(journees, annee, mois, registre=nom_registre)
    chemin, archive = bordereau.enregistrer(contenu, annee, mois)
    store.enregistrer_bordereau(
        conn, annee, mois, nom_registre, bordereau.empreinte(contenu), totaux,
        fichier=str(chemin),
    )
    st.session_state[cle_produit] = {
        "contenu": contenu, "chemin": str(chemin),
        "archive": str(archive) if archive else None,
    }
    st.rerun()

produit = st.session_state.get(cle_produit)
if produit:
    st.success(f"Bordereau enregistré : `{produit['chemin']}`",
               icon=":material/check_circle:")
    if produit["archive"]:
        st.caption(f":material/inventory_2: Édition précédente conservée : "
                   f"`{produit['archive']}`")
    st.download_button(
        "Télécharger le bordereau", data=produit["contenu"],
        file_name=bordereau.nom_fichier(annee, mois),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:", key=f"dl_{cle_mois}",
    )

# --- le détail du mois --------------------------------------------------------

with st.expander(f"Les {len(journees)} journées telles qu'elles partiront",
                 icon=":material/table_rows:"):
    st.caption(
        "**Les 28 colonnes chiffrées du bordereau**, dans l'ordre du classeur — "
        "rien de moins que ce que le fichier emporte. Le nom de chaque colonne "
        "rappelle sa lettre."
    )
    st.dataframe(
        pd.DataFrame([
            {"Date": j.date, "Jour": j.nom_jour.capitalize()}
            | {libelle: getattr(j, champ)
               for _, libelle, champ in bordereau.APERCU}
            for j in journees
        ]),
        hide_index=True,
        column_config={
            "Date": st.column_config.DateColumn(format="DD/MM/YYYY"),
            **{
                libelle: st.column_config.NumberColumn(
                    format="%d" if libelle in bordereau.APERCU_COMPTEURS
                    else "%.0f",
                    help=f"Colonne {lettre} du classeur.",
                )
                for lettre, libelle, _ in bordereau.APERCU
            },
        },
        height=420,
    )

st.divider()

# --- historique des éditions --------------------------------------------------

st.subheader("Historique", anchor=False)

if editions:
    st.caption(
        f"**Éditions de {mois_long(annee, mois)}** — de la plus récente à la "
        "plus ancienne. L'écart est calculé sur l'édition qui précède."
    )
    lignes = []
    for i, e in enumerate(editions):
        avant = editions[i + 1]["totaux"] if i + 1 < len(editions) else None
        lignes.append({
            "Édité le": dt.datetime.fromisoformat(e["edite_le"]),
            "Registre": e["registre"],
            "Recettes": e["totaux"].get("recettes", 0.0),
            "CA à déclarer": e["totaux"].get("ca_declare", 0.0),
            "Patients": int(e["totaux"].get("patients", 0)),
            "Δ recettes": (e["totaux"].get("recettes", 0.0)
                           - avant.get("recettes", 0.0)) if avant else None,
            "Empreinte": e["empreinte"],
        })
    st.dataframe(
        pd.DataFrame(lignes), hide_index=True,
        column_config={
            "Édité le": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
            "Recettes": st.column_config.NumberColumn(format="%.0f TND"),
            "CA à déclarer": st.column_config.NumberColumn(format="%.0f TND"),
            "Δ recettes": st.column_config.NumberColumn(
                format="%+.0f",
                help="Écart de recettes avec l'édition précédente du même mois."),
        },
    )
else:
    st.caption(f"{mois_long(annee, mois).capitalize()} n'a pas encore été édité.")

# --- ce qui a été transmis au comptable ---------------------------------------

st.divider()
st.subheader("Ce qui a été transmis", anchor=False)
st.caption(
    f"Les classeurs mensuels rangés dans `{dossier_comptable.RACINE}`, lus tels qu'ils "
    "sont. **Ce ne sont pas le registre** : ce sont les chiffres qui sont partis "
    "chez le comptable. L'app les lit, ne les modifie pas, et ne s'en sert "
    "jamais comme source — le bordereau, lui, vient du registre."
)

transmis = store.transmis_par_mois(conn)
lu_le = store.meta_get(conn, "transmis_lu_le")

with st.container(horizontal=True, vertical_alignment="center"):
    relire = st.button(
        "Lire le dossier du comptable" if not lu_le else "Relire le dossier",
        icon=":material/folder_open:",
        type="primary" if not lu_le else "secondary",
        key="relire_transmis",
    )
    if lu_le:
        st.caption(
            f"{len(transmis)} mois lus · dernier passage le "
            f"{dt.datetime.fromisoformat(lu_le):%d/%m/%Y à %H:%M}. Seuls les "
            "fichiers qui ont bougé sont rouverts."
        )
    else:
        st.caption("Une centaine de classeurs à ouvrir : comptez une dizaine "
                   "de secondes. Ensuite, seuls les fichiers modifiés sont relus.")

# Le compte rendu est posé de côté avant le rechargement : affiché juste après
# la lecture, `st.rerun()` l'effacerait sans qu'on ait eu le temps de le lire.
rapport = st.session_state.pop("rapport_transmis", None)
if rapport:
    st.success(
        f"{rapport['vus']} classeurs vus — {rapport['nouveaux']} nouveaux, "
        f"{rapport['relus']} relus, {rapport['inchanges']} inchangés, "
        f"{rapport['ignores']} sans feuille mensuelle"
        + (f", {rapport['disparus']} disparus" if rapport["disparus"] else "")
        + ".",
        icon=":material/check_circle:",
    )

if relire:
    barre = st.progress(0.0, text="Lecture du dossier…")
    st.session_state["rapport_transmis"] = store.rafraichir_transmis(
        conn, progress=lambda p, nom: barre.progress(min(p, 1.0), text=nom))
    barre.empty()
    st.rerun()

fiches = store.transmis_du_mois(conn, annee, mois)
if fiches:
    fiche = fiches[0]
    envoye = fiche["totaux"]
    st.caption(
        f"**{mois_long(annee, mois).capitalize()}** — `{fiche['chemin']}`, "
        f"feuille « {fiche['feuille']} », {fiche['jours']} journées, modifié le "
        f"{dt.datetime.fromisoformat(fiche['modifie_le']):%d/%m/%Y}."
        + (f" ({len(fiches) - 1} autre(s) classeur(s) pour ce mois dans le "
           "dossier ; c'est le plus récent qui est retenu.)"
           if len(fiches) > 1 else "")
    )

    comparaison = [
        ("CA à déclarer", "ca_declare", totaux["ca_declare"]),
        ("TVA déduite", "tva_deduite", totaux["tva_deduite"]),
        ("Patients", "patients", totaux["patients"]),
    ]
    colonnes = st.columns(len(comparaison))
    for col, (libelle, cle, au_registre) in zip(colonnes, comparaison):
        if cle not in envoye:
            col.metric(f"{libelle} transmis", "non lu",
                       help="Ce fichier ne porte pas cette colonne.")
            continue
        ecart = float(envoye[cle]) - au_registre
        col.metric(
            f"{libelle} transmis",
            f"{int(envoye[cle])}" if cle == "patients"
            else montant(float(envoye[cle])),
            delta=(f"{ecart:+.0f}".replace(",", " ")
                   if abs(ecart) > 0.5 else "identique au registre"),
            delta_color="normal" if abs(ecart) > 0.5 else "off",
            help=f"Écart avec le registre {nom_registre}, qui dit "
                 + (f"{int(au_registre)}" if cle == "patients"
                    else montant(au_registre)) + ".",
        )
else:
    st.caption(
        f"Aucun classeur mensuel trouvé pour {mois_long(annee, mois)}"
        + (" — le dossier n'a pas encore été lu." if not lu_le else ".")
    )

# --- évolution ----------------------------------------------------------------

edites = store.derniers_bordereaux_par_mois(conn)

periodes = {"24 derniers mois": 24, "5 dernières années": 60, "Tout l'historique": None}
choix = st.segmented_control("Période", list(periodes), default="24 derniers mois",
                             key="periode_bordereaux", label_visibility="collapsed")
serie = list(agregats.values())
limite = periodes.get(choix)
if limite:
    serie = serie[-limite:]

df = pd.DataFrame([
    {
        "Mois": pd.Period(r["mois"], freq="M").to_timestamp(),
        "Recettes": r["recettes"] or 0.0,
        "CA à déclarer": r["ca_declare"] or 0.0,
        "CA transmis": transmis.get(r["mois"], {}).get("totaux", {})
                               .get("ca_declare"),
        "Édité": r["mois"] in edites,
    }
    for r in serie
])

if df.empty:
    st.stop()

series = ["Recettes", "CA à déclarer"]
if df["CA transmis"].notna().any():
    series.append("CA transmis")
long = df.melt(id_vars=["Mois", "Édité"], value_vars=series,
               var_name="Série", value_name="Montant").dropna(subset=["Montant"])
couleurs = alt.Scale(domain=["Recettes", "CA à déclarer", "CA transmis"],
                     range=["#2a78d6", "#eb6834", "#1baf7a"])
base_graphe = alt.Chart(long).encode(
    x=alt.X("Mois:T", title=None),
    y=alt.Y("Montant:Q", title="TND"),
    color=alt.Color("Série:N", title=None, scale=couleurs),
    tooltip=[alt.Tooltip("Mois:T", format="%m/%Y"), "Série:N",
             alt.Tooltip("Montant:Q", format=",.0f"), "Édité:N"],
)
st.altair_chart(
    (base_graphe.mark_line(strokeWidth=2)
     + base_graphe.transform_filter(alt.datum["Édité"]).mark_point(
         size=70, filled=True, opacity=1))
    .properties(height=320)
)
st.caption(
    ":material/circle: Les points marquent les mois dont un bordereau a été "
    f"édité — {len(edites)} mois à ce jour. Les deux premières courbes viennent "
    f"du registre {nom_registre}"
    + (f" ; « CA transmis » vient des classeurs du comptable, {len(transmis)} "
       "mois lus." if "CA transmis" in series else
       " ; lisez le dossier du comptable ci-dessus pour y ajouter ce qui a été "
       "transmis.")
)

if edites:
    st.caption("**Tous les mois édités**, dernière édition de chacun.")
    st.dataframe(
        pd.DataFrame([
            {
                "Mois": pd.Period(m, freq="M").to_timestamp(),
                "Éditions": len(store.bordereaux_du_mois(conn, *map(int, m.split("-")))),
                "Dernière édition": dt.datetime.fromisoformat(e["edite_le"]),
                "Registre": e["registre"],
                "Recettes": e["totaux"].get("recettes", 0.0),
                "CA à déclarer": e["totaux"].get("ca_declare", 0.0),
                "Patients": int(e["totaux"].get("patients", 0)),
                "Fichier": e["fichier"] or "",
            }
            for m, e in sorted(edites.items(), reverse=True)
        ]),
        hide_index=True,
        column_config={
            "Mois": st.column_config.DateColumn(format="MM/YYYY"),
            "Dernière édition": st.column_config.DatetimeColumn(
                format="DD/MM/YYYY HH:mm"),
            "Recettes": st.column_config.NumberColumn(format="%.0f TND"),
            "CA à déclarer": st.column_config.NumberColumn(format="%.0f TND"),
        },
    )
