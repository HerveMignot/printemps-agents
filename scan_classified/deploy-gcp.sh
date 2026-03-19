#!/usr/bin/env bash
set -euo pipefail

REGION="europe-west1"
IMAGE_NAME="printemps-terres-scan-classified"
JOB_NAME="printemps-terres-scan-classified"

# --- Check prerequisites ---

if ! command -v gcloud &> /dev/null; then
    echo "Error: gcloud CLI not found. Install it from https://cloud.google.com/sdk/docs/install"
    exit 1
fi

PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "(unset)" ]; then
    echo "Error: No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"
    exit 1
fi

echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "Image:    gcr.io/$PROJECT_ID/$IMAGE_NAME"
echo ""

# --- Parse command ---

COMMAND="${1:-help}"

case "$COMMAND" in

setup)
    echo "==> Enabling required APIs..."
    gcloud services enable run.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com cloudscheduler.googleapis.com

    echo ""
    echo "==> Creating secrets..."
    echo "You will be prompted for each secret value."
    echo ""

    secrets=(
        "azure-openai-api-key:Azure OpenAI API key"
        "azure-openai-endpoint:Azure OpenAI endpoint (https://...openai.azure.com/)"
        "smtp-username:SMTP username"
        "smtp-password:SMTP password"
        "sender:Sender email address"
        "reply-to:Reply-to email address"
        "recipients:Recipients (comma-separated emails)"
        "gist-id:GitHub Gist ID"
        "github-token:GitHub personal access token (gist scope)"
    )

    for entry in "${secrets[@]}"; do
        secret_name="${entry%%:*}"
        secret_desc="${entry#*:}"

        if gcloud secrets describe "$secret_name" &>/dev/null; then
            echo "  Secret '$secret_name' already exists, skipping."
        else
            read -rp "  $secret_desc: " secret_value
            echo -n "$secret_value" | gcloud secrets create "$secret_name" --data-file=-
            echo "  Created secret '$secret_name'."
        fi
    done

    echo ""
    echo "Setup complete. Next: $0 build"
    ;;

build)
    echo "==> Building and pushing image..."
    cd "$(git rev-parse --show-toplevel)"
    gcloud builds submit \
        --tag "gcr.io/$PROJECT_ID/$IMAGE_NAME" \
        --dockerfile=scan_classified/Dockerfile

    echo ""
    echo "Build complete. Next: $0 deploy"
    ;;

deploy)
    echo "==> Deploying Cloud Run job..."
    cd "$(git rev-parse --show-toplevel)"

    # Generate job YAML with PROJECT_ID replaced
    sed "s/PROJECT_ID/$PROJECT_ID/g" scan_classified/cloudrun-job.yaml > /tmp/cloudrun-job-deploy.yaml
    gcloud run jobs replace /tmp/cloudrun-job-deploy.yaml --region="$REGION"
    rm -f /tmp/cloudrun-job-deploy.yaml

    echo ""
    echo "Deploy complete. Run manually with: $0 run"
    ;;

run)
    echo "==> Executing job..."
    gcloud run jobs execute "$JOB_NAME" --region="$REGION"

    echo ""
    echo "Job started. View logs with: $0 logs"
    ;;

logs)
    echo "==> Fetching logs..."
    gcloud run jobs executions logs "$JOB_NAME" --region="$REGION"
    ;;

schedule)
    echo "==> Setting up Cloud Scheduler (Mon & Thu at 6am Paris time)..."

    SA_NAME="scheduler-sa"
    SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

    if ! gcloud iam service-accounts describe "$SA_EMAIL" &>/dev/null; then
        gcloud iam service-accounts create "$SA_NAME" --display-name="Cloud Scheduler SA"
    fi

    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SA_EMAIL" \
        --role="roles/run.invoker" \
        --quiet

    SCHEDULER_JOB="$JOB_NAME-biweekly"
    if gcloud scheduler jobs describe "$SCHEDULER_JOB" --location="$REGION" &>/dev/null; then
        echo "  Scheduler job '$SCHEDULER_JOB' already exists, updating..."
        gcloud scheduler jobs update http "$SCHEDULER_JOB" \
            --location="$REGION" \
            --schedule="0 6 * * 1,4" \
            --time-zone="Europe/Paris" \
            --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/$JOB_NAME:run" \
            --http-method=POST \
            --oauth-service-account-email="$SA_EMAIL"
    else
        gcloud scheduler jobs create http "$SCHEDULER_JOB" \
            --location="$REGION" \
            --schedule="0 6 * * 1,4" \
            --time-zone="Europe/Paris" \
            --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/$JOB_NAME:run" \
            --http-method=POST \
            --oauth-service-account-email="$SA_EMAIL"
    fi

    echo ""
    echo "Scheduler configured."
    ;;

all)
    echo "==> Full deployment pipeline"
    echo ""
    "$0" build
    echo ""
    "$0" deploy
    ;;

help|*)
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  setup     Create secrets and enable APIs (first time only)"
    echo "  build     Build and push Docker image to GCR"
    echo "  deploy    Deploy Cloud Run job from YAML"
    echo "  run       Execute the job manually"
    echo "  logs      View execution logs"
    echo "  schedule  Set up Cloud Scheduler (Mon & Thu 6am)"
    echo "  all       Build + deploy"
    ;;

esac
