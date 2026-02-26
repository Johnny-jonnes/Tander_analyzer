# app/models/analysis.py
"""
Modèle Analysis - Résultats d'analyse IA des appels d'offres
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, DateTime, Text, ForeignKey
)
from sqlalchemy.orm import relationship
from app.database import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tender_id = Column(
        Integer,
        ForeignKey("tenders.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    enterprise_id = Column(
        Integer,
        ForeignKey("enterprises.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    summary = Column(Text, nullable=True, comment="Résumé max 200 mots")
    score = Column(Float, nullable=False, default=0.0, comment="Score 0-100")
    explanation = Column(Text, nullable=True, comment="Explication détaillée du score")
    extracted_sector = Column(Text, nullable=True)
    extracted_budget = Column(Float, nullable=True)
    extracted_location = Column(Text, nullable=True)
    extracted_deadline = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relations
    tender = relationship("Tender", back_populates="analysis")

    def __repr__(self):
        return f"<Analysis(tender_id={self.tender_id}, score={self.score})>"