# app/schemas/enterprise.py
"""
Schemas pour les entreprises
"""

from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class EnterpriseBase(BaseModel):
    """Champs communs"""
    name: str = Field(..., min_length=2, max_length=255, description="Nom de l'entreprise")
    sector: str = Field(..., min_length=2, max_length=255, description="Secteur d'activité")
    min_budget: float = Field(0.0, ge=0, description="Budget minimum en USD")
    max_budget: float = Field(0.0, ge=0, description="Budget maximum en USD")
    zones: str | None = Field(None, description="Zones géographiques (séparées par virgules)")
    experience_years: int = Field(0, ge=0, description="Années d'expérience")
    technical_capacity: str | None = Field(None, description="Capacités techniques")
    email: str | None = Field(None, description="Email de contact")
    specific_keywords: str | None = Field(None, description="Mots-clés spécifiques (séparés par virgules)")
    exclude_keywords: str | None = Field(None, description="Mots-clés à exclure (séparés par virgules)")
    logo_url: str | None = Field(None, description="URL du logo de l'entreprise")

    @field_validator("max_budget")
    @classmethod
    def validate_budget_range(cls, v, info):
        min_b = info.data.get("min_budget", 0)
        if v > 0 and min_b > 0 and v < min_b:
            raise ValueError("max_budget doit être supérieur ou égal à min_budget")
        return v


class EnterpriseCreate(EnterpriseBase):
    """Création d'une entreprise"""
    pass


class EnterpriseUpdate(BaseModel):
    """Mise à jour partielle"""
    name: str | None = None
    sector: str | None = None
    min_budget: float | None = Field(None, ge=0)
    max_budget: float | None = Field(None, ge=0)
    zones: str | None = None
    experience_years: int | None = Field(None, ge=0)
    technical_capacity: str | None = None
    email: str | None = None
    specific_keywords: str | None = None
    exclude_keywords: str | None = None
    logo_url: str | None = None


class EnterpriseResponse(EnterpriseBase):
    """Réponse API"""
    id: int
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True