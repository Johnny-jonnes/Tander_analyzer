# app/services/scorer.py
"""
Service de scoring - Calcule un score de correspondance (0-100)
entre un appel d'offres et une entreprise.
Critères : secteur, budget, zone géographique, expérience.
"""

import logging
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.models.enterprise import Enterprise
from app.models.tender import Tender
from app.models.analysis import Analysis

logger = logging.getLogger(__name__)


class ScorerService:
    """Calcul du score de correspondance tender/entreprise"""

    # Pondérations des critères
    WEIGHTS = {
        "sector": 35,       # 35% - Correspondance sectorielle
        "budget": 30,       # 30% - Adéquation budgétaire
        "location": 20,     # 20% - Zone géographique
        "experience": 15,   # 15% - Expérience
    }

    # Mapping de secteurs similaires (20 catégories)
    SECTOR_SYNONYMS = {
        "agriculture": ["pêche", "développement rural", "élevage", "semence", "agropastoral"],
        "agroalimentaire": ["transformation", "alimentaire", "agro-industrie"],
        "communication": ["médias", "publicité", "presse", "audiovisuel"],
        "éducation": ["formation", "enseignement", "académique", "scolaire", "universitaire"],
        "energie": ["eau", "électricité", "solaire", "hydraulique", "assainissement", "hydrocarbure"],
        "environnement": ["forêts", "changement climatique", "reboisement", "écologie"],
        "études": ["consultances", "consultant", "audit", "expertise", "conseil"],
        "fournitures": ["équipements", "matériel", "mobilier", "approvisionnement"],
        "gouvernance": ["administration publique", "institutionnel", "décentralisation"],
        "immobilier": ["aménagement urbain", "lotissement", "urbanisme", "foncier"],
        "industrie": ["commerce", "usine", "manufacture", "production"],
        "informatique": ["télécommunications", "digital", "numérique", "tic", "logiciel", "it"],
        "mines": ["ressources naturelles", "minier", "géologie", "extraction"],
        "qse": ["qualité", "sécurité environnement", "hse", "norme"],
        "santé": ["paramédical", "médical", "pharmaceutique", "hospitalier", "health"],
        "sécurité": ["protection", "surveillance", "gardiennage", "défense"],
        "services": ["prestations diverses", "nettoyage", "entretien", "maintenance"],
        "tourisme": ["culture", "loisirs", "hôtellerie", "patrimoine"],
        "transport": ["logistique", "mobilité", "transit", "véhicule", "routier"],
        "travaux publics": ["construction", "btp", "génie civil", "bâtiment", "infrastructure", "route"],
    }

    def __init__(self, db: Session):
        self.db = db

    def _sector_score(self, enterprise_sector: str, tender_sector: str) -> float:
        """
        Calcule la correspondance sectorielle (0-1).
        Utilise la similarité textuelle + synonymes.
        """
        if not enterprise_sector or not tender_sector:
            return 0.0

        e_sector = enterprise_sector.lower().strip()
        t_sector = tender_sector.lower().strip()

        # Correspondance exacte
        if e_sector == t_sector:
            return 1.0

        # Vérifier si l'un contient l'autre
        if e_sector in t_sector or t_sector in e_sector:
            return 0.9

        # Vérifier les synonymes
        for base_sector, synonyms in self.SECTOR_SYNONYMS.items():
            all_terms = [base_sector] + synonyms
            e_match = any(term in e_sector for term in all_terms)
            t_match = any(term in t_sector for term in all_terms)
            if e_match and t_match:
                return 0.85

        # Similarité textuelle de fallback
        similarity = SequenceMatcher(None, e_sector, t_sector).ratio()
        return similarity if similarity > 0.5 else similarity * 0.3

    def _budget_score(
        self,
        min_budget: float,
        max_budget: float,
        estimated_budget: float | None,
    ) -> float:
        """
        Calcule l'adéquation budgétaire (0-1).
        Score maximal si le budget estimé est dans la fourchette.
        """
        if not estimated_budget or estimated_budget <= 0:
            return 0.5  # Score neutre si budget non disponible

        if min_budget <= 0 and max_budget <= 0:
            return 0.5  # Score neutre si pas de fourchette définie

        # Dans la fourchette
        if min_budget <= estimated_budget <= max_budget:
            return 1.0

        # Calcul de la proximité si hors fourchette
        if max_budget > 0 and estimated_budget > max_budget:
            # Budget trop élevé - pénalité progressive
            ratio = max_budget / estimated_budget
            return max(0.1, ratio)

        if min_budget > 0 and estimated_budget < min_budget:
            # Budget trop faible - pénalité progressive
            ratio = estimated_budget / min_budget
            return max(0.1, ratio)

        return 0.5

    def _location_score(self, enterprise_zones: str | None, tender_location: str | None) -> float:
        """
        Calcule la correspondance géographique (0-1).
        """
        if not enterprise_zones or not tender_location:
            return 0.5  # Score neutre si pas de données

        zones = [z.strip().lower() for z in enterprise_zones.split(",")]
        location = tender_location.lower().strip()

        # Correspondance exacte avec une zone
        for zone in zones:
            if zone in location or location in zone:
                return 1.0

        # Correspondance partielle (mots communs)
        location_words = set(location.split())
        for zone in zones:
            zone_words = set(zone.split())
            common = location_words & zone_words
            if common:
                return 0.7

        return 0.2

    def _experience_score(self, experience_years: int, tender_text: str | None) -> float:
        """
        Score d'expérience basique (0-1).
        Les entreprises plus expérimentées ont un avantage.
        """
        if experience_years >= 10:
            return 1.0
        elif experience_years >= 5:
            return 0.8
        elif experience_years >= 3:
            return 0.6
        elif experience_years >= 1:
            return 0.4
        return 0.2



    def _keyword_score(self, enterprise: Enterprise, tender_text: str) -> float:
        """
        Calcule un ajustement de score basé sur les mots-clés spécifiques et à exclure.
        Retourne un multiplicateur ou un ajustement (0.0 à 2.0).
        """
        text = tender_text.lower()
        score_adj = 1.0

        # Mots-clés à exclure (Malus fort / Exclusion)
        if enterprise.exclude_keywords:
            ex_keywords = [k.strip().lower() for k in enterprise.exclude_keywords.split(",") if k.strip()]
            for kw in ex_keywords:
                if kw in text:
                    logger.info(f"🚫 Exclusion trouvée ({kw}) pour {enterprise.name}")
                    return 0.0  # Score zéro si un mot exclu est présent

        # Mots-clés spécifiques (Bonus)
        if enterprise.specific_keywords:
            sp_keywords = [k.strip().lower() for k in enterprise.specific_keywords.split(",") if k.strip()]
            matches = 0
            for kw in sp_keywords:
                if kw in text:
                    matches += 1
            
            if matches > 0:
                # Bonus de 10% par match, max 30%
                bonus = min(0.3, matches * 0.1)
                score_adj += bonus
                logger.info(f"✨ Bonus mots-clés (+{bonus*100:.0f}%) pour {enterprise.name} ({matches} matchs)")

        return score_adj

    def calculate_score(self, enterprise: Enterprise, tender: Tender, analysis: Analysis | None = None) -> dict:
        """
        Calcule le score global de correspondance (0-100).
        """
        tender_sector = tender.sector or (analysis.extracted_sector if analysis else None) or ""
        tender_budget = tender.estimated_budget or (analysis.extracted_budget if analysis else None)
        tender_location = tender.location or (analysis.extracted_location if analysis else None)
        tender_text = (tender.raw_text or tender.description or tender.title or "").lower()

        # Calcul de chaque critère de base
        sector_s = self._sector_score(enterprise.sector, tender_sector)
        budget_s = self._budget_score(enterprise.min_budget, enterprise.max_budget, tender_budget)
        location_s = self._location_score(enterprise.zones, tender_location)
        experience_s = self._experience_score(enterprise.experience_years, tender_text)

        # Score pondéré de base
        base_weighted_score = (
            sector_s * self.WEIGHTS["sector"]
            + budget_s * self.WEIGHTS["budget"]
            + location_s * self.WEIGHTS["location"]
            + experience_s * self.WEIGHTS["experience"]
        )

        # Ajustement par mots-clés
        kw_multiplier = self._keyword_score(enterprise, tender_text)
        final_score = base_weighted_score * kw_multiplier

        # Cap à 100
        final_score = min(100.0, round(final_score, 1))

        # Générer l'explication
        explanation_parts = []
        explanation_parts.append(f"Secteur: {sector_s:.0%}")
        explanation_parts.append(f"Budget: {budget_s:.0%}")
        explanation_parts.append(f"Zone: {location_s:.0%}")
        if kw_multiplier > 1.0:
            explanation_parts.append(f"Bonus Mots-clés: +{(kw_multiplier-1)*100:.0f}%")
        elif kw_multiplier == 0:
            explanation_parts.append("Exclusion : Mot-clé interdit détecté")

        explanation = " | ".join(explanation_parts)

        return {
            "score": final_score,
            "details": {
                "sector": round(sector_s * 100, 1),
                "budget": round(budget_s * 100, 1),
                "location": round(location_s * 100, 1),
                "experience": round(experience_s * 100, 1),
                "keyword_adj": kw_multiplier
            },
            "explanation": explanation,
        }

    def score_all_for_enterprise(self, enterprise: Enterprise) -> list[dict]:
        """
        Calcule les scores pour tous les tenders analysés vs une entreprise.
        Met à jour les analyses en base.
        """
        analyses = self.db.query(Analysis).join(Tender).filter(
            Tender.is_analyzed == True  # noqa: E712
        ).all()

        results = []

        for analysis in analyses:
            tender = analysis.tender
            score_result = self.calculate_score(enterprise, tender, analysis)

            # Mettre à jour l'analyse
            analysis.enterprise_id = enterprise.id
            analysis.score = score_result["score"]
            analysis.explanation = score_result["explanation"]

            results.append({
                "tender_id": tender.id,
                "tender_title": tender.title,
                "score": score_result["score"],
                "details": score_result["details"],
                "explanation": score_result["explanation"],
                "source_url": tender.source_url or "",
            })

        self.db.commit()

        # Trier par score décroissant
        results.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"📊 {len(results)} scores calculés pour {enterprise.name}")

        return results