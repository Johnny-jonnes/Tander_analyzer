# app/services/pdf_parser.py
"""
Service d'extraction de texte depuis les fichiers PDF.
Utilise PyPDF2 pour parser les documents.
"""

import logging
from pathlib import Path

from PyPDF2 import PdfReader

logger = logging.getLogger(__name__)


class PDFParserService:
    """Extraction de texte depuis les PDFs"""

    @staticmethod
    def extract_text(pdf_path: str, max_pages: int = 50) -> str | None:
        """
        Extrait le texte d'un fichier PDF.

        Args:
            pdf_path: Chemin vers le fichier PDF
            max_pages: Nombre maximum de pages à traiter

        Returns:
            Texte extrait ou None en cas d'erreur
        """
        try:
            filepath = Path(pdf_path)
            if not filepath.exists():
                logger.error(f"❌ Fichier PDF introuvable: {pdf_path}")
                return None

            if filepath.stat().st_size == 0:
                logger.error(f"❌ Fichier PDF vide: {pdf_path}")
                return None

            reader = PdfReader(str(filepath))
            total_pages = len(reader.pages)
            pages_to_read = min(total_pages, max_pages)

            logger.info(f"📄 Parsing PDF: {filepath.name} ({total_pages} pages)")

            text_parts = []
            for i in range(pages_to_read):
                try:
                    page = reader.pages[i]
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text.strip())
                except Exception as e:
                    logger.warning(f"⚠️ Erreur page {i+1}: {e}")
                    continue

            if not text_parts:
                logger.warning(f"⚠️ Aucun texte extrait de {filepath.name}")
                return None

            full_text = "\n\n".join(text_parts)

            # Nettoyage basique
            full_text = PDFParserService._clean_text(full_text)

            logger.info(f"✅ Texte extrait: {len(full_text)} caractères depuis {filepath.name}")
            return full_text

        except Exception as e:
            logger.error(f"❌ Erreur parsing PDF {pdf_path}: {e}")
            return None

    @staticmethod
    def _clean_text(text: str) -> str:
        """Nettoie le texte extrait"""
        import re

        # Supprimer les caractères de contrôle
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

        # Normaliser les espaces multiples
        text = re.sub(r' {3,}', '  ', text)

        # Normaliser les sauts de ligne multiples
        text = re.sub(r'\n{4,}', '\n\n\n', text)

        # Supprimer les lignes contenant uniquement des tirets ou underscores
        text = re.sub(r'^[-_=]{5,}$', '', text, flags=re.MULTILINE)

        return text.strip()

    @staticmethod
    def extract_metadata(pdf_path: str) -> dict | None:
        """Extrait les métadonnées d'un PDF"""
        try:
            reader = PdfReader(pdf_path)
            metadata = reader.metadata

            if not metadata:
                return None

            return {
                "title": metadata.get("/Title", ""),
                "author": metadata.get("/Author", ""),
                "subject": metadata.get("/Subject", ""),
                "creator": metadata.get("/Creator", ""),
                "pages": len(reader.pages),
            }

        except Exception as e:
            logger.error(f"❌ Erreur extraction métadonnées: {e}")
            return None