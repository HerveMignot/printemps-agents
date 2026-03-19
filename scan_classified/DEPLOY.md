# Deploying the Scan Classified Agent to Google Cloud Run

## Prerequisites

- Google Cloud SDK installed and configured
- A GCP project set with `gcloud config set project YOUR_PROJECT_ID`
- A `.env` file at the repository root (copy from `.env.example`)

## Deploy script

All deployment operations are managed via `deploy.sh` (copy from `example-gcp-deploy.sh`).

The script loads secrets from the `.env` file and uses Artifact Registry for images.

```bash
# Show available commands
./scan_classified/deploy.sh help
```

### Commands

| Command | Description |
|---------|-------------|
| `setup` | Enable APIs, create secrets from `.env`, grant IAM permissions (first time only) |
| `build` | Build and push Docker image to Artifact Registry via Cloud Build |
| `deploy` | Deploy the Cloud Run job from `cloudrun-job.yaml` |
| `run` | Execute the job manually |
| `logs` | View logs for the latest execution |
| `schedule` | Set up Cloud Scheduler (Monday and Thursday at 6am Paris time) |
| `all` | Build + deploy in one step |

### First-time setup

```bash
# 1. Set your GCP project
gcloud config set project your-project-id

# 2. Create secrets and enable APIs
./scan_classified/deploy.sh setup

# 3. Build and deploy
./scan_classified/deploy.sh all

# 4. Run manually to test
./scan_classified/deploy.sh run

# 5. Set up scheduling (optional)
./scan_classified/deploy.sh schedule
```

### Secrets

The `setup` command creates the following GCP secrets from `.env` variables:

| GCP Secret | `.env` variable |
|------------|-----------------|
| `azure-openai-api-key` | `AZURE_OPENAI_API_KEY` |
| `azure-openai-endpoint` | `AZURE_OPENAI_ENDPOINT` |
| `smtp-username` | `SMTP_USERNAME` |
| `smtp-password` | `SMTP_PASSWORD` |
| `sender` | `SENDER` |
| `reply-to` | `REPLY_TO` |
| `recipients` | `RECIPIENTS` |
| `gist-id` | `GIST_ID` |
| `github-token` | `GITHUB_TOKEN` |

### Build context

The Dockerfile expects to be built from `scan_classified/`. The `build` command copies `pyproject.toml` and `uv.lock` into the build context before submitting to Cloud Build, and cleans them up after.
