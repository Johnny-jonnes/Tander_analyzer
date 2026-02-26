# app/services/email_service.py
"""
Service d'envoi d'emails - Notifications SMTP avec corps HTML.
Gere l'envoi des resumes d'appels d'offres aux entreprises.
Optimise pour la delivrabilite (anti-spam).
"""

import html
import logging
import re
import smtplib
import ssl
import unicodedata
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formatdate, formataddr, make_msgid

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
    """Service d'envoi d'emails SMTP optimise pour la delivrabilite"""

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
        """Corrige le double-encodage UTF-8 (ex: 'dÃ\xa2extension' -> 'd\'extension')."""
        if not text:
            return ""
        # Tentative 1 : decode latin-1 -> utf-8
        try:
            fixed = text.encode('latin-1').decode('utf-8')
            if fixed != text:
                return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        # Tentative 2 : decode cp1252 -> utf-8
        try:
            fixed = text.encode('cp1252').decode('utf-8')
            if fixed != text:
                return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        # Tentative 3 : remplacement manuel des patterns casses les plus courants
        replacements = {
            '\u00c3\u00a9': 'é', '\u00c3\u00a8': 'è', '\u00c3\u00aa': 'ê',
            '\u00c3\u00ab': 'ë', '\u00c3\u00a0': 'à', '\u00c3\u00a2': 'â',
            '\u00c3\u00a7': 'ç', '\u00c3\u00b4': 'ô', '\u00c3\u00b9': 'ù',
            '\u00c3\u00bb': 'û', '\u00c3\u00ae': 'î', '\u00c3\u00af': 'ï',
            '\u00c3\u0089': 'É', '\u00c3\u0080': 'À',
            'Ã©': 'é', 'Ã¨': 'è', 'Ãª': 'ê', 'Ã«': 'ë',
            'Ã ': 'à', 'Ã¢': 'â', 'Ã§': 'ç', 'Ã´': 'ô',
            'Ã¹': 'ù', 'Ã»': 'û', 'Ã®': 'î', 'Ã¯': 'ï',
            'Ã\x89': 'É', 'Ã\x80': 'À', 'Ã\x94': 'Ô',
            'â\x80\x99': "'", 'â\x80\x93': '-', 'â\x80\x94': '-',
            'â\x80\x98': "'", 'â\x80\x9c': '"', 'â\x80\x9d': '"',
            'â\x80\xa6': '...', 'â\x80\x9e': '"',
            '\u2019': "'", '\u2018': "'", '\u201c': '"', '\u201d': '"',
            '\u2013': '-', '\u2014': '-', '\u2026': '...',
            '\u00e2\u0080\u0099': "'",
            'd\u00e2\u0080\u0099': "d'", 'l\u00e2\u0080\u0099': "l'",
            'd\u00e2': "d'", 'l\u00e2': "l'", 'n\u00e2': "n'",
        }
        for bad, good in replacements.items():
            text = text.replace(bad, good)
        # Caracteres orphelins restants de double-encodage (tentative intelligente)
        # Si on voit Ã suivi d'un caractere latin-1 sensible, on tente de reconstruire
        text = re.sub(r'Ã([\u00a0-\u00bf])', lambda m: (chr(ord(m.group(1)) + 64)).encode('latin-1').decode('utf-8', errors='ignore'), text)
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
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
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
            clean_explanation = self._clean_text(item.get('explanation', ''))

            if source_url and source_url.startswith('http') and '/plan/' not in source_url:
                btn_url = source_url
            else:
                # Fallback : recherche Google sur le titre de l'offre
                import urllib.parse
                search_query = urllib.parse.quote_plus(self._clean_plain_text(item['tender_title'][:100]))
                btn_url = f"https://www.google.com/search?q={search_query}+appel+d%27offres+Guinee"

            level_label = "Excellent" if score >= 70 else "Moyen" if score >= 40 else "A surveiller"
            level_bg = "#e8f5e9" if score >= 70 else "#fff8e1" if score >= 40 else "#fce4ec"
            level_txt = "#1b5e20" if score >= 70 else "#e65100" if score >= 40 else "#b71c1c"

            tender_rows += f"""
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;background:#ffffff;border-radius:16px;border:1px solid #eaedf2;overflow:hidden;box-shadow:0 2px 14px rgba(0,0,0,0.06);">
              <tr>
                <td width="88" style="padding:22px 0 22px 16px;vertical-align:top;text-align:center;">
                  <table cellpadding="0" cellspacing="0" style="margin:0 auto;"><tr><td style="width:62px;height:62px;border-radius:50%;background:{score_color}1a;border:2.5px solid {score_color}55;text-align:center;vertical-align:middle;">
                    <span style="font-size:16px;font-weight:900;color:{score_color};font-family:-apple-system,BlinkMacSystemFont,sans-serif;letter-spacing:-0.5px;">{score:.0f}</span><br>
                    <span style="font-size:9px;font-weight:700;color:{score_color}99;text-transform:uppercase;font-family:-apple-system,sans-serif;">/100</span>
                  </td></tr></table>
                </td>
                <td style="padding:18px 18px 18px 10px;vertical-align:top;">
                  <span style="display:inline-block;padding:3px 10px;border-radius:20px;background:{level_bg};font-size:10px;font-weight:700;color:{level_txt};font-family:-apple-system,sans-serif;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:8px;">{level_label}</span>
                  <p style="margin:0 0 7px 0;font-size:14px;font-weight:700;color:#0d1117;line-height:1.4;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">{clean_title}</p>
                  <p style="margin:0 0 14px 0;font-size:12px;color:#6b7280;line-height:1.6;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">{clean_summary}</p>
                  <a href="{btn_url}" target="_blank" style="display:inline-block;background:#0d1117;color:#ffffff;padding:9px 18px;border-radius:100px;text-decoration:none;font-size:12px;font-weight:600;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Voir l'offre &rarr;</a>
                </td>
              </tr>
            </table>"""
            text_lines.append(f"- {self._clean_plain_text(item['tender_title'][:80])} (Score: {score:.0f}/100) - {source_url}")

        self._text_summary = "\n".join(text_lines) if text_lines else "Aucun appel d'offres correspondant."

        # ── Recommandations IA ──────────────────────────────────────────────
        reco_section = ""
        reco_text = ""
        if recommendations:
            reco_items = ""
            reco_text_lines = []
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
                reco_text_lines.append(f"  {i}. {self._clean_plain_text(reco)}")
            reco_text = "\n".join(reco_text_lines)
            reco_section = f"""
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;background:#fafbff;border-radius:16px;border:1px solid #e0e4ff;overflow:hidden;">
              <tr><td style="padding:22px 24px 4px 24px;">
                <p style="margin:0 0 4px 0;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#6366f1;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Intelligence artificielle</p>
                <p style="margin:0 0 14px 0;font-size:18px;font-weight:800;color:#0d1117;font-family:-apple-system,BlinkMacSystemFont,sans-serif;letter-spacing:-0.3px;">Recommandations personnalisees</p>
                <table width="100%" cellpadding="0" cellspacing="0"><tbody>{reco_items}</tbody></table>
              </td></tr>
              <tr><td style="padding:12px 24px 18px 24px;">
                <p style="margin:0;font-size:12px;color:#9ca3af;font-style:italic;font-family:-apple-system,sans-serif;">Analyse generee par IA selon votre profil.</p>
              </td></tr>
            </table>"""

        # ── Cas concret ────────────────────────────────────────────────────
        case_study_section = ""
        if scored_analyses:
            best = scored_analyses[0]
            best_title = self._clean_text(best['tender_title'][:100])
            best_score = best['score']
            best_explanation = self._clean_text(best.get('explanation', ''))
            best_details = best.get('details', {})
            best_sc_color = "#27ae60" if best_score >= 70 else "#f39c12" if best_score >= 40 else "#e74c3c"

            def _premium_bar(label, value, weight):
                color = "#27ae60" if value >= 70 else "#f39c12" if value >= 40 else "#e74c3c"
                w = max(3, int(value))
                return f"""<tr><td style="padding:9px 0 0 0;">
                    <table width="100%" cellpadding="0" cellspacing="0"><tr>
                      <td style="font-size:11px;font-weight:600;color:#6b7280;font-family:-apple-system,sans-serif;padding-bottom:4px;">{label} <span style="color:#6b7280;font-weight:400;">({weight})</span></td>
                      <td style="text-align:right;font-size:12px;font-weight:800;color:{color};font-family:-apple-system,sans-serif;padding-bottom:4px;">{value:.0f}%</td>
                    </tr><tr><td colspan="2">
                      <div style="background:rgba(255,255,255,0.1);border-radius:100px;height:7px;overflow:hidden;">
                        <div style="background:linear-gradient(90deg,{color}99,{color});height:7px;width:{w}%;border-radius:100px;"></div>
                      </div>
                    </td></tr></table>
                </td></tr>"""

            case_study_section = f"""
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;background:#0d1117;border-radius:16px;overflow:hidden;">
              <tr><td style="padding:24px 24px 20px 24px;">
                <p style="margin:0 0 4px 0;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#f39c12;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Meilleure opportunite</p>
                <p style="margin:0 0 16px 0;font-size:14px;font-weight:700;color:#ffffff;line-height:1.4;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">{best_title}</p>
                <table cellpadding="0" cellspacing="0" width="100%"><tr>
                  <td width="90" style="padding-right:16px;vertical-align:middle;">
                    <div style="background:{best_sc_color}22;border:1.5px solid {best_sc_color}55;border-radius:14px;padding:10px 14px;text-align:center;">
                      <p style="margin:0;font-size:27px;font-weight:900;color:{best_sc_color};font-family:-apple-system,sans-serif;letter-spacing:-1px;">{best_score:.0f}<span style="font-size:14px;font-weight:600;">%</span></p>
                      <p style="margin:2px 0 0 0;font-size:10px;color:{best_sc_color}99;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;font-family:-apple-system,sans-serif;">Score</p>
                    </div>
                  </td>
                  <td style="vertical-align:middle;">
                    <p style="margin:0;font-size:12px;color:#8b949e;font-family:-apple-system,sans-serif;font-style:italic;line-height:1.5;">{best_explanation[:120] if best_explanation else "Correspondance elevee avec votre profil."}</p>
                  </td>
                </tr></table>
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;">
                  {_premium_bar("Secteur", best_details.get("sector", 0), "35%")}
                  {_premium_bar("Budget", best_details.get("budget", 0), "30%")}
                  {_premium_bar("Zone", best_details.get("location", 0), "20%")}
                  {_premium_bar("Experience", best_details.get("experience", 0), "15%")}
                </table>
              </td></tr>
            </table>"""

        clean_name = self._clean_text(enterprise.name)
        clean_sector = self._clean_text(enterprise.sector)
        nb_high = len([s for s in scored_analyses if s["score"] >= 70])
        nb_medium = len([s for s in scored_analyses if 40 <= s["score"] < 70])
        nb_total = len(scored_analyses)
        date_str = datetime.utcnow().strftime("%d %B %Y")

        pdf_banner = ""
        if has_pdf:
            pdf_banner = """
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;background:linear-gradient(135deg,#fffbeb,#fef3c7);border-radius:14px;border:1px solid #fcd34d;overflow:hidden;">
              <tr><td style="padding:14px 18px;">
                <table cellpadding="0" cellspacing="0"><tr>
                  <td style="font-size:22px;padding-right:12px;vertical-align:middle;">&#128206;</td>
                  <td>
                    <p style="margin:0 0 2px 0;font-size:13px;font-weight:700;color:#92400e;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Rapport PDF joint en piece jointe</p>
                    <p style="margin:0;font-size:11px;color:#b45309;font-family:-apple-system,sans-serif;">Scores detailles, analyses et recommandations en PDF.</p>
                  </td>
                </tr></table>
              </td></tr>
            </table>"""

        empty_row = "<tr><td style='padding:40px;text-align:center;color:#9ca3af;font-style:italic;font-family:-apple-system,sans-serif;font-size:14px;'>Aucun appel d'offres correspondant aujourd'hui</td></tr>"

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

  <!-- HEADER DARK -->
  <tr><td style="background:linear-gradient(160deg,#0d1117 0%,#161b22 55%,#1a2035 100%);border-radius:20px 20px 0 0;padding:40px 32px 36px 32px;text-align:center;">
    <p style="margin:0 0 6px 0;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:2px;color:#3d8bff;font-family:-apple-system,sans-serif;">Rapport Quotidien &bull; {date_str}</p>
    <h1 style="margin:0 0 8px 0;font-size:32px;font-weight:900;color:#ffffff;letter-spacing:-1px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Tender Analyzer</h1>
    <p style="margin:0 0 28px 0;font-size:14px;color:#8b949e;font-weight:400;font-family:-apple-system,sans-serif;">Vos opportunites d'appels d'offres, analysees par IA</p>
    <table cellpadding="0" cellspacing="0" style="margin:0 auto;"><tr>
      <td style="padding:0 4px;"><div style="background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.12);border-radius:100px;padding:8px 16px;text-align:center;">
        <span style="font-size:20px;font-weight:900;color:#ffffff;display:block;line-height:1.1;">{nb_total}</span>
        <span style="font-size:10px;font-weight:600;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px;">Analyses</span>
      </div></td>
      <td style="padding:0 4px;"><div style="background:rgba(39,174,96,0.12);border:1px solid rgba(39,174,96,0.3);border-radius:100px;padding:8px 16px;text-align:center;">
        <span style="font-size:20px;font-weight:900;color:#27ae60;display:block;line-height:1.1;">{nb_high}</span>
        <span style="font-size:10px;font-weight:600;color:#27ae60aa;text-transform:uppercase;letter-spacing:0.5px;">Excellents</span>
      </div></td>
      <td style="padding:0 4px;"><div style="background:rgba(243,156,18,0.12);border:1px solid rgba(243,156,18,0.3);border-radius:100px;padding:8px 16px;text-align:center;">
        <span style="font-size:20px;font-weight:900;color:#f39c12;display:block;line-height:1.1;">{nb_medium}</span>
        <span style="font-size:10px;font-weight:600;color:#f39c12aa;text-transform:uppercase;letter-spacing:0.5px;">Moyens</span>
      </div></td>
    </tr></table>
  </td></tr>

  <!-- BODY -->
  <tr><td style="background:#f8f9fc;padding:28px 22px;border-radius:0 0 20px 20px;border:1px solid #eaedf2;border-top:none;">

    <p style="margin:0 0 4px 0;font-size:22px;font-weight:800;color:#0d1117;letter-spacing:-0.3px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Bonjour, {clean_name} &#x1F44B;</p>
    <p style="margin:0 0 24px 0;font-size:14px;color:#6b7280;line-height:1.6;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Votre selection personnalisee pour <strong style="color:#0d1117;">{clean_sector}</strong>. Chaque opportunite est scoree par IA selon votre profil.</p>

    <p style="margin:0 0 12px 0;font-size:11px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:1.2px;font-family:-apple-system,sans-serif;">Top opportunites</p>

    {tender_rows if tender_rows else f'<table width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;border:1px solid #eaedf2;"><tbody>{empty_row}</tbody></table>'}

    {case_study_section}

    {reco_section}

    {pdf_banner}

    <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:26px;">
      <tr><td style="text-align:center;padding:22px 20px;background:#0d1117;border-radius:14px;">
        <p style="margin:0 0 12px 0;font-size:13px;color:#8b949e;font-family:-apple-system,sans-serif;">Des questions sur vos resultats ?</p>
        <a href="https://wa.me/224627171397" style="display:inline-block;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#ffffff;padding:12px 26px;border-radius:100px;text-decoration:none;font-size:13px;font-weight:700;letter-spacing:-0.1px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;">Contacter le support &#x2192;</a>
      </td></tr>
    </table>

  </td></tr>

  <!-- FOOTER -->
  <tr><td style="padding:18px 0;text-align:center;">
    <p style="margin:0 0 5px 0;font-size:12px;color:#9ca3af;font-family:-apple-system,sans-serif;">Tender Analyzer &bull; {date_str}</p>
    <p style="margin:0;font-size:11px;font-family:-apple-system,sans-serif;"><a href="mailto:{settings.SMTP_FROM}?subject=unsubscribe" style="color:#9ca3af;text-decoration:underline;">Se desabonner</a></p>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>"""

        if reco_text:
            self._text_summary += f"\n\nRecommandations :\n{reco_text}"
        return html_content

    # ------------------------------------------------------------------
    #  Envoi SMTP avec headers anti-spam
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=30),
    )
    def _send_smtp(self, to_email: str, subject: str, html_body: str, pdf_path: str | None = None) -> bool:
        """Envoie un email via SMTP avec headers anti-spam et retry."""
        logger.info(f"Tentative SMTP -> {settings.SMTP_HOST}:{settings.SMTP_PORT}")

        clean_subj = self._clean_subject(subject)
        msg = MIMEMultipart("mixed")

        # Headers anti-spam
        msg["From"] = formataddr(("Tender Analyzer", settings.SMTP_FROM))
        msg["To"] = to_email
        msg["Subject"] = clean_subj
        msg["Reply-To"] = settings.SMTP_FROM
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=settings.SMTP_FROM.split("@")[-1])
        msg["MIME-Version"] = "1.0"
        msg["List-Unsubscribe"] = f"<mailto:{settings.SMTP_FROM}?subject=unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        msg["Precedence"] = "bulk"
        msg["X-Auto-Response-Suppress"] = "OOF, AutoReply"
        msg["Feedback-ID"] = f"tender-report:{settings.SMTP_FROM.split('@')[0]}:tender-analyzer"

        # Partie alternative (texte + HTML)
        alt_part = MIMEMultipart("alternative")
        plain_text = self._clean_plain_text(getattr(self, '_text_summary', '') or clean_subj)
        text_content = f"Bonjour,\n\nVoici votre rapport d'appels d'offres de Tender Analyzer.\n\n{plain_text}\n\n---\nTender Analyzer - {datetime.utcnow().strftime('%d/%m/%Y')}\nPour vous desabonner, repondez a cet email avec le sujet 'unsubscribe'."
        alt_part.attach(MIMEText(text_content, "plain", "utf-8"))
        alt_part.attach(MIMEText(html_body, "html", "utf-8"))
        msg.attach(alt_part)

        # Piece jointe PDF
        if pdf_path:
            try:
                import os
                with open(pdf_path, "rb") as f:
                    pdf_att = MIMEBase("application", "pdf")
                    pdf_att.set_payload(f.read())
                    encoders.encode_base64(pdf_att)
                    pdf_att.add_header("Content-Disposition", "attachment", filename=os.path.basename(pdf_path))
                    msg.attach(pdf_att)
            except Exception as e:
                logger.error(f"Erreur attachement PDF: {e}")

        context = ssl.create_default_context()
        try:
            if settings.SMTP_PORT == 465:
                server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=30)
            else:
                server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30)
                server.ehlo()
                if settings.SMTP_TLS:
                    server.starttls(context=context)
                    server.ehlo()
            if settings.DEBUG:
                server.set_debuglevel(1)
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, to_email, msg.as_string())
            server.quit()
            logger.info(f"Email envoye a {to_email}")
            return True
        except Exception as e:
            logger.error(f"Erreur envoi email a {to_email}: {e}")
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
            self._send_smtp(enterprise.email, subject, html_body, pdf_path)
            email_log.status = "sent"
            email_log.sent_at = datetime.utcnow()
            self.db.commit()
            return True
        except Exception as e:
            email_log.status = "failed"
            email_log.error_message = str(e)[:500]
            self.db.commit()
            logger.error(f"Echec envoi email a {enterprise.name}: {e}")
            return False

    # ------------------------------------------------------------------
    #  Email de bienvenue
    # ------------------------------------------------------------------

    def send_welcome_email(self, enterprise: Enterprise) -> bool:
        if not enterprise.email:
            return False
        subject = f"Bienvenue sur Tender Analyzer - {enterprise.name}"
        clean_name = self._clean_text(enterprise.name)
        clean_sector = self._clean_text(enterprise.sector)
        clean_keywords = self._clean_text(enterprise.specific_keywords or 'Aucun')
        clean_excludes = self._clean_text(enterprise.exclude_keywords or 'Aucune')

        logo_img = ""
        if hasattr(enterprise, 'logo_url') and enterprise.logo_url:
            logo_img = f'<div style="text-align: center; margin-bottom: 15px;"><img src="{enterprise.logo_url}" alt="Logo" style="max-height: 60px; max-width: 200px; border-radius: 8px;"></div>'

        html_body = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"></head>
<body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #f5f6fa; margin: 0; padding: 20px;">
    <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
        <div style="background: linear-gradient(135deg, #2c3e50, #3498db); padding: 30px; text-align: center;">
            <h1 style="color: white; margin: 0; font-size: 24px;">Bienvenue !</h1>
        </div>
        <div style="padding: 30px;">
            {logo_img}
            <p style="font-size: 16px; color: #2c3e50;">Bonjour <strong>{clean_name}</strong>,</p>
            <p style="color: #555; line-height: 1.6;">Votre inscription a <strong>Tender Analyzer</strong> est confirmee.</p>
            <p style="color: #555; line-height: 1.6;">A partir de demain matin, vous recevrez quotidiennement les meilleurs appels d'offres correspondant a votre profil :</p>
            <ul style="color: #555; line-height: 1.6;">
                <li><strong>Secteur :</strong> {clean_sector}</li>
                <li><strong>Mots-cles :</strong> {clean_keywords}</li>
                <li><strong>Exclusions :</strong> {clean_excludes}</li>
            </ul>
            <p style="margin-top: 25px; font-style: italic; color: #7f8c8d;">L'equipe Tender Analyzer</p>
        </div>
        <div style="background-color: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #eee;">
            <p style="color: #999; font-size: 13px; margin: 0 0 8px 0;">Besoin d'aide ? <a href="https://wa.me/224627171397" style="color: #3498db; text-decoration: none; font-weight: bold;">Contactez-nous sur WhatsApp</a></p>
            <p style="color: #999; font-size: 11px; margin: 0;">Ceci est un message automatique. <a href="mailto:{settings.SMTP_FROM}?subject=unsubscribe" style="color: #999; text-decoration: underline;">Se desabonner</a></p>
        </div>
    </div>
</body></html>"""

        email_log = EmailLog(enterprise_id=enterprise.id, recipient_email=enterprise.email, subject=self._clean_subject(subject), status="pending")
        self.db.add(email_log)
        self.db.flush()
        try:
            self._send_smtp(enterprise.email, subject, html_body)
            email_log.status = "sent"
            email_log.sent_at = datetime.utcnow()
            self.db.commit()
            return True
        except Exception as e:
            email_log.status = "failed"
            email_log.error_message = str(e)[:500]
            self.db.commit()
            return False

    # ------------------------------------------------------------------
    #  Envoi en masse (avec recommandations IA + PDF)
    # ------------------------------------------------------------------

    def send_all_daily_reports(self) -> dict:
        from app.services.scorer import ScorerService
        from app.services.ai_analyzer import AIAnalyzerService
        from app.services.report_generator import ReportGeneratorService

        enterprises = self.db.query(Enterprise).filter(Enterprise.email.isnot(None)).all()
        logger.info(f"Envoi de rapports a {len(enterprises)} entreprises")

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
                    if analysis:
                        item["summary"] = analysis.summary or ""
                    tender = self.db.query(Tender).get(item["tender_id"])
                    if tender:
                        item["source_url"] = tender.source_url or ""

                # Recommandations IA
                recommendations = None
                try:
                    recommendations = ai_service.generate_budget_recommendations(enterprise, scored[:5])
                except Exception as e:
                    logger.error(f"Erreur recommandations pour {enterprise.name}: {e}")

                # PDF
                pdf_path = None
                try:
                    pdf_path = report_service.generate_pdf_report(enterprise.id, recommendations=recommendations)
                except Exception as e:
                    logger.error(f"Erreur PDF pour {enterprise.name}: {e}")

                success = self.send_daily_report(enterprise, scored, recommendations=recommendations, pdf_path=pdf_path)
                results["sent" if success else "failed"] += 1

            except Exception as e:
                logger.error(f"Erreur rapport pour {enterprise.name}: {e}")
                results["failed"] += 1

        logger.info(f"Resultat envoi: {results}")
        return results