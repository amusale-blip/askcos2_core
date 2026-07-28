# ASKCOSv2 Core App - Master Deployment & Infrastructure Guide

This master guide covers end-to-end container compilation, Cloud Run deployment, Google Cloud Serverless Network Endpoint Group (NEG) setup, and Load Balancer configuration for `askcos2-core-app`.

---

## 🏗️ 1. Infrastructure Overview

| Resource | Value / Name | Details |
| :--- | :--- | :--- |
| **GCP Project** | `x-woodward` | Target Google Cloud Project |
| **GCP Region** | `us-central1` | Cloud Run & Serverless NEG Region |
| **Cloud Run Service** | `askcos2-core-app` | Dynamic Port (8080) FastAPI Container |
| **Artifact Registry** | `us-central1-docker.pkg.dev/x-woodward/moltrans-containers/askcos2-core-app` | Container Repository |
| **Public Load Balancer IP** | **`8.232.102.201`** | Static Global IPv4 |
| **Backend Service** | `askcos2-core-backend` | Global HTTPS Load Balancer Backend |
| **Serverless NEG** | `askcos2-core-neg` | Cloud Run Serverless NEG (`us-central1`) |

---

## 📦 2. Container Build & Push

Ensure `Dockerfile` matches `Dockerfile_app` so Cloud Build compiles all required dependencies (`google-auth`, `gcloud` CLI, `/opt/conda/bin/python` environment):

```bash
# 1. Sync Dockerfile_app into Dockerfile
cp Dockerfile_app Dockerfile

# 2. Commit and Push to feature branch
git add Dockerfile Dockerfile_app
git commit -m "ci: sync Dockerfile with Dockerfile_app for Cloud Build"
git push origin feature/retrochimera-integration

# 3. Build & Tag Image by Git Commit SHA
COMMIT_SHA=$(git rev-parse --short HEAD)
gcloud builds submit \
    --tag us-central1-docker.pkg.dev/x-woodward/moltrans-containers/askcos2-core-app:${COMMIT_SHA} .
```

---

## 🚀 3. Cloud Run Service Deployment

Deploy the container image to Cloud Run service `askcos2-core-app` with Vertex AI integration environment variables:

```bash
COMMIT_SHA=$(git rev-parse --short HEAD)

gcloud run deploy askcos2-core-app \
    --image us-central1-docker.pkg.dev/x-woodward/moltrans-containers/askcos2-core-app:${COMMIT_SHA} \
    --region us-central1 \
    --project x-woodward \
    --ingress internal-and-cloud-load-balancing \
    --set-env-vars USE_VERTEX_AI=1,VERTEX_PROJECT=x-woodward,VERTEX_LOCATION=us-central1,VERTEX_ENDPOINT_ID=2804467684119412736,RETROCHIMERA_VERTEX_ENDPOINT_ID=2012551031283515392,AIZYNTHFINDER_VERTEX_ENDPOINT_ID=1495270392833507328
```

---

## 🌐 4. Load Balancer & Serverless NEG Setup

If configuring the External Load Balancer and Serverless NEG from scratch:

```bash
# 1. Create Serverless NEG in us-central1
gcloud compute network-endpoint-groups create askcos2-core-neg \
    --region=us-central1 \
    --network-endpoint-type=serverless \
    --cloud-run-service=askcos2-core-app \
    --project=x-woodward

# 2. Attach Serverless NEG to Global Backend Service
gcloud compute backend-services add-backend askcos2-core-backend \
    --global \
    --network-endpoint-group=askcos2-core-neg \
    --network-endpoint-group-region=us-central1 \
    --project=x-woodward
```

---

## 📋 5. Operational Logs & Monitoring

To read live system and application logs from Cloud Run:

```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=askcos2-core-app" \
  --limit=30 \
  --project=x-woodward \
  --format="value(textPayload,jsonPayload.message)"
```
