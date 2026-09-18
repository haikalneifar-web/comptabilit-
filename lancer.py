"""Point d'entrée de l'exe : démarre le serveur Streamlit et ouvre le navigateur.

`streamlit run` n'existe pas dans un exe — il n'y a pas de ligne de commande.
On appelle donc directement le bootstrap de Streamlit, qui fait le même travail :
il démarre le serveur, exécute le script de l'app et ouvre le navigateur.

Deux dossiers à ne pas confondre :

- **le code** est déplié par PyInstaller dans un dossier temporaire (`_MEIPASS`),
  effacé à la fermeture. C'est de là qu'on exécute ;
- **le registre** (`data/`, `sauvegardes/`) vit à côté de l'exe, sinon il
  disparaîtrait avec le temporaire. C'est `compta/config.py` qui s'en charge.

Hors exe, `python lancer.py` fait exactement la même chose depuis les sources.
"""

from __future__ import annotations

import sys
from pathlib import Path


def racine_code() -> Path:
    """Le dossier d'où exécuter l'app : le temporaire en exe, les sources sinon."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # noqa: SLF001 — posé par PyInstaller
    return Path(__file__).resolve().parent


def main() -> None:
    racine = racine_code()
    sys.path.insert(0, str(racine))
    script = racine / "streamlit_app.py"

    from streamlit import config
    from streamlit.web import bootstrap

    options = {
        # Streamlit se croit en développement dès que son propre fichier n'est
        # pas sous `site-packages` — ce qui est le cas une fois déplié dans le
        # temporaire de l'exe. Il sert alors le front depuis le port 3000 d'un
        # serveur de développement qui n'existe pas, et l'app répond 404.
        "global_developmentMode": False,
        # lancé d'un double-clic : le navigateur doit s'ouvrir tout seul,
        # alors que le config.toml du projet demande le mode silencieux
        "server_headless": False,
        # le code est figé dans l'exe : rien à surveiller, et le veilleur de
        # fichiers irait fouiller un dossier temporaire pour rien
        "server_fileWatcherType": "none",
    }

    # Ces deux gestes sont ceux que `streamlit run` fait avant de démarrer, et
    # ils comptent : sans le premier, Streamlit cherche `.streamlit/config.toml`
    # ailleurs qu'à côté du script ; sans le second, les options ci-dessus sont
    # purement ignorées — `bootstrap.run` ne les lit que pour les surveiller.
    config._main_script_path = str(script)  # noqa: SLF001 — comme la CLI
    bootstrap.load_config_options(flag_options=options)

    bootstrap.run(str(script), False, [], options)


if __name__ == "__main__":
    main()
