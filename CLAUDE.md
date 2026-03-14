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

Module layout:
- `agent.py` — main pipeline, LLM prompt, HTML email generation, SMTP sending
- `utils.py` — config loading, ad field extraction (surface, tenure, ad ID), French number formatting
- `history.py` — `SeenAd` model and persistence (local JSON file or GitHub Gist), cooldown/discard/LLM decision logic
- `gistfs.py` — standalone GitHub Gist read/write helper

Pipeline flow:
1. Load cities from `scan_classified/cities.yaml` (name, lat, lng, radius, cooldown, discard threshold)
2. Load seen ads from `seen_ads.json` (local file) or GitHub Gist (if `GIST_ID`/`GITHUB_TOKEN` set)
3. Discard ads not seen for longer than `discard_threshold_days`
4. For each city, search LeBonCoin via the `lbc` Python package
5. Deduplicate ads by ID across cities
6. For each ad, decide: skip LLM if already evaluated with current `PROMPT_VERSION`, otherwise filter through Azure OpenAI → `FilterResult` (Pydantic structured output)
7. Enrich matched ads with price/hectare calculation and tenure → `FilteredAd`
8. Apply email cooldown: only include ads not emailed within `cooldown_days`, tag re-inclusions with "déjà vue"
9. Generate HTML email grouped by city with Informations section, send via SMTP (or save to `outputs/results.html`)
10. Mark emailed ads and save seen ads back to file/Gist

**Key constant:** `PROMPT_VERSION` in `agent.py` — bump when `PROMPT_TEMPLATE` changes to force re-evaluation of all previously seen ads.

**Key dependencies:** `lbc` (LeBonCoin API client), `langchain-openai` (Azure OpenAI via LangChain), `pydantic` (structured LLM output), `pyyaml`, `python-dotenv`, `requests` (Gist API).

## Configuration

- `.env` file (copy from `.env.example`): Azure OpenAI credentials, SMTP credentials, email addresses, optional `GIST_ID`/`GITHUB_TOKEN` for Gist-based persistence
- `scan_classified/cities.yaml`: list of cities (name, lat, lng, radius) + `cooldown_days` (re-email delay) and `discard_threshold_days` (purge unseen ads)
- `SEND_EMAIL` env var controls whether email is sent or HTML is saved locally

## Deployment

Deployed as a Google Cloud Run Job. See `scan_classified/DEPLOY.md`. Secrets are managed via GCP Secret Manager. Scheduling via Cloud Scheduler (Monday and Thursday at 6am Paris time).
