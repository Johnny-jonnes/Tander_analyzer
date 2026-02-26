
import sys
import os
from sqlalchemy import text
from app.database import engine

def migrate():
    print("🚀 Démarrage de la migration de la base de données...")
    
    # Liste des colonnes à ajouter si elles n'existent pas
    columns_to_add = [
        ("specific_keywords", "TEXT"),
        ("exclude_keywords", "TEXT"),
        ("min_budget", "FLOAT DEFAULT 0.0"),
        ("max_budget", "FLOAT DEFAULT 0.0"),
        ("experience_years", "INTEGER DEFAULT 0"),
        ("technical_capacity", "TEXT")
    ]
    
    with engine.connect() as conn:
        for column_name, column_type in columns_to_add:
            print(f"⌛ Tentative d'ajout de la colonne '{column_name}'...")
            try:
                # PostgreSQL ALTER TABLE ADD COLUMN IF NOT EXISTS (PG 9.6+)
                query = text(f"ALTER TABLE enterprises ADD COLUMN IF NOT EXISTS {column_name} {column_type};")
                conn.execute(query)
                conn.commit()
                print(f"✅ Colonne '{column_name}' ajoutée ou déjà présente.")
            except Exception as e:
                print(f"❌ Erreur lors de l'ajout de '{column_name}': {e}")
                conn.rollback()

    print("✨ Migration terminée !")

if __name__ == "__main__":
    # S'assurer que le chemin d'import fonctionne
    sys.path.append(os.getcwd())
    migrate()
