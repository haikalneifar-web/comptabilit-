"""Tests du registre réel figé + journal des rectifications, sur une COPIE de la base."""

import datetime as dt
import shutil
import sys
import tempfile
from pathlib import Path

PROJET = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJET))

from compta import store  # noqa: E402
from compta.model import Journee  # noqa: E402

tmp = Path(tempfile.mkdtemp()) / "test.db"
shutil.copy2(PROJET / "data" / "compta.db", tmp)
store.DB_PATH = tmp

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


print("\n1. Migration : clôture des seules journées qui portent des chiffres")
n_cloture = conn.execute("SELECT COUNT(*) n FROM jours WHERE cloture=1").fetchone()["n"]
n_ouvert = conn.execute("SELECT COUNT(*) n FROM jours WHERE cloture=0").fetchone()["n"]
verifier("2 903 journées acquises sont clôturées", n_cloture == 2903, f"({n_cloture})")
verifier("1 227 emplacements vides restent ouverts", n_ouvert == 1227, f"({n_ouvert})")
from compta.model import CHAMPS_SAISIE  # noqa: E402
verifier("aucune journée clôturée n'est vide",
         conn.execute(
             f"SELECT COUNT(*) n FROM jours WHERE cloture=1 "
             f"AND ({' + '.join(CHAMPS_SAISIE)}) = 0"
         ).fetchone()["n"] == 0)
verifier("aucune journée ouverte ne porte de chiffres",
         conn.execute(
             f"SELECT COUNT(*) n FROM jours WHERE cloture=0 "
             f"AND ({' + '.join(CHAMPS_SAISIE)}) > 0"
         ).fetchone()["n"] == 0)
verifier("la saisie du jour reste possible",
         not store.est_cloture(conn, dt.date.today()))

print("\n2. Une journée clôturée refuse l'écrasement")
d = dt.date(2026, 7, 15)
reel = store.lire_jour(conn, d)
verifier("la journée test est clôturée", reel.cloture)
avant = reel.pay_n
reel.pay_n = avant + 50
try:
    store.ecrire_jour(conn, reel)
    verifier("ecrire_jour lève JourCloture", False, "(aucune exception)")
except store.JourCloture:
    verifier("ecrire_jour lève JourCloture", True)
verifier("la valeur d'origine est intacte", store.lire_jour(conn, d).pay_n == avant)

print("\n3. Motif obligatoire")
for motif in ("", "   ", None):
    try:
        store.ajouter_rectification(conn, d, "pay_n", avant + 1, motif)
        verifier(f"motif {motif!r} refusé", False, "(accepté)")
    except ValueError:
        verifier(f"motif {motif!r} refusé", True)

print("\n4. Champ non rectifiable, journée inexistante, valeur inchangée")
try:
    store.ajouter_rectification(conn, d, "recettes", 10, "motif")
    verifier("champ calculé refusé", False)
except ValueError:
    verifier("champ calculé refusé", True)
try:
    store.ajouter_rectification(conn, dt.date(1990, 1, 1), "pay_n", 1, "motif")
    verifier("journée absente refusée", False)
except ValueError:
    verifier("journée absente refusée", True)
try:
    store.ajouter_rectification(conn, d, "pay_n", avant, "motif")
    verifier("valeur identique refusée", False)
except ValueError:
    verifier("valeur identique refusée", True)

print("\n5. La rectification corrige sans écraser")
reel_avant = store.lire_jour(conn, d)
rid = store.ajouter_rectification(
    conn, d, "pay_n", avant - 3, "3 patients comptés deux fois (test)")
reel_apres = store.lire_jour(conn, d)
corrige = store.lire_jour_corrige(conn, d)
verifier("registre réel inchangé", reel_apres.pay_n == avant)
verifier("registre corrigé à jour", corrige.pay_n == avant - 3)
verifier("recettes corrigées cohérentes",
         abs(corrige.recettes - (reel_apres.recettes - 3 * reel_apres.tarifs["t_pay"]))
         < 0.01)
verifier("journée marquée à exporter", store.lire_jour(conn, d).a_exporter)

print("\n6. Le journal mensuel distingue les deux vues")
debut, fin = dt.date(2026, 7, 1), dt.date(2026, 7, 31)
jr = {r["date"]: r for r in store.journal(conn, debut, fin, corrige=False)}
jc = {r["date"]: r for r in store.journal(conn, debut, fin, corrige=True)}
cle = d.isoformat()
verifier("vue réelle non corrigée", jr[cle]["pay_n"] == avant)
verifier("vue corrigée corrigée", jc[cle]["pay_n"] == avant - 3)
verifier("journée signalée rectifiée dans les deux vues",
         jr[cle]["rectifiee"] and jc[cle]["rectifiee"])
verifier("les autres journées sont identiques",
         all(jr[k]["recettes"] == jc[k]["recettes"] for k in jr if k != cle))

print("\n7. Agrégats")
m_reel = {r["mois"]: r for r in store.agregat_mensuel(conn)}
m_corr = {r["mois"]: r for r in store.agregat_mensuel(conn, corrige=True)}
ecart = m_reel["2026-07"]["recettes"] - m_corr["2026-07"]["recettes"]
verifier("écart mensuel = 3 consultations payantes",
         abs(ecart - 3 * reel_apres.tarifs["t_pay"]) < 0.01, f"({ecart})")
verifier("patients corrigés = réels - 3",
         m_corr["2026-07"]["patients"] == m_reel["2026-07"]["patients"] - 3)
verifier("mois non touchés inchangés",
         all(abs(m_reel[k]["recettes"] - m_corr[k]["recettes"]) < 0.01
             for k in m_reel if k != "2026-07"))
a_reel = {r["annee"]: r for r in store.agregat_annuel(conn)}
a_corr = {r["annee"]: r for r in store.agregat_annuel(conn, corrige=True)}
verifier("écart annuel identique",
         abs((a_reel["2026"]["recettes"] - a_corr["2026"]["recettes"]) - ecart) < 0.01)
t_reel, t_corr = store.totaux(conn), store.totaux(conn, corrige=True)
verifier("écart sur le total général identique",
         abs((t_reel["recettes"] - t_corr["recettes"]) - ecart) < 0.01)
verifier("nombre de jours inchangé", t_reel["jours"] == t_corr["jours"])

print("\n8. Empilement de rectifications sur le même champ")
store.ajouter_rectification(conn, d, "pay_n", avant - 1, "recomptage (test)")
verifier("la dernière fait foi", store.lire_jour_corrige(conn, d).pay_n == avant - 1)
journal_d = store.rectifications_du_jour(conn, d)
verifier("deux lignes au journal", len(journal_d) == 2, f"({len(journal_d)})")
verifier("une seule en vigueur",
         sum(1 for r in journal_d if r["en_vigueur"]) == 1)
verifier("la 2e part de la valeur corrigée par la 1re",
         any(abs(r["ancienne"] - (avant - 3)) < 0.01 for r in journal_d))

print("\n9. Revenir en arrière n'efface rien")
dernier = [r for r in store.rectifications_du_jour(conn, d) if r["en_vigueur"]][0]
store.annuler_rectification(conn, dernier["id"], "retour : le recomptage était faux (test)")
verifier("valeur revenue à l'état précédent",
         store.lire_jour_corrige(conn, d).pay_n == avant - 3)
journal_d = store.rectifications_du_jour(conn, d)
verifier("trois lignes au journal", len(journal_d) == 3, f"({len(journal_d)})")
verifier("l'annulation référence la rectification annulée",
         journal_d[0]["annule_id"] == dernier["id"])
verifier("registre réel toujours intact", store.lire_jour(conn, d).pay_n == avant)

print("\n10. Montants directs")
store.ajouter_rectification(conn, d, "divers", 250.0, "recette divers oubliée (test)")
verifier("montant direct rectifiable",
         abs(store.lire_jour_corrige(conn, d).divers - 250.0) < 0.01)
verifier("réel inchangé", store.lire_jour(conn, d).divers == reel_avant.divers)
try:
    store.ajouter_rectification(conn, d, "divers", -10, "négatif (test)")
    verifier("valeur négative refusée", False)
except ValueError:
    verifier("valeur négative refusée", True)

print("\n11. Clôture d'une journée ouverte")
neuve = dt.date(2027, 3, 5)
j = Journee(date=neuve, pay_n=4, source="app")
j.tarifs = store.tarifs_courants(conn)
store.ecrire_jour(conn, j)
verifier("journée neuve ouverte", not store.est_cloture(conn, neuve))
j.pay_n = 6
store.ecrire_jour(conn, j)
verifier("modifiable tant qu'ouverte", store.lire_jour(conn, neuve).pay_n == 6)
store.cloturer(conn, [neuve])
verifier("clôturée", store.est_cloture(conn, neuve))
try:
    store.ecrire_jour(conn, store.lire_jour(conn, neuve))
    verifier("figée après clôture", False)
except store.JourCloture:
    verifier("figée après clôture", True)

print("\n12. L'écriture au classeur clôture")
autre = dt.date(2027, 3, 6)
j2 = Journee(date=autre, pay_n=2, source="app")
j2.tarifs = store.tarifs_courants(conn)
store.ecrire_jour(conn, j2)
store.marquer_exporte(conn, [autre])
verifier("clôturée par l'export", store.est_cloture(conn, autre))
verifier("plus en attente", autre not in store.jours_a_exporter(conn))

print("\n13. Comptes")
verifier("nb_rectifications", store.nb_rectifications(conn) == 4,
         f"({store.nb_rectifications(conn)})")
verifier("dates_rectifiees", store.dates_rectifiees(conn) == [d])
ecarts = store.ecarts_rectifications(conn)
verifier("une seule journée en écart", list(ecarts) == [d.isoformat()])

print(f"\n{'=' * 50}\n{ok} réussis, {ko} échecs\n{'=' * 50}")
conn.close()
sys.exit(1 if ko else 0)
