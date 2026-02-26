# app/models/enterprise.py
"""
Modèle Enterprise - Entreprises inscrites au système
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, ARRAY
)
from sqlalchemy.orm import relationship
from app.database import Base


class Enterprise(Base):
    __tablename__ = "enterprises"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    sector = Column(String(255), nullable=False, index=True)
    min_budget = Column(Float, nullable=False, default=0.0)
    max_budget = Column(Float, nullable=False, default=0.0)
    zones = Column(Text, nullable=True, comment="Zones géographiques séparées par des virgules")
    experience_years = Column(Integer, nullable=False, default=0)
    technical_capacity = Column(Text, nullable=True, comment="Description des capacités techniques")
    email = Column(String(255), nullable=True, comment="Email de contact pour notifications")
    specific_keywords = Column(Text, nullable=True, comment="Mots-clés spécifiques recherchés")
    exclude_keywords = Column(Text, nullable=True, comment="Mots-clés à exclure")
    logo_url = Column(String(500), nullable=True, comment="URL du logo de l'entreprise")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    email_logs = relationship("EmailLog", back_populates="enterprise", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Enterprise(id={self.id}, name='{self.name}', sector='{self.sector}')>"

    @property
    def zones_list(self) -> list[str]:
        """Retourne les zones sous forme de liste"""
        if not self.zones:
            return []
        return [z.strip().lower() for z in self.zones.split(",")]

    @property
    def budget_range(self) -> tuple[float, float]:
        """Retourne la fourchette budgétaire"""
        return (self.min_budget, self.max_budget)