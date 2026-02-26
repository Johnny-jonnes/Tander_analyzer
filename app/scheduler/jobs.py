# app/scheduler/jobs.py
"""
Scheduler APScheduler - Job unique automatisé.
- 7h (Conakry) : Scraping + Analyse IA + Envoi emails
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from app.config import get_settings
from app.database import get_db_context
from app.services.scraper import ScraperService
from app.services.pdf_parser import PDFParserService
from app.services.ai_analyzer import AIAnalyzerService
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)
settings = get_settings()

# Instance globale du scheduler
scheduler = BackgroundScheduler(
    timezone="Africa/Conakry",  # UTC+0 — Conakry, Guinée
    job_defaults={
        "coalesce": True,            # Fusionner les exécutions manquées
        "max_instances": 1,          # Une seule instance par job
        "misfire_grace_time": 3600,  # 1h de grâce
    },
)


def job_daily_cycle():
    """
    Job planifié à 7h : Scraping + Parsing PDF + Analyse IA + Envoi emails.
    Cycle complet exécuté dans un context manager pour la session DB.
    """
    logger.info("=" * 60)
    logger.info(f"🕐 CYCLE QUOTIDIEN DÉMARRÉ | {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)

    try:
        with get_db_context() as db:
            # Étape 1 : Scraping
            logger.info("📡 Étape 1/4 : Scraping des appels d'offres...")
            scraper = ScraperService(db)
            new_tenders = scraper.scrape_tenders()
            logger.info(f"✅ {len(new_tenders)} nouveaux tenders scrapés")

            # Étape 2 : Parsing PDF
            logger.info("📄 Étape 2/4 : Extraction texte des PDFs...")
            pdf_parser = PDFParserService()
            parsed_count = 0
            for tender in new_tenders:
                if tender.pdf_path:
                    text = pdf_parser.extract_text(tender.pdf_path)
                    if text:
                        tender.raw_text = text
                        parsed_count += 1

            db.commit()
            logger.info(f"✅ {parsed_count} PDFs parsés")

            # Étape 3 : Analyse IA
            logger.info("🤖 Étape 3/4 : Analyse IA...")
            analyzer = AIAnalyzerService(db)
            analyses = analyzer.analyze_all_pending()
            logger.info(f"✅ {len(analyses)} analyses terminées")

            # Étape 4 : Envoi des emails
            logger.info("📧 Étape 4/4 : Envoi des rapports quotidiens...")
            email_service = EmailService(db)
            results = email_service.send_all_daily_reports()
            logger.info(f"📧 Résultats envoi: {results}")

    except Exception as e:
        logger.error(f"❌ ERREUR CYCLE QUOTIDIEN: {e}", exc_info=True)

    logger.info(f"🏁 CYCLE QUOTIDIEN TERMINÉ | {datetime.utcnow().isoformat()}")


def scheduler_event_listener(event):
    """Listener pour les événements du scheduler"""
    if event.exception:
        logger.error(f"❌ Job {event.job_id} a échoué: {event.exception}")
    else:
        logger.info(f"✅ Job {event.job_id} exécuté avec succès")


def init_scheduler():
    """
    Initialise et démarre le scheduler avec le job quotidien à 7h.
    """
    # Listener d'événements
    scheduler.add_listener(scheduler_event_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # Job unique : Cycle complet à 7h (heure de Conakry)
    scheduler.add_job(
        func=job_daily_cycle,
        trigger=CronTrigger(hour=settings.SCRAPE_SCHEDULE_HOUR, minute=0),
        id="daily_cycle",
        name="Cycle quotidien 7h — Scraping + IA + Emails",
        replace_existing=True,
    )

    scheduler.start()

    logger.info("⏰ Scheduler démarré:")
    for job in scheduler.get_jobs():
        logger.info(f"   📌 {job.name} | Prochain run: {job.next_run_time}")

    return scheduler


def shutdown_scheduler():
    """Arrête proprement le scheduler"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("⏰ Scheduler arrêté")