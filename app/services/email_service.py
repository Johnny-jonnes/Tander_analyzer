# app/services/email_service.py
"""
Service d'envoi d'emails via l'API HTTP Mailjet.
Gere l'envoi des resumes d'appels d'offres aux entreprises.
Utilise l'API REST Mailjet (port 443) pour eviter les blocages SMTP cloud.
"""

import base64
import html
import logging
import os
import re
import unicodedata
from datetime import datetime

import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enterprise import Enterprise
from app.models.tender import Tender
from app.models.analysis import Analysis
from app.models.email_log import EmailLog

logger = logging.getLogger(__name__)
settings = get_settings()


class EmailService:
    """Service d'envoi d'emails via API HTTP Mailjet"""

    def __init__(self, db: Session):
        self.db = db
        self._text_summary = ""

    # ------------------------------------------------------------------
    #  Nettoyage de texte (suppression caracteres speciaux / emojis)
    # ------------------------------------------------------------------

    def _strip_emojis(self, text: str) -> str:
        """Supprime tous les emojis et symboles unicode decoratifs."""
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"
            "\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "\U0001f900-\U0001f9FF"
            "\U00002600-\U000026FF"
            "\U0000FE00-\U0000FE0F"
            "\U0000200D"
            "\U0000200B"
            "]+",
            flags=re.UNICODE
        )
        return emoji_pattern.sub('', text)

    def _fix_encoding(self, text: str) -> str:
        """Corrige le double-encodage UTF-8."""
        if not text:
            return ""
        try:
            fixed = text.encode('latin-1').decode('utf-8')
            if fixed != text:
                return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        
        replacements = {
            '\u00c3\u00a9': 'é', '\u00c3\u00a8': 'è', '\u00c3\u00aa': 'ê',
            '\u00c3\u00ab': 'ë', '\u00c3\u00a0': 'à', '\u00c3\u00a2': 'â',
            '\u00c3\u00a7': 'ç', '\u00c3\u00b4': 'ô', '\u00c3\u00b9': 'ù',
            '\u00c3\u00bb': 'û', '\u00c3\u00ae': 'î', '\u00c3\u00af': 'ï',
            'Ã©': 'é', 'Ã¨': 'è', 'Ãª': 'ê', 'Ã«': 'ë',
            'Ã ': 'à', 'Ã¢': 'â', 'Ã§': 'ç', 'Ã´': 'ô',
            'Ã¹': 'ù', 'Ã»': 'û', 'Ã®': 'î', 'Ã¯': 'ï',
            'â\x80\x99': "'", 'â\x80\x93': '-', 'â\x80\x94': '-',
            '\u2019': "'", '\u00e2\u0080\u0099': "'",
        }
        for bad, good in replacements.items():
            text = text.replace(bad, good)
        return text

    def _clean_text(self, text: str) -> str:
        """Nettoie le texte : corrige encodage, supprime emojis, encode HTML."""
        if not text:
            return ""
        text = self._fix_encoding(text)
        text = unicodedata.normalize('NFC', text)
        text = self._strip_emojis(text)
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        text = html.escape(text)
        return text.strip()

    def _clean_subject(self, subject: str) -> str:
        """Nettoie le sujet de l'email."""
        if not subject:
            return "Tender Analyzer - Rapport"
        subject = self._fix_encoding(subject)
        subject = self._strip_emojis(subject)
        subject = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', subject)
        return subject.strip() or "Tender Analyzer - Rapport"

    def _clean_plain_text(self, text: str) -> str:
        """Nettoie le texte brut."""
        if not text:
            return ""
        text = self._fix_encoding(text)
        text = self._strip_emojis(text)
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        return text.strip()

    # ------------------------------------------------------------------
    #  Construction du corps HTML
    # ------------------------------------------------------------------

    def _build_html_body(
        self,
        enterprise: Enterprise,
        scored_analyses: list[dict],
        recommendations: list[str] | None = None,
        has_pdf: bool = False,
    ) -> str:
        """Construit le corps HTML de l'email - Design premium."""
        tender_rows = ""
        text_lines = []

        for item in scored_analyses[:10]:
            score = item["score"]
            score_color = "#27ae60" if score >= 70 else "#f39c12" if score >= 40 else "#e74c3c"
            source_url = item.get('source_url', '')
            clean_title = self._clean_text(item['tender_title'][:80])
            clean_summary = self._clean_text(item.get('summary', '')[:200])

            if source_url and source_url.startswith('http') and '/plan/' not in source_url:
                btn_url = source_url
            else:
                import urllib.parse
                search_query = urllib.parse.quote_plus(self._clean_plain_text(item['tender_title'][:100]))
                btn_url = f"https://www.google.com/search?q={search_query}+appel+d%27offres+Guinee"

            level_label = "Excellent" if score >= 70 else "Moyen" if score >= 40 else "A surveiller"
            level_bg = "#e8f5e9" if score >= 70 else "#fff8e1" if score >= 40 else "#fce4ec"
            level_txt = "#1b5e20" if score >= 70 else "#e65100" if score >= 40 else "#b71c1c"

            tender_rows += f"""
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:18px;background:#ffffff;border-radius:16px;border:1px solid #eaedf2;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.05);">
              <tr>
                <td width="88" style="padding:24px 0 24px 16px;vertical-align:top;text-align:center;">
                  <table cellpadding="0" cellspacing="0" style="margin:0 auto;"><tr><td style="width:64px;height:64px;border-radius:50%;background:{score_color}1a;border:2px solid {score_color}44;text-align:center;vertical-align:middle;">
                    <span style="font-size:18px;font-weight:900;color:{score_color};font-family:-apple-system,BlinkMacSystemFont,sans-serif;">{score:.0f}</span><br>
                    <span style="font-size:9px;font-weight:700;color:{score_color}99;text-transform:uppercase;font-family:-apple-system,sans-serif;">/100</span>
                  </td></tr></table>
                </td>
                <td style="padding:20px 20px 20px 10px;vertical-align:top;">
                  <span style="display:inline-block;padding:4px 12px;border-radius:20px;background:{level_bg};font-size:10px;font-weight:700;color:{level_txt};font-family:-apple-system,sans-serif;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">{level_label}</span>
                  <p style="margin:0 0 8px 0;font-size:15px;font-weight:700;color:#0d1117;line-height:1.4;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">{clean_title}</p>
                  <p style="margin:0 0 16px 0;font-size:13px;color:#4b5563;line-height:1.6;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">{clean_summary}</p>
                  <a href="{btn_url}" target="_blank" style="display:inline-block;background:#0d1117;color:#ffffff;padding:10px 24px;border-radius:100px;text-decoration:none;font-size:13px;font-weight:600;font-family:-apple-system,BlinkMacSystemFont,sans-serif;-webkit-font-smoothing:antialiased;">Voir l'offre &rarr;</a>
                </td>
              </tr>
            </table>"""
            text_lines.append(f"- {self._clean_plain_text(item['tender_title'][:80])} (Score: {score:.0f}/100)")

        self._text_summary = "\n".join(text_lines) if text_lines else "Aucun appel d'offres correspondant."

        reco_section = ""
        if recommendations:
            reco_items = ""
            for i, reco in enumerate(recommendations, 1):
                clean_reco = self._clean_text(reco)
                reco_items += f"""
                <tr><td style="padding:12px 0;border-bottom:1px solid #f0f2f8;">
                  <table cellpadding="0" cellspacing="0" width="100%"><tr>
                    <td width="32" style="vertical-align:top;padding-top:1px;">
                      <div style="width:24px;height:24px;border-radius:50%;background:linear-gradient(135deg,#6366f1,#8b5cf6);text-align:center;line-height:24px;display:inline-block;">
                        <span style="font-size:12px;font-weight:800;color:#fff;font-family:-apple-system,sans-serif;">{i}</span>
                      </div>
                    </td>
                    <td style="padding-left:10px;font-size:13px;color:#374151;line-height:1.6;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">{clean_reco}</td>
                  </tr></table>
                </td></tr>"""
            reco_section = f"""<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;background:#fafbff;border-radius:16px;border:1px solid #e0e4ff;overflow:hidden;">
              <tr><td style="padding:22px 24px 4px 24px;">
                <p style="margin:0 0 4px 0;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#6366f1;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Intelligence artificielle</p>
                <p style="margin:0 0 14px 0;font-size:18px;font-weight:800;color:#0d1117;font-family:-apple-system,BlinkMacSystemFont,sans-serif;letter-spacing:-0.3px;">Recommandations personnalisees</p>
                <table width="100%" cellpadding="0" cellspacing="0"><tbody>{reco_items}</tbody></table>
              </td></tr>
            </table>"""

        date_str = datetime.utcnow().strftime("%d %B %Y")
        clean_name = self._clean_text(enterprise.name)
        clean_sector = self._clean_text(enterprise.sector)

        html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tender Analyzer - {date_str}</title>
</head>
<body style="margin:0;padding:0;background-color:#f3f4f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f8;padding:32px 14px;">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0" style="max-width:620px;width:100%;">
  <tr><td style="background:linear-gradient(160deg,#0d1117 0%,#161b22 55%,#1a2035 100%);border-radius:20px 20px 0 0;padding:40px 32px 36px 32px;text-align:center;">
    <h1 style="margin:0 0 8px 0;font-size:32px;font-weight:900;color:#ffffff;letter-spacing:-1px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Tender Analyzer</h1>
    <p style="margin:0;font-size:14px;color:#8b949e;font-weight:400;font-family:-apple-system,sans-serif;">Rapport Quotidien &bull; {date_str}</p>
  </td></tr>
  <tr><td style="background:#f8f9fc;padding:28px 22px;border-radius:0 0 20px 20px;border:1px solid #eaedf2;border-top:none;">
    <p style="margin:0 0 4px 0;font-size:22px;font-weight:800;color:#0d1117;letter-spacing:-0.3px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Bonjour, {clean_name} &#x1F44B;</p>
    <p style="margin:0 0 24px 0;font-size:14px;color:#6b7280;line-height:1.6;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Votre selection personnalisee pour <strong style="color:#0d1117;">{clean_sector}</strong>.</p>
    {tender_rows}
    {reco_section}
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:26px;">
      <tr><td style="text-align:center;padding:22px 20px;background:#0d1117;border-radius:14px;">
        <p style="margin:0 0 12px 0;font-size:13px;color:#8b949e;font-family:-apple-system,sans-serif;">Des questions sur vos resultats ?</p>
        <a href="https://wa.me/224627171397" style="display:inline-block;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#ffffff;padding:12px 26px;border-radius:100px;text-decoration:none;font-size:13px;font-weight:700;letter-spacing:-0.1px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Contacter le support &#x2192;</a>
      </td></tr>
    </table>
  </td></tr>
</table>
</td></tr>
</table>
</body></html>"""
        return html_content

    # ------------------------------------------------------------------
    #  Envoi via API HTTP Mailjet (Port 443)
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=30),
    )
    def _send_mailjet_http(self, to_email: str, subject: str, html_body: str, pdf_path: str | None = None) -> bool:
        """Envoie un email via l'API REST Mailjet v3.1 (Port 443)."""
        logger.info(f"Tentative API Mailjet -> {to_email}")

        api_url = "https://api.mailjet.com/v3.1/send"
        auth = (settings.SMTP_USER, settings.SMTP_PASSWORD)
        
        plain_text = self._clean_plain_text(getattr(self, '_text_summary', '') or subject)
        
        payload = {
            "Messages": [
                {
                    "From": {
                        "Email": settings.SMTP_FROM,
                        "Name": "Tender Analyzer"
                    },
                    "To": [
                        {
                            "Email": to_email
                        }
                    ],
                    "Subject": self._clean_subject(subject),
                    "TextPart": f"Bonjour,\n\nVoici votre rapport de Tender Analyzer.\n\n{plain_text}",
                    "HTMLPart": html_body,
                    "CustomID": f"tender_{datetime.utcnow().strftime('%Y%H%M')}"
                }
            ]
        }

        # Piece jointe PDF
        if pdf_path and os.path.exists(pdf_path):
            try:
                with open(pdf_path, "rb") as f:
                    content_b64 = base64.b64encode(f.read()).decode('utf-8')
                
                payload["Messages"][0]["Attachments"] = [
                    {
                        "ContentType": "application/pdf",
                        "Filename": os.path.basename(pdf_path),
                        "Base64Content": content_b64
                    }
                ]
            except Exception as e:
                logger.error(f"Erreur preparation PDF: {e}")

        try:
            response = requests.post(api_url, json=payload, auth=auth, timeout=30)
            response.raise_for_status()
            logger.info(f"Email envoye via API Mailjet a {to_email}")
            return True
        except Exception as e:
            logger.error(f"Echec envoi API Mailjet: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response Mailjet: {e.response.text}")
            raise

    # ------------------------------------------------------------------
    #  Rapport quotidien
    # ------------------------------------------------------------------

    def send_daily_report(self, enterprise: Enterprise, scored_analyses: list[dict], recommendations: list[str] | None = None, pdf_path: str | None = None) -> bool:
        if not enterprise.email:
            return False
        subject = f"Tender Analyzer - {len(scored_analyses)} appels d'offres pour {enterprise.name}"
        html_body = self._build_html_body(enterprise, scored_analyses, recommendations, has_pdf=bool(pdf_path))
        
        email_log = EmailLog(enterprise_id=enterprise.id, recipient_email=enterprise.email, subject=self._clean_subject(subject), status="pending")
        self.db.add(email_log)
        self.db.flush()
        
        try:
            self._send_mailjet_http(enterprise.email, subject, html_body, pdf_path)
            email_log.status = "sent"
            email_log.sent_at = datetime.utcnow()
            self.db.commit()
            return True
        except Exception as e:
            email_log.status = "failed"
            email_log.error_message = str(e)[:500]
            self.db.commit()
            return False

    def send_welcome_email(self, enterprise: Enterprise) -> bool:
        if not enterprise.email:
            return False
        subject = f"Bienvenue sur Tender Analyzer - {enterprise.name}"
        clean_name = self._clean_text(enterprise.name)
        
        html_body = f"""<!DOCTYPE html>
<html lang="fr"><body style="font-family: sans-serif; padding: 20px;">
    <h2>Bienvenue {clean_name}!</h2>
    <p>Votre inscription est confirmee. Vous recevrez desormais nos rapports quotidiens.</p>
    <p><a href="https://wa.me/224627171397">Contactez-nous sur WhatsApp</a></p>
</body></html>"""

        email_log = EmailLog(enterprise_id=enterprise.id, recipient_email=enterprise.email, subject=self._clean_subject(subject), status="pending")
        self.db.add(email_log)
        self.db.flush()
        
        try:
            self._send_mailjet_http(enterprise.email, subject, html_body)
            email_log.status = "sent"
            email_log.sent_at = datetime.utcnow()
            self.db.commit()
            return True
        except Exception as e:
            email_log.status = "failed"
            email_log.error_message = str(e)[:500]
            self.db.commit()
            return False

    def send_all_daily_reports(self) -> dict:
        from app.services.scorer import ScorerService
        from app.services.ai_analyzer import AIAnalyzerService
        from app.services.report_generator import ReportGeneratorService

        enterprises = self.db.query(Enterprise).filter(Enterprise.email.isnot(None)).all()
        scorer = ScorerService(self.db)
        ai_service = AIAnalyzerService(self.db)
        report_service = ReportGeneratorService(self.db)
        
        results = {"sent": 0, "failed": 0, "skipped": 0}

        for enterprise in enterprises:
            try:
                scored = scorer.score_all_for_enterprise(enterprise)
                if not scored:
                    results["skipped"] += 1
                    continue

                for item in scored:
                    analysis = self.db.query(Analysis).filter(Analysis.tender_id == item["tender_id"]).first()
                    if analysis: item["summary"] = analysis.summary or ""
                
                reco = None
                try: reco = ai_service.generate_budget_recommendations(enterprise, scored[:5])
                except: pass

                pdf_path = None
                try: pdf_path = report_service.generate_pdf_report(enterprise.id, recommendations=reco)
                except: pass

                success = self.send_daily_report(enterprise, scored, recommendations=reco, pdf_path=pdf_path)
                results["sent" if success else "failed"] += 1
            except:
                results["failed"] += 1

        return results