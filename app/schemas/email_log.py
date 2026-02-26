# app/schemas/email_log.py
"""
Schemas pour les logs email
"""

from datetime import datetime
from pydantic import BaseModel


class EmailLogResponse(BaseModel):
    """Réponse log email"""
    id: int
    enterprise_id: int
    tender_id: int | None = None
    recipient_email: str
    subject: str | None = None
    status: str
    error_message: str | None = None
    sent_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True