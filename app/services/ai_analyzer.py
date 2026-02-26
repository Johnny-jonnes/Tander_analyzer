# app/services/ai_analyzer.py
"""
Service d'analyse IA - Utilise l'API Groq pour analyser
les appels d'offres, générer des résumés et extraire
les informations structurées.
"""

import json
import logging
import time
from datetime import datetime

from openai import OpenAI, RateLimitError  # SDK compatible avec Groq
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.tender import Tender
from app.models.analysis import Analysis

logger = logging.getLogger(__name__)
settings = get_settings()


class AIAnalyzerService:
    """Service d'analyse par IA des appels d'offres"""

    def __init__(self, db: Session):
        self.db = db
        self.client = OpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url=settings.GROQ_BASE_URL,
        )
        self.model = settings.GROQ_MODEL

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=3, min=15, max=120),
        retry=retry_if_exception_type((RateLimitError, Exception)),
        before_sleep=lambda retry_state: logger.warning(
            f"Retry {retry_state.attempt_number}/4 - Appel Groq echoue, attente..."
        ),
    )
    def _call_groq(self, system_prompt: str, user_prompt: str, max_tokens: int = 1500) -> str:
        """
        Appel a l'API Groq avec retry automatique et gestion du rate limit.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            content = response.choices[0].message.content
            logger.info(f"Reponse Groq recue ({response.usage.total_tokens} tokens)")
            return content
        except RateLimitError as e:
            logger.warning(f"Rate limit Groq atteint - pause de 30s avant retry: {e}")
            time.sleep(30)
            raise

    def generate_summary(self, text: str) -> str:
        """
        Génère un résumé de max 200 mots de l'appel d'offres.
        """
        system_prompt = (
            "Tu es un expert en analyse d'appels d'offres publics. "
            "Tu dois fournir des résumés clairs, concis et professionnels en français."
        )

        user_prompt = f"""Résume cet appel d'offres en maximum 200 mots.
Le résumé doit inclure :
- L'objet du marché
- Le commanditaire
- Les conditions principales
- La date limite si mentionnée

Texte de l'appel d'offres :
---
{text[:8000]}
---

Résumé (max 200 mots) :"""

        return self._call_groq(system_prompt, user_prompt, max_tokens=500)

    def extract_structured_data(self, text: str) -> dict:
        """
        Extrait les informations structurées de l'appel d'offres.
        Retourne un dict avec : sector, estimated_budget, location, deadline
        """
        system_prompt = (
            "Tu es un système d'extraction de données. "
            "Tu dois extraire les informations demandées et les retourner "
            "strictement au format JSON, sans aucun texte supplémentaire."
        )

        user_prompt = f"""Analyse ce texte d'appel d'offres et extrais les informations suivantes.
Retourne UNIQUEMENT un objet JSON valide avec ces clés :

{{
    "sector": "secteur d'activité parmi: Agriculture Pêche & Développement Rural, Agroalimentaire & Transformation, Communication Médias & Publicité, Éducation & Formation, Energie Eau & Environnement, Environnement Forêts & Changement Climatique, Études & Consultances, Fournitures & Équipements, Gouvernance & Administration Publique, Immobilier & Aménagement Urbain, Industrie & Commerce, Informatique & Télécommunications, Mines & Ressources Naturelles, QSE - Qualité Sécurité & Environnement, Santé & Paramédical, Sécurité & Protection, Services Généraux & Prestations diverses, Tourisme Culture & Loisirs, Transport & Logistique, Travaux Publics & Construction",
    "estimated_budget": 0,
    "location": "lieu/zone géographique",
    "deadline": "date limite au format YYYY-MM-DD ou null"
}}

Règles :
- sector : détermine le secteur le plus pertinent
- estimated_budget : montant en USD (0 si non mentionné), nombre uniquement
- location : ville, province ou pays mentionné
- deadline : date au format YYYY-MM-DD, ou null si non trouvée

Texte :
---
{text[:8000]}
---

JSON :"""

        try:
            response = self._call_groq(system_prompt, user_prompt, max_tokens=300)

            # Nettoyage de la réponse pour extraire le JSON
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]

            data = json.loads(response.strip())

            # Validation et nettoyage des valeurs
            return {
                "sector": str(data.get("sector", "Non déterminé"))[:255],
                "estimated_budget": float(data.get("estimated_budget", 0) or 0),
                "location": str(data.get("location", "Non spécifié"))[:255],
                "deadline": data.get("deadline"),
            }

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.error(f"❌ Erreur parsing JSON Groq: {e}")
            return {
                "sector": "Non déterminé",
                "estimated_budget": 0.0,
                "location": "Non spécifié",
                "deadline": None,
            }

    def _analyze_locally(self, tender: Tender) -> dict:
        """
        Analyse locale sans API : génère un résumé et extrait le secteur
        directement depuis le titre/description, sans appel Groq.
        Utilisée quand le texte est trop court pour justifier un appel IA.
        """
        title = tender.title or ""
        desc = tender.description or ""
        text_combined = f"{title}. {desc}".strip()

        # Résumé simple basé sur le titre et la description
        if desc and len(desc) > 30:
            summary = f"Appel d'offres : {title}. {desc[:300]}"
        else:
            summary = f"Appel d'offres : {title}. Consultez la source pour les details complets."

        # Secteur : priorité au secteur déjà détecté par le scraper
        sector = tender.sector or "Services Généraux & Prestations diverses"

        # Localisation : priorité à la valeur existante
        location = tender.location or "Guinée"

        return {
            "summary": summary[:500],
            "sector": sector,
            "estimated_budget": tender.estimated_budget or 0.0,
            "location": location,
            "deadline": None,
        }

    def analyze_tender(self, tender: Tender) -> Analysis | None:
        """
        Analyse complète d'un appel d'offres.
        - Texte court (< 300 car.) : analyse locale sans appel Groq
        - Texte long              : analyse IA via Groq
        """
        try:
            text = tender.raw_text or tender.description or tender.title
            if not text or len(text) < 20:
                logger.warning(f"Texte insuffisant pour tender #{tender.id}")
                return None

            logger.info(f"Analyse tender #{tender.id}: {tender.title[:60]}")

            # ── Décision : IA ou local ? ────────────────────────────────
            use_ai = len(text) >= 300  # Seulement si texte substantiel

            if use_ai:
                logger.info(f"Appel Groq pour tender #{tender.id} ({len(text)} car.)")
                summary = self.generate_summary(text)
                structured = self.extract_structured_data(text)
            else:
                logger.info(f"Analyse locale pour tender #{tender.id} ({len(text)} car. — pas d'appel Groq)")
                local = self._analyze_locally(tender)
                summary = local["summary"]
                structured = {
                    "sector": local["sector"],
                    "estimated_budget": local["estimated_budget"],
                    "location": local["location"],
                    "deadline": local["deadline"],
                }

            # Mise à jour du tender
            tender.sector = tender.sector or structured.get("sector")
            tender.estimated_budget = tender.estimated_budget or structured.get("estimated_budget")
            tender.location = tender.location or structured.get("location")

            deadline_str = structured.get("deadline")
            if deadline_str:
                try:
                    tender.deadline = datetime.strptime(deadline_str, "%Y-%m-%d")
                except ValueError:
                    pass

            tender.is_analyzed = True

            # Créer l'analyse
            analysis = Analysis(
                tender_id=tender.id,
                summary=summary,
                score=0.0,
                explanation="Analyse terminee, en attente de scoring",
                extracted_sector=structured.get("sector"),
                extracted_budget=structured.get("estimated_budget"),
                extracted_location=structured.get("location"),
                extracted_deadline=structured.get("deadline"),
            )

            self.db.add(analysis)
            self.db.flush()
            logger.info(f"Analyse creee pour tender #{tender.id} ({'IA' if use_ai else 'local'})")
            return analysis

        except Exception as e:
            logger.error(f"Erreur analyse tender #{tender.id}: {e}")
            return None



    def analyze_all_pending(self) -> list[Analysis]:
        """
        Analyse tous les tenders non encore analyses.
        Traitement par batch avec pause pour respecter le rate limit Groq.
        """
        pending_tenders = self.db.query(Tender).filter(
            Tender.is_analyzed == False  # noqa: E712
        ).all()

        logger.info(f"{len(pending_tenders)} tenders en attente d'analyse")

        analyses = []
        batch_size = 5  # 5 tenders par batch
        delay_between = 4   # 4s entre chaque tender
        delay_batch = 20    # 20s entre chaque batch (respecter quota Groq)

        for batch_idx in range(0, len(pending_tenders), batch_size):
            batch = pending_tenders[batch_idx:batch_idx + batch_size]
            logger.info(f"Batch {batch_idx // batch_size + 1}: analyse de {len(batch)} tenders")

            for i, tender in enumerate(batch):
                analysis = self.analyze_tender(tender)
                if analysis:
                    analyses.append(analysis)
                # Pause entre chaque appel (sauf le dernier du batch)
                if i < len(batch) - 1:
                    time.sleep(delay_between)

            self.db.commit()
            logger.info(f"Batch termine : {len(analyses)} analyses au total")

            # Pause entre batches (sauf apres le dernier)
            if batch_idx + batch_size < len(pending_tenders):
                logger.info(f"Pause de {delay_batch}s avant le prochain batch (rate limit Groq)...")
                time.sleep(delay_batch)

        logger.info(f"{len(analyses)} analyses terminees")
        return analyses

    def generate_budget_recommendations(self, enterprise, top_scored: list[dict]) -> list[str]:
        """Genere 3-5 recommandations personnalisees basees sur le budget et le profil."""
        try:
            opps = ""
            for i, item in enumerate(top_scored[:5], 1):
                opps += f"{i}. {item.get('tender_title', 'N/A')[:80]} (Score: {item.get('score', 0):.0f}/100)\n"

            system_prompt = "Tu es un conseiller expert en marches publics. Tu donnes des recommandations concretes et actionnables en francais. Tu ne dois JAMAIS utiliser d'emojis."
            user_prompt = f"""Profil entreprise :
- Nom : {enterprise.name}
- Secteur : {enterprise.sector}
- Budget : {enterprise.min_budget} - {enterprise.max_budget} USD
- Zones : {enterprise.zones or 'Non precisees'}
- Experience : {enterprise.experience_years} ans

Meilleures opportunites :
{opps or 'Aucune.'}

Donne exactement 3 a 5 recommandations courtes (max 2 phrases chacune). Pas d'introduction, pas de conclusion, juste une liste numerotee."""

            response = self._call_groq(system_prompt, user_prompt, max_tokens=600)
            recommendations = []
            for line in response.strip().split("\n"):
                line = line.strip()
                if line and line[0].isdigit():
                    clean = line.lstrip("0123456789").lstrip(".").lstrip(")").strip()
                    if clean:
                        recommendations.append(clean)
            return recommendations[:5] if recommendations else [response.strip()]
        except Exception as e:
            logger.error(f"Erreur recommandations: {e}")
            return [
                "Consultez regulierement les nouveaux appels d'offres pour ne pas manquer d'opportunites.",
                "Preparez vos dossiers de candidature a l'avance pour reagir rapidement.",
                "Adaptez votre budget previsionnel aux fourchettes des appels d'offres de votre secteur.",
            ]