"""Rendu des pages de l'app, sur une COPIE de la base (AppTest, sans navigateur)."""

import calendar
import datetime as dt
import shutil
import sys
import tempfile
from pathlib import Path

PROJET = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJET))

from compta import store  # noqa: E402

tmp = Path(tempfile.mkdtemp()) / "test.db"
shutil.copy2(PROJET / "data" / "compta.db", tmp)
store.DB_PATH = tmp

# une journée rectifiée, pour que les pages aient de la matière à afficher
conn = store.connect()
store.init_db(conn)
D = dt.date(2026, 7, 15)
store.ajouter_rectification(conn, D, "pay_n", store.lire_jour(conn, D).pay_n - 2,
                            "2 patients comptés deux fois (test)")
store.ajouter_rectification(conn, D, "divers", 120.0, "recette divers oubliée (test)")
conn.close()

from streamlit.testing.v1 import AppTest  # noqa: E402

ok, ko = 0, 0


def verifier(nom, condition, detail=""):
    global ok, ko
    if condition:
        ok += 1
        print(f"  OK   {nom}")
    else:
        ko += 1
        print(f"  ECHEC {nom} {detail}")


def table(at, *colonnes):
    """Le premier tableau qui porte ces colonnes — plus robuste qu'un index."""
    for d in at.dataframe:
        if all(c in d.value.columns for c in colonnes):
            return d.value
    return None


def metrique(at, libelle):
    """Une métrique retrouvée par son libellé, pas par sa position."""
    for m in at.metric:
        if m.label == libelle:
            return m
    return None


def lancer(page=None, etat=None):
    at = AppTest.from_file(str(PROJET / "streamlit_app.py"), default_timeout=30)
    for k, v in (etat or {}).items():
        at.session_state[k] = v
    at.run()
    if page:
        at.switch_page(page).run()
    return at


print("\n0. La page d'accueil est le mois comptable, ouvert sur le mois à saisir")
at = lancer()
verifier("aucune exception", not at.exception, str(at.exception))
verifier("le mois comptable est la page par défaut",
         any("Mois comptable" in h.value for h in at.header))
conn = store.connect()
attendu_mois = store.mois_a_saisir(conn)
dernier = store.dernier_jour_rempli(conn)
actifs_mois = conn.execute(
    "SELECT COUNT(*) n FROM jours WHERE substr(date,1,7)=? AND recettes>0",
    (f"{attendu_mois[0]:04d}-{attendu_mois[1]:02d}",),
).fetchone()["n"]
conn.close()

# Le mois proposé dépend de l'avancement de la saisie : on vérifie ses bornes,
# pas sa valeur, qui change à chaque mois repris.
aujourdhui = dt.date.today()
verifier("le mois proposé part de la dernière journée renseignée, sans dépasser "
         "le mois courant",
         (dernier.year, dernier.month) <= attendu_mois
         <= (aujourdhui.year, aujourdhui.month),
         f"({attendu_mois}, dernier={dernier})")
verifier("c'est bien lui qui est retenu à l'affichage",
         at.session_state["mois_travail"] == attendu_mois,
         f"({at.session_state['mois_travail']} au lieu de {attendu_mois})")
if actifs_mois:
    print(f"       (le mois proposé porte déjà {actifs_mois} journée(s) : "
          "pas d'avertissement attendu)")
else:
    verifier("le mois non saisi est signalé",
             any("n'est pas encore saisi" in w.value for w in at.warning))
verifier("toutes les journées du mois sont affichées",
         len(at.dataframe[1].value) == calendar.monthrange(*attendu_mois)[1],
         f"({len(at.dataframe[1].value)} pour {attendu_mois})")

print("\n0 bis. Un mois au-delà de la dernière ligne du classeur")
at = lancer(etat={"mois_travail": (2027, 3)})
verifier("aucune exception", not at.exception, str(at.exception))
verifier("mars 2027 s'affiche entièrement", len(at.dataframe[1].value) == 31,
         f"({len(at.dataframe[1].value)})")
verifier("les journées absentes du registre sont signalées",
         any("n'existent pas encore au registre" in c.value for c in at.caption))

print("\n0 quater. Un outil d'export sous chaque tableau")
at = lancer(etat={"mois_travail": (2026, 7)})
boutons = at.get("download_button")
verifier("trois formats sous chacun des deux tableaux",
         [b.label for b in boutons] == ["PDF", "Excel", "CSV"] * 2,
         f"({[b.label for b in boutons]})")
verifier("chaque bouton est rattaché au mois affiché",
         all("2026_7" in b.key for b in boutons), f"({[b.key for b in boutons]})")
verifier("les deux tableaux exportent séparément",
         {b.key.split("_")[1] for b in boutons} == {"saisie", "calcul"},
         f"({[b.key for b in boutons]})")

at = lancer("app_pages/rectifications.py", {"mois_travail": (2026, 7)})
boutons = at.get("download_button")
verifier("trois tableaux exportables sur la page des rectifications",
         len(boutons) == 9, f"({len(boutons)})")
verifier("réel, corrigé et journal sont proposés",
         {b.key.split("_")[1] for b in boutons} == {"reel", "corrige", "journal"},
         f"({[b.key for b in boutons]})")
verifier("chacun dans les trois formats",
         sorted(b.label for b in boutons) == sorted(["PDF", "Excel", "CSV"] * 3))

print("\n0 ter. Horizon des années et navigation de mois en mois")
at = lancer(etat={"mois_travail": (2026, 12)})
annees = [s for s in at.selectbox if s.label == "Année"][0].options
verifier("le choix des années remonte au début du registre", "2015" in annees)
verifier("il ne s'arrête pas à la dernière ligne du classeur",
         "2028" in annees and "2031" in annees, f"(jusqu'à {annees[-1]})")
verifier("aucune année manquante",
         len(annees) == int(annees[-1]) - int(annees[0]) + 1)

at.button(key="mois_suivant").click().run()
verifier("le mois suivant franchit l'année",
         at.session_state["mois_travail"] == (2027, 1),
         f"({at.session_state['mois_travail']})")
at.button(key="mois_suivant").click().run()
at.button(key="mois_precedent").click().run()
at.button(key="mois_precedent").click().run()
verifier("le mois précédent revient au même point",
         at.session_state["mois_travail"] == (2026, 12),
         f"({at.session_state['mois_travail']})")
verifier("aucune exception en naviguant", not at.exception, str(at.exception))

at.switch_page("app_pages/rectifications.py").run()
verifier("le mois suit d'une page à l'autre",
         at.session_state["mois_travail"] == (2026, 12),
         f"({at.session_state['mois_travail']})")
verifier("la page des rectifications affiche le même mois",
         [s for s in at.selectbox if s.label == "Mois"][0].value in (12, "Décembre"),
         f"({[s for s in at.selectbox if s.label == 'Mois'][0].value})")

print("\n1. Saisie du jour — journée ouverte")
at = lancer("app_pages/saisie.py", {"date_saisie": dt.date(2027, 6, 1)})
verifier("aucune exception", not at.exception, str(at.exception))
verifier("mode de saisie proposé", len(at.segmented_control) >= 1)
verifier("bouton de clôture présent",
         any("Clôturer" in b.label for b in at.button))

print("\n2. Saisie — journée clôturée et rectifiée")
at = lancer("app_pages/saisie.py", {"date_saisie": D})
verifier("aucune exception", not at.exception, str(at.exception))
verifier("bandeau de clôture", any("clôturée" in i.value for i in at.info))
verifier("bouton de rectification",
         any("Rectifier" in b.label for b in at.button))
textes = [m.value for m in at.markdown] + [c.value for c in at.caption]
verifier("les rectifications sont listées",
         any("comptés deux fois" in t for t in textes))

print("\n3. Saisie — la rectification est bien celle affichée")
at = lancer("app_pages/saisie.py", {"date_saisie": D})
conn = store.connect()
corrige = store.lire_jour_corrige(conn, D)
conn.close()
verifier("recettes du bandeau = registre corrigé",
         at.metric[0].value == f"{corrige.recettes:,.0f}".replace(",", " ") + " TND",
         f"({at.metric[0].value})")

print("\n4. Mois comptable — tableau du mois et colonnes calculées")
at = lancer("app_pages/journal.py", {"mois_travail": (2026, 7)})
verifier("aucune exception", not at.exception, str(at.exception))
verifier("mention des journées rectifiées",
         any("rectifiée" in c.value for c in at.caption))
verifier("tableau des colonnes calculées affiché", len(at.dataframe) >= 1)
verifier("aucune modification en attente au chargement",
         any("Aucune." in c.value for c in at.caption))

verifier("deux tableaux côte à côte : saisie et calculé", len(at.dataframe) == 2,
         f"({len(at.dataframe)})")
saisie_df, calcul = at.dataframe[0].value, at.dataframe[1].value
verifier("le tableau de gauche porte les colonnes de saisie",
         "pay_n" in saisie_df.columns and "divers" in saisie_df.columns)
conn = store.connect()
attendu = {d: store.lire_jour_corrige(conn, d)
           for d in store.jours_ouverts(conn, dt.date(2026, 7, 1), dt.date(2026, 7, 31))}
jour_corrige = store.lire_jour_corrige(conn, D)
ouvertes = list(attendu)
conn.close()

verifier("une ligne par journée du mois", len(calcul) == 31, f"({len(calcul)})")
verifier("recettes calculées = registre corrigé",
         abs(float(calcul.loc[D, "Recettes"]) - jour_corrige.recettes) < 0.01,
         f"({calcul.loc[D, 'Recettes']} vs {jour_corrige.recettes})")
verifier("patients calculés = registre corrigé",
         int(calcul.loc[D, "Patients"]) == jour_corrige.patients)
verifier("aucun écart en attente au chargement",
         all(abs(float(v)) < 0.01 for v in calcul["Δ en attente"]))
verifier("la journée rectifiée est signalée comme telle",
         calcul.loc[D, "État"] == "Rectifiée", f"({calcul.loc[D, 'État']})")
verifier("les emplacements vides sont ouverts",
         all(calcul.loc[d, "État"] == "Ouverte" for d in ouvertes))
verifier("la journée rectifiée n'est pas un emplacement ouvert", D not in ouvertes)

at.segmented_control(key="registre_journal").select("Réel").run()
verifier("bascule vers le réel sans exception", not at.exception, str(at.exception))
verifier("valeurs d'origine annoncées",
         any("avant rectification" in c.value for c in at.caption))
verifier("registre réel non éditable",
         any("ne s'éditent pas" in i.value for i in at.info))
calcul_reel = at.dataframe[1].value
verifier("le réel diffère du corrigé sur la journée rectifiée",
         abs(float(calcul_reel.loc[D, "Recettes"])
             - float(calcul.loc[D, "Recettes"])) > 0.01)
verifier("les autres journées sont identiques dans les deux registres",
         all(abs(float(calcul_reel.loc[d, "Recettes"])
                 - float(calcul.loc[d, "Recettes"])) < 0.01
             for d in calcul.index if d != D))

print("\n5. Mois comptable — un mois hors du classeur, entièrement ouvert")
conn = store.connect()
from compta.model import Journee  # noqa: E402
j = Journee(date=dt.date(2027, 6, 3), pay_n=5, source="app")
j.tarifs = store.tarifs_courants(conn)
store.ecrire_jour(conn, j)
attendu_juin = store.lire_jour(conn, dt.date(2027, 6, 3))
conn.close()
at = lancer("app_pages/journal.py", {"mois_travail": (2027, 6)})
verifier("aucune exception", not at.exception, str(at.exception))
calcul = at.dataframe[1].value
verifier("la journée saisie est ouverte",
         calcul.loc[dt.date(2027, 6, 3), "État"] == "Ouverte")
verifier("ses recettes sont calculées",
         abs(float(calcul.loc[dt.date(2027, 6, 3), "Recettes"])
             - attendu_juin.recettes) < 0.01)
verifier("aucun motif demandé sans modification",
         not any("Motif des rectifications" in t.label for t in at.text_area))

print("\n5 bis. Mois comptable — modifier une cellule, puis enregistrer")
# AppTest ne clique pas dans une grille : on injecte l'état du widget, ce que
# `st.data_editor` relit comme des modifications en attente.
GRILLE = "grille_2026_7"
POS_15 = 14  # 15 juillet, 15e ligne du mois
conn = store.connect()
avant = store.lire_jour_corrige(conn, D)
reel_avant = store.lire_jour(conn, D)
nb_rectifs_avant = store.nb_rectifications(conn)
conn.close()

at = lancer("app_pages/journal.py", {
    "mois_travail": (2026, 7),
    GRILLE: {"edited_rows": {POS_15: {"pay_n": avant.pay_n + 5}},
             "added_rows": [], "deleted_rows": []},
})
verifier("aucune exception", not at.exception, str(at.exception))
calcul = at.dataframe[1].value
verifier("la colonne calculée suit la modification",
         abs(float(calcul.loc[D, "Δ en attente"]) - 5 * avant.tarifs["t_pay"]) < 0.01,
         f"({calcul.loc[D, 'Δ en attente']})")
verifier("les recettes affichées intègrent la modification",
         abs(float(calcul.loc[D, "Recettes"])
             - (avant.recettes + 5 * avant.tarifs["t_pay"])) < 0.01)
verifier("les autres journées ne bougent pas",
         all(abs(float(calcul.loc[d, "Δ en attente"])) < 0.01
             for d in calcul.index if d != D))
verifier("la modification est listée",
         any("Modifications en attente" in s.value for s in at.subheader))
verifier("un motif est exigé",
         any("Motif des rectifications" in t.label for t in at.text_area))
bouton = [b for b in at.button if "Enregistrer" in b.label][0]
verifier("enregistrement bloqué sans motif", bouton.disabled)

at.text_area(key="motif_2026_7").set_value("5 patients oubliés au report (test)").run()
bouton = [b for b in at.button if "Enregistrer" in b.label][0]
verifier("enregistrement débloqué avec motif", not bouton.disabled)
bouton.click().run()
verifier("aucune exception à l'enregistrement", not at.exception, str(at.exception))

conn = store.connect()
verifier("une rectification de plus au journal",
         store.nb_rectifications(conn) == nb_rectifs_avant + 1,
         f"({store.nb_rectifications(conn)})")
apres = store.lire_jour_corrige(conn, D)
verifier("registre corrigé à jour", apres.pay_n == avant.pay_n + 5)
verifier("registre réel intact", store.lire_jour(conn, D).pay_n == reel_avant.pay_n)
derniere_rectif = store.rectifications_du_jour(conn, D)[0]
verifier("le motif saisi est bien attaché",
         derniere_rectif["motif"] == "5 patients oubliés au report (test)")
verifier("l'ancienne valeur est celle d'avant",
         derniere_rectif["ancienne"] == avant.pay_n)
conn.close()

print("\n5 ter. Mois comptable — une journée ouverte s'enregistre sans motif")
conn = store.connect()
nb_rectifs_avant = store.nb_rectifications(conn)
ouverte = store.jours_ouverts(conn, dt.date(2026, 7, 1), dt.date(2026, 7, 31))[0]
conn.close()
at = lancer("app_pages/journal.py", {
    "mois_travail": (2026, 7),
    GRILLE: {"edited_rows": {ouverte.day - 1: {"pay_n": 3}},
             "added_rows": [], "deleted_rows": []},
})
verifier("aucune exception", not at.exception, str(at.exception))
verifier("aucun motif demandé pour une journée ouverte",
         not any("Motif des rectifications" in t.label for t in at.text_area))
bouton = [b for b in at.button if "Enregistrer" in b.label][0]
verifier("enregistrement possible d'emblée", not bouton.disabled)
bouton.click().run()
verifier("aucune exception à l'enregistrement", not at.exception, str(at.exception))
conn = store.connect()
verifier("écriture directe, sans rectification",
         store.nb_rectifications(conn) == nb_rectifs_avant)
verifier("la journée ouverte porte la nouvelle valeur",
         store.lire_jour(conn, ouverte).pay_n == 3)
conn.close()

print("\n5 quater. Une saisie non enregistrée survit au changement d'onglet")
conn = store.connect()
avant_q = store.lire_jour_corrige(conn, D)
nb_rectifs_avant = store.nb_rectifications(conn)
conn.close()

at = lancer("app_pages/journal.py", {
    "mois_travail": (2026, 7),
    GRILLE: {"edited_rows": {POS_15: {"pay_n": avant_q.pay_n + 7}},
             "added_rows": [], "deleted_rows": []},
})
verifier("modification visible avant de changer d'onglet",
         any("Modifications en attente" in s.value for s in at.subheader)
         and abs(float(at.dataframe[1].value.loc[D, "Δ en attente"])) > 0.01)
verifier("le brouillon est mémorisé hors de l'état des widgets",
         at.session_state["_brouillons"][GRILLE].get((POS_15, "pay_n"))
         == avant_q.pay_n + 7,
         f"({at.session_state['_brouillons'].get(GRILLE)})")

# Aller-retour, en reproduisant ce que fait Streamlit dans le navigateur :
# l'état du widget est purgé quand la page n'est plus affichée. Seul le
# brouillon, clé ordinaire, doit permettre de retrouver la saisie.
at.switch_page("app_pages/tableau_bord.py").run()
verifier("passage sur un autre onglet sans exception", not at.exception,
         str(at.exception))
del at.session_state[GRILLE]
verifier("état du widget bien purgé", GRILLE not in at.session_state.filtered_state)
verifier("le brouillon a survécu à la purge",
         GRILLE in at.session_state["_brouillons"])

at.switch_page("app_pages/journal.py").run()
verifier("retour sans exception", not at.exception, str(at.exception))
verifier("la modification est restaurée depuis le brouillon",
         abs(float(at.dataframe[1].value.loc[D, "Δ en attente"])
             - 7 * avant_q.tarifs["t_pay"]) < 0.01,
         f"({at.dataframe[1].value.loc[D, 'Δ en attente']})")
verifier("elle est signalée comme non enregistrée",
         any("Rien n'est encore enregistré" in c.value for c in at.caption))
verifier("rien n'a été enregistré entre-temps",
         store.lire_jour_corrige(store.connect(), D).pay_n == avant_q.pay_n)

# le motif aussi
at.text_area(key="motif_2026_7").set_value("motif en cours de frappe (test)").run()
at.switch_page("app_pages/rectifications.py").run()
at.switch_page("app_pages/journal.py").run()
verifier("le motif a survécu au détour",
         at.text_area(key="motif_2026_7").value == "motif en cours de frappe (test)",
         f"({at.text_area(key='motif_2026_7').value!r})")

# abandon explicite
at.button(key="abandon_mois").click().run()
verifier("après abandon, plus aucune modification",
         any("Aucune." in c.value for c in at.caption))
verifier("les colonnes calculées sont revenues au registre",
         all(abs(float(v)) < 0.01 for v in at.dataframe[1].value["Δ en attente"]))
at.switch_page("app_pages/tableau_bord.py").run()
at.switch_page("app_pages/journal.py").run()
verifier("l'abandon tient après un changement d'onglet",
         all(abs(float(v)) < 0.01 for v in at.dataframe[1].value["Δ en attente"]))
verifier("toujours rien en base",
         store.nb_rectifications(store.connect()) == nb_rectifs_avant)

print("\n6. Rectifications — le mois de juillet 2026")
conn = store.connect()
du_mois = store.liste_rectifications(conn, dt.date(2026, 7, 1), dt.date(2026, 7, 31))
attendu_total = len(du_mois)
attendu_vigueur = sum(1 for r in du_mois if r["en_vigueur"])
conn.close()

at = lancer("app_pages/rectifications.py", {"mois_travail": (2026, 7)})
verifier("aucune exception", not at.exception, str(at.exception))
verifier("compteur de rectifications du mois",
         metrique(at, "Rectifications du mois").value == str(attendu_total),
         f"({metrique(at, 'Rectifications du mois')} vs {attendu_total})")
verifier("compteur des rectifications en vigueur",
         metrique(at, "En vigueur").value == str(attendu_vigueur),
         f"({metrique(at, 'En vigueur')} vs {attendu_vigueur})")
journal_df = table(at, "Motif", "En vigueur")
verifier("journal affiché", journal_df is not None)
verifier("les corrections du mois sont au journal",
         len(journal_df) == attendu_total, f"({len(journal_df)})")
verifier("toutes portent sur juillet 2026",
         all(d.month == 7 and d.year == 2026 for d in journal_df["Journée"]))
verifier("chaque motif de test est présent",
         all("test" in str(m) for m in journal_df["Motif"]))
verifier("une rectification remplacée n'est plus en vigueur",
         int(journal_df["En vigueur"].sum()) == attendu_vigueur)
comparaison = table(at, "Recettes réelles", "Recettes corrigées")
verifier("comparaison jour par jour", comparaison is not None)
verifier("la comparaison ne porte que sur les journées rectifiées",
         len(comparaison) == 1 and comparaison["Journée"].iloc[0] == D,
         f"({len(comparaison)} lignes)")
verifier("réel et corrigé diffèrent sur cette journée",
         abs(float(comparaison["Recettes réelles"].iloc[0])
             - float(comparaison["Recettes corrigées"].iloc[0])) > 0.01)
verifier("les mois porteurs de corrections sont listés",
         any("Mois avec rectifications" in c.value for c in at.caption))

print("\n6 bis. Rectifications — un mois sans aucune correction")
at = lancer("app_pages/rectifications.py", {"mois_travail": (2026, 6)})
verifier("aucune exception", not at.exception, str(at.exception))
verifier("le mois est annoncé identique au réel",
         any("identique au registre réel" in i.value for i in at.info))
verifier("le cumul général reste visible",
         any("Sur l'ensemble du registre" in c.value for c in at.caption))

print("\n7. Rectifications — le tableau réel / corrigé")
conn = store.connect()
cloturees = [dt.date.fromisoformat(r["date"])
             for r in store.journal(conn, dt.date(2026, 7, 1), dt.date(2026, 7, 31),
                                    corrige=True) if r["cloture"]]
position = cloturees.index(D)
reel_D = store.lire_jour(conn, D)
corrige_D = store.lire_jour_corrige(conn, D)
nb_avant = store.nb_rectifications(conn)
conn.close()

at = lancer("app_pages/rectifications.py", {"mois_travail": (2026, 7)})
verifier("deux tableaux : réel et corrigé", len(at.dataframe) >= 2)
reel_df = at.dataframe[0].value
verifier("le tableau de gauche montre le registre réel",
         int(reel_df["pay_n"].iloc[position]) == reel_D.pay_n,
         f"({reel_df['pay_n'].iloc[position]} vs {reel_D.pay_n})")
verifier("le tableau de droite montre le registre corrigé",
         int(at.dataframe[1].value["pay_n"].iloc[position]) == corrige_D.pay_n)
verifier("les deux diffèrent sur la journée déjà rectifiée",
         reel_D.pay_n != corrige_D.pay_n)
verifier("seules les journées clôturées y figurent",
         len(reel_df) == len(cloturees), f"({len(reel_df)})")
verifier("aucune correction en attente au chargement",
         any("Aucune." in c.value for c in at.caption))

conn = store.connect()
mois_reel = [store.vers_journee(r) for r in store.journal(
    conn, dt.date(2026, 7, 1), dt.date(2026, 7, 31)) if r["cloture"]]
conn.close()
recettes_reelles = sum(j.recettes for j in mois_reel)
verifier("un bandeau de totaux par tableau",
         sum(1 for m in at.metric if m.label == "Recettes") == 2,
         f"({sum(1 for m in at.metric if m.label == 'Recettes')})")
verifier("les totaux du registre réel sont ceux du registre",
         at.metric[0].value == f"{recettes_reelles:,.0f}".replace(",", " ") + " TND",
         f"({at.metric[0].value})")
conn = store.connect()
mois_corrige = [store.vers_journee(r) for r in store.journal(
    conn, dt.date(2026, 7, 1), dt.date(2026, 7, 31), corrige=True) if r["cloture"]]
conn.close()
ecart_deja_la = sum(j.recettes for j in mois_corrige) - recettes_reelles
recettes = [m for m in at.metric if m.label == "Recettes"]
verifier("le bandeau du réel n'affiche pas d'écart", not recettes[0].delta)
verifier("celui du corrigé chiffre les rectifications déjà enregistrées",
         recettes[1].delta.replace(" ", "").replace("TND", "")
         == f"{ecart_deja_la:+.0f}",
         f"({recettes[1].delta} vs {ecart_deja_la:+.0f})")

print("\n7 bis. Rectifications — modifier le tableau de droite")
at = lancer("app_pages/rectifications.py", {
    "mois_travail": (2026, 7),
    f"rectif_2026_7": {"edited_rows": {position: {"pay_n": corrige_D.pay_n + 4}},
                       "added_rows": [], "deleted_rows": []},
})
verifier("aucune exception", not at.exception, str(at.exception))
attente = table(at, "Écart au réel", "Rectifié")
verifier("la correction en attente est détaillée", attente is not None)
verifier("elle rappelle la valeur réelle",
         attente["Réel"].iloc[0] == str(reel_D.pay_n), f"({attente['Réel'].iloc[0]})")
verifier("elle rappelle la valeur en vigueur",
         attente["En vigueur"].iloc[0] == str(corrige_D.pay_n))
verifier("elle montre la valeur rectifiée",
         attente["Rectifié"].iloc[0] == str(corrige_D.pay_n + 4))
verifier("l'écart est mesuré par rapport au réel",
         abs(float(attente["Écart au réel"].iloc[0])
             - (corrige_D.pay_n + 4 - reel_D.pay_n)) < 0.01)

recettes = [m for m in at.metric if m.label == "Recettes"]
verifier("le bandeau du réel reste sans écart", not recettes[0].delta)
verifier("le bandeau du corrigé chiffre l'écart en attente",
         recettes[1].delta and "+" in recettes[1].delta,
         f"({recettes[1].delta})")
verifier("l'écart correspond aux 4 consultations ajoutées",
         recettes[1].delta.replace(" ", "").replace("TND", "")
         == f"{4 * corrige_D.tarifs['t_pay'] + (corrige_D.recettes - reel_D.recettes):+.0f}",
         f"({recettes[1].delta})")

bouton = [b for b in at.button if "Enregistrer" in b.label][0]
verifier("enregistrement bloqué sans motif", bouton.disabled)
at.text_area(key="motif_rectif_2026_7").set_value("recomptage du registre (test)").run()
bouton = [b for b in at.button if "Enregistrer" in b.label][0]
verifier("débloqué avec motif", not bouton.disabled)
bouton.click().run()
verifier("aucune exception à l'enregistrement", not at.exception, str(at.exception))

conn = store.connect()
verifier("une rectification de plus", store.nb_rectifications(conn) == nb_avant + 1)
verifier("le registre corrigé a bougé",
         store.lire_jour_corrige(conn, D).pay_n == corrige_D.pay_n + 4)
verifier("le registre réel n'a pas bougé",
         store.lire_jour(conn, D).pay_n == reel_D.pay_n)
verifier("le motif est attaché",
         store.rectifications_du_jour(conn, D)[0]["motif"]
         == "recomptage du registre (test)")
conn.close()

print("\n7 ter. Rectifications — un mois sans journée clôturée")
at = lancer("app_pages/rectifications.py", {"mois_travail": (2027, 5)})
verifier("aucune exception", not at.exception, str(at.exception))
verifier("le cas est expliqué",
         any("rien à rectifier" in i.value for i in at.info))
verifier("et renvoie vers la saisie",
         any("Mois comptable" in i.value for i in at.info))

print("\n8. Tableau de bord — les deux registres")
at = lancer("app_pages/tableau_bord.py")
verifier("aucune exception", not at.exception, str(at.exception))
verifier("mention des rectifications",
         any("rectification" in c.value for c in at.caption))
corrige_recettes = at.metric[0].value
at.segmented_control(key="registre_bord").select("Réel").run()
verifier("bascule sans exception", not at.exception, str(at.exception))
verifier("le total change entre les deux vues",
         at.metric[0].value != corrige_recettes,
         f"({at.metric[0].value} vs {corrige_recettes})")

print("\n9. Classeur Excel")
at = lancer("app_pages/excel.py")
verifier("aucune exception", not at.exception, str(at.exception))
verifier("journée rectifiée en attente d'écriture",
         any("en attente" in s.value for s in at.subheader))

print("\n10. Tarifs")
at = lancer("app_pages/tarifs.py")
verifier("aucune exception", not at.exception, str(at.exception))

print(f"\n{'=' * 50}\n{ok} réussis, {ko} échecs\n{'=' * 50}")
sys.exit(1 if ko else 0)
