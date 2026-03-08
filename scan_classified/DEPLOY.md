# Deploying the Scan Classified Agent to Google Cloud Run

## Prerequisites

- Google Cloud SDK installed and configured
- A GCP project with Cloud Run and Secret Manager APIs enabled

## 1. Project Configuration

```bash
# Set the project
export PROJECT_ID=your-project-id
gcloud config set project $PROJECT_ID

# Enable required APIs
gcloud services enable run.googleapis.com secretmanager.googleapis.com
```

## 2. Create Secrets

```bash
# Azure OpenAI
echo -n "your-api-key" | gcloud secrets create azure-openai-api-key --data-file=-
echo -n "https://your-resource.openai.azure.com/" | gcloud secrets create azure-openai-endpoint --data-file=-

# SMTP Scaleway
echo -n "your-smtp-username" | gcloud secrets create smtp-username --data-file=-
echo -n "your-smtp-password" | gcloud secrets create smtp-password --data-file=-

# Recipients (comma-separated list)
echo -n "email1@example.com,email2@example.com" | gcloud secrets create recipients --data-file=-
```

## 3. Build and Push the Image

Run from the repository root:

```bash
# Build and push to Google Container Registry
gcloud builds submit --tag gcr.io/$PROJECT_ID/printemps-terres-scan-classified --dockerfile=scan_classified/Dockerfile
```

Or build locally:

```bash
docker build -f scan_classified/Dockerfile -t printemps-terres-scan-classified .
```

## 4. Deploy the Job

```bash
# Replace PROJECT_ID in the YAML file
sed -i "s/PROJECT_ID/$PROJECT_ID/g" scan_classified/cloudrun-job.yaml

# Deploy the job
gcloud run jobs replace scan_classified/cloudrun-job.yaml --region=europe-west1
```

## 5. Run the Job

```bash
# Execute the job manually
gcloud run jobs execute printemps-terres-scan-classified --region=europe-west1

# View logs
gcloud run jobs executions logs printemps-terres-scan-classified --region=europe-west1
```

## 6. Scheduling (Optional)

To run the job automatically (Monday and Thursday at 6am, Paris time):

```bash
# Create a service account for Cloud Scheduler
gcloud iam service-accounts create scheduler-sa --display-name="Cloud Scheduler SA"

# Grant permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:scheduler-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# Create the Cloud Scheduler job
gcloud scheduler jobs create http printemps-terres-scan-classified-biweekly \
  --location=europe-west1 \
  --schedule="0 6 * * 1,4" \
  --time-zone="Europe/Paris" \
  --uri="https://europe-west1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/printemps-terres-scan-classified:run" \
  --http-method=POST \
  --oauth-service-account-email="scheduler-sa@$PROJECT_ID.iam.gserviceaccount.com"
```
