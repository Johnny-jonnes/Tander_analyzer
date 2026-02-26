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