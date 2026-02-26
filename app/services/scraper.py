# app/services/scraper.py
"""
Service de scraping - DGCMP, Telemo, JAO Guinée et autres sources d'appels d'offres
Gère le téléchargement des pages, extraction des liens PDF,
et stockage des appels d'offres en base.
"""

import os
import logging
import hashlib
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.tender import Tender

logger = logging.getLogger(__name__)
settings = get_settings()

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Headers pour simuler un navigateur
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
}


class ScraperService:
    """Service de scraping des appels d'offres"""

    def __init__(self, db: Session):
        self.db = db
        self.base_url = settings.DGCMP_BASE_URL
        self.telemo_url = settings.TELEMO_BASE_URL
        self.jao_url = settings.JAO_BASE_URL
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        before_sleep=lambda retry_state: logger.warning(
            f"Retry {retry_state.attempt_number}/3 - Scraping échoué, nouvelle tentative..."
        ),
    )
    def _fetch_page(self, url: str, timeout: int = 30) -> str:
        """
        Récupère le contenu HTML d'une page avec retry automatique.
        3 tentatives avec backoff exponentiel.
        """
        logger.info(f"📡 Fetching: {url}")
        response = self.session.get(url, timeout=timeout)
        response.raise_for_status()
        return response.text

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    )
    def _download_pdf(self, url: str, timeout: int = 60) -> str | None:
        """
        Télécharge un fichier PDF et le sauvegarde localement.
        Retourne le chemin du fichier ou None en cas d'échec.
        """
        try:
            logger.info(f"📥 Downloading PDF: {url}")
            response = self.session.get(url, timeout=timeout, stream=True)
            response.raise_for_status()

            # Nom de fichier basé sur le hash de l'URL
            filename = hashlib.md5(url.encode()).hexdigest() + ".pdf"
            filepath = DOWNLOADS_DIR / filename

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            file_size = filepath.stat().st_size
            logger.info(f"✅ PDF sauvegardé: {filepath} ({file_size} bytes)")
            return str(filepath)

        except Exception as e:
            logger.error(f"❌ Échec téléchargement PDF {url}: {e}")
            return None

    # ──────────────────────────────────────────────
    #  PARSERS DGCMP (source originale)
    # ──────────────────────────────────────────────

    def _parse_dgcmp_listings(self, html: str) -> list[dict]:
        """
        Parse la page HTML DGCMP pour extraire les appels d'offres.
        """
        soup = BeautifulSoup(html, "html.parser")
        tenders = []

        # Stratégie 1 : Recherche dans les tableaux
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows[1:]:  # Skip header
                cells = row.find_all("td")
                if len(cells) >= 2:
                    tender_data = self._extract_from_table_row(cells, self.base_url)
                    if tender_data:
                        tenders.append(tender_data)

        # Stratégie 2 : Recherche dans les articles/divs
        if not tenders:
            articles = soup.find_all(["article", "div"], class_=lambda c: c and (
                "tender" in str(c).lower() or
                "appel" in str(c).lower() or
                "offre" in str(c).lower() or
                "post" in str(c).lower() or
                "entry" in str(c).lower()
            ))
            for article in articles:
                tender_data = self._extract_from_article(article, self.base_url)
                if tender_data:
                    tenders.append(tender_data)

        # Stratégie 3 : Recherche de tous les liens PDF
        if not tenders:
            tenders = self._extract_pdf_links(soup, self.base_url)

        return tenders

    # ──────────────────────────────────────────────
    #  PARSER TELEMO (portail guinéen)
    # ──────────────────────────────────────────────

    def _parse_telemo_listings(self, html: str) -> list[dict]:
        """
        Parse la page Telemo pour extraire les plans de passation de marchés.
        """
        soup = BeautifulSoup(html, "html.parser")
        tenders = []

        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 2:
                    year_text = ""
                    entity_text = ""
                    link_href = None

                    for cell in cells:
                        text = cell.get_text(strip=True)
                        link = cell.find("a")
                        if link and link.get("href"):
                            href = link["href"]
                            if not href.startswith("javascript:"):
                                link_href = href if href.startswith("http") else f"{self.telemo_url}{href}"

                        if text and text.isdigit() and len(text) == 4:
                            year_text = text
                        elif text and len(text) > 5:
                            entity_text = text

                    if entity_text:
                        title = f"Plan de passation des marchés {year_text} — {entity_text}"
                        # Utiliser le lien réel s'il existe, sinon une recherche Google
                        if link_href and link_href.startswith("http"):
                            source_url = link_href
                        else:
                            import urllib.parse
                            q = urllib.parse.quote_plus(f"plan passation marche {year_text} {entity_text} Guinee")
                            source_url = f"https://www.google.com/search?q={q}"

                        tenders.append({
                            "title": title[:500],
                            "description": f"Plan de passation des marchés publics {year_text} de {entity_text}",
                            "source_url": source_url,
                            "deadline_str": None,
                            "location": "Guinée",
                            "sector": self._guess_sector(entity_text),
                        })

        return tenders

    # ──────────────────────────────────────────────
    #  PARSER JAO GUINÉE (Journal Officiel)
    # ──────────────────────────────────────────────

    def _parse_jao_listings(self, html: str, category: str = None) -> list[dict]:
        """
        Parse la page JAO Guinée pour extraire les appels d'offres.
        Format : Articles Wordpress avec titre et lien.
        """
        soup = BeautifulSoup(html, "html.parser")
        tenders = []

        # JAO utilise souvent des structures d'articles Wordpress standard
        articles = soup.find_all(["article", "div"], class_=lambda c: c and ("post" in str(c).lower() or "entry" in str(c).lower()))
        
        if not articles:
            # Fallback simple
            articles = soup.find_all("h2", class_=lambda c: c and "entry-title" in str(c).lower())
            if not articles:
                articles = soup.find_all(["h1", "h2", "h3"])

        for article in articles:
            link = article.find("a")
            if not link or not link.get("href"):
                continue

            title = link.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            # Ignorer les articles qui ne sont pas des appels d'offres (ex: actualités gérnérales)
            if any(kw in title.lower() for kw in ["recrutement", "avis d'attribution", "résultats"]):
                continue

            source_url = link["href"]
            
            # Tenter d'extraire la date
            date_tag = article.find(["span", "time"], class_=lambda c: c and "date" in str(c).lower())
            date_str = date_tag.get_text(strip=True) if date_tag else None

            tenders.append({
                "title": title[:500],
                "description": f"Appel d'offres publié sur JAO Guinée : {title}",
                "source_url": source_url,
                "deadline_str": None, # JAO ne met pas souvent la deadline dans le titre
                "location": "Guinée",
                "sector": category or self._guess_sector(title),
            })

        logger.info(f"✅ JAO: {len(tenders)} tenders trouvés")
        return tenders

    def _guess_sector(self, text: str) -> str | None:
        """Devine le secteur à partir d'un texte (20 catégories)."""
        text_lower = text.lower()
        sector_map = {
            # Agriculture, Pêche & Développement Rural
            "agri": "Agriculture, Pêche & Développement Rural",
            "pêche": "Agriculture, Pêche & Développement Rural",
            "élevage": "Agriculture, Pêche & Développement Rural",
            "rural": "Agriculture, Pêche & Développement Rural",
            "semence": "Agriculture, Pêche & Développement Rural",
            # Agroalimentaire & Transformation
            "agroalimentaire": "Agroalimentaire & Transformation",
            "transformation": "Agroalimentaire & Transformation",
            "alimentaire": "Agroalimentaire & Transformation",
            # Communication, Médias & Publicité
            "communic": "Communication, Médias & Publicité",
            "média": "Communication, Médias & Publicité",
            "publicité": "Communication, Médias & Publicité",
            "presse": "Communication, Médias & Publicité",
            # Éducation & Formation
            "éducation": "Éducation & Formation",
            "enseign": "Éducation & Formation",
            "formation": "Éducation & Formation",
            "universit": "Éducation & Formation",
            "scolaire": "Éducation & Formation",
            # Energie, Eau & Environnement
            "énergi": "Energie, Eau & Environnement",
            "électri": "Energie, Eau & Environnement",
            "solaire": "Energie, Eau & Environnement",
            "eau": "Energie, Eau & Environnement",
            "hydraulique": "Energie, Eau & Environnement",
            "assainissement": "Energie, Eau & Environnement",
            # Environnement, Forêts & Changement Climatique
            "forêt": "Environnement, Forêts & Changement Climatique",
            "climat": "Environnement, Forêts & Changement Climatique",
            "reboisement": "Environnement, Forêts & Changement Climatique",
            # Études & Consultances
            "étude": "Études & Consultances",
            "consultanc": "Études & Consultances",
            "consultant": "Études & Consultances",
            "audit": "Études & Consultances",
            # Fournitures & Équipements
            "fourniture": "Fournitures & Équipements",
            "équipement": "Fournitures & Équipements",
            "matériel": "Fournitures & Équipements",
            "mobilier": "Fournitures & Équipements",
            # Gouvernance & Administration Publique
            "gouvern": "Gouvernance & Administration Publique",
            "administrat": "Gouvernance & Administration Publique",
            "institution": "Gouvernance & Administration Publique",
            # Immobilier & Aménagement Urbain
            "immobilier": "Immobilier & Aménagement Urbain",
            "urbain": "Immobilier & Aménagement Urbain",
            "aménagement": "Immobilier & Aménagement Urbain",
            "lotissement": "Immobilier & Aménagement Urbain",
            # Industrie & Commerce
            "industri": "Industrie & Commerce",
            "commerce": "Industrie & Commerce",
            "usine": "Industrie & Commerce",
            # Informatique & Télécommunications
            "informatique": "Informatique & Télécommunications",
            "telecom": "Informatique & Télécommunications",
            "digital": "Informatique & Télécommunications",
            "logiciel": "Informatique & Télécommunications",
            "numérique": "Informatique & Télécommunications",
            # Mines & Ressources Naturelles
            "minier": "Mines & Ressources Naturelles",
            "mines": "Mines & Ressources Naturelles",
            "géologi": "Mines & Ressources Naturelles",
            "ressources naturelles": "Mines & Ressources Naturelles",
            # QSE
            "qualité": "QSE - Qualité, Sécurité & Environnement",
            "qse": "QSE - Qualité, Sécurité & Environnement",
            "environ": "QSE - Qualité, Sécurité & Environnement",
            # Santé & Paramédical
            "santé": "Santé & Paramédical",
            "médi": "Santé & Paramédical",
            "pharmac": "Santé & Paramédical",
            "hôpital": "Santé & Paramédical",
            "paramédical": "Santé & Paramédical",
            # Sécurité & Protection
            "sécurité": "Sécurité & Protection",
            "surveillance": "Sécurité & Protection",
            "gardiennage": "Sécurité & Protection",
            "défense": "Sécurité & Protection",
            # Services Généraux & Prestations diverses
            "nettoyage": "Services Généraux & Prestations diverses",
            "entretien": "Services Généraux & Prestations diverses",
            "prestation": "Services Généraux & Prestations diverses",
            "service": "Services Généraux & Prestations diverses",
            # Tourisme, Culture & Loisirs
            "tourisme": "Tourisme, Culture & Loisirs",
            "culture": "Tourisme, Culture & Loisirs",
            "hôtel": "Tourisme, Culture & Loisirs",
            # Transport & Logistique
            "transport": "Transport & Logistique",
            "logistique": "Transport & Logistique",
            "véhicule": "Transport & Logistique",
            # Travaux Publics & Construction
            "travaux": "Travaux Publics & Construction",
            "constru": "Travaux Publics & Construction",
            "route": "Travaux Publics & Construction",
            "bâtiment": "Travaux Publics & Construction",
            "génie civil": "Travaux Publics & Construction",
            "infrastr": "Travaux Publics & Construction",
        }
        for keyword, sector in sector_map.items():
            if keyword in text_lower:
                return sector
        return "Services Généraux & Prestations diverses"

    # ──────────────────────────────────────────────
    #  HELPERS COMMUNS
    # ──────────────────────────────────────────────

    def _extract_from_table_row(self, cells: list, base_url: str) -> dict | None:
        """Extrait les données d'une ligne de tableau"""
        try:
            title_cell = cells[0]
            link = title_cell.find("a")
            title = title_cell.get_text(strip=True)

            if not title or len(title) < 5:
                return None

            source_url = ""
            if link and link.get("href"):
                href = link["href"]
                source_url = href if href.startswith("http") else f"{base_url}{href}"
            else:
                return None

            description = ""
            if len(cells) > 1:
                description = cells[1].get_text(strip=True)

            deadline_str = None
            if len(cells) > 2:
                deadline_str = cells[2].get_text(strip=True)

            return {
                "title": title[:500],
                "description": description[:2000] if description else None,
                "source_url": source_url,
                "deadline_str": deadline_str,
            }

        except Exception as e:
            logger.debug(f"Erreur extraction ligne tableau: {e}")
            return None

    def _extract_from_article(self, article, base_url: str) -> dict | None:
        """Extrait les données d'un article/div"""
        try:
            title_tag = article.find(["h1", "h2", "h3", "h4", "a"])
            if not title_tag:
                return None

            title = title_tag.get_text(strip=True)
            if not title or len(title) < 5:
                return None

            link = article.find("a")
            if not link or not link.get("href"):
                return None

            href = link["href"]
            source_url = href if href.startswith("http") else f"{base_url}{href}"

            desc_tag = article.find("p")
            description = desc_tag.get_text(strip=True) if desc_tag else None

            return {
                "title": title[:500],
                "description": description[:2000] if description else None,
                "source_url": source_url,
                "deadline_str": None,
            }

        except Exception as e:
            logger.debug(f"Erreur extraction article: {e}")
            return None

    def _extract_pdf_links(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Extrait tous les liens PDF de la page"""
        tenders = []
        links = soup.find_all("a", href=True)

        for link in links:
            href = link["href"]
            if href.lower().endswith(".pdf"):
                title = link.get_text(strip=True) or href.split("/")[-1]
                url = href if href.startswith("http") else f"{base_url}{href}"
                tenders.append({
                    "title": title[:500],
                    "description": None,
                    "source_url": url,
                    "deadline_str": None,
                })

        return tenders

    def _tender_exists(self, source_url: str) -> bool:
        """Vérifie si un appel d'offres existe déjà en base"""
        existing = self.db.query(Tender).filter(
            Tender.source_url == source_url
        ).first()
        return existing is not None

    def _parse_deadline(self, deadline_str: str | None) -> datetime | None:
        """Tente de parser une date limite"""
        if not deadline_str:
            return None

        formats = [
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y-%m-%d",
            "%d/%m/%Y %H:%M",
            "%d %B %Y",
            "%d %b %Y",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(deadline_str.strip(), fmt)
            except ValueError:
                continue

        return None

    def _map_enterprise_sector_to_jao_categories(self, enterprise_sectors: set[str]) -> dict[str, str]:
        """
        Mappe les secteurs des entreprises inscrites vers les categories JAO correspondantes.
        Retourne seulement les categories pertinentes.
        """
        all_jao_categories = {
            "Travaux Publics & Construction": f"{self.jao_url}/category/appels-d-offres/travaux-publics-construction/",
            "Sante & Paramedical": f"{self.jao_url}/category/appels-d-offres/sante-medicaments/",
            "Informatique & Telecommunications": f"{self.jao_url}/category/appels-d-offres/informatique-telecommunications/",
            "Services Generaux & Prestations diverses": f"{self.jao_url}/category/appels-d-offres/services-generaux-prestations-diverses/",
            "Agriculture, Peche & Developpement Rural": f"{self.jao_url}/category/appels-d-offres/agriculture-peche-developpement-rural/",
            "Education & Formation": f"{self.jao_url}/category/appels-d-offres/education-formation/",
            "Energie, Eau & Environnement": f"{self.jao_url}/category/appels-d-offres/energie-eau-environnement/",
            "Transport & Logistique": f"{self.jao_url}/category/appels-d-offres/transport-logistique/",
            "Fournitures & Equipements": f"{self.jao_url}/category/appels-d-offres/fournitures-equipements/",
            "Etudes & Consultances": f"{self.jao_url}/category/appels-d-offres/etudes-consultances/",
            "Mines & Ressources Naturelles": f"{self.jao_url}/category/appels-d-offres/mines-ressources-naturelles/",
        }

        # Mapping secteur entreprise -> categorie(s) JAO
        sector_to_jao = {
            "travaux": ["Travaux Publics & Construction"],
            "construction": ["Travaux Publics & Construction"],
            "btp": ["Travaux Publics & Construction"],
            "batiment": ["Travaux Publics & Construction"],
            "genie civil": ["Travaux Publics & Construction"],
            "sante": ["Sante & Paramedical"],
            "medical": ["Sante & Paramedical"],
            "pharma": ["Sante & Paramedical"],
            "hopital": ["Sante & Paramedical"],
            "informatique": ["Informatique & Telecommunications"],
            "telecom": ["Informatique & Telecommunications"],
            "digital": ["Informatique & Telecommunications"],
            "numerique": ["Informatique & Telecommunications"],
            "logiciel": ["Informatique & Telecommunications"],
            "service": ["Services Generaux & Prestations diverses"],
            "nettoyage": ["Services Generaux & Prestations diverses"],
            "entretien": ["Services Generaux & Prestations diverses"],
            "prestation": ["Services Generaux & Prestations diverses"],
            "agri": ["Agriculture, Peche & Developpement Rural"],
            "peche": ["Agriculture, Peche & Developpement Rural"],
            "elevage": ["Agriculture, Peche & Developpement Rural"],
            "rural": ["Agriculture, Peche & Developpement Rural"],
            "education": ["Education & Formation"],
            "formation": ["Education & Formation"],
            "enseign": ["Education & Formation"],
            "universit": ["Education & Formation"],
            "scolaire": ["Education & Formation"],
            "energie": ["Energie, Eau & Environnement"],
            "electri": ["Energie, Eau & Environnement"],
            "eau": ["Energie, Eau & Environnement"],
            "solaire": ["Energie, Eau & Environnement"],
            "environnement": ["Energie, Eau & Environnement"],
            "transport": ["Transport & Logistique"],
            "logistique": ["Transport & Logistique"],
            "vehicule": ["Transport & Logistique"],
            "fourniture": ["Fournitures & Equipements"],
            "equipement": ["Fournitures & Equipements"],
            "materiel": ["Fournitures & Equipements"],
            "mobilier": ["Fournitures & Equipements"],
            "etude": ["Etudes & Consultances"],
            "consultanc": ["Etudes & Consultances"],
            "consultant": ["Etudes & Consultances"],
            "audit": ["Etudes & Consultances"],
            "mine": ["Mines & Ressources Naturelles"],
            "minier": ["Mines & Ressources Naturelles"],
            "geologi": ["Mines & Ressources Naturelles"],
        }

        matched_categories = {}
        for e_sector in enterprise_sectors:
            e_lower = e_sector.lower().replace('é', 'e').replace('è', 'e').replace('ê', 'e').replace('à', 'a').replace('â', 'a').replace('ô', 'o').replace('î', 'i').replace('û', 'u').replace('ç', 'c').replace('&', '&')
            for keyword, jao_cats in sector_to_jao.items():
                if keyword in e_lower:
                    for cat in jao_cats:
                        if cat in all_jao_categories:
                            matched_categories[cat] = all_jao_categories[cat]

        if not matched_categories:
            logger.info("Aucun secteur specifique trouve, scraping de toutes les categories JAO")
            return all_jao_categories

        logger.info(f"Scraping intelligent: {len(matched_categories)} categories pour {len(enterprise_sectors)} secteur(s): {list(matched_categories.keys())}")
        return matched_categories

    def scrape_tenders(self) -> list[Tender]:
        """
        Point d'entree principal : scrape les appels d'offres.
        Scraping INTELLIGENT : ne scrape que les categories JAO
        correspondant aux secteurs des entreprises inscrites.
        Sources : JAO Guinee + DGCMP + Telemo
        """
        from app.models.enterprise import Enterprise

        new_tenders = []
        all_tender_data = []

        # Recuperer les secteurs des entreprises inscrites
        enterprises = self.db.query(Enterprise).all()
        enterprise_sectors = set()
        for ent in enterprises:
            if ent.sector:
                enterprise_sectors.add(ent.sector)
        logger.info(f"Secteurs des entreprises inscrites: {enterprise_sectors}")

        # Source 1 : JAO Guinee (scraping INTELLIGENT par secteur)
        jao_categories = self._map_enterprise_sector_to_jao_categories(enterprise_sectors)

        for cat, url in jao_categories.items():
            try:
                html = self._fetch_page(url)
                tender_data_list = self._parse_jao_listings(html, category=cat)
                all_tender_data.extend(tender_data_list)
            except Exception as e:
                logger.warning(f"Echec scraping JAO {cat}: {e}")

        # Source 2 : DGCMP
        try:
            html = self._fetch_page(self.base_url, timeout=10)
            all_tender_data.extend(self._parse_dgcmp_listings(html))
        except Exception:
            logger.info("DGCMP est toujours indisponible")

        # Source 3 : Telemo
        try:
            telemo_plan_url = f"{self.telemo_url}/eb/bpp/selectPageProcurementPlan.do?menuId=EB03010100&leftTopFlag=t"
            html = self._fetch_page(telemo_plan_url)
            all_tender_data.extend(self._parse_telemo_listings(html))
        except Exception as e:
            logger.warning(f"Echec scraping Telemo: {e}")

        # Deduplication et Stockage
        seen_urls = set()
        unique_tenders = []
        for td in all_tender_data:
            if td["source_url"] not in seen_urls:
                seen_urls.add(td["source_url"])
                unique_tenders.append(td)

        for tender_data in unique_tenders:
            try:
                if self._tender_exists(tender_data["source_url"]):
                    continue

                tender = Tender(
                    title=tender_data["title"],
                    description=tender_data.get("description"),
                    source_url=tender_data["source_url"],
                    sector=tender_data.get("sector"),
                    location=tender_data.get("location", "Guinee"),
                    is_analyzed=False,
                )

                self.db.add(tender)
                self.db.flush()
                new_tenders.append(tender)
                logger.info(f"Nouveau tender #{tender.id}: {tender.title[:60]}")

            except Exception as e:
                logger.error(f"Erreur tender '{tender_data.get('title')}': {e}")
                continue

        self.db.commit()
        logger.info(f"Scraping termine: {len(new_tenders)} nouveaux ({len(jao_categories)} categories scrapees)")
        return new_tenders