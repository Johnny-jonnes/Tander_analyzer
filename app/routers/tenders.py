# app/routers/tenders.py
"""
Endpoints pour les appels d'offres (lecture seule - cycle automatique via scheduler)
"""

import logging
import os
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tender import Tender
from app.schemas.tender import TenderResponse, TenderListResponse
from app.services.ai_analyzer import AIAnalyzerService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tenders",
    tags=["Appels d'offres"],
)


@router.get(
    "",
    response_model=TenderListResponse,
    summary="Lister les appels d'offres",
    description="Retourne la liste paginée des appels d'offres avec filtres optionnels.",
)
def list_tenders(
    page: int = Query(1, ge=1, description="Numéro de page"),
    per_page: int = Query(20, ge=1, le=100, description="Résultats par page"),
    sector: str | None = Query(None, description="Filtrer par secteur"),
    location: str | None = Query(None, description="Filtrer par zone"),
    analyzed: bool | None = Query(None, description="Filtrer par statut d'analyse"),
    db: Session = Depends(get_db),
):
    """GET /tenders - Liste paginée"""

    query = db.query(Tender)

    if sector:
        query = query.filter(Tender.sector.ilike(f"%{sector}%"))
    if location:
        query = query.filter(Tender.location.ilike(f"%{location}%"))
    if analyzed is not None:
        query = query.filter(Tender.is_analyzed == analyzed)

    total = query.count()
    offset = (page - 1) * per_page
    tenders = query.order_by(Tender.created_at.desc()).offset(offset).limit(per_page).all()

    return TenderListResponse(
        total=total,
        page=page,
        per_page=per_page,
        tenders=tenders,
    )


@router.get(
    "/{tender_id}",
    response_model=TenderResponse,
    summary="Détail d'un appel d'offres",
)
def get_tender(
    tender_id: int,
    db: Session = Depends(get_db),
):
    """GET /tenders/{id}"""
    tender = db.query(Tender).get(tender_id)
    if not tender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender #{tender_id} non trouvé",
        )
    return tender


@router.get(
    "/enterprises/{enterprise_id}/report/pdf",
    summary="Télécharger le rapport PDF personnalisé",
    tags=["Rapports"],
)
def download_enterprise_pdf(
    enterprise_id: int,
    db: Session = Depends(get_db),
):
    """GET /enterprises/{id}/report/pdf - Télécharger PDF"""
    from app.models.enterprise import Enterprise
    from app.services.report_generator import ReportGeneratorService
    from app.services.scorer import ScorerService

    enterprise = db.query(Enterprise).get(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entreprise #{enterprise_id} non trouvée")

    recommendations = None
    try:
        scorer = ScorerService(db)
        scored_list = scorer.score_all_for_enterprise(enterprise)
        analyzer = AIAnalyzerService(db)
        recommendations = analyzer.generate_budget_recommendations(enterprise, scored_list[:5])
    except Exception as e:
        logger.error(f"Erreur recommandations PDF: {e}")

    report_service = ReportGeneratorService(db)
    pdf_path = report_service.generate_pdf_report(enterprise_id, recommendations=recommendations)

    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erreur génération du PDF")

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=os.path.basename(pdf_path),
        headers={"Content-Disposition": f"attachment; filename={os.path.basename(pdf_path)}"},
    )
