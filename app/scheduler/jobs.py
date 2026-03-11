# app/scheduler/jobs.py
"""
Scheduler APScheduler - NOBILIS X
- 7h : Cycle complet quotidien (tous les plans actifs)
- Toutes les 2h (8h-20h) : Alertes temps reel pour ELITE
"""

import logging
from datetime import datetime, timedelta

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
    timezone="Africa/Conakry",
    job_defaults={
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 3600,
    },
)


def job_daily_cycle():
    """
    Job planifie a 7h : Scraping + Parsing PDF + Analyse IA + Envoi emails.
    Cycle complet pour TOUS les plans actifs (PASS, ENTRY, ELITE).
    """
    logger.info("=" * 60)
    logger.info(f"NOBILIS X — CYCLE QUOTIDIEN DEMARRE | {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)

    try:
        with get_db_context() as db:
            # Etape 1 : Scraping
            logger.info("Etape 1/4 : Scraping des appels d'offres...")
            scraper = ScraperService(db)
            new_tenders = scraper.scrape_tenders()
            logger.info(f"{len(new_tenders)} nouveaux tenders scrapes")

            # Etape 2 : Parsing PDF
            logger.info("Etape 2/4 : Extraction texte des PDFs...")
            pdf_parser = PDFParserService()
            parsed_count: int = 0
            for tender in new_tenders:
                if tender.pdf_path:
                    text = pdf_parser.extract_text(tender.pdf_path)
                    if text:
                        tender.raw_text = text
                        parsed_count += 1

            db.commit()
            logger.info(f"{parsed_count} PDFs parses")

            # Etape 3 : Analyse IA
            logger.info("Etape 3/4 : Analyse IA...")
            analyzer = AIAnalyzerService(db)
            analyses = analyzer.analyze_all_pending()
            logger.info(f"{len(analyses)} analyses terminees")

            # Etape 4 : Envoi des emails
            logger.info("Etape 4/4 : Envoi des rapports quotidiens...")
            email_service = EmailService(db)
            results = email_service.send_all_daily_reports()
            logger.info(f"Resultats envoi: {results}")

    except Exception as e:
        logger.error(f"ERREUR CYCLE QUOTIDIEN: {e}", exc_info=True)

    logger.info(f"NOBILIS X — CYCLE QUOTIDIEN TERMINE | {datetime.utcnow().isoformat()}")


def job_elite_realtime_alert():
    """
    Job ELITE temps reel — Toutes les 2h pendant les heures ouvrables.
    1. Scrape les sources pour de nouveaux tenders
    2. Analyse IA rapide
    3. Score uniquement pour les comptes ELITE
    4. Envoie une alerte flash si score >= 70 sur un nouveau tender
    """
    logger.info("=" * 60)
    logger.info(f"NOBILIS X — ALERTE ELITE TEMPS REEL | {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)

    try:
        with get_db_context() as db:
            from app.models.enterprise import Enterprise
            from app.models.analysis import Analysis
            from app.services.scorer import ScorerService

            # Etape 1 : Scraping rapide
            scraper = ScraperService(db)
            new_tenders = scraper.scrape_tenders()
            logger.info(f"ELITE RT: {len(new_tenders)} nouveaux tenders")

            if not new_tenders:
                logger.info("ELITE RT: Aucun nouveau tender, pas d'alerte")
                return

            # Etape 2 : Analyse IA des nouveaux tenders
            pdf_parser = PDFParserService()
            for tender in new_tenders:
                if tender.pdf_path:
                    text = pdf_parser.extract_text(tender.pdf_path)
                    if text:
                        tender.raw_text = text
            db.commit()

            analyzer = AIAnalyzerService(db)
            analyses = analyzer.analyze_all_pending()
            logger.info(f"ELITE RT: {len(analyses)} analyses rapides")

            # Etape 3 : Cibler uniquement les ELITE
            elite_enterprises = db.query(Enterprise).filter(
                Enterprise.email.isnot(None),
                Enterprise.subscription_plan == "ELITE",
            ).all()

            if not elite_enterprises:
                logger.info("ELITE RT: Aucun client ELITE actif")
                return

            logger.info(f"ELITE RT: {len(elite_enterprises)} clients ELITE a alerter")

            scorer = ScorerService(db)
            email_service = EmailService(db)
            alerts_sent: int = 0

            for enterprise in elite_enterprises:
                try:
                    scored = scorer.score_all_for_enterprise(enterprise)
                    # Filtrer uniquement les excellents (>= 70)
                    top_matches = [s for s in scored if s["score"] >= 70]

                    if not top_matches:
                        continue

                    # Enrichir avec les resumés
                    for item in top_matches[:5]:
                        analysis = db.query(Analysis).filter(
                            Analysis.tender_id == item["tender_id"]
                        ).first()
                        if analysis:
                            item["summary"] = analysis.summary or ""

                    success = email_service.send_daily_report(
                        enterprise, top_matches[:5]
                    )
                    if success:
                        alerts_sent += 1
                        logger.info(f"ELITE RT: Alerte envoyee a {enterprise.name} ({len(top_matches)} matchs)")
                except Exception as e:
                    logger.error(f"ELITE RT: Erreur pour {enterprise.name}: {e}")

            logger.info(f"ELITE RT: {alerts_sent} alertes envoyees")

    except Exception as e:
        logger.error(f"ERREUR ALERTE ELITE: {e}", exc_info=True)

    logger.info(f"NOBILIS X — ALERTE ELITE TERMINEE | {datetime.utcnow().isoformat()}")


def scheduler_event_listener(event):
    if event.exception:
        logger.error(f"Job {event.job_id} a echoue: {event.exception}")
    else:
        logger.info(f"Job {event.job_id} execute avec succes")


def init_scheduler():
    """
    Initialise le scheduler avec :
    - Job quotidien a 7h (tous les plans)
    - Job temps reel toutes les 2h de 8h a 20h (ELITE uniquement)
    """
    scheduler.add_listener(scheduler_event_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # Job 1 : Cycle complet quotidien a 7h
    scheduler.add_job(
        func=job_daily_cycle,
        trigger=CronTrigger(hour=settings.SCRAPE_SCHEDULE_HOUR, minute=0),
        id="daily_cycle",
        name="NOBILIS X — Cycle quotidien (tous plans)",
        replace_existing=True,
    )

    # Job 2 : Alertes temps reel ELITE (toutes les 2h, 8h-20h)
    scheduler.add_job(
        func=job_elite_realtime_alert,
        trigger=CronTrigger(hour="8-20/2", minute=30),
        id="elite_realtime",
        name="NOBILIS X — Alertes temps reel ELITE",
        replace_existing=True,
    )

    scheduler.start()

    logger.info("Scheduler demarre:")
    for job in scheduler.get_jobs():
        logger.info(f"   {job.name} | Prochain run: {job.next_run_time}")

    return scheduler


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler arrete")