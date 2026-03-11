# app/main.py
"""
NOBILIS X — Système Expert de Veille & Analyse des Appels d'Offres.
L'intelligence des marchés. La noblesse de l'avance.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.routers import enterprises, tenders, analyses
from app.scheduler.jobs import init_scheduler, shutdown_scheduler

# Configuration du logging
import os
log_handlers = [logging.StreamHandler()]
try:
    os.makedirs("logs", exist_ok=True)
    log_handlers.append(logging.FileHandler("logs/tender_analyzer.log", mode="a", encoding="utf-8"))
except Exception:
    pass  # Pas de fichier log si le dossier n'est pas accessible

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=log_handlers,
)

logger = logging.getLogger(__name__)
settings = get_settings()


# === Lifespan : startup + shutdown ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestion du cycle de vie de l'application"""
    # --- STARTUP ---
    logger.info("🚀 Démarrage de NOBILIS X")
    logger.info(f"   Version: {settings.APP_VERSION}")
    logger.info(f"   Debug: {settings.DEBUG}")

    # Initialiser la base de données
    init_db()
    logger.info("✅ Base de données initialisée")

    # Démarrer le scheduler
    init_scheduler()
    logger.info("✅ Scheduler initialisé")

    logger.info("🟢 Application prête")

    yield  # L'application tourne ici

    # --- SHUTDOWN ---
    logger.info("🔴 Arrêt de l'application...")
    shutdown_scheduler()
    logger.info("👋 Application arrêtée proprement")


# === Création de l'application FastAPI ===
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## 🏆 NOBILIS X — Système Expert de Veille & Analyse

L'intelligence des marchés. La noblesse de l'avance.
Fait en Guinée. Conçu pour que les meilleurs gagnent.

### Fonctionnalités :
- **Surveillance centralisée 24h/24** des sources officielles (JAO, DGCMP, TELEMO)
- **Analyse instantanée de documents** (50+ pages) via IA
- **Indice de Crédibilité (0-100)** pour cibler les marchés gagnables
- **Filtrage de précision** sur 20 secteurs spécialisés
- **Rapport personnalisé chaque matin à 8h** directement en boîte mail

### Endpoints principaux :
- `POST /enterprises` — Enregistrer une entreprise
- `GET /tenders` — Lister les appels d'offres
- `GET /analysis/{enterprise_id}` — Analyses avec Indice de Crédibilité
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# === Middleware CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Montage des fichiers statiques ===
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# === Gestion globale des erreurs ===
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handler global pour les erreurs non gérées"""
    logger.error(f"❌ Erreur non gérée: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Erreur interne du serveur",
            "error": str(exc) if settings.DEBUG else "Contactez l'administrateur",
        },
    )


# === Enregistrement des routers ===
app.include_router(enterprises.router, prefix="/api/v1")
app.include_router(tenders.router, prefix="/api/v1")
app.include_router(analyses.router, prefix="/api/v1")


# === Endpoints utilitaires ===
@app.get("/", tags=["Root"])
def root():
    """Page d'accueil - Sert le frontend"""
    import os
    index_path = os.path.join("app", "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "status": "running",
    }


@app.get("/health", tags=["Health"])
def health_check():
    """Health check pour Docker et monitoring"""
    from app.database import engine

    try:
        # Vérifier la connexion DB
        with engine.connect() as conn:
            conn.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "healthy",
        "database": db_status,
        "version": settings.APP_VERSION,
    }


@app.get("/scheduler/status", tags=["Scheduler"])
def scheduler_status():
    """Vérifie le statut du scheduler"""
    from app.scheduler.jobs import scheduler

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
        })

    return {
        "running": scheduler.running,
        "jobs": jobs,
    }