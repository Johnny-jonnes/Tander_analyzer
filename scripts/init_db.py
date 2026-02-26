# scripts/init_db.py
import sys
import os

# Ajouter le dossier parent au path pour importer 'app'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import init_db
from app.config import get_settings

def main():
    print("🚀 Initialisation de la base de données...")
    settings = get_settings()
    print(f"📡 Connexion à : {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}")
    
    try:
        init_db()
        print("✅ Base de données initialisée avec succès !")
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation : {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
