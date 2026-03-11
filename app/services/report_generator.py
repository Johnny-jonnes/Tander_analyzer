import os
import re
import html
import logging
import unicodedata
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.enterprise import Enterprise
from app.models.tender import Tender
from app.models.analysis import Analysis
from app.services.scorer import ScorerService

logger = logging.getLogger(__name__)

REPORTS_DIR = os.path.join("downloads", "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


class ReportGeneratorService:
    """Generation de rapports PDF premium NOBILIS X"""

    def __init__(self, db: Session):
        self.db = db
        self.scorer = ScorerService(db)

    def _fix_encoding(self, text: str) -> str:
        if not text:
            return ""
        try:
            fixed = text.encode('latin-1').decode('utf-8')
            if fixed != text: return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        replacements = {
            'Ã©': 'é', 'Ã¨': 'è', 'Ãª': 'ê', 'Ã«': 'ë', 'Ã ': 'à', 'Ã¢': 'â', 'Ã§': 'ç', 'Ã´': 'ô',
            'Ã¹': 'ù', 'Ã»': 'û', 'Ã®': 'î', 'Ã¯': 'ï', 'Ã\x89': 'É', 'Ã\x80': 'À', 'Ã\x94': 'Ô',
            'â\x80\x99': "'", 'â\x80\x93': '-', 'â\x80\x94': '-', 'â\x80\xa6': '...',
            'd\u00e2\u0080\u0099': "d'", 'l\u00e2\u0080\u0099': "l'",
            'd\u00e2': "d'", 'l\u00e2': "l'", 'n\u00e2': "n'",
        }
        for bad, good in replacements.items():
            text = text.replace(bad, good)
        text = re.sub(r'Ã([\u00a0-\u00bf])', lambda m: (chr(ord(m.group(1)) + 64)).encode('latin-1').decode('utf-8', errors='ignore'), text)
        return text

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        text = self._fix_encoding(text)
        text = unicodedata.normalize('NFC', text)
        text = re.sub(r'[^\x00-\x7F\xc0-\xff]+', ' ', text)
        return text.strip()

    def _fmt_gnf(self, amount) -> str:
        """Formate un montant en GNF."""
        if not amount or amount == 0:
            return "Non specifie"
        return f"{amount:,.0f} GNF".replace(",", " ")

    def generate_enterprise_report(self, enterprise_id: int) -> dict:
        enterprise = self.db.query(Enterprise).get(enterprise_id)
        if not enterprise:
            return {"error": "Entreprise non trouvee"}
        scored_analyses = self.scorer.score_all_for_enterprise(enterprise)
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "enterprise": {"id": enterprise.id, "name": enterprise.name, "sector": enterprise.sector, "budget_range": f"{self._fmt_gnf(enterprise.min_budget)} - {self._fmt_gnf(enterprise.max_budget)}", "zones": enterprise.zones, "experience_years": enterprise.experience_years},
            "summary": {"total_tenders_analyzed": len(scored_analyses), "high_match": len([s for s in scored_analyses if s["score"] >= 70]), "medium_match": len([s for s in scored_analyses if 40 <= s["score"] < 70]), "low_match": len([s for s in scored_analyses if s["score"] < 40]), "average_score": round(sum(s["score"] for s in scored_analyses) / len(scored_analyses), 1) if scored_analyses else 0},
            "top_opportunities": [],
        }
        for item in scored_analyses[:20]:
            analysis = self.db.query(Analysis).filter(Analysis.tender_id == item["tender_id"]).first()
            tender = self.db.query(Tender).get(item["tender_id"])
            report["top_opportunities"].append({"tender_id": item["tender_id"], "title": item["tender_title"], "score": item["score"], "score_details": item["details"], "summary": analysis.summary if analysis else None, "sector": tender.sector if tender else None, "budget": tender.estimated_budget if tender else None, "location": tender.location if tender else None, "deadline": tender.deadline.isoformat() if tender and tender.deadline else None, "source_url": tender.source_url if tender else None})
        return report

    def generate_pdf_report(self, enterprise_id: int, recommendations: list[str] | None = None, subscription_plan: str = "ENTRY") -> str | None:
        """Genere un rapport PDF premium. Le contenu varie selon le plan."""
        plan = (subscription_plan or "ENTRY").upper()
        is_elite = plan == "ELITE"
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import cm, mm
            from reportlab.lib.colors import HexColor, white
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
            from reportlab.platypus import (
                BaseDocTemplate, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                HRFlowable, PageBreak, NextPageTemplate, PageTemplate, Frame
            )
            from reportlab.graphics.shapes import Drawing, Rect, String
        except ImportError:
            logger.error("reportlab non installe")
            return None

        enterprise = self.db.query(Enterprise).get(enterprise_id)
        if not enterprise:
            return None

        scored = self.scorer.score_all_for_enterprise(enterprise)
        for item in scored:
            item["tender_title"] = self._clean_text(item["tender_title"])
            analysis = self.db.query(Analysis).filter(Analysis.tender_id == item["tender_id"]).first()
            if analysis:
                item["summary"] = self._clean_text(analysis.summary or "")
            tender = self.db.query(Tender).get(item["tender_id"])
            if tender:
                item["deadline"] = tender.deadline.strftime("%d/%m/%Y") if tender.deadline else "N/A"
                item["budget_display"] = self._fmt_gnf(tender.estimated_budget)
                item["source_url"] = tender.source_url or ""
                item["budget"] = tender.estimated_budget or 0
            else:
                item["deadline"] = "N/A"
                item["budget_display"] = "N/A"
                item["source_url"] = ""
                item["budget"] = 0

        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in enterprise.name)
        filename = f"rapport_{safe_name}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.pdf"
        filepath = os.path.join(REPORTS_DIR, filename)

        # ── PALETTE ──
        NAVY       = HexColor("#0B1D3A")
        DARK_NAVY  = HexColor("#06132A")
        GOLD       = HexColor("#C9A84C")
        BLUE_ACC   = HexColor("#2E86DE")
        GREEN      = HexColor("#27AE60")
        ORANGE     = HexColor("#F39C12")
        RED        = HexColor("#E74C3C")
        DARK_GRAY  = HexColor("#2C3E50")
        MID_GRAY   = HexColor("#636E72")
        LIGHT_GRAY = HexColor("#DFE6E9")
        CARD_BG    = HexColor("#F8F9FA")
        WHITE_CLR  = white

        W, H = A4
        date_str = datetime.utcnow().strftime("%d/%m/%Y")
        ent_name = self._clean_text(enterprise.name)
        ent_sector = self._clean_text(enterprise.sector)

        # ── CALLBACKS ──
        def draw_cover(canvas, doc):
            """Couverture pleine page bleu marine + or."""
            canvas.saveState()
            canvas.setFillColor(DARK_NAVY)
            canvas.rect(0, 0, W, H, fill=1, stroke=0)

            # Lignes decoratives
            canvas.setStrokeColor(GOLD)
            canvas.setLineWidth(0.6)
            canvas.line(30*mm, H - 50*mm, W - 30*mm, H - 50*mm)
            canvas.line(30*mm, 70*mm, W - 30*mm, 70*mm)

            # Logo
            canvas.setFillColor(GOLD)
            canvas.setFont("Helvetica-Bold", 38)
            canvas.drawCentredString(W/2, H - 85*mm, "NOBILIS X")
            canvas.setFillColor(HexColor("#7A8FA6"))
            canvas.setFont("Helvetica", 8)
            canvas.drawCentredString(W/2, H - 94*mm, "SYSTEME EXPERT DE VEILLE & ANALYSE DES MARCHES PUBLICS")

            # Separator
            canvas.setStrokeColor(GOLD)
            canvas.setLineWidth(1.5)
            canvas.line(W/2 - 25*mm, H - 108*mm, W/2 + 25*mm, H - 108*mm)

            # Titre rapport
            canvas.setFillColor(WHITE_CLR)
            canvas.setFont("Helvetica-Bold", 17)
            canvas.drawCentredString(W/2, H - 130*mm, "Rapport d'Intelligence des Marches")
            canvas.setFont("Helvetica", 11)
            canvas.setFillColor(HexColor("#AAB5C0"))
            canvas.drawCentredString(W/2, H - 142*mm, "Analyse Strategique Personnalisee")

            # Nom entreprise
            canvas.setFillColor(GOLD)
            canvas.setFont("Helvetica-Bold", 24)
            canvas.drawCentredString(W/2, H - 175*mm, ent_name)
            canvas.setFillColor(HexColor("#7A8FA6"))
            canvas.setFont("Helvetica", 10)
            canvas.drawCentredString(W/2, H - 188*mm, f"Secteur : {ent_sector}")

            # Date
            canvas.setFillColor(WHITE_CLR)
            canvas.setFont("Helvetica", 9)
            canvas.drawCentredString(W/2, H - 210*mm, f"Genere le {datetime.utcnow().strftime('%d %B %Y')}")

            # Bottom
            canvas.setFillColor(GOLD)
            canvas.setFont("Helvetica", 7.5)
            canvas.drawCentredString(W/2, 52*mm, "Fait en Guinee. Concu pour que les meilleurs gagnent.")
            canvas.setFillColor(HexColor("#556677"))
            canvas.setFont("Helvetica", 6.5)
            canvas.drawCentredString(W/2, 44*mm, f"Document confidentiel - Destine exclusivement a {ent_name}")
            canvas.restoreState()

        def draw_header_footer(canvas, doc):
            """Header + footer sur les pages de contenu."""
            canvas.saveState()
            # ── HEADER ──
            canvas.setFillColor(WHITE_CLR)
            canvas.rect(0, H - 22*mm, W, 22*mm, fill=1, stroke=0)
            # Ligne or sous le header
            canvas.setStrokeColor(GOLD)
            canvas.setLineWidth(1.2)
            canvas.line(0, H - 22*mm, W, H - 22*mm)
            # Logo
            canvas.setFillColor(NAVY)
            canvas.setFont("Helvetica-Bold", 11)
            canvas.drawString(18*mm, H - 14*mm, "NOBILIS X")
            canvas.setFillColor(MID_GRAY)
            canvas.setFont("Helvetica", 6)
            canvas.drawString(18*mm, H - 18.5*mm, "INTELLIGENCE DES MARCHES PUBLICS")
            # Droite
            canvas.setFillColor(MID_GRAY)
            canvas.setFont("Helvetica", 7.5)
            canvas.drawRightString(W - 18*mm, H - 13*mm, f"Rapport du {date_str}")
            canvas.setFont("Helvetica", 7)
            canvas.drawRightString(W - 18*mm, H - 18*mm, f"Page {doc.page}")

            # ── FOOTER ──
            canvas.setStrokeColor(LIGHT_GRAY)
            canvas.setLineWidth(0.4)
            canvas.line(18*mm, 15*mm, W - 18*mm, 15*mm)
            canvas.setFillColor(MID_GRAY)
            canvas.setFont("Helvetica", 6)
            canvas.drawString(18*mm, 10.5*mm, f"NOBILIS X  |  Rapport confidentiel  |  {ent_name}")
            canvas.setFillColor(GOLD)
            canvas.setFont("Helvetica", 6)
            canvas.drawRightString(W - 18*mm, 10.5*mm, "trillionnx@gmail.com  |  +224 627 27 13 97")
            canvas.restoreState()

        # ── DOCUMENT AVEC 2 TEMPLATES ──
        # Template couverture : frame vide (tout dessine par le callback)
        cover_frame = Frame(0, 0, W, H, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='cover')
        cover_template = PageTemplate(id='cover', frames=[cover_frame], onPage=draw_cover)

        # Template contenu : frame avec marges normales
        content_frame = Frame(18*mm, 22*mm, W - 36*mm, H - 50*mm, id='content')
        content_template = PageTemplate(id='content', frames=[content_frame], onPage=draw_header_footer)

        doc = BaseDocTemplate(filepath, pagesize=A4)
        doc.addPageTemplates([cover_template, content_template])

        # ── STYLES ──
        styles = getSampleStyleSheet()
        S = {}
        S['section_label'] = ParagraphStyle('NX_SL', fontName='Helvetica-Bold', fontSize=8, textColor=GOLD, spaceBefore=0, spaceAfter=2, leading=10)
        S['section_title'] = ParagraphStyle('NX_ST', fontName='Helvetica-Bold', fontSize=14, textColor=NAVY, spaceBefore=4, spaceAfter=6, leading=17)
        S['body'] = ParagraphStyle('NX_Body', fontName='Helvetica', fontSize=9, textColor=DARK_GRAY, spaceAfter=4, leading=13)
        S['small'] = ParagraphStyle('NX_Small', fontName='Helvetica', fontSize=7, textColor=MID_GRAY, spaceAfter=2, leading=9)

        # ── ELEMENTS ──
        elements = []

        # Page 1 : couverture (spacer invisible + passage au template contenu)
        elements.append(Spacer(1, 10))  # Besoin d'un flowable minimal pour la page
        elements.append(NextPageTemplate('content'))
        elements.append(PageBreak())

        # ══════════════════════════════════════════════════════════════
        # PAGE 2+ : SOMMAIRE EXECUTIF
        # ══════════════════════════════════════════════════════════════
        total = len(scored)
        high = len([s for s in scored if s["score"] >= 70])
        medium = len([s for s in scored if 40 <= s["score"] < 70])
        low = len([s for s in scored if s["score"] < 40])
        avg = round(sum(s["score"] for s in scored) / total, 1) if total else 0

        elements.append(Paragraph("SOMMAIRE EXECUTIF", S['section_label']))
        elements.append(Paragraph("Vue d'ensemble de l'analyse", S['section_title']))
        elements.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=14))

        # KPI — 4 cartes métriques
        avg_color = "#27AE60" if avg >= 70 else "#F39C12" if avg >= 40 else "#E74C3C"
        kpi_row1 = [
            Paragraph(f'<font size="20"><b>{total}</b></font>', ParagraphStyle('K1', alignment=TA_CENTER, textColor=NAVY)),
            Paragraph(f'<font size="20" color="#27AE60"><b>{high}</b></font>', ParagraphStyle('K2', alignment=TA_CENTER)),
            Paragraph(f'<font size="20" color="#F39C12"><b>{medium}</b></font>', ParagraphStyle('K3', alignment=TA_CENTER)),
            Paragraph(f'<font size="20" color="{avg_color}"><b>{avg}%</b></font>', ParagraphStyle('K4', alignment=TA_CENTER)),
        ]
        kpi_row2 = [
            Paragraph("Appels analyses", ParagraphStyle('KL1', fontSize=7, textColor=MID_GRAY, alignment=TA_CENTER)),
            Paragraph("Indice >= 70", ParagraphStyle('KL2', fontSize=7, textColor=MID_GRAY, alignment=TA_CENTER)),
            Paragraph("Indice 40-69", ParagraphStyle('KL3', fontSize=7, textColor=MID_GRAY, alignment=TA_CENTER)),
            Paragraph("Indice moyen", ParagraphStyle('KL4', fontSize=7, textColor=MID_GRAY, alignment=TA_CENTER)),
        ]
        kpi = Table([kpi_row1, kpi_row2], colWidths=[3.8*cm]*4)
        kpi.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BACKGROUND', (0,0), (-1,-1), CARD_BG),
            ('GRID', (0,0), (-1,-1), 0.3, LIGHT_GRAY),
            ('TOPPADDING', (0,0), (-1,0), 14),
            ('BOTTOMPADDING', (0,0), (-1,0), 6),
            ('TOPPADDING', (0,1), (-1,1), 2),
            ('BOTTOMPADDING', (0,1), (-1,1), 10),
        ]))
        elements.append(kpi)
        elements.append(Spacer(1, 7*mm))

        # ══════════════════════════════════════════════════════════════
        # PROFIL ENTREPRISE
        # ══════════════════════════════════════════════════════════════
        elements.append(Paragraph("PROFIL CLIENT", S['section_label']))
        elements.append(Paragraph("Informations de l'entreprise", S['section_title']))
        elements.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=10))

        budget_str = f"{self._fmt_gnf(enterprise.min_budget)} - {self._fmt_gnf(enterprise.max_budget)}"
        pdata = [
            ["NOM", self._clean_text(enterprise.name)],
            ["SECTEUR", self._clean_text(enterprise.sector)],
            ["BUDGET", budget_str],
            ["ZONES", self._clean_text(enterprise.zones or "Non precisees")],
            ["EXPERIENCE", f"{enterprise.experience_years} ans"],
            ["CAPACITES", self._clean_text((enterprise.technical_capacity or "Non precisees")[:200])],
        ]
        pt = Table(pdata, colWidths=[3.2*cm, 12.5*cm])
        pt.setStyle(TableStyle([
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('TEXTCOLOR', (0,0), (0,-1), NAVY),
            ('TEXTCOLOR', (1,0), (1,-1), DARK_GRAY),
            ('BACKGROUND', (0,0), (0,-1), CARD_BG),
            ('LINEBELOW', (0,0), (-1,-2), 0.3, LIGHT_GRAY),
            ('TOPPADDING', (0,0), (-1,-1), 7),
            ('BOTTOMPADDING', (0,0), (-1,-1), 7),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        elements.append(pt)
        elements.append(Spacer(1, 7*mm))

        # ══════════════════════════════════════════════════════════════
        # TOP OPPORTUNITES
        # ══════════════════════════════════════════════════════════════
        elements.append(Paragraph("OPPORTUNITES STRATEGIQUES", S['section_label']))
        elements.append(Paragraph("Top 10 des appels d'offres", S['section_title']))
        elements.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=10))

        if scored:
            tdata = [["#", "Appel d'offres", "Indice", "Niveau", "Budget", "Deadline"]]
            for i, item in enumerate(scored[:10], 1):
                s = item["score"]
                niveau = "Excellent" if s >= 70 else "Moyen" if s >= 40 else "Faible"
                tdata.append([
                    str(i),
                    item["tender_title"][:48],
                    f"{s:.0f}",
                    niveau,
                    item.get("budget_display", "N/A"),
                    item.get("deadline", "N/A"),
                ])
            ot = Table(tdata, colWidths=[0.7*cm, 6.8*cm, 1.2*cm, 1.8*cm, 3.2*cm, 1.8*cm])
            ts = [
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 7),
                ('FONTSIZE', (0,1), (-1,-1), 7.5),
                ('BACKGROUND', (0,0), (-1,0), NAVY),
                ('TEXTCOLOR', (0,0), (-1,0), GOLD),
                ('ALIGN', (0,0), (0,-1), 'CENTER'),
                ('ALIGN', (2,0), (5,-1), 'CENTER'),
                ('LINEBELOW', (0,1), (-1,-2), 0.3, LIGHT_GRAY),
                ('TOPPADDING', (0,0), (-1,0), 7),
                ('BOTTOMPADDING', (0,0), (-1,0), 7),
                ('TOPPADDING', (0,1), (-1,-1), 5),
                ('BOTTOMPADDING', (0,1), (-1,-1), 5),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 4),
            ]
            for i, item in enumerate(scored[:10], 1):
                s = item["score"]
                if s >= 70:
                    sc_color = GREEN
                elif s >= 40:
                    sc_color = ORANGE
                else:
                    sc_color = RED
                row_bg = HexColor("#F8F9FA") if i % 2 == 0 else WHITE_CLR
                ts.extend([
                    ('BACKGROUND', (0,i), (-1,i), row_bg),
                    ('TEXTCOLOR', (2,i), (2,i), sc_color),
                    ('FONTNAME', (2,i), (2,i), 'Helvetica-Bold'),
                    ('FONTSIZE', (2,i), (2,i), 9),
                    ('TEXTCOLOR', (3,i), (3,i), sc_color),
                    ('FONTNAME', (3,i), (3,i), 'Helvetica-Bold'),
                ])
            ot.setStyle(TableStyle(ts))
            elements.append(ot)
        else:
            elements.append(Paragraph("Aucune opportunite correspondante.", S['body']))

        # ══════════════════════════════════════════════════════════════
        # ANALYSE DETAILLEE (meilleure opportunite)
        # ══════════════════════════════════════════════════════════════
        if scored:
            elements.append(PageBreak())
            elements.append(Paragraph("ANALYSE APPROFONDIE", S['section_label']))
            elements.append(Paragraph("Votre meilleure opportunite", S['section_title']))
            elements.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=10))

            best = scored[0]
            details = best.get("details", {})
            sc = best["score"]
            sc_hex = "#27AE60" if sc >= 70 else "#F39C12" if sc >= 40 else "#E74C3C"

            # Titre
            clean_title = self._clean_text(best["tender_title"])
            elements.append(Paragraph(
                f'<b>"{clean_title[:200]}"</b>',
                ParagraphStyle('BT', fontName='Helvetica-Bold', fontSize=10, textColor=NAVY, spaceAfter=10, leading=14)
            ))

            # Score badge
            score_data = [
                [Paragraph(f'<font size="26" color="{sc_hex}"><b>{sc:.0f}</b></font>', ParagraphStyle('SV', alignment=TA_CENTER))],
                [Paragraph('<font size="7" color="#636E72">INDICE DE CREDIBILITE / 100</font>', ParagraphStyle('SL', alignment=TA_CENTER))],
            ]
            score_tbl = Table(score_data, colWidths=[5*cm])
            score_tbl.setStyle(TableStyle([
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('BACKGROUND', (0,0), (-1,-1), CARD_BG),
                ('BOX', (0,0), (-1,-1), 1, HexColor(sc_hex)),
                ('TOPPADDING', (0,0), (0,0), 14),
                ('BOTTOMPADDING', (0,-1), (0,-1), 10),
            ]))
            elements.append(score_tbl)
            elements.append(Spacer(1, 5*mm))

            # Barres de progression
            elements.append(Paragraph("Decomposition de l'Indice", ParagraphStyle('DI', fontName='Helvetica-Bold', fontSize=9, textColor=NAVY, spaceAfter=8)))

            criteria = [
                ("Secteur (35%)", details.get("sector", 0)),
                ("Budget (30%)", details.get("budget", 0)),
                ("Zone (20%)", details.get("location", 0)),
                ("Experience (15%)", details.get("experience", 0)),
            ]
            for label, value in criteria:
                val_hex = "#27AE60" if value >= 70 else "#F39C12" if value >= 40 else "#E74C3C"
                d = Drawing(420, 24)
                d.add(String(0, 15, label, fontName="Helvetica-Bold", fontSize=7.5, fillColor=DARK_GRAY))
                d.add(String(390, 15, f"{value:.0f}%", fontName="Helvetica-Bold", fontSize=7.5, fillColor=HexColor(val_hex)))
                # Fond
                d.add(Rect(0, 2, 380, 8, fillColor=LIGHT_GRAY, strokeColor=None, rx=4, ry=4))
                # Barre remplie
                bar_w = max(6, 380 * value / 100)
                d.add(Rect(0, 2, bar_w, 8, fillColor=HexColor(val_hex), strokeColor=None, rx=4, ry=4))
                elements.append(d)

            # Resume
            summary = best.get("summary", "")
            if summary:
                elements.append(Spacer(1, 5*mm))
                elements.append(Paragraph("RESUME STRATEGIQUE", S['section_label']))
                sum_tbl = Table(
                    [[Paragraph(summary[:1500], ParagraphStyle('SumC', fontName='Helvetica', fontSize=8.5, textColor=DARK_GRAY, leading=13))]],
                    colWidths=[15.5*cm]
                )
                sum_tbl.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), CARD_BG),
                    ('BOX', (0,0), (-1,-1), 0.4, LIGHT_GRAY),
                    ('TOPPADDING', (0,0), (-1,-1), 12),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 12),
                    ('LEFTPADDING', (0,0), (-1,-1), 12),
                    ('RIGHTPADDING', (0,0), (-1,-1), 12),
                ]))
                elements.append(sum_tbl)

        # ══════════════════════════════════════════════════════════════
        # RECOMMANDATIONS
        # ══════════════════════════════════════════════════════════════
        if recommendations:
            elements.append(Spacer(1, 8*mm))
            elements.append(Paragraph("RECOMMANDATIONS STRATEGIQUES", S['section_label']))
            elements.append(Paragraph("Actions prioritaires", S['section_title']))
            elements.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=10))

            for i, reco in enumerate(recommendations, 1):
                clean_reco = self._clean_text(reco)
                reco_tbl = Table(
                    [[
                        Paragraph(f'<font color="#C9A84C" size="12"><b>{i}</b></font>', ParagraphStyle('RN', alignment=TA_CENTER)),
                        Paragraph(clean_reco, ParagraphStyle(f'RT{i}', fontName='Helvetica', fontSize=8.5, textColor=DARK_GRAY, leading=13)),
                    ]],
                    colWidths=[1.2*cm, 14.5*cm]
                )
                reco_tbl.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), CARD_BG),
                    ('BOX', (0,0), (-1,-1), 0.3, LIGHT_GRAY),
                    ('LINEAFTER', (0,0), (0,-1), 1.5, GOLD),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('TOPPADDING', (0,0), (-1,-1), 8),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                    ('LEFTPADDING', (0,0), (0,-1), 6),
                ]))
                elements.append(reco_tbl)
                elements.append(Spacer(1, 2*mm))

        # ── Upsell ENTRY → ELITE ──
        if not is_elite:
            elements.append(Spacer(1, 6*mm))
            upsell_data = [[
                Paragraph(
                    '<font color="#C9A84C" size="9"><b>PASSEZ A NOBILIS ELITE</b></font><br/>'
                    '<font color="#636E72" size="8">'
                    'Debloquez les recommandations strategiques detaillees, '
                    'l\'alerte temps reel et la couverture des 20 secteurs. '
                    'Contactez-nous : +224 627 27 13 97 ou trillionnx@gmail.com'
                    '</font>',
                    ParagraphStyle('Upsell', leading=13)
                )
            ]]
            upsell_tbl = Table(upsell_data, colWidths=[15.7*cm])
            upsell_tbl.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), HexColor("#FFF8E1")),
                ('BOX', (0,0), (-1,-1), 1, GOLD),
                ('TOPPADDING', (0,0), (-1,-1), 14),
                ('BOTTOMPADDING', (0,0), (-1,-1), 14),
                ('LEFTPADDING', (0,0), (-1,-1), 14),
                ('RIGHTPADDING', (0,0), (-1,-1), 14),
            ]))
            elements.append(upsell_tbl)

        # ── Footer final ──
        elements.append(Spacer(1, 10*mm))
        elements.append(HRFlowable(width="100%", thickness=0.8, color=GOLD, spaceAfter=6))
        elements.append(Paragraph(
            f"NOBILIS X  |  trillionnx@gmail.com  |  +224 627 27 13 97  |  Paiement Orange Money : +224 627 27 13 97",
            S['small']
        ))
        elements.append(Paragraph(
            f"Ce rapport est strictement confidentiel et destine exclusivement a {ent_name}.",
            S['small']
        ))

        # BUILD
        doc.build(elements)
        logger.info(f"PDF premium genere: {filepath}")
        return filepath