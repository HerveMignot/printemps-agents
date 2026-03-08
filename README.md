# Printemps des Terres - Agents

Collection d'agents automatisés pour le Printemps des Terres.

## Agents disponibles

### Agent LBC (`lbc/`)

Agent de veille pour la recherche de terres agricoles et forestières sur des sites d'annonces.

**Fonctionnalités :**
- Recherche automatique d'annonces de terrains agricoles autour d'une liste de villes
- Filtrage intelligent via Azure OpenAI (terres agricoles, forêts, bois >= 10 hectares)
- Calcul du prix à l'hectare
- Génération d'un email HTML avec les résultats groupés par ville
- Envoi par email aux destinataires configurés

**Configuration :** `lbc/cities.yaml`

## Installation

```bash
uv sync
```

## Configuration

Copier `.env.example` vers `.env` et renseigner les variables :

- `AZURE_OPENAI_API_KEY` : clé API Azure OpenAI
- `AZURE_OPENAI_ENDPOINT` : endpoint Azure OpenAI
- `SMTP_USERNAME` / `SMTP_PASSWORD` : identifiants SMTP
- `RECIPIENTS` : liste des destinataires (séparés par des virgules)

## Utilisation

```bash
uv run python main.py
```

## Déploiement

Voir [DEPLOY.md](DEPLOY.md) pour le déploiement sur Google Cloud Run.
