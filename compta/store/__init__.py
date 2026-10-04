"""Registre SQLite : source de travail de l'app.

Le classeur Excel reste le document de référence pour le comptable ; cette base
est le carnet dans lequel on saisit, corrige et consulte avant d'écrire dans le
classeur. Chaque journée modifiée est marquée « à exporter ».

Deux registres, un seul jeu de données :

* le **registre réel** — la table `jours` — porte les valeurs d'origine, telles
  qu'importées du classeur ou saisies au fil de la journée. Une journée
  *clôturée* n'y est plus modifiable ;
* le **registre corrigé** — `jours` + la table `rectifications` — est ce que le
  registre aurait dû dire. Chaque écart entre les deux est une ligne motivée et
  horodatée, jamais un écrasement.

On ne supprime pas une rectification : on en passe une autre qui revient à la
valeur précédente. La valeur en vigueur pour un champ est donc simplement la
dernière rectification enregistrée.

Le paquet se découpe par sujet ; `from compta import store` et les appels
`store.xxx` restent ceux d'avant :

* `base` — schéma SQLite, réglages (`meta`), tarifs ;
* `journees` — le registre réel : lecture, écriture, clôture, export ;
* `rectifications` — le journal des rectifications et le registre corrigé ;
* `actes` — la saisie patient par patient ;
* `agregats` — totaux mensuels et annuels, journal, mois à saisir ;
* `bordereaux` — bordereaux mensuels et ce qui part chez le comptable.
"""

from __future__ import annotations

import sqlite3

from ..config import DB_PATH
from .actes import *  # noqa: F401,F403
from .agregats import *  # noqa: F401,F403
from .base import *  # noqa: F401,F403
from .bordereaux import *  # noqa: F401,F403
from .journees import *  # noqa: F401,F403
from .rectifications import *  # noqa: F401,F403


# `connect` vit ici : les tests (et l'exe) réaffectent `store.DB_PATH`, que cette
# fonction doit relire à chaque appel.
def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

