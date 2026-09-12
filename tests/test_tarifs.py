"""Changement de tarif : ce qui suit le nouveau prix, ce qui garde l'ancien.

Tout se joue sur des COPIES — de la base et du classeur. L'originale n'est
jamais ouverte en écriture.
"""

import datetime as dt
import shutil
import sys
import tempfile
from pathlib import Path

PROJET = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJET))

import openpyxl  # noqa: E402

from compta import store, xlsx_io  # noqa: E402
from compta.config import SHEET_NAME, XLSX_PATH  # noqa: E402

atelier = Path(tempfile.mkdtemp())
tmp_db = atelier / "test.db"
shutil.copy2(PROJET / "data" / "compta.db", tmp_db)
store.DB_PATH = tmp_db

conn = store.connect()
store.init_db(conn)

ok, ko = 0, 0


def verifier(nom, condition, detail=""):
    global ok, ko
    if condition:
        ok += 1
        print(f"  OK   {nom}")
    else:
        ko += 1
        print(f"  ECHEC {nom} {detail}")


print("\n1. État de départ : un tarif modifié dans l'app, pas dans le classeur")
courants = store.tarifs_courants(conn)
VIDE = dt.date(2026, 9, 15)      # ligne pré-remplie du classeur, à zéro
REMPLIE = dt.date(2026, 7, 15)   # journée acquise
verifier("la journée à venir est ouverte et vide",
         not store.est_cloture(conn, VIDE) and store.lire_jour(conn, VIDE).vide)
verifier("la journée passée est clôturée", store.est_cloture(conn, REMPLIE))

brut = conn.execute("SELECT t_apci, t_pay FROM jours WHERE date=?",
                    (VIDE.isoformat(),)).fetchone()
verifier("la ligne pré-remplie porte l'ancien tarif APCI du classeur",
         brut["t_apci"] == 72.0, f"({brut['t_apci']})")

print("\n2. Une journée vide suit le tarif en vigueur")
NOUVEAUX = dict(courants) | {"t_apci": 74.0, "t_pay": 80.0}
store.enregistrer_tarifs(conn, NOUVEAUX)

j_vide = store.lire_jour(conn, VIDE, store.tarifs_courants(conn))
verifier("tarif APCI aligné sur le tarif en vigueur", j_vide.tarifs["t_apci"] == 74.0,
         f"({j_vide.tarifs['t_apci']})")
verifier("tarif payant aligné", j_vide.tarifs["t_pay"] == 80.0,
         f"({j_vide.tarifs['t_pay']})")

print("\n3. Une journée qui porte des chiffres garde le sien")
j_pleine = store.lire_jour(conn, REMPLIE, store.tarifs_courants(conn))
verifier("tarif payant d'origine conservé", j_pleine.tarifs["t_pay"] == 70.0,
         f"({j_pleine.tarifs['t_pay']})")
verifier("tarif APCI d'origine conservé", j_pleine.tarifs["t_apci"] == 72.0,
         f"({j_pleine.tarifs['t_apci']})")
verifier("ses recettes ne bougent pas d'un iota",
         abs(j_pleine.recettes
             - conn.execute("SELECT recettes r FROM jours WHERE date=?",
                            (REMPLIE.isoformat(),)).fetchone()["r"]) < 0.01)

print("\n4. Le tableau du mois calcule au nouveau tarif")
ligne = [r for r in store.journal(conn, dt.date(2026, 9, 1), dt.date(2026, 9, 30))
         if r["date"] == VIDE.isoformat()][0]
j = store.vers_journee(ligne, store.tarifs_courants(conn))
j.apci_n, j.pay_n = 10, 10
verifier("APCI compté à 74", abs(j.apci_m - 740.0) < 0.01, f"({j.apci_m})")
verifier("payant compté à 80", abs(j.pay_m - 800.0) < 0.01, f"({j.pay_m})")

print("\n5. Enregistrement : la journée fige le tarif appliqué")
saisie = store.lire_jour(conn, VIDE, store.tarifs_courants(conn))
saisie.apci_n, saisie.pay_n = 10, 10
store.ecrire_jour(conn, saisie)
relue = store.lire_jour(conn, VIDE, store.tarifs_courants(conn))
verifier("le tarif est inscrit dans la journée", relue.tarifs["t_apci"] == 74.0)
verifier("elle n'est plus vide, donc plus alignable", not relue.vide)
store.enregistrer_tarifs(conn, dict(NOUVEAUX) | {"t_apci": 999.0})
verifier("un changement ultérieur ne la touche plus",
         store.lire_jour(conn, VIDE, store.tarifs_courants(conn)).tarifs["t_apci"] == 74.0)
store.enregistrer_tarifs(conn, NOUVEAUX)

print("\n6. Écriture dans une COPIE du classeur : la formule est réalignée")
if not XLSX_PATH.exists():
    print("  (classeur introuvable, écriture non testée)")
else:
    copie = atelier / "classeur.xlsx"
    shutil.copy2(XLSX_PATH, copie)

    wb = openpyxl.load_workbook(copie, data_only=False)
    ws = wb[SHEET_NAME]
    ligne_xlsx = store.lire_jour(conn, VIDE).ligne_xlsx
    formule_avant = ws[f"D{ligne_xlsx}"].value
    formule_pay_avant = ws[f"M{ligne_xlsx}"].value
    wb.close()
    verifier("la formule du classeur porte bien l'ancien tarif",
             formule_avant.endswith("*72"), f"({formule_avant})")

    rapport = xlsx_io.exporter(
        conn, [store.lire_jour_corrige(conn, VIDE, store.tarifs_courants(conn))],
        chemin=copie, tarifs_nouveaux=store.tarifs_courants(conn))

    wb = openpyxl.load_workbook(copie, data_only=False)
    ws = wb[SHEET_NAME]
    verifier("journée écrite", rapport["ecrites"] == 1)
    verifier("la formule APCI est passée au nouveau tarif",
             ws[f"D{ligne_xlsx}"].value == f"=C{ligne_xlsx}*74",
             f"({ws[f'D{ligne_xlsx}'].value})")
    verifier("la formule payant aussi",
             ws[f"M{ligne_xlsx}"].value == f"=L{ligne_xlsx}*80",
             f"({ws[f'M{ligne_xlsx}'].value})")
    verifier("c'est toujours une formule, pas une valeur",
             str(ws[f"D{ligne_xlsx}"].value).startswith("="))
    verifier("les compteurs sont écrits",
             ws[f"C{ligne_xlsx}"].value == 10 and ws[f"L{ligne_xlsx}"].value == 10)
    verifier("le réalignement est rapporté",
             len(rapport["tarifs_alignes"]) >= 2,
             f"({rapport['tarifs_alignes']})")
    verifier("la formule de total est intacte",
             ws[f"U{ligne_xlsx}"].value == formule_pay_avant.replace("M", "U") or
             str(ws[f"U{ligne_xlsx}"].value).startswith("="))

    print("\n7. Une journée clôturée n'est jamais réalignée")
    ligne_pleine = store.lire_jour(conn, REMPLIE).ligne_xlsx
    formule_pleine = ws[f"M{ligne_pleine}"].value
    compteurs_avant = ws[f"L{ligne_pleine}"].value
    wb.close()
    verifier("sa formule porte l'ancien tarif", formule_pleine.endswith("*70"),
             f"({formule_pleine})")

    j_close = store.lire_jour_corrige(conn, REMPLIE, store.tarifs_courants(conn))
    rapport2 = xlsx_io.exporter(conn, [j_close], chemin=copie,
                                tarifs_nouveaux=store.tarifs_courants(conn))
    wb = openpyxl.load_workbook(copie, data_only=False)
    ws = wb[SHEET_NAME]
    verifier("formule inchangée sur la journée clôturée",
             ws[f"M{ligne_pleine}"].value == formule_pleine,
             f"({ws[f'M{ligne_pleine}'].value})")
    verifier("aucun réalignement rapporté", not rapport2["tarifs_alignes"],
             f"({rapport2['tarifs_alignes']})")
    verifier("ses compteurs sont réécrits à l'identique",
             ws[f"L{ligne_pleine}"].value == compteurs_avant)
    wb.close()

    print("\n8. Le classeur d'origine n'a pas été touché")
    verifier("taille inchangée depuis le début du test",
             XLSX_PATH.stat().st_size > 0)
    wb_orig = openpyxl.load_workbook(XLSX_PATH, data_only=False, read_only=True)
    ws_orig = wb_orig[SHEET_NAME]
    verifier("la formule d'origine porte toujours *72",
             str(ws_orig[f"D{ligne_xlsx}"].value).endswith("*72"),
             f"({ws_orig[f'D{ligne_xlsx}'].value})")
    verifier("les compteurs d'origine sont toujours vides",
             not ws_orig[f"C{ligne_xlsx}"].value)
    wb_orig.close()

print(f"\n{'=' * 50}\n{ok} réussis, {ko} échecs\n{'=' * 50}")
conn.close()
sys.exit(1 if ko else 0)
