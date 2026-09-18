"""Point d'entrée du logiciel : démarre le serveur et ouvre sa fenêtre.

Streamlit est un framework web : son interface est une page servie en local, et
il n'y a pas moyen de la dessiner autrement. Mais rien n'oblige à la montrer dans
un navigateur ordinaire — on ouvre donc Edge (ou Chrome) en **mode application**,
c'est-à-dire une fenêtre sans barre d'adresse, sans onglets et sans favoris, qui
porte son propre bouton dans la barre des tâches. Fermer cette fenêtre arrête le
serveur : le logiciel se quitte comme n'importe quel autre.

Tout reste sur la machine. Le serveur n'écoute que `localhost`.

Deux dossiers à ne pas confondre :

- **le code** est déplié par PyInstaller dans un dossier temporaire (`_MEIPASS`),
  effacé à la fermeture. C'est de là qu'on exécute ;
- **le registre** (`data/`, `sauvegardes/`) vit à côté de l'exe, sinon il
  disparaîtrait avec le temporaire. C'est `compta/config.py` qui s'en charge.

Hors exe, `python lancer.py` fait exactement la même chose depuis les sources.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

TITRE = "Registre du cabinet"


def racine_code() -> Path:
    """Le dossier d'où exécuter l'app : le temporaire en exe, les sources sinon."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # noqa: SLF001 — posé par PyInstaller
    return Path(__file__).resolve().parent


# --- la fenêtre ---------------------------------------------------------------

def _navigateur() -> Path | None:
    """Edge ou Chrome, les seuls à savoir ouvrir une fenêtre sans habillage."""
    dossiers = [os.environ.get("ProgramFiles", ""),
                os.environ.get("ProgramFiles(x86)", "")]
    for relatif in (r"Microsoft\Edge\Application\msedge.exe",
                    r"Google\Chrome\Application\chrome.exe"):
        for dossier in dossiers:
            if dossier and (chemin := Path(dossier) / relatif).is_file():
                return chemin
    return None


def _ouvrir_fenetre(url: str) -> subprocess.Popen | None:
    """Ouvre l'app en fenêtre d'application. Retourne le processus à surveiller.

    Le `--user-data-dir` dédié n'est pas un détail : sans lui, Edge confie
    l'ouverture à l'instance déjà lancée et rend la main aussitôt. On perdrait le
    seul signal qui dit que l'utilisateur a fermé le logiciel.
    """
    exe = _navigateur()
    if exe is None:
        # ni Edge ni Chrome : le navigateur par défaut fera l'affaire, mais on
        # ne saura pas quand il se ferme, et le serveur devra être arrêté à la main
        webbrowser.open(url)
        return None

    profil = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    profil = profil / "RegistreCabinet" / "fenetre"
    profil.mkdir(parents=True, exist_ok=True)

    return subprocess.Popen([
        str(exe),
        f"--app={url}",
        f"--user-data-dir={profil}",
        "--window-size=1500,950",
        "--no-first-run",
        "--no-default-browser-check",
    ])


def _serveur_repond(url: str, delai: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/_stcore/health", timeout=delai) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _arreter() -> None:
    """Arrêt propre : le gestionnaire posé par Streamlit ferme le serveur.

    `raise_signal` fait exécuter le gestionnaire par le thread principal, qui
    tourne dans la boucle asyncio — c'est exactement ce qui se passe sur Ctrl+C.
    Si l'arrêt traîne, on tranche : mieux vaut un processus fermé qu'un serveur
    fantôme qui garde le port.
    """
    try:
        signal.raise_signal(signal.SIGINT)
    except Exception:  # noqa: BLE001
        os._exit(0)  # noqa: SLF001
    time.sleep(10)
    os._exit(0)  # noqa: SLF001


def _accompagner(url: str) -> None:
    """Attend que le serveur soit prêt, ouvre la fenêtre, puis suit sa vie."""
    for _ in range(120):          # deux minutes de patience, largement de quoi
        if _serveur_repond(url):
            break
        time.sleep(1)
    else:
        return

    fenetre = _ouvrir_fenetre(url)
    if fenetre is None:
        return
    fenetre.wait()
    _arreter()


# --- démarrage ----------------------------------------------------------------

def _signaler(message: str) -> None:
    """Dit ce qui ne va pas, même sans console — l'exe n'en a pas."""
    print(message, file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, TITRE, 0x10)
        except Exception:  # noqa: BLE001
            pass


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
        # c'est nous qui ouvrons la fenêtre, pas Streamlit : sans ça un onglet
        # de navigateur s'ouvrirait en plus
        "server_headless": True,
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

    url = f"http://localhost:{config.get_option('server.port')}"

    # déjà lancé : on se contente d'ouvrir une fenêtre sur l'instance en place,
    # plutôt que d'échouer sur un port occupé
    if _serveur_repond(url):
        fenetre = _ouvrir_fenetre(url)
        if fenetre is not None:
            fenetre.wait()
        return

    threading.Thread(target=_accompagner, args=(url,), daemon=True).start()
    bootstrap.run(str(script), False, [], options)


if __name__ == "__main__":
    try:
        main()
    except Exception as err:  # noqa: BLE001
        import traceback

        trace = traceback.format_exc()
        journal = Path(sys.executable if getattr(sys, "frozen", False)
                       else __file__).resolve().parent / "erreur_demarrage.txt"
        try:
            journal.write_text(trace, encoding="utf-8")
        except OSError:
            journal = None
        _signaler(f"Le registre n'a pas pu démarrer.\n\n{err}"
                  + (f"\n\nDétail écrit dans :\n{journal}" if journal else ""))
        raise SystemExit(1) from err
