# app/routers/enterprises.py
"""
Endpoints pour la gestion des entreprises
"""

import logging
import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enterprise import Enterprise
from app.schemas.enterprise import EnterpriseCreate, EnterpriseResponse, EnterpriseUpdate
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)

LOGO_DIR = os.path.join("app", "static", "logos")
os.makedirs(LOGO_DIR, exist_ok=True)

router = APIRouter(
    prefix="/enterprises",
    tags=["Entreprises"],
)


@router.post(
    "",
    response_model=EnterpriseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Creer une entreprise",
)
def create_enterprise(
    enterprise_data: EnterpriseCreate,
    db: Session = Depends(get_db),
):
    existing = db.query(Enterprise).filter(Enterprise.name == enterprise_data.name).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"L'entreprise '{enterprise_data.name}' existe deja (id={existing.id})")
    enterprise = Enterprise(**enterprise_data.model_dump())
    db.add(enterprise)
    db.commit()
    db.refresh(enterprise)
    logger.info(f"Entreprise creee: {enterprise.name} (id={enterprise.id})")
    try:
        email_service = EmailService(db)
        email_service.send_welcome_email(enterprise)
    except Exception as e:
        logger.error(f"Erreur envoi email bienvenue: {e}")
    return enterprise


@router.post(
    "/{enterprise_id}/logo",
    summary="Uploader le logo d'une entreprise",
)
async def upload_logo(
    enterprise_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    enterprise = db.query(Enterprise).get(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entreprise #{enterprise_id} non trouvee")
    allowed = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Type non supporte: {file.content_type}. Utilisez PNG, JPG ou WEBP.")
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le logo ne doit pas depasser 2 Mo.")
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png"
    filename = f"logo_{enterprise_id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(LOGO_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(content)
    enterprise.logo_url = f"/static/logos/{filename}"
    db.commit()
    db.refresh(enterprise)
    logger.info(f"Logo uploade pour {enterprise.name}: {filename}")
    return {"message": "Logo uploade avec succes", "logo_url": enterprise.logo_url, "enterprise_id": enterprise.id}


@router.get("", response_model=list[EnterpriseResponse], summary="Lister les entreprises")
def list_enterprises(skip: int = 0, limit: int = 50, sector: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Enterprise)
    if sector:
        query = query.filter(Enterprise.sector.ilike(f"%{sector}%"))
    return query.offset(skip).limit(limit).all()


@router.get("/{enterprise_id}", response_model=EnterpriseResponse, summary="Detail d'une entreprise")
def get_enterprise(enterprise_id: int, db: Session = Depends(get_db)):
    enterprise = db.query(Enterprise).get(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entreprise #{enterprise_id} non trouvee")
    return enterprise


@router.put("/{enterprise_id}", response_model=EnterpriseResponse, summary="Mettre a jour une entreprise")
def update_enterprise(enterprise_id: int, update_data: EnterpriseUpdate, db: Session = Depends(get_db)):
    enterprise = db.query(Enterprise).get(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entreprise #{enterprise_id} non trouvee")
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(enterprise, field, value)
    db.commit()
    db.refresh(enterprise)
    logger.info(f"Entreprise mise a jour: {enterprise.name}")
    return enterprise


@router.delete("/{enterprise_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une entreprise")
def delete_enterprise(enterprise_id: int, db: Session = Depends(get_db)):
    enterprise = db.query(Enterprise).get(enterprise_id)
    if not enterprise:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entreprise #{enterprise_id} non trouvee")
    db.delete(enterprise)
    db.commit()
    logger.info(f"Entreprise supprimee: #{enterprise_id}")