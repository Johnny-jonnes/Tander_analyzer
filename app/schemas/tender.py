# app/schemas/tender.py
"""
Schemas pour les appels d'offres
"""

from datetime import datetime
from pydantic import BaseModel, Field


class TenderResponse(BaseModel):
    """Réponse pour un appel d'offres"""
    id: int
    title: str
    description: str | None = None
    sector: str | None = None
    estimated_budget: float | None = None
    location: str | None = None
    deadline: datetime | None = None
    source_url: str
    is_analyzed: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class TenderListResponse(BaseModel):
    """Liste paginée d'appels d'offres"""
    total: int
    page: int
    per_page: int
    tenders: list[TenderResponse]