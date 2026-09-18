# -*- mode: python ; coding: utf-8 -*-
"""Recette PyInstaller : l'app entière dans un seul `Registre du cabinet.exe`.

    pyinstaller registre.spec --noconfirm

Le résultat est dans `dist/`. L'exe se pose où l'on veut : il crée `data/` et
`sauvegardes/` à côté de lui, et va lire le classeur là où `COMPTA_XLSX` — ou
`compta/config.py` — le désigne.

Trois choses que PyInstaller ne devine pas seul :

- **les métadonnées** : Streamlit lit sa propre version par `importlib.metadata`,
  et s'arrête net si le paquet n'a pas de dossier `.dist-info` embarqué ;
- **les fichiers statiques** de Streamlit (le front compilé) et d'Altair (les
  schémas Vega), qui ne sont pas du code et échappent donc à l'analyse ;
- **les sources de l'app**, qu'il faut embarquer telles quelles : Streamlit
  exécute `streamlit_app.py` en le lisant sur le disque, pas en l'important.
"""

from PyInstaller.utils.hooks import collect_all, copy_metadata

datas, binaries, hiddenimports = [], [], []

for paquet in ("streamlit", "altair", "reportlab", "openpyxl", "pandas"):
    d, b, h = collect_all(paquet)
    datas += d
    binaries += b
    hiddenimports += h

for paquet in ("streamlit", "altair", "pandas", "numpy", "openpyxl", "reportlab",
               "pyarrow", "tornado", "watchdog"):
    try:
        datas += copy_metadata(paquet)
    except Exception:       # noqa: BLE001 — paquet absent, tant pis pour lui
        pass

# les sources, déposées à la racine du bundle : `lancer.py` s'y place avant de
# rendre la main à Streamlit
datas += [
    ("streamlit_app.py", "."),
    ("app_utils.py", "."),
    ("compta", "compta"),
    ("app_pages", "app_pages"),
    (".streamlit", ".streamlit"),
]

a = Analysis(
    ["lancer.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # le registre de travail n'a pas besoin d'une trousse de développement
    excludes=["tkinter", "pytest", "PyInstaller", "IPython", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Registre du cabinet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # une fenêtre de console reste ouverte derrière le navigateur : c'est elle
    # qui porte les messages du serveur, et la fermer arrête l'app proprement
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
