# app/routers/analyses.py
"""
Endpoints pour les analyses et rapports
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enterprise import Enterprise
from app.models.analysis import Analysis
from app.models.tender import Tender
from app.schemas.analysis import AnalysisResponse, AnalysisDetailResponse
from app.services.scorer import ScorerService
from app.services.report_generator import ReportGeneratorService
from app.services.email_service import EmailService
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/analysis",
    tags=["Analyses"],
)


@router.get(
    "/{enterprise_id}",
    summary="Analyses pour une entreprise",
    description="Retourne les analyses scorées pour une entreprise spécifique.",
)
def get_analysis_for_enterprise(
    enterprise_id: int,
    min_score: float = 0.0,
    db: Session = Depends(get_db),
):
    """GET /analysis/{enterprise_id} - Analyses scorées"""

    enterprise = db.query(Enterprise).get(enterprise_id)
    if not enterprise:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entreprise #{enterprise_id} non trouvée",
        )

    # Blocage de paiement (Essai PASS terminé)
    if enterprise.subscription_plan == "PASS":
        if datetime.utcnow() > enterprise.created_at + timedelta(days=2):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Période d'essai terminée. Veuillez effectuer le paiement pour réactiver votre compte.",
            )

    scorer = ScorerService(db)
    scored = scorer.score_all_for_enterprise(enterprise)

    # Filtrer par score minimum
    if min_score > 0:
        scored = [s for s in scored if s["score"] >= min_score]

    return {
        "enterprise": {
            "id": enterprise.id,
            "name": enterprise.name,
            "sector": enterprise.sector,
        },
        "total_results": len(scored),
        "analyses": scored,
    }


@router.get(
    "/report/{enterprise_id}",
    summary="Rapport complet",
    description="Génère un rapport détaillé pour une entreprise.",
)
def get_report(
    enterprise_id: int,
    db: Session = Depends(get_db),
):
    """GET /analysis/report/{enterprise_id} - Rapport complet"""

    report_service = ReportGeneratorService(db)
    report = report_service.generate_enterprise_report(enterprise_id)

    if "error" in report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=report["error"],
        )

    return report


@router.post(
    "/send-report/{enterprise_id}",
    summary="Envoyer le rapport par email",
)
def send_report_email(
    enterprise_id: int,
    db: Session = Depends(get_db),
):
    """POST /analysis/send-report/{enterprise_id}"""

    enterprise = db.query(Enterprise).get(enterprise_id)
    if not enterprise:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entreprise #{enterprise_id} non trouvée",
        )

    if not enterprise.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucun email configuré pour cette entreprise",
        )

    scorer = ScorerService(db)
    scored = scorer.score_all_for_enterprise(enterprise)

    # Enrichir avec résumés
    for item in scored:
        analysis = db.query(Analysis).filter(
            Analysis.tender_id == item["tender_id"]
        ).first()
        if analysis:
            item["summary"] = analysis.summary or ""

    email_service = EmailService(db)
    success = email_service.send_daily_report(enterprise, scored)

    if success:
        return {"status": "sent", "recipient": enterprise.email}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Échec de l'envoi de l'email",
        )


@router.post(
    "/send-all-reports",
    summary="Envoyer tous les rapports quotidiens",
)
def send_all_reports(db: Session = Depends(get_db)):
    """POST /analysis/send-all-reports"""

    email_service = EmailService(db)
    results = email_service.send_all_daily_reports()

    return {
        "status": "completed",
        "results": results,
    }


@router.post(
    "/test-email/{enterprise_id}",
    summary="Analyse immédiate — Scraping + IA + Scoring + Email instantané",
)
def run_test_cycle_for_enterprise(enterprise_id: int, db: Session = Depends(get_db)):
    """POST /analysis/test-email/{enterprise_id}
    Cycle complet instantané : Scrape → Parse PDF → Analyse IA → Score → Email
    """
    from app.services.scraper import ScraperService
    from app.services.ai_analyzer import AIAnalyzerService

    enterprise = db.query(Enterprise).get(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=404, detail="Entreprise non trouvée")

    if not enterprise.email:
        raise HTTPException(status_code=400, detail="Aucun email configuré pour cette entreprise")

    # Bloquer si abonnement expiré
    if enterprise.subscription_plan == "PASS" and datetime.utcnow() > enterprise.created_at + timedelta(days=2):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Période d'essai terminée. Veuillez effectuer le paiement via Orange Money (+224 627 27 13 97).",
        )

    steps_log = []

    # Étape 1 : Scraping
    try:
        scraper = ScraperService(db)
        new_tenders = scraper.scrape_tenders()
        steps_log.append(f"Scraping: {len(new_tenders)} nouveaux tenders")
    except Exception as e:
        logger.error(f"Erreur scraping test: {e}")
        steps_log.append(f"Scraping: erreur ({e})")

    # Étape 2 : Parsing PDF
    try:
        from app.services.pdf_parser import PDFParserService
        pdf_parser = PDFParserService()
        parsed = 0
        from app.models.tender import Tender
        unparsed = db.query(Tender).filter(Tender.raw_text.is_(None), Tender.pdf_path.isnot(None)).all()
        for t in unparsed:
            text = pdf_parser.extract_text(t.pdf_path)
            if text:
                t.raw_text = text
                parsed += 1
        db.commit()
        steps_log.append(f"PDF parsing: {parsed} documents")
    except Exception as e:
        logger.error(f"Erreur PDF parsing test: {e}")
        steps_log.append(f"PDF parsing: erreur ({e})")

    # Étape 3 : Analyse IA
    try:
        analyzer = AIAnalyzerService(db)
        analyses = analyzer.analyze_all_pending()
        steps_log.append(f"Analyse IA: {len(analyses)} analyses")
    except Exception as e:
        logger.error(f"Erreur analyse IA test: {e}")
        steps_log.append(f"Analyse IA: erreur ({e})")

    # Étape 4 : Scoring
    scorer = ScorerService(db)
    scored = scorer.score_all_for_enterprise(enterprise)
    steps_log.append(f"Scoring: {len(scored)} résultats")

    if not scored:
        return {
            "status": "warning",
            "message": "Cycle exécuté mais aucun appel d'offres trouvé correspondant à votre profil.",
            "steps": steps_log,
        }

    # Enrichir avec résumés
    for item in scored[:10]:
        analysis = db.query(Analysis).filter(Analysis.tender_id == item["tender_id"]).first()
        if analysis:
            item["summary"] = analysis.summary or ""

    # Recommandations IA
    recos = None
    try:
        recos = analyzer.generate_budget_recommendations(enterprise, scored[:5])
    except Exception as e:
        logger.error(f"Erreur recommandations test: {e}")

    # PDF
    pdf_path = None
    try:
        report_service = ReportGeneratorService(db)
        pdf_path = report_service.generate_pdf_report(enterprise_id, recos)
    except Exception as e:
        logger.error(f"Erreur PDF test: {e}")

    # Email
    email_service = EmailService(db)
    success = email_service.send_daily_report(enterprise, scored[:10], recommendations=recos, pdf_path=pdf_path)

    if success:
        return {
            "status": "ok",
            "message": f"Rapport envoyé à {enterprise.email} avec {len(scored)} opportunités.",
            "steps": steps_log,
        }
    else:
        raise HTTPException(status_code=500, detail="Échec de l'envoi de l'email")