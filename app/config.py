# app/config.py
"""
Configuration centralisée - variables d'environnement
"""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration de l'application chargée depuis l'environnement ou .env"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # --- Application ---
    APP_NAME: str = "Tender Analyzer MVP"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # --- Base de données ---
    DATABASE_URL: str = ""
    
    # Defaults pour dev local
    POSTGRES_USER: str = "tender_user"
    POSTGRES_PASSWORD: str = "tender_secret_password_2024"
    POSTGRES_DB: str = "tender_analyzer"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    # --- Groq (gratuit) ---
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

    # --- SMTP / Mailjet ---
    SMTP_HOST: str = "in-v3.mailjet.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_TLS: bool = True

    # --- Scraping ---
    DGCMP_BASE_URL: str = "https://www.dgcmp.cd"
    TELEMO_BASE_URL: str = "https://telemo.gov.gn"
    JAO_BASE_URL: str = "https://www.jaoguinee.com"
    SCRAPE_SCHEDULE_HOUR: int = 7
    EMAIL_SCHEDULE_HOUR: int = 8

    # --- Retry ---
    MAX_RETRY_ATTEMPTS: int = 3
    RETRY_DELAY_SECONDS: int = 5

    @property
    def database_url(self) -> str:
        """Priorité absolue à l'URL complète (DATABASE_URL)"""
        # 1. Vérifier os.environ directement (priorité Railway)
        env_url = os.environ.get("DATABASE_URL")
        if env_url:
            return env_url
            
        # 2. Vérifier l'attribut Pydantic (chargé via .env ou env vars)
        if self.DATABASE_URL:
            return self.DATABASE_URL
        
        # 3. Fallback sur les composants individuels
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache()
def get_settings() -> Settings:
    """Singleton des settings - cache en mémoire"""
    return Settings()
