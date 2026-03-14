# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Collection of automated agents for "Printemps des Terres" — a project focused on finding agricultural and forestry land. The codebase is in French context (French prompts, French number formatting, French email content).

## Commands

```bash
# Install dependencies
uv sync

# Run an agent
uv run python main.py lbc

# Build Docker image (from repo root)
docker build -f scan_classified/Dockerfile -t printemps-terres-scan-classified .
```

## Architecture

**Entry point:** `main.py` dispatches to agents by name. The `AGENTS` dict maps CLI names to module paths (e.g., `"lbc"` → `"scan_classified.agent"`). Each agent module exposes a `main()` function.

**scan_classified agent** (`scan_classified/`): Searches LeBonCoin for agricultural land listings, filters them with Azure OpenAI (LangChain + structured output via Pydantic models), and sends results as an HTML email.

Pipeline flow:
1. Load cities from `scan_classified/cities.yaml` (name, lat, lng, radius)
2. For each city, search LeBonCoin via the `lbc` Python package
3. Deduplicate ads by ID across cities
4. Filter each ad through Azure OpenAI using a detailed French prompt → `FilterResult` (Pydantic structured output)
5. Enrich matched ads with price/hectare calculation and tenure → `FilteredAd`
6. Generate HTML email grouped by city, send via SMTP (or save to `outputs/results.html` if `SEND_EMAIL` is not set)

**Key dependencies:** `lbc` (LeBonCoin API client), `langchain-openai` (Azure OpenAI via LangChain), `pydantic` (structured LLM output), `pyyaml`, `python-dotenv`.

## Configuration

- `.env` file (copy from `.env.example`): Azure OpenAI credentials, SMTP credentials, email addresses
- `scan_classified/cities.yaml`: list of cities to search with coordinates and radius
- `SEND_EMAIL` env var controls whether email is sent or HTML is saved locally

## Deployment

Deployed as a Google Cloud Run Job. See `scan_classified/DEPLOY.md`. Secrets are managed via GCP Secret Manager. Scheduling via Cloud Scheduler (Monday and Thursday at 6am Paris time).
