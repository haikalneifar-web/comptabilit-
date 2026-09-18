"""Des actes comptés sans montant en face : ce que l'import en fait.

Le classeur contient des cellules de montant **vides — pas à zéro, sans formule
du tout** en face d'un compteur rempli. Il n'y a alors aucun tarif à lire, et
retomber sur `TARIFS_DEFAUT` donnerait à une journée de 2018 le prix de 2026.
L'import hérite du tarif des lignes voisines, et signale les actes que le
classeur ne valorise nulle part.

Tout se joue sur un classeur fabriqué ici et une base neuve : ces tests ne
dépendent ni du registre du cabinet, ni de son classeur.
"""

import datetime as dt
import os
import shutil
import sys
import tempfile
from pathlib import Path

import openpyxl

PROJET = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJET))

# Le chemin du classeur est figé à l'import de `compta.config`, et sert de valeur
# par défaut à `importer`. On le détourne vers l'atelier avant tout import, pour
# que la page de démarrage travaille elle aussi sur le classeur fabriqué ici.
atelier = Path(tempfile.mkdtemp())
classeur = atelier / "fabrique.xlsx"
os.environ["COMPTA_XLSX"] = str(classeur)

from compta import store  # noqa: E402
from compta.config import SHEET_NAME, XLSX_PATH  # noqa: E402
from compta.model import TARIFS_DEFAUT  # noqa: E402

store.DB_PATH = atelier / "test.db"

from compta import xlsx_io  # noqa: E402

ok, ko = 0, 0


def verifier(nom, condition, detail=""):
    global ok, ko
    if condition:
        ok += 1
        print(f"  OK   {nom}")
    else:
        ko += 1
        print(f"  ECHEC {nom} {detail}")


# --- 1. l'héritage lui-même ---------------------------------------------------

print("\n1. Un tarif illisible prend celui de la voisine la plus proche")

verifier("rien de lisible, rien d'inventé",
         xlsx_io._heriter_des_voisines([None, None, None]) == [None, None, None])

verifier("une valeur lisible se propage vers l'aval",
         xlsx_io._heriter_des_voisines([30.0, None, None]) == [30.0, 30.0, 30.0])

verifier("et vers l'amont quand il n'y a rien avant",
         xlsx_io._heriter_des_voisines([None, None, 30.0]) == [30.0, 30.0, 30.0])

verifier("les valeurs lisibles ne bougent pas",
         xlsx_io._heriter_des_voisines([30.0, None, 45.0]) == [30.0, 30.0, 45.0])

# 30 en 0, 45 en 4 : les trous 1 et 2 sont plus près de 30, le trou 3 de 45
verifier("la plus proche gagne",
         xlsx_io._heriter_des_voisines([30.0, None, None, None, 45.0])
         == [30.0, 30.0, 30.0, 45.0, 45.0],
         f"({xlsx_io._heriter_des_voisines([30.0, None, None, None, 45.0])})")

# à égalité de distance, c'est celle d'avant : un tarif vaut jusqu'à ce qu'il change
verifier("à égalité, le tarif d'avant l'emporte",
         xlsx_io._heriter_des_voisines([30.0, None, 45.0, None, None])[1] == 30.0)


# --- 2. un classeur fabriqué pour l'occasion ----------------------------------

TARIFS_ANCIENS = {"D": 52, "F": 9, "G": 21, "I": 40, "K": 30, "M": 40,
                  "O": 600, "Q": 600, "W": 11}
TARIFS_RECENTS = {"D": 72, "F": 20, "G": 21, "I": 70, "K": 70, "M": 70,
                  "O": 700, "Q": 750, "W": 11}
COMPTEUR_DE = {"D": "C", "F": "E", "G": "E", "I": "H", "K": "J", "M": "L",
               "O": "N", "Q": "P", "W": "E"}


def ligne(ws, r, date, compteurs, tarifs, sans_formule=()):
    """Écrit une journée. `sans_formule` laisse ces colonnes de montant vides."""
    ws[f"A{r}"] = date.strftime("%A").upper()
    ws[f"B{r}"] = dt.datetime(date.year, date.month, date.day)
    for col in "CEHJLNP":
        ws[f"{col}{r}"] = 0
    for col, n in compteurs.items():
        ws[f"{col}{r}"] = n
    for col, t in tarifs.items():
        if col in sans_formule:
            continue
        ws[f"{col}{r}"] = f"={COMPTEUR_DE[col]}{r}*{t}"
    ws[f"U{r}"] = (f"=D{r}+F{r}+I{r}+K{r}+M{r}+O{r}+Q{r}+S{r}+T{r}+R{r}+W{r}")
    ws[f"AB{r}"] = f"=C{r}+E{r}+H{r}+J{r}+L{r}"


wb = openpyxl.Workbook()
ws = wb.active
ws.title = SHEET_NAME

debut = dt.date(2018, 6, 1)
# 10 journées anciennes, puis 10 récentes. Les trous sont posés au milieu des
# anciennes, loin des lignes récentes : le tarif hérité doit être l'ancien.
for i in range(10):
    trous = ()
    compteurs = {"C": 2, "E": 1, "H": 1, "L": 5}
    if i in (4, 5, 6):
        compteurs["J"] = 1      # un patient assurance…
        trous = ("K",)          # …sans montant en face
    if i == 7:
        compteurs["P"] = 2      # deux cataractes payantes…
        trous = ("Q",)          # …sans montant en face
    if i == 8:
        trous = ("K",)          # colonne vide, mais compteur J à zéro
    ligne(ws, 4 + i, debut + dt.timedelta(days=i), compteurs,
          TARIFS_ANCIENS, trous)

for i in range(10):
    ligne(ws, 14 + i, dt.date(2026, 7, 1) + dt.timedelta(days=i),
          {"C": 2, "E": 1, "H": 1, "J": 1, "L": 5}, TARIFS_RECENTS)

wb.save(classeur)

conn = store.connect()
store.init_db(conn)
rapport = xlsx_io.importer(conn, chemin=classeur)

print("\n2. L'import lit le classeur fabriqué")
verifier("les 20 journées sont reprises", rapport["lignes"] == 20,
         f"({rapport['lignes']})")

print("\n3. Les actes sans montant sont signalés, poste par poste")
postes = {p["cle"]: p for p in rapport["postes_sans_tarif"]}
verifier("deux postes sont signalés", set(postes) == {"t_star", "t_cat_pay"},
         f"({sorted(postes)})")

star = postes.get("t_star", {})
verifier("l'assurance : 3 journées", star.get("journees") == 3,
         f"({star.get('journees')})")
verifier("l'assurance : 3 actes", star.get("actes") == 3, f"({star.get('actes')})")
verifier("l'assurance : la période est celle des trous",
         star.get("premiere") == dt.date(2018, 6, 5)
         and star.get("derniere") == dt.date(2018, 6, 7),
         f"({star.get('premiere')} → {star.get('derniere')})")
verifier("l'assurance : les colonnes sont nommées",
         star.get("compteur") == "J" and star.get("colonne") == "K",
         f"({star.get('compteur')}→{star.get('colonne')})")
verifier("l'assurance : chiffrée au tarif voisin, pas au défaut d'aujourd'hui",
         star.get("montant") == 3 * 30, f"({star.get('montant')})")

cat = postes.get("t_cat_pay", {})
verifier("la cataracte : 1 journée, 2 actes",
         cat.get("journees") == 1 and cat.get("actes") == 2,
         f"({cat.get('journees')}, {cat.get('actes')})")
verifier("la cataracte : chiffrée à 600, pas à 750",
         cat.get("montant") == 2 * 600, f"({cat.get('montant')})")

verifier("le plus gros manque est annoncé en premier",
         rapport["postes_sans_tarif"][0]["cle"] == "t_cat_pay",
         f"({rapport['postes_sans_tarif'][0]['cle']})")

print("\n4. Un compteur à zéro ne fait pas d'histoire")
# ligne 12 : colonne K vide elle aussi, mais aucun patient assurance ce jour-là.
# Rien n'est perdu, donc rien à signaler — le tarif est comblé en silence.
verifier("la journée sans acte n'est pas signalée",
         12 not in star.get("lignes", []), f"({star.get('lignes')})")
verifier("mais son tarif est hérité quand même",
         store.lire_jour(conn, dt.date(2018, 6, 9)).tarifs["t_star"] == 30.0,
         f"({store.lire_jour(conn, dt.date(2018, 6, 9)).tarifs['t_star']})")
verifier("les cinq cellules vides ont été comblées",
         rapport["tarifs_herites"] == 5, f"({rapport['tarifs_herites']})")

print("\n5. La journée touchée porte le tarif de son époque")
j = store.lire_jour(conn, dt.date(2018, 6, 5))
verifier("le tarif assurance est celui des voisines", j.tarifs["t_star"] == 30.0,
         f"({j.tarifs['t_star']})")
verifier("et surtout pas le défaut moderne",
         j.tarifs["t_star"] != TARIFS_DEFAUT["t_star"])
verifier("les autres tarifs de la journée sont lus normalement",
         j.tarifs["t_apci"] == 52.0 and j.tarifs["t_pay"] == 40.0,
         f"({j.tarifs['t_apci']}, {j.tarifs['t_pay']})")

jq = store.lire_jour(conn, dt.date(2018, 6, 8))
verifier("la cataracte payante hérite de 600", jq.tarifs["t_cat_pay"] == 600.0,
         f"({jq.tarifs['t_cat_pay']})")

print("\n6. Une journée récente n'est pas contaminée")
jr = store.lire_jour(conn, dt.date(2026, 7, 3))
verifier("elle garde ses tarifs lisibles",
         jr.tarifs["t_star"] == 70.0 and jr.tarifs["t_cat_pay"] == 750.0,
         f"({jr.tarifs['t_star']}, {jr.tarifs['t_cat_pay']})")

print("\n7. Un classeur sans trou ne signale rien")
propre = atelier / "propre.xlsx"
wb2 = openpyxl.Workbook()
ws2 = wb2.active
ws2.title = SHEET_NAME
for i in range(5):
    ligne(ws2, 4 + i, dt.date(2026, 7, 1) + dt.timedelta(days=i),
          {"C": 1, "J": 1, "P": 1}, TARIFS_RECENTS)
wb2.save(propre)

db2 = atelier / "test2.db"
store.DB_PATH = db2
conn2 = store.connect()
store.init_db(conn2)
r2 = xlsx_io.importer(conn2, chemin=propre)
verifier("aucun poste signalé", r2["postes_sans_tarif"] == [],
         f"({r2['postes_sans_tarif']})")
verifier("aucun tarif hérité", r2["tarifs_herites"] == 0,
         f"({r2['tarifs_herites']})")

print("\n8. Rectifiée un jour, la journée sera comptée au prix de son époque")
# c'est tout l'enjeu de l'héritage : le modèle ne reprend la main que sur une
# journée modifiée ou rectifiée, et il doit alors valoriser l'acte à 30, pas à 70.
jt = store.lire_jour(conn, dt.date(2018, 6, 5))
sans_assurance = 2 * 52 + 1 * 9 + 1 * 40 + 5 * 40 + 1 * 11
verifier("l'acte vaut le tarif de 2018", jt.star_n == 1
         and abs(jt.recettes - (sans_assurance + 30)) < 0.005,
         f"({jt.recettes}, attendu {sans_assurance + 30})")
verifier("et non celui d'aujourd'hui",
         abs(jt.recettes - (sans_assurance + TARIFS_DEFAUT["t_star"])) > 0.005)

print("\n9. Signaler n'est pas corriger : les totaux du classeur sont gardés")
# Excel garde en cache le résultat de ses formules, et c'est lui que l'import
# stocke : là où une cellule vide a fait mentir la colonne U, le registre reste
# fidèle au classeur. Porter ces actes au CA est une rectification, pas un import.
cache = atelier / "avec_cache.xlsx"
wb3 = openpyxl.Workbook()
ws3 = wb3.active
ws3.title = SHEET_NAME
ligne(ws3, 4, dt.date(2018, 6, 5), {"C": 2, "E": 1, "H": 1, "J": 1, "L": 5},
      TARIFS_ANCIENS, ("K",))
ws3["U4"] = sans_assurance          # ce qu'Excel avait calculé, assurance absente
ligne(ws3, 5, dt.date(2018, 6, 6), {"C": 2, "J": 1}, TARIFS_ANCIENS)
wb3.save(cache)

db3 = atelier / "test3.db"
store.DB_PATH = db3
conn3 = store.connect()
store.init_db(conn3)
r3 = xlsx_io.importer(conn3, chemin=cache)
stocke = conn3.execute("SELECT recettes FROM jours WHERE date=?",
                       ("2018-06-05",)).fetchone()["recettes"]
verifier("le total stocké est celui du classeur",
         abs(stocke - sans_assurance) < 0.005,
         f"({stocke} au lieu de {sans_assurance})")
verifier("l'acte manquant est signalé quand même",
         [p["cle"] for p in r3["postes_sans_tarif"]] == ["t_star"],
         f"({[p['cle'] for p in r3['postes_sans_tarif']]})")
verifier("le tarif, lui, est bien hérité",
         store.lire_jour(conn3, dt.date(2018, 6, 5)).tarifs["t_star"] == 30.0)

print("\n10. La page de démarrage le dit à l'écran")
# base neuve : sans `import_fait`, l'app s'ouvre sur la page de reprise, et le
# bouton importe le classeur fabriqué plus haut (`COMPTA_XLSX`).
verifier("le classeur de l'app est bien celui de l'atelier", XLSX_PATH == classeur,
         f"({XLSX_PATH})")

store.DB_PATH = atelier / "test4.db"
from streamlit.testing.v1 import AppTest  # noqa: E402

at = AppTest.from_file(str(PROJET / "streamlit_app.py"), default_timeout=60)
at.run()
verifier("l'app s'ouvre sur la reprise d'historique",
         any("Reprise de l'historique" in t.value for t in at.title),
         str(at.exception))

boutons = [b for b in at.button if "Importer" in b.label]
verifier("le bouton d'import est là", bool(boutons))
if boutons:
    at = boutons[0].click().run()
    verifier("aucune exception", not at.exception, str(at.exception))
    verifier("l'import est annoncé",
             any("20 journées reprises" in s.value for s in at.success),
             str([s.value for s in at.success]))
    alertes = " ".join(w.value for w in at.warning)
    verifier("les actes sans montant sont signalés",
             "actes comptés sans montant" in alertes, f"({alertes[:120]})")
    verifier("le nombre de journées touchées est annoncé",
             "sur 4 journées" in alertes.lower(), f"({alertes[:200]})")
    verifier("le détail par poste est affiché", len(at.dataframe) >= 1,
             f"({len(at.dataframe)} tableaux)")
    if at.dataframe:
        table = at.dataframe[0].value
        verifier("une ligne par poste touché", len(table) == 2, f"({len(table)})")
        verifier("les deux postes sont nommés",
                 {"Cataracte payante", "Assurance / STAR"}
                 <= set(table["Poste"]), f"({list(table['Poste'])})")
        verifier("le manque est chiffré",
                 "1 200 TND" in list(table["Manque au CA"]),
                 f"({list(table['Manque au CA'])})")

    print("\n11. Et le constat reste lisible avant de passer à la saisie")
    suite = [b for b in at.button if "Commencer" in b.label]
    verifier("le passage à la saisie est proposé", bool(suite))
    if suite:
        at = suite[0].click().run()
        verifier("aucune exception au passage", not at.exception, str(at.exception))
        verifier("l'app s'ouvre alors sur le mois comptable",
                 any("Mois comptable" in h.value for h in at.header),
                 str([h.value for h in at.header]))

print("\n12. À l'écriture, une journée ouverte sans formule est rendue entière")
# c'est la seule façon que le défaut se reproduise : saisir aujourd'hui une des
# journées restées vides dont la colonne de montant n'a jamais eu de formule.
xlsx_io.BACKUP_DIR = atelier          # pas de sauvegarde dans le dossier du projet

ecriture = atelier / "ecriture.xlsx"
wb5 = openpyxl.Workbook()
ws5 = wb5.active
ws5.title = SHEET_NAME
for i in range(5):
    # journées vides, donc ouvertes ; la deuxième n'a ni `K` ni `Q`
    ligne(ws5, 4 + i, dt.date(2026, 9, 1) + dt.timedelta(days=i), {},
          TARIFS_RECENTS, ("K", "Q") if i == 1 else ())
wb5.save(ecriture)

store.DB_PATH = atelier / "test5.db"
conn5 = store.connect()
store.init_db(conn5)
xlsx_io.importer(conn5, chemin=ecriture)

cible = dt.date(2026, 9, 2)
verifier("la journée trouée est ouverte", not store.est_cloture(conn5, cible))
j5 = store.lire_jour(conn5, cible)
j5.star_n, j5.cat_pay_n, j5.pay_n = 2, 1, 4
store.ecrire_jour(conn5, j5)

rapport5 = xlsx_io.exporter(conn5, [store.lire_jour_corrige(conn5, cible)],
                            chemin=ecriture)
verifier("la journée est écrite", rapport5["ecrites"] == 1)
posees = {col for d, col in rapport5["formules_posees"]}
verifier("les deux formules manquantes sont posées", posees == {"K", "Q"},
         f"({posees})")
verifier("et rapportées sur la bonne journée",
         {d for d, _ in rapport5["formules_posees"]} == {cible})
verifier("rien n'est signalé comme resté sans montant",
         rapport5["formules_absentes"] == [],
         f"({rapport5['formules_absentes']})")

relu = openpyxl.load_workbook(ecriture, data_only=False)[SHEET_NAME]
verifier("la formule assurance est en place et au bon tarif",
         relu["K5"].value == "=J5*70", f"({relu['K5'].value})")
verifier("la formule cataracte aussi", relu["Q5"].value == "=P5*750",
         f"({relu['Q5'].value})")
verifier("le compteur est bien écrit en face", relu["J5"].value == 2,
         f"({relu['J5'].value})")
verifier("les journées voisines gardent leurs formules d'origine",
         relu["K4"].value == "=J4*70" and relu["K6"].value == "=J6*70",
         f"({relu['K4'].value}, {relu['K6'].value})")

print("\n13. Une journée acquise n'est pas récrite en douce, elle est signalée")
acquise = atelier / "acquise.xlsx"
wb6 = openpyxl.Workbook()
ws6 = wb6.active
ws6.title = SHEET_NAME
# une journée de 2018 qui porte des chiffres, dont un patient assurance sans `K`
ligne(ws6, 4, dt.date(2018, 6, 4), {"C": 2, "L": 3, "J": 1}, TARIFS_ANCIENS, ("K",))
ligne(ws6, 5, dt.date(2018, 6, 5), {"C": 1, "L": 2}, TARIFS_ANCIENS)
wb6.save(acquise)

store.DB_PATH = atelier / "test6.db"
conn6 = store.connect()
store.init_db(conn6)
xlsx_io.importer(conn6, chemin=acquise)

vieille = dt.date(2018, 6, 4)
verifier("la journée est bien acquise", store.est_cloture(conn6, vieille))
rapport6 = xlsx_io.exporter(conn6, [store.lire_jour_corrige(conn6, vieille)],
                            chemin=acquise)
verifier("aucune formule n'est posée sur une journée acquise",
         rapport6["formules_posees"] == [], f"({rapport6['formules_posees']})")
verifier("le trou est signalé, avec son compteur",
         rapport6["formules_absentes"] == [(vieille, "K", "J", 1)],
         f"({rapport6['formules_absentes']})")
relu6 = openpyxl.load_workbook(acquise, data_only=False)[SHEET_NAME]
verifier("la cellule vide le reste", relu6["K4"].value is None,
         f"({relu6['K4'].value})")
verifier("le total de la journée n'a pas bougé",
         relu6["U4"].value == "=D4+F4+I4+K4+M4+O4+Q4+S4+T4+R4+W4",
         f"({relu6['U4'].value})")

print(f"\n{'=' * 50}\n{ok} réussis, {ko} échecs\n{'=' * 50}")
for c in (conn, conn2, conn3, conn5, conn6):
    c.close()
shutil.rmtree(atelier, ignore_errors=True)
sys.exit(1 if ko else 0)
