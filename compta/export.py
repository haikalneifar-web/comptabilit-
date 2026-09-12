"""Export d'un tableau de l'app en CSV, Excel ou PDF.

Trois formats pour trois usages : le CSV se relit partout, le classeur Excel se
retravaille, le PDF se transmet. Les trois portent le même contenu — le titre,
les totaux affichés au-dessus du tableau, puis le tableau lui-même — pour qu'un
document imprimé dise exactement ce que l'écran disait.

Ces exports ne touchent jamais `compta jdid .xlsx` : ce sont des fichiers
nouveaux, produits en mémoire et proposés au téléchargement.
"""

from __future__ import annotations

import datetime as dt
from io import BytesIO, StringIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

# mêmes teintes que les graphiques de l'app
BLEU = colors.HexColor("#2a78d6")
ARDOISE = colors.HexColor("#44515e")
GRIS_CLAIR = colors.HexColor("#f2f4f6")
GRIS_TRAIT = colors.HexColor("#d4dae0")


def _texte(valeur) -> str:
    """Une cellule telle qu'elle se lit : dates à la française, milliers espacés."""
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return ""
    if isinstance(valeur, bool):
        return "oui" if valeur else "non"
    if isinstance(valeur, (dt.date, dt.datetime)):
        return valeur.strftime("%d/%m/%Y")
    if isinstance(valeur, float):
        return f"{valeur:,.0f}".replace(",", " ") if valeur == int(valeur) \
            else f"{valeur:,.2f}".replace(",", " ").replace(".", ",")
    return str(valeur)


def _avec_index(df: pd.DataFrame) -> pd.DataFrame:
    """Ramène l'index dans les colonnes : un export se lit sans index caché."""
    return df.reset_index() if df.index.name else df.copy()


# --- CSV ---------------------------------------------------------------------

def vers_csv(df: pd.DataFrame, totaux: list[tuple[str, str]] | None = None) -> bytes:
    """Séparateur `;` et virgule décimale : Excel francophone l'ouvre directement."""
    sortie = StringIO()
    for libelle, valeur in totaux or []:
        sortie.write(f"{libelle};{valeur}\n")
    if totaux:
        sortie.write("\n")

    donnees = _avec_index(df)
    # les dates s'écrivent comme partout ailleurs dans l'app, pas en ISO
    for colonne in donnees.columns:
        if donnees[colonne].map(lambda v: isinstance(v, (dt.date, dt.datetime))).any():
            donnees[colonne] = donnees[colonne].map(
                lambda v: v.strftime("%d/%m/%Y")
                if isinstance(v, (dt.date, dt.datetime)) else v)
    donnees.to_csv(sortie, sep=";", decimal=",", index=False, float_format="%.2f")
    # BOM : sans lui, Excel affiche les accents de travers
    return sortie.getvalue().encode("utf-8-sig")


# --- Excel -------------------------------------------------------------------

def vers_xlsx(df: pd.DataFrame, titre: str,
              totaux: list[tuple[str, str]] | None = None,
              sous_titre: str = "") -> bytes:
    """Un classeur autonome : titre, totaux, puis le tableau, prêt à retravailler."""
    donnees = _avec_index(df)
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"

    ligne = 1
    ws.cell(row=ligne, column=1, value=titre).font = Font(bold=True, size=14)
    ligne += 1
    if sous_titre:
        ws.cell(row=ligne, column=1, value=sous_titre).font = Font(
            italic=True, color="666666")
        ligne += 1
    ws.cell(row=ligne, column=1, value=f"Édité le {dt.datetime.now():%d/%m/%Y à %H:%M}"
            ).font = Font(italic=True, size=9, color="888888")
    ligne += 2

    for libelle, valeur in totaux or []:
        ws.cell(row=ligne, column=1, value=libelle).font = Font(bold=True)
        ws.cell(row=ligne, column=2, value=valeur)
        ligne += 1
    if totaux:
        ligne += 1

    entete = ligne
    bordure = Border(bottom=Side(style="thin", color="D4DAE0"))
    for j, colonne in enumerate(donnees.columns, start=1):
        cellule = ws.cell(row=entete, column=j, value=str(colonne))
        cellule.font = Font(bold=True, color="FFFFFF")
        cellule.fill = PatternFill("solid", fgColor="2A78D6")
        cellule.alignment = Alignment(horizontal="center", vertical="center",
                                      wrap_text=True)

    for i, (_, enregistrement) in enumerate(donnees.iterrows(), start=entete + 1):
        for j, colonne in enumerate(donnees.columns, start=1):
            valeur = enregistrement[colonne]
            if isinstance(valeur, (dt.date, dt.datetime)):
                cellule = ws.cell(row=i, column=j, value=valeur)
                cellule.number_format = "DD/MM/YYYY"
            elif isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
                cellule = ws.cell(row=i, column=j, value=float(valeur))
                cellule.number_format = "# ##0" if float(valeur) == int(valeur) \
                    else "# ##0.00"
            else:
                cellule = ws.cell(row=i, column=j, value=_texte(valeur))
            cellule.border = bordure
            if (i - entete) % 2 == 0:
                cellule.fill = PatternFill("solid", fgColor="F7F9FA")

    for j, colonne in enumerate(donnees.columns, start=1):
        # `max` sur un tableau vide : la valeur par défaut évite l'exception
        largeur = max((len(_texte(v)) for v in donnees[colonne]),
                      default=0)
        largeur = max(largeur, len(str(colonne))) + 3
        ws.column_dimensions[get_column_letter(j)].width = min(max(largeur, 9), 40)

    ws.freeze_panes = ws.cell(row=entete + 1, column=1)

    tampon = BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


# --- PDF ---------------------------------------------------------------------

def _pied_de_page(canevas, document) -> None:
    canevas.saveState()
    canevas.setFont("Helvetica", 7.5)
    canevas.setFillColor(colors.HexColor("#888888"))
    canevas.drawString(12 * mm, 8 * mm,
                       f"Registre du cabinet · édité le {dt.datetime.now():%d/%m/%Y}")
    canevas.drawRightString(landscape(A4)[0] - 12 * mm, 8 * mm,
                            f"page {document.page}")
    canevas.restoreState()


def vers_pdf(df: pd.DataFrame, titre: str,
             totaux: list[tuple[str, str]] | None = None,
             sous_titre: str = "") -> bytes:
    """Un document à transmettre : paysage, en-tête répété à chaque page."""
    donnees = _avec_index(df)
    tampon = BytesIO()
    document = SimpleDocTemplate(
        tampon, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=14 * mm,
        title=titre, author="Registre du cabinet",
    )

    styles = getSampleStyleSheet()
    style_titre = ParagraphStyle("titre", parent=styles["Title"], fontSize=15,
                                 alignment=0, spaceAfter=2, textColor=ARDOISE)
    style_sous = ParagraphStyle("sous", parent=styles["Normal"], fontSize=9,
                                textColor=colors.HexColor("#666666"), spaceAfter=8)
    style_cellule = ParagraphStyle("cellule", parent=styles["Normal"], fontSize=7,
                                   leading=8.5)

    histoire = [Paragraph(titre, style_titre)]
    if sous_titre:
        histoire.append(Paragraph(sous_titre, style_sous))

    if totaux:
        bloc = Table(
            [[Paragraph(f"<b>{libelle}</b>", style_cellule) for libelle, _ in totaux],
             [Paragraph(valeur, style_cellule) for _, valeur in totaux]],
            colWidths=[document.width / len(totaux)] * len(totaux),
        )
        bloc.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GRIS_CLAIR),
            ("BOX", (0, 0), (-1, -1), 0.5, GRIS_TRAIT),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        histoire += [bloc, Spacer(1, 8)]

    entetes = [Paragraph(f"<b>{c}</b>", ParagraphStyle(
        "entete", parent=style_cellule, textColor=colors.white)) for c in donnees.columns]
    corps = [[Paragraph(_texte(enregistrement[c]), style_cellule)
              for c in donnees.columns]
             for _, enregistrement in donnees.iterrows()]

    largeur = document.width / max(len(donnees.columns), 1)
    tableau = Table([entetes] + corps, colWidths=[largeur] * len(donnees.columns),
                    repeatRows=1)
    tableau.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLEU),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS_CLAIR]),
        ("GRID", (0, 0), (-1, -1), 0.25, GRIS_TRAIT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    histoire.append(tableau)

    document.build(histoire, onFirstPage=_pied_de_page, onLaterPages=_pied_de_page)
    return tampon.getvalue()


FORMATS = {
    "pdf": ("PDF", "application/pdf", vers_pdf),
    "xlsx": ("Excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             vers_xlsx),
    "csv": ("CSV", "text/csv", vers_csv),
}
