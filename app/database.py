# app/database.py
"""
Configuration SQLAlchemy et gestion des sessions PostgreSQL
"""

import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Création du moteur avec pool de connexions
engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,       # Vérifie la connexion avant utilisation
    pool_recycle=3600,         # Recycle les connexions après 1h
    echo=settings.DEBUG,       # Log SQL en mode debug
)

# Factory de sessions
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Base déclarative pour tous les modèles
Base = declarative_base()


def get_db():
    """
    Dépendance FastAPI : fournit une session DB par requête.
    La session est automatiquement fermée après la requête.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db_context():
    """
    Context manager pour utilisation hors FastAPI (scheduler, scripts).
    Usage:
        with get_db_context() as db:
            db.query(...)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """
    Crée toutes les tables en base.
    À appeler au démarrage de l'application.
    """
    # Import tous les modèles pour que SQLAlchemy les enregistre
    from app.models import enterprise, tender, analysis, email_log  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("✅ Tables créées avec succès")