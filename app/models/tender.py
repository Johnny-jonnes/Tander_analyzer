# app/models/tender.py
"""
Modèle Tender - Appels d'offres scrapés
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, Boolean
)
from sqlalchemy.orm import relationship
from app.database import Base


class Tender(Base):
    __tablename__ = "tenders"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(500), nullable=False, index=True)
    description = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True, comment="Texte brut extrait du PDF")
    sector = Column(String(255), nullable=True, index=True)
    estimated_budget = Column(Float, nullable=True)
    location = Column(String(255), nullable=True)
    deadline = Column(DateTime, nullable=True)
    source_url = Column(String(1000), nullable=False, unique=True)
    pdf_path = Column(String(500), nullable=True, comment="Chemin local du PDF téléchargé")
    is_analyzed = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relations
    analysis = relationship("Analysis", back_populates="tender", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Tender(id={self.id}, title='{self.title[:50]}...')>"

    @property
    def is_expired(self) -> bool:
        """Vérifie si l'appel d'offres est expiré"""
        if not self.deadline:
            return False
        return datetime.utcnow() > self.deadline