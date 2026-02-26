# app/models/email_log.py
"""
Modèle EmailLog - Journal des emails envoyés
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, ForeignKey
)
from sqlalchemy.orm import relationship
from app.database import Base


class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    enterprise_id = Column(
        Integer,
        ForeignKey("enterprises.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tender_id = Column(
        Integer,
        ForeignKey("tenders.id", ondelete="SET NULL"),
        nullable=True,
    )
    recipient_email = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=True)
    status = Column(
        String(50),
        nullable=False,
        default="pending",
        comment="pending | sent | failed",
    )
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relations
    enterprise = relationship("Enterprise", back_populates="email_logs")

    def __repr__(self):
        return f"<EmailLog(enterprise_id={self.enterprise_id}, status='{self.status}')>"