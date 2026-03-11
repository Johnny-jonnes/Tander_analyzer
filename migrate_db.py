"""Script pour ajouter les colonnes manquantes à la base de données."""
from app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    # Ajouter subscription_plan à la table enterprises
    conn.execute(text(
        "ALTER TABLE enterprises ADD COLUMN IF NOT EXISTS subscription_plan VARCHAR(20) NOT NULL DEFAULT 'PASS'"
    ))
    conn.commit()
    print("OK: colonne subscription_plan ajoutée à enterprises")

    # Créer la table subscriptions si elle n'existe pas
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            enterprise_id INTEGER NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
            plan VARCHAR(20) NOT NULL DEFAULT 'PASS',
            max_sectors INTEGER NOT NULL DEFAULT 3,
            price_gnf FLOAT NOT NULL DEFAULT 0.0,
            start_date TIMESTAMP NOT NULL DEFAULT NOW(),
            end_date TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    conn.commit()
    print("OK: table subscriptions créée")

print("Migration terminée avec succès!")
