"""Le classeur peut bouger sans l'app : ce qui le détecte.

Tout se joue sur des COPIES — de la base et du classeur. L'originale n'est
jamais ouverte en écriture.
"""

import datetime as dt
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJET = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJET))

# le cabinet fictif de tests/atelier.py : ni le classeur réel, ni data/compta.db
import atelier  # noqa: E402

CLASSEUR, BASE = atelier.installer()

from compta import store, xlsx_io  # noqa: E402
from compta.config import XLSX_PATH  # noqa: E402

atelier = Path(tempfile.mkdtemp())
tmp_db = atelier / "test.db"
shutil.copy2(BASE, tmp_db)
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


print("\n1. Un classeur absent ne fait pas d'histoire")
etat = xlsx_io.etat_synchronisation(conn, atelier / "nexiste_pas.xlsx")
verifier("l'absence est signalée", etat["absent"])
verifier("rien n'est prétendu", not etat["connu"] and not etat["a_jour"])

if not XLSX_PATH.exists():
    print("\n  (classeur introuvable, le reste n'est pas testé)")
else:
    copie = atelier / "classeur.xlsx"
    shutil.copy2(XLSX_PATH, copie)
    taille_origine = XLSX_PATH.stat().st_size

    print("\n2. Sans relevé, l'app ne prétend rien")
    conn.execute("DELETE FROM meta WHERE cle=?", (xlsx_io._META_SOURCE,))
    conn.commit()
    etat = xlsx_io.etat_synchronisation(conn, copie)
    verifier("l'état n'est pas connu", not etat["connu"], f"({etat})")
    verifier("et n'est pas annoncé à jour pour autant", not etat["a_jour"])

    print("\n3. Un relevé pris, les deux sont d'accord")
    xlsx_io.marquer_synchronise(conn, copie)
    etat = xlsx_io.etat_synchronisation(conn, copie)
    verifier("l'état est connu", etat["connu"])
    verifier("registre et classeur sont d'accord", etat["a_jour"], f"({etat})")

    print("\n4. Modifié à l'extérieur, le classeur est repéré")
    futur = copie.stat().st_mtime + 120
    os.utime(copie, (futur, futur))
    etat = xlsx_io.etat_synchronisation(conn, copie)
    verifier("le désaccord est vu", etat["connu"] and not etat["a_jour"], f"({etat})")
    verifier("la date de modification est rapportée",
             etat["modifie_le"] == dt.datetime.fromtimestamp(futur),
             f"({etat['modifie_le']})")

    print("\n5. Une seconde d'écart ne réveille personne")
    xlsx_io.marquer_synchronise(conn, copie)
    presque = copie.stat().st_mtime + 0.5
    os.utime(copie, (presque, presque))
    verifier("la tolérance joue",
             xlsx_io.etat_synchronisation(conn, copie)["a_jour"])

    print("\n6. Un réimport remet les deux d'accord")
    os.utime(copie, (futur + 500, futur + 500))
    verifier("le désaccord est bien là avant",
             not xlsx_io.etat_synchronisation(conn, copie)["a_jour"])
    rapport = xlsx_io.importer(conn, chemin=copie)
    verifier("le classeur est relu", rapport["lignes"] > 0, f"({rapport['lignes']})")
    verifier("l'accord est rétabli",
             xlsx_io.etat_synchronisation(conn, copie)["a_jour"])

    print("\n7. L'écriture de l'app ne déclenche pas de fausse alerte")
    tarifs = store.tarifs_courants(conn)
    ouverts = store.jours_ouverts(conn, dt.date(2026, 9, 1), dt.date(2026, 12, 31))
    verifier("une journée ouverte est disponible pour le test", bool(ouverts))
    if ouverts:
        cible = ouverts[0]
        j = store.lire_jour(conn, cible, tarifs)
        j.pay_n = 3
        store.ecrire_jour(conn, j)
        # le test 6 a daté le fichier dans le futur : on le ramène à maintenant,
        # sinon l'écriture (datée d'aujourd'hui) paraîtrait plus ancienne
        os.utime(copie, None)
        avant = copie.stat().st_mtime
        xlsx_io.exporter(conn, [store.lire_jour_corrige(conn, cible, tarifs)],
                         chemin=copie, tarifs_nouveaux=tarifs)
        verifier("le fichier a bien changé", copie.stat().st_mtime >= avant)
        verifier("mais l'app le sait : aucune alerte",
                 xlsx_io.etat_synchronisation(conn, copie)["a_jour"],
                 f"({xlsx_io.etat_synchronisation(conn, copie)})")

    print("\n8. Le classeur d'origine n'a pas été touché")
    verifier("taille inchangée", XLSX_PATH.stat().st_size == taille_origine,
             f"({XLSX_PATH.stat().st_size} au lieu de {taille_origine})")

print(f"\n{'=' * 50}\n{ok} réussis, {ko} échecs\n{'=' * 50}")
conn.close()
sys.exit(1 if ko else 0)
