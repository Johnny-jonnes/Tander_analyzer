# Tender Analyzer MVP

Solution automatisée de collecte, analyse et distribution d'appels d'offres en Guinée.

## 🚀 Fonctionnalités

- **Scraping Automatisé** : Collecte quotidienne depuis JAO Guinée (11 sources sectorielles).
- **Analyse par IA (Groq)** : Synthèse automatique et extraction de données structurées (budget, lieu, deadline).
- **Matching Intelligent** : Calcul de score de pertinence pour chaque entreprise inscrite.
- **Rapports Quotidiens** : Envoi automatique par email des meilleures opportunités.
- **Anti-Spam Optimisé** : Délivrabilité améliorée grâce aux headers MIME et au contenu texte brut.
- **20 Secteurs d'Activité** : Couverture complète des domaines économiques.

## 🛠️ Installation

```bash
# cloner le dépôt
git clone <repo_url>
cd tender-analyzer

# installer les dépendances
pip install -r requirements.txt

# configurer les variables d'environnement
cp .env.example .env # et remplir les clés API
```

## 🖥️ Lancement

```bash
uvicorn app.main:app --reload
```

L'application sera disponible sur `http://localhost:8000`.

## ⚙️ Configuration (.env)

- `GROQ_API_KEY` : Votre clé API Groq (gratuite et performante).
- `DATABASE_URL` : URL de votre base de données PostgreSQL.
- `SMTP_*` : Configuration de votre serveur d'envoi d'emails.

## 📄 Licence

Propriété de TrillionBerg / Luxe.


