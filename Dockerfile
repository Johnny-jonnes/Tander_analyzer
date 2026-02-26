# Dockerfile
FROM python:3.11-slim

# Métadonnées
LABEL maintainer="tender-analyzer"
LABEL version="1.0.0"

# Variables d'environnement système
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dépendances système pour psycopg2 et PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Répertoire de travail
WORKDIR /app

# Copier et installer les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code source
COPY . .

# Créer répertoire pour les PDFs téléchargés
RUN mkdir -p /app/downloads /app/logs

# Exposer le port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Commande de démarrage (Railway fournit $PORT dynamiquement)
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1