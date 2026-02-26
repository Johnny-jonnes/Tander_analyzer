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
    """Generation de rapports PDF professionnels"""

    def __init__(self, db: Session):
        self.db = db
        self.scorer = ScorerService(db)

    def _fix_encoding(self, text: str) -> str:
        """Corrige le double-encodage UTF-8 (copie de email_service)."""
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
        """Nettoie le texte pour le PDF."""
        if not text:
            return ""
        text = self._fix_encoding(text)
        text = unicodedata.normalize('NFC', text)
        # Supprimer emojis pour reportlab (peut causer des erreurs de police)
        text = re.sub(r'[^\x00-\x7F\xc0-\xff]+', ' ', text)
        return text.strip()

    def generate_enterprise_report(self, enterprise_id: int) -> dict:
        """Genere un rapport structure (dict) pour compatibilite API."""
        enterprise = self.db.query(Enterprise).get(enterprise_id)
        if not enterprise:
            return {"error": "Entreprise non trouvee"}
        scored_analyses = self.scorer.score_all_for_enterprise(enterprise)
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "enterprise": {"id": enterprise.id, "name": enterprise.name, "sector": enterprise.sector, "budget_range": f"{enterprise.min_budget} - {enterprise.max_budget} USD", "zones": enterprise.zones, "experience_years": enterprise.experience_years},
            "summary": {"total_tenders_analyzed": len(scored_analyses), "high_match": len([s for s in scored_analyses if s["score"] >= 70]), "medium_match": len([s for s in scored_analyses if 40 <= s["score"] < 70]), "low_match": len([s for s in scored_analyses if s["score"] < 40]), "average_score": round(sum(s["score"] for s in scored_analyses) / len(scored_analyses), 1) if scored_analyses else 0},
            "top_opportunities": [],
        }
        for item in scored_analyses[:20]:
            analysis = self.db.query(Analysis).filter(Analysis.tender_id == item["tender_id"]).first()
            tender = self.db.query(Tender).get(item["tender_id"])
            report["top_opportunities"].append({"tender_id": item["tender_id"], "title": item["tender_title"], "score": item["score"], "score_details": item["details"], "summary": analysis.summary if analysis else None, "sector": tender.sector if tender else None, "budget": tender.estimated_budget if tender else None, "location": tender.location if tender else None, "deadline": tender.deadline.isoformat() if tender and tender.deadline else None, "source_url": tender.source_url if tender else None})
        logger.info(f"Rapport genere pour {enterprise.name}: {len(scored_analyses)} tenders")
        return report

    def generate_pdf_report(self, enterprise_id: int, recommendations: list[str] | None = None) -> str | None:
        """Genere un PDF reel et retourne le chemin du fichier."""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import cm
            from reportlab.lib.colors import HexColor, white
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.enums import TA_CENTER
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
            from reportlab.graphics.shapes import Drawing, Rect, String
        except ImportError:
            logger.error("reportlab non installe. pip install reportlab")
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
                item["budget_display"] = f"{tender.estimated_budget:,.0f} USD" if tender.estimated_budget else "N/A"
                item["source_url"] = tender.source_url or ""
            else:
                item["deadline"] = "N/A"
                item["budget_display"] = "N/A"
                item["source_url"] = ""

        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in enterprise.name)
        filename = f"rapport_{safe_name}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.pdf"
        filepath = os.path.join(REPORTS_DIR, filename)

        PRIMARY = HexColor("#2c3e50")
        BLUE = HexColor("#3498db")
        GREEN = HexColor("#27ae60")
        ORANGE = HexColor("#f39c12")
        RED = HexColor("#e74c3c")
        LIGHT_BG = HexColor("#f0f4f8")
        WHITE = white

        doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle('Title_C', parent=styles['Title'], fontSize=24, textColor=PRIMARY, spaceAfter=6, fontName='Helvetica-Bold'))
        styles.add(ParagraphStyle('Sub_C', parent=styles['Normal'], fontSize=12, textColor=BLUE, spaceAfter=12, alignment=TA_CENTER))
        styles.add(ParagraphStyle('Section', parent=styles['Heading2'], fontSize=14, textColor=PRIMARY, spaceBefore=16, spaceAfter=8, fontName='Helvetica-Bold'))
        styles.add(ParagraphStyle('Body', parent=styles['Normal'], fontSize=10, textColor=HexColor("#333"), spaceAfter=4, leading=14))
        styles.add(ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, textColor=HexColor("#888"), spaceAfter=2))

        elements = []

        # Page de garde
        elements.append(Spacer(1, 3*cm))
        elements.append(Paragraph("TENDER ANALYZER", styles['Title_C']))
        elements.append(Paragraph("Rapport d'analyse personnalise", styles['Sub_C']))
        elements.append(Spacer(1, 1*cm))
        elements.append(HRFlowable(width="80%", thickness=2, color=BLUE, spaceAfter=20, spaceBefore=10))
        elements.append(Paragraph(f"<b>{enterprise.name}</b>", ParagraphStyle('EN', parent=styles['Title'], fontSize=18, textColor=PRIMARY)))
        elements.append(Paragraph(f"Secteur : {enterprise.sector}", styles['Sub_C']))
        elements.append(Spacer(1, 2*cm))

        total = len(scored)
        high = len([s for s in scored if s["score"] >= 70])
        medium = len([s for s in scored if 40 <= s["score"] < 70])
        low = len([s for s in scored if s["score"] < 40])
        avg = round(sum(s["score"] for s in scored) / total, 1) if total else 0

        stats = [["Appels analyses", "Score >= 70%", "Score 40-69%", "Score < 40%", "Moyenne"], [str(total), str(high), str(medium), str(low), f"{avg}%"]]
        st = Table(stats, colWidths=[3*cm]*5)
        st.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('FONTSIZE', (0,0), (-1,0), 9), ('FONTSIZE', (0,1), (-1,1), 14), ('TEXTCOLOR', (0,0), (-1,0), PRIMARY), ('TEXTCOLOR', (1,1), (1,1), GREEN), ('TEXTCOLOR', (2,1), (2,1), ORANGE), ('TEXTCOLOR', (3,1), (3,1), RED), ('TEXTCOLOR', (4,1), (4,1), BLUE), ('BACKGROUND', (0,0), (-1,0), LIGHT_BG), ('GRID', (0,0), (-1,-1), 0.5, HexColor("#ddd")), ('TOPPADDING', (0,0), (-1,-1), 8), ('BOTTOMPADDING', (0,0), (-1,-1), 8)]))
        elements.append(st)
        elements.append(Spacer(1, 1*cm))
        elements.append(Paragraph(f"Genere le {datetime.utcnow().strftime('%d/%m/%Y a %H:%M UTC')}", ParagraphStyle('D', parent=styles['Normal'], fontSize=10, textColor=HexColor("#999"), alignment=TA_CENTER)))

        # Profil
        elements.append(Spacer(1, 1*cm))
        elements.append(Paragraph("Profil de l'entreprise", styles['Section']))
        elements.append(HRFlowable(width="100%", thickness=1, color=BLUE, spaceAfter=10))
        pdata = [["Nom", enterprise.name], ["Secteur", enterprise.sector], ["Budget", f"{enterprise.min_budget:,.0f} - {enterprise.max_budget:,.0f} USD"], ["Zones", enterprise.zones or "Non precisees"], ["Experience", f"{enterprise.experience_years} ans"], ["Capacites", (enterprise.technical_capacity or "Non precisees")[:150]]]
        pt = Table(pdata, colWidths=[4*cm, 12*cm])
        pt.setStyle(TableStyle([('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'), ('FONTSIZE', (0,0), (-1,-1), 10), ('TEXTCOLOR', (0,0), (0,-1), PRIMARY), ('BACKGROUND', (0,0), (0,-1), LIGHT_BG), ('GRID', (0,0), (-1,-1), 0.5, HexColor("#ddd")), ('TOPPADDING', (0,0), (-1,-1), 6), ('BOTTOMPADDING', (0,0), (-1,-1), 6), ('LEFTPADDING', (0,0), (-1,-1), 8), ('VALIGN', (0,0), (-1,-1), 'TOP')]))
        elements.append(pt)

        # Tableau top 10
        elements.append(Spacer(1, 1*cm))
        elements.append(Paragraph("Top 10 des opportunites", styles['Section']))
        elements.append(HRFlowable(width="100%", thickness=1, color=BLUE, spaceAfter=10))
        if scored:
            tdata = [["#", "Appel d'offres", "Score", "Niveau", "Budget", "Deadline"]]
            for i, item in enumerate(scored[:10], 1):
                s = item["score"]
                niveau = "Excellent" if s >= 70 else "Moyen" if s >= 40 else "Faible"
                tdata.append([
                    str(i),
                    item["tender_title"][:45],
                    f"{s:.0f}%",
                    niveau,
                    item.get("budget_display", "N/A"),
                    item.get("deadline", "N/A")
                ])
            ot = Table(tdata, colWidths=[0.8*cm, 6*cm, 2*cm, 2.2*cm, 3*cm, 2*cm])
            ts = [
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,-1), 9),
                ('BACKGROUND', (0,0), (-1,0), PRIMARY),
                ('TEXTCOLOR', (0,0), (-1,0), WHITE),
                ('ALIGN', (0,0), (0,-1), 'CENTER'),
                ('ALIGN', (2,0), (3,-1), 'CENTER'),
                ('ALIGN', (4,0), (5,-1), 'CENTER'),
                ('GRID', (0,0), (-1,-1), 0.5, HexColor("#ddd")),
                ('TOPPADDING', (0,0), (-1,-1), 6),
                ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [HexColor("#ffffff"), HexColor("#f9f9f9")]),
            ]
            for i, item in enumerate(scored[:10], 1):
                s = item["score"]
                if s >= 70:
                    row_bg = HexColor("#e8f5e9")
                    score_color = GREEN
                    niveau_color = GREEN
                elif s >= 40:
                    row_bg = HexColor("#fff8e1")
                    score_color = ORANGE
                    niveau_color = ORANGE
                else:
                    row_bg = HexColor("#fce4ec")
                    score_color = RED
                    niveau_color = RED
                ts.extend([
                    ('BACKGROUND', (0,i), (-1,i), row_bg),
                    ('TEXTCOLOR', (2,i), (2,i), score_color),
                    ('FONTNAME', (2,i), (2,i), 'Helvetica-Bold'),
                    ('FONTSIZE', (2,i), (2,i), 11),
                    ('TEXTCOLOR', (3,i), (3,i), niveau_color),
                    ('FONTNAME', (3,i), (3,i), 'Helvetica-Bold'),
                ])
            ot.setStyle(TableStyle(ts))
            elements.append(ot)
        else:
            elements.append(Paragraph("Aucun appel d'offres correspondant.", styles['Body']))

        # Cas concret
        if scored:
            elements.append(Spacer(1, 1*cm))
            elements.append(Paragraph("Cas concret : votre meilleure opportunite", styles['Section']))
            elements.append(HRFlowable(width="100%", thickness=1, color=ORANGE, spaceAfter=10))
            best = scored[0]
            details = best.get("details", {})
            sc = best["score"]
            sc_color = "#27ae60" if sc >= 70 else "#f39c12" if sc >= 40 else "#e74c3c"
            # Nettoyage supplementaire pour le titre long
            clean_best_title = self._clean_text(best["tender_title"])
            elements.append(Paragraph(f'<b>"{clean_best_title[:150]}"</b>', ParagraphStyle('CT', parent=styles['Normal'], fontSize=12, textColor=PRIMARY, spaceAfter=6)))
            elements.append(Paragraph(f'Votre score : <font color="{sc_color}"><b>{sc:.0f}%</b></font> - Pourquoi ?', ParagraphStyle('SQ', parent=styles['Normal'], fontSize=13, textColor=PRIMARY, spaceAfter=12)))
            for label, value in [("Secteur (35%)", details.get("sector", 0)), ("Budget (30%)", details.get("budget", 0)), ("Zone (20%)", details.get("location", 0)), ("Experience (15%)", details.get("experience", 0))]:
                bc = "#27ae60" if value >= 70 else "#f39c12" if value >= 40 else "#e74c3c"
                d = Drawing(400, 20)
                d.add(Rect(0, 4, 300, 12, fillColor=HexColor("#eee"), strokeColor=None))
                d.add(Rect(0, 4, 300 * max(5, value) / 100, 12, fillColor=HexColor(bc), strokeColor=None))
                d.add(String(310, 5, f"{value:.0f}%", fontName="Helvetica-Bold", fontSize=10, fillColor=HexColor(bc)))
                elements.append(Paragraph(f"<b>{label}</b>", styles['Body']))
                elements.append(d)
                elements.append(Spacer(1, 4))
            summary = best.get("summary", "")
            if summary:
                elements.append(Spacer(1, 6))
                elements.append(Paragraph(f"<b>Resume :</b><br/>{summary[:300]}", styles['Body']))

        # Recommandations
        if recommendations:
            elements.append(Spacer(1, 1*cm))
            elements.append(Paragraph("Recommandations personnalisees", styles['Section']))
            elements.append(HRFlowable(width="100%", thickness=1, color=GREEN, spaceAfter=10))
            elements.append(Paragraph("En fonction de votre budget et de votre profil :", styles['Body']))
            for i, reco in enumerate(recommendations, 1):
                elements.append(Paragraph(f"<b>{i}.</b> {reco}", ParagraphStyle(f'R{i}', parent=styles['Normal'], fontSize=10, textColor=HexColor("#2c3e50"), spaceBefore=4, spaceAfter=4, leftIndent=10, leading=14)))

        # Footer
        elements.append(Spacer(1, 2*cm))
        elements.append(HRFlowable(width="100%", thickness=1, color=HexColor("#ccc"), spaceAfter=10))
        elements.append(Paragraph(f"Tender Analyzer - Rapport genere le {datetime.utcnow().strftime('%d/%m/%Y a %H:%M UTC')}", styles['Small']))
        elements.append(Paragraph(f"Ce rapport est confidentiel et destine exclusivement a {enterprise.name}.", styles['Small']))

        doc.build(elements)
        logger.info(f"PDF genere: {filepath}")
        return filepath