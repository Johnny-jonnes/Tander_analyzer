# app/schemas/subscription.py
"""
Schemas pour les abonnements NOBILIS X
"""

from datetime import datetime
from pydantic import BaseModel, Field


class SubscriptionCreate(BaseModel):
    """Création d'un abonnement"""
    enterprise_id: int
    plan: str = Field("PASS", description="Plan: PASS, ENTRY ou ELITE")


class SubscriptionResponse(BaseModel):
    """Réponse API"""
    id: int
    enterprise_id: int
    plan: str
    max_sectors: int
    price_gnf: float
    start_date: datetime
    end_date: datetime | None = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class PlanInfo(BaseModel):
    """Informations sur un plan"""
    code: str
    name: str
    description: str
    max_sectors: int
    price_gnf: float
    duration_days: int
    features: list[str]
