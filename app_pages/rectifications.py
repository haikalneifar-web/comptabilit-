"""Rectifier un mois déjà enregistré, sans jamais toucher au registre réel.

À gauche ce que le registre dit vraiment, à droite ce qu'il devrait dire. On
modifie la colonne de droite, on explique pourquoi, et l'écart devient une
rectification datée. La gauche ne bouge jamais.
"""

from __future__ import annotations

import calendar
import datetime as dt

import pandas as pd
import streamlit as st

from app_utils import (bandeau_registre, barre_export, demander_rectification,
                       editeur_persistant, get_conn, memoriser, montant,
                       oublier, rectification_en_attente, selecteur_mois,
                       totaux_registre, valeur_champ)
from compta import store
from compta.config import LIBELLES_CHAMPS, MONTANTS_DIRECTS, TOUS_ACTES
from compta.model import MONTANTS, mois_long

conn = get_conn()
premiere, derniere = store.bornes(conn)

st.header("Rectifications", anchor=False)
st.caption(
    "Une journée clôturée ne se réécrit pas. Elle se corrige : la valeur "
    "d'origine reste au registre réel, la correction s'ajoute par-dessus avec "
    "son motif et sa date."
)

if premiere is None:
    st.info("Aucune journée enregistrée.", icon=":material/inbox:")
    st.stop()

annee, mois = selecteur_mois(premiere, derniere)
debut = dt.date(annee, mois, 1)
fin = dt.date(annee, mois, calendar.monthrange(annee, mois)[1])

champs = [a.cle for a in TOUS_ACTES] + [c for c, _ in MONTANTS_DIRECTS]
libelles = {a.cle: a.libelle for a in TOUS_ACTES} | dict(MONTANTS_DIRECTS)

corrige = store.journal(conn, debut, fin, corrige=True)
reel = {r["date"]: r for r in store.journal(conn, debut, fin, corrige=False)}
cloturees = [r for r in corrige if r["cloture"]]

# --- repérage : les mois qui portent des corrections -------------------------

toutes = store.liste_rectifications(conn)
par_mois: dict[str, int] = {}
for r in toutes:
    par_mois[r["date"][:7]] = par_mois.get(r["date"][:7], 0) + 1

if par_mois:
    st.caption(
        ":material/event_list: Mois avec rectifications — "
        + " · ".join(
            f"{mois_long(int(m[:4]), int(m[5:7]))} ({n})"
            for m, n in sorted(par_mois.items())
        )
    )

st.divider()

# --- le tableau de rectification --------------------------------------------

st.subheader(f"Rectifier {mois_long(annee, mois)}", anchor=False)

if not cloturees:
    st.info(
        f"Aucune journée clôturée en {mois_long(annee, mois)} : il n'y a rien à "
        "rectifier. Les journées encore ouvertes se corrigent directement dans "
        "**Mois comptable**, sans motif — une journée se clôture à l'écriture "
        "dans le classeur.",
        icon=":material/lock_open:",
    )
    rectification_en_attente(conn)
    st.stop()

dates = [dt.date.fromisoformat(r["date"]) for r in cloturees]
cle_grille = f"rectif_{annee}_{mois}"
cle_motif = f"motif_rectif_{annee}_{mois}"

base_reelle = pd.DataFrame(
    [{"Date": d, **{c: reel[d.isoformat()][c] for c in champs}} for d in dates]
).set_index("Date")
base_corrigee = pd.DataFrame(
    [{"Date": d, **{c: r[c] for c in champs}} for d, r in zip(dates, cloturees)]
).set_index("Date")

config = {
    **{c: st.column_config.NumberColumn(libelles[c], min_value=0, step=1,
                                        format="%d", width="small")
       for c in champs if c not in MONTANTS},
    **{c: st.column_config.NumberColumn(libelles[c], min_value=0.0, step=10.0,
                                        format="%.0f", width="small")
       for c in champs if c in MONTANTS},
}

journees_reelles = [store.vers_journee(reel[d.isoformat()]) for d in dates]

gauche, droite = st.columns(2, gap="medium")

periode = mois_long(annee, mois)

with gauche:
    st.caption("**Registre réel** — les valeurs saisies à l'origine, non modifiables")
    bandeau_registre(journees_reelles)
    st.dataframe(base_reelle, column_config=config, height=520)
    barre_export(
        base_reelle, f"registre_reel_{annee}-{mois:02d}",
        f"Registre réel — {periode}", cle=f"reel_{annee}_{mois}",
        libelles=libelles, totaux=totaux_registre(journees_reelles),
        sous_titre="Cabinet d'ophtalmologie · valeurs d'origine, avant toute "
                   "rectification",
    )

with droite:
    st.caption("**Registre corrigé** — modifiez ici, ligne par ligne")
    totaux_corriges = st.container()   # rempli une fois le tableau connu
    edite, ecarts = editeur_persistant(base_corrigee, cle_grille, MONTANTS,
                                       config, height=520)
    zone_export_corrige = st.container()

journees_corrigees = []
for i, ligne_jour in enumerate(cloturees):
    j = store.vers_journee(ligne_jour)
    for c in champs:
        valeur = edite[c].iloc[i]
        valeur = 0 if pd.isna(valeur) else valeur
        setattr(j, c, float(valeur) if c in MONTANTS else int(valeur))
    journees_corrigees.append(j)

with totaux_corriges:
    bandeau_registre(journees_corrigees, reference=journees_reelles)

with zone_export_corrige:
    barre_export(
        edite, f"registre_corrige_{annee}-{mois:02d}",
        f"Registre corrigé — {periode}", cle=f"corrige_{annee}_{mois}",
        libelles=libelles, totaux=totaux_registre(journees_corrigees),
        sous_titre="Cabinet d'ophtalmologie · valeurs d'origine plus les "
                   "rectifications motivées",
    )

st.caption(
    f"{len(cloturees)} journée(s) clôturée(s) ce mois-ci. Les journées encore "
    "ouvertes ne figurent pas ici : elles se saisissent dans **Mois comptable**."
)

# --- ce qui change et pourquoi ----------------------------------------------

st.divider()
st.subheader("Corrections en attente", anchor=False)

if not ecarts:
    st.caption(
        "Aucune. Modifiez une valeur dans le tableau de droite : l'écart avec le "
        "registre réel s'affiche ici, et vous pourrez l'expliquer."
    )
else:
    st.caption(
        ":material/history: Rien n'est encore enregistré. Ces corrections sont "
        "reprises de votre session : elles survivent au changement d'onglet."
    )
    st.dataframe(
        pd.DataFrame([
            {
                "Journée": dates[position],
                "Poste": libelles[champ],
                "Réel": valeur_champ(champ, base_reelle[champ].iloc[position]),
                "En vigueur": valeur_champ(champ, avant),
                "Rectifié": valeur_champ(champ, apres),
                "Écart au réel": float(apres) - float(base_reelle[champ].iloc[position]),
            }
            for position, champ, avant, apres in ecarts
        ]),
        hide_index=True,
        column_config={
            "Journée": st.column_config.DateColumn(format="DD/MM/YYYY", pinned=True),
            "Écart au réel": st.column_config.NumberColumn(format="%+.0f"),
        },
    )

    memoriser(cle_motif)
    motif = st.text_area(
        "Motif des rectifications",
        placeholder="Ce qui s'est réellement passé : patients comptés deux fois, "
                    "tarif erroné, encaissement porté au mauvais jour…",
        height=90, key=cle_motif,
    )
    st.caption(
        "Le motif est obligatoire et reste attaché à chaque correction. Une "
        "rectification qui ne corrige pas une erreur constatée n'en est pas une."
    )

    with st.container(horizontal=True, vertical_alignment="center"):
        enregistrer = st.button(
            f"Enregistrer {len(ecarts)} rectification{'s' if len(ecarts) > 1 else ''}",
            icon=":material/edit_note:", type="primary",
            disabled=not motif.strip(),
        )
        if st.button("Tout abandonner", icon=":material/undo:", type="tertiary",
                     key="abandon_rectif"):
            oublier(cle_grille, cle_motif)
            st.toast("Corrections abandonnées.", icon=":material/undo:")
            st.rerun()

    if enregistrer:
        refus = []
        for position, champ, _, apres in ecarts:
            try:
                store.ajouter_rectification(conn, dates[position], champ, apres, motif)
            except ValueError as err:
                refus.append(f"{dates[position]:%d/%m} {libelles[champ]} : {err}")
        oublier(cle_grille, cle_motif)
        if refus:
            st.warning("Non enregistré — " + " · ".join(refus),
                       icon=":material/warning:")
        st.toast(f"{len(ecarts) - len(refus)} rectification(s) enregistrée(s).",
                 icon=":material/check:")
        st.rerun()

# --- ce que les rectifications du mois ont déjà changé -----------------------

lignes = store.liste_rectifications(conn, debut, fin)

st.divider()

if not lignes:
    st.subheader("Journal des corrections", anchor=False)
    st.info(
        f"Aucune rectification en {mois_long(annee, mois)} : sur ce mois, le "
        "registre corrigé est identique au registre réel.",
        icon=":material/check_circle:",
    )
    if toutes:
        ecarts_tous = store.ecarts_rectifications(conn)
        st.caption(
            f"Sur l'ensemble du registre : {len(toutes)} rectification(s), "
            f"{len(ecarts_tous)} journée(s) touchée(s), "
            f"{montant(sum(e['recettes'] for e in ecarts_tous.values()))} d'écart "
            "sur les recettes."
        )
    rectification_en_attente(conn)
    st.stop()

ecarts_mois = {d: e for d, e in store.ecarts_rectifications(conn).items()
               if d.startswith(f"{annee:04d}-{mois:02d}")}
en_vigueur = [r for r in lignes if r["en_vigueur"]]

cols = st.columns(5)
cols[0].metric("Rectifications du mois", f"{len(lignes)}")
cols[1].metric("En vigueur", f"{len(en_vigueur)}")
cols[2].metric("Journées touchées", f"{len(ecarts_mois)}")
cols[3].metric("Écart recettes",
               montant(sum(e["recettes"] for e in ecarts_mois.values())),
               delta="réel → corrigé", delta_color="off")
cols[4].metric("Écart CA déclaré",
               montant(sum(e["ca_declare"] for e in ecarts_mois.values())),
               delta=f"{sum(e['patients'] for e in ecarts_mois.values()):+.0f} patients",
               delta_color="off")

st.subheader(f"Journal des corrections de {mois_long(annee, mois)}", anchor=False)

df = pd.DataFrame([
    {
        "Journée": dt.date.fromisoformat(r["date"]),
        "Poste": LIBELLES_CHAMPS.get(r["champ"], r["champ"]),
        "Avant": valeur_champ(r["champ"], r["ancienne"]),
        "Après": valeur_champ(r["champ"], r["nouvelle"]),
        "Motif": r["motif"],
        "Saisie le": r["created_at"],
        "En vigueur": r["en_vigueur"],
        "Revenir": ":material/undo: Revenir" if r["en_vigueur"] else None,
    }
    for r in lignes
])


def _demander_annulation() -> None:
    clic = st.session_state.get("clic_annulation")
    if clic is None:
        return
    st.session_state["annuler_id"] = lignes[clic.row]["id"]


st.dataframe(
    df, hide_index=True,
    column_config={
        "Journée": st.column_config.DateColumn(format="DD/MM/YYYY", pinned=True),
        "Motif": st.column_config.TextColumn(width="large"),
        "En vigueur": st.column_config.CheckboxColumn(width="small"),
        "Revenir": st.column_config.ButtonColumn(
            "", on_click=_demander_annulation, key="clic_annulation",
            type="tertiary", width="small",
        ),
    },
)
st.caption(
    "« En vigueur » : la dernière rectification d'un poste sur une journée. Les "
    "lignes décochées ont été remplacées depuis, elles restent au journal."
)
barre_export(
    df.drop(columns=["Revenir"]), f"journal_rectifications_{annee}-{mois:02d}",
    f"Journal des rectifications — {periode}", cle=f"journal_{annee}_{mois}",
    totaux=[("Rectifications", f"{len(lignes)}"),
            ("En vigueur", f"{len(en_vigueur)}"),
            ("Journées touchées", f"{len(ecarts_mois)}"),
            ("Écart recettes",
             montant(sum(e["recettes"] for e in ecarts_mois.values())))],
    sous_titre="Cabinet d'ophtalmologie · chaque correction avec son motif et "
               "sa date de saisie",
)


@st.dialog("Revenir sur une rectification")
def dialogue_annulation(rectif_id: int) -> None:
    r = next((x for x in lignes if x["id"] == rectif_id), None)
    if r is None:
        st.error("Rectification introuvable.")
        return
    date = dt.date.fromisoformat(r["date"])
    st.markdown(
        f"Rectification du **{date:%d/%m/%Y}** sur "
        f"**{LIBELLES_CHAMPS.get(r['champ'], r['champ'])}** : "
        f"{valeur_champ(r['champ'], r['ancienne'])} → "
        f"{valeur_champ(r['champ'], r['nouvelle'])}"
    )
    st.caption(f"Motif d'origine : {r['motif']}")
    st.info(
        "Elle ne sera pas effacée. Une nouvelle rectification ramène le poste à "
        f"{valeur_champ(r['champ'], r['ancienne'])}, et les deux restent au journal.",
        icon=":material/history:",
    )
    motif_retour = st.text_area(
        "Pourquoi revenir en arrière ?",
        placeholder="La correction précédente était elle-même une erreur parce que…",
        height=90,
    )
    if st.button("Revenir à la valeur d'avant", icon=":material/undo:",
                 type="primary", disabled=not motif_retour.strip()):
        try:
            store.annuler_rectification(conn, rectif_id, motif_retour)
        except ValueError as err:
            st.error(str(err), icon=":material/error:")
            return
        st.toast("Retour enregistré au journal.", icon=":material/check:")
        st.rerun()


# --- effet sur les totaux ----------------------------------------------------

st.subheader("Effet sur les totaux, jour par jour", anchor=False)

comparaison = pd.DataFrame([
    {
        "Journée": dt.date.fromisoformat(d),
        "Recettes réelles": reel[d]["recettes"],
        "Recettes corrigées": next(r["recettes"] for r in corrige if r["date"] == d),
        "CA déclaré réel": reel[d]["ca_declare"],
        "CA déclaré corrigé": next(r["ca_declare"] for r in corrige if r["date"] == d),
        "Patients réels": int(reel[d]["patients"]),
        "Patients corrigés": int(next(r["patients"] for r in corrige if r["date"] == d)),
    }
    for d in sorted(ecarts_mois) if d in reel
])

st.dataframe(
    comparaison, hide_index=True,
    column_config={
        "Journée": st.column_config.DateColumn(format="DD/MM/YYYY", pinned=True),
        **{c: st.column_config.NumberColumn(format="%.0f TND")
           for c in ["Recettes réelles", "Recettes corrigées",
                     "CA déclaré réel", "CA déclaré corrigé"]},
    },
)
st.caption(
    "Un registre corrigé sain reste proche du réel : il corrige des erreurs de "
    "saisie, il ne construit pas un second résultat."
)

with st.expander("Rectifier un seul poste, avec son propre motif",
                 icon=":material/edit_note:"):
    st.caption(
        "Le tableau ci-dessus applique un motif commun à toutes les corrections "
        "d'un enregistrement. Pour attacher un motif propre à une correction "
        "précise, passez par ce formulaire."
    )
    with st.container(horizontal=True, vertical_alignment="bottom"):
        cible = st.selectbox(
            "Journée", dates, format_func=lambda d: f"{d:%d/%m/%Y} · {d:%a}",
            width=240,
        )
        st.button("Ouvrir le formulaire", icon=":material/open_in_new:",
                  on_click=demander_rectification, args=(cible,))

if "annuler_id" in st.session_state:
    dialogue_annulation(st.session_state.pop("annuler_id"))
else:
    rectification_en_attente(conn)
