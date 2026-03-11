# app/models/subscription.py
"""
Modèle Subscription — Plans d'abonnement NOBILIS X
Plans : PASS (essai 2 jours), ENTRY (1.5M GNF/mois), ELITE (4.5M GNF/mois)
"""

from datetime import datetime, timedelta
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text
)
from sqlalchemy.orm import relationship
from app.database import Base


# Définition des plans
SUBSCRIPTION_PLANS = {
    "PASS": {
        "name": "NOBILIS PASS",
        "description": "Essai Gratuit 2 Jours — Votre laissez-passer vers l'avance.",
        "max_sectors": 3,
        "price_gnf": 0,
        "duration_days": 2,
        "features": [
            "Veille sur 3 secteurs",
            "Alertes quotidiennes",
            "Notifications par email",
        ],
    },
    "ENTRY": {
        "name": "NOBILIS ENTRY",
        "description": "Idéal pour démarrer et tester le système.",
        "max_sectors": 5,
        "price_gnf": 1_500_000,
        "duration_days": 30,
        "features": [
            "Veille sur 5 secteurs clés de votre choix",
            "Alertes quotidiennes centralisées",
            "Notifications en temps réel par email",
            "Idéal pour démarrer et tester le système",
        ],
    },
    "ELITE": {
        "name": "NOBILIS ELITE ★",
        "description": "Système Expert complet — Analyse approfondie de documents.",
        "max_sectors": 20,
        "price_gnf": 3_500_000,
        "duration_days": 30,
        "features": [
            "Système Expert complet — Analyse approfondie de documents",
            "Conseils stratégiques personnalisés",
            "Indice de compatibilité (0-100) pour chaque appel d'offres",
            "Couverture totale des 20 secteurs économiques",
            "Rapport stratégique personnalisé chaque matin à 8h00",
            "Support prioritaire dédié",
        ],
    },
}


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    enterprise_id = Column(
        Integer,
        ForeignKey("enterprises.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan = Column(
        String(20),
        nullable=False,
        default="PASS",
        comment="PASS | ENTRY | ELITE",
    )
    max_sectors = Column(Integer, nullable=False, default=3)
    price_gnf = Column(Float, nullable=False, default=0.0, comment="Prix en GNF/mois")
    start_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    end_date = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relations
    enterprise = relationship("Enterprise", back_populates="subscriptions")

    def __repr__(self):
        return f"<Subscription(enterprise_id={self.enterprise_id}, plan='{self.plan}', active={self.is_active})>"

    @property
    def is_expired(self) -> bool:
        if not self.end_date:
            return False
        return datetime.utcnow() > self.end_date

    @property
    def plan_info(self) -> dict:
        return SUBSCRIPTION_PLANS.get(self.plan, SUBSCRIPTION_PLANS["PASS"])
