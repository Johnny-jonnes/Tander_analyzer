# app/schemas/analysis.py
"""
Schemas pour les analyses
"""

from datetime import datetime
from pydantic import BaseModel, Field
from app.schemas.tender import TenderResponse


class AnalysisResponse(BaseModel):
    """Réponse d'analyse"""
    id: int
    tender_id: int
    enterprise_id: int | None = None
    summary: str | None = None
    score: float = 0.0
    explanation: str | None = None
    extracted_sector: str | None = None
    extracted_budget: float | None = None
    extracted_location: str | None = None
    extracted_deadline: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class AnalysisDetailResponse(BaseModel):
    """Analyse avec détail du tender"""
    analysis: AnalysisResponse
    tender: TenderResponse