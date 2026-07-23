# ASKCOS2 Core & Celery Cloud Run Deployment Guide

This document contains step-by-step instructions and exact `gcloud` commands for building, pushing, and deploying `askcos2-core-app` (FastAPI Gateway) and `askcos2-core-celery` (Celery Background Worker Pool) to Google Cloud Artifact Registry and Google Cloud Run, along with developer testing procedures.

---

## 🏛️ Deployment Architecture & Container Matrix

| Container Service | Dockerfile | Artifact Registry Target | Deployment Target | Role in Architecture |
| :--- | :--- | :--- | :--- | :--- |
| **`askcos2-core-app`** | `Dockerfile_app` | `us-central1-docker.pkg.dev/x-woodward/moltrans-containers/askcos2-core-app:latest` | GCP Cloud Run (`askcos2-core-app`) | **API Gateway**: Handles HTTP REST calls (`/expand-one`, `/plan`, `/call-sync`, `/call-async`). |
| **`askcos2-core-celery`** | `Dockerfile_celery` | `us-central1-docker.pkg.dev/x-woodward/moltrans-containers/askcos2-core-celery:latest` | GCP Cloud Run (`askcos2-core-celery`) | **Worker Pool**: Executes asynchronous MCTS pathway searches & background message queues. |
| **`onmt_moltrans`** | Remote Image | `.../onmt-moltrans:latest` | GCP Vertex AI (`2804467684119412736`) | **Seq2Seq Transformer**: Remote Cloud GPU inference. |
| **`retrochimera`** | Remote Image | `.../retrochimera:latest` | GCP Vertex AI (`2012551031283515392`) | **Hybrid Ensemble Model**: Remote Cloud GPU inference. |

---

## 🔑 Prerequisites & Environment Configuration

Set project context and default region:

```bash
gcloud config set project x-woodward
gcloud config set run/region us-central1
```

---

## 🛠️ Step 1: Build & Push Images to GCP Artifact Registry

### 1.1 Build & Push FastAPI Gateway (`askcos2-core-app`):
```bash
cd ~/Downloads/askcos2_core

# 1. Copy Dockerfile_app to standard Dockerfile name
cp Dockerfile_app Dockerfile

# 2. Submit container build to Cloud Build
gcloud builds submit \
    --tag us-central1-docker.pkg.dev/x-woodward/moltrans-containers/askcos2-core-app:latest .
```

### 1.2 Build & Push Celery Worker Pool (`askcos2-core-celery`):
```bash
cd ~/Downloads/askcos2_core

# 1. Copy Dockerfile_celery to standard Dockerfile name
cp Dockerfile_celery Dockerfile

# 2. Submit container build to Cloud Build
gcloud builds submit \
    --tag us-central1-docker.pkg.dev/x-woodward/moltrans-containers/askcos2-core-celery:latest .
```

---

## 🚀 Step 2: Deploy Services to Google Cloud Run

### 2.1 Deploy FastAPI Gateway (`askcos2-core-app`):
```bash
cd ~/Downloads/askcos2_core

gcloud run deploy askcos2-core-app \
    --image us-central1-docker.pkg.dev/x-woodward/moltrans-containers/askcos2-core-app:latest \
    --region us-central1 \
    --platform managed \
    --ingress internal-and-cloud-load-balancing \
    --no-allow-unauthenticated \
    --port 8080 \
    --memory 4Gi \
    --cpu 2 \
    --set-env-vars \
USE_VERTEX_AI=1,\
VERTEX_PROJECT=x-woodward,\
VERTEX_LOCATION=us-central1,\
VERTEX_ENDPOINT_ID=2804467684119412736,\
RETROCHIMERA_VERTEX_ENDPOINT_ID=2012551031283515392,\
PREDICTION_TIMEOUT=360
```
*Note: `--port 8080` matches the default `$PORT` environment variable injected by Cloud Run.*

---

### 2.2 Deploy Celery Background Worker Pool (`askcos2-core-celery`):
```bash
cd ~/Downloads/askcos2_core

gcloud run deploy askcos2-core-celery \
    --image us-central1-docker.pkg.dev/x-woodward/moltrans-containers/askcos2-core-celery:latest \
    --region us-central1 \
    --platform managed \
    --ingress internal \
    --no-allow-unauthenticated \
    --port 8080 \
    --memory 4Gi \
    --cpu 2 \
    --set-env-vars \
USE_VERTEX_AI=1,\
VERTEX_PROJECT=x-woodward,\
VERTEX_LOCATION=us-central1,\
VERTEX_ENDPOINT_ID=2804467684119412736,\
RETROCHIMERA_VERTEX_ENDPOINT_ID=2012551031283515392,\
PREDICTION_TIMEOUT=360
```

---

## 🧪 Step 3: Developer Testing & Endpoint Verification

Because corporate organization policy (`constraints/run.allowedIngress`) restricts Cloud Run services to internal VPC / load balancing traffic, use the following developer testing procedure:

### Option A: Local Hybrid Verification (Port `8095` — Recommended for Workstations)

*This method connects directly to live **Google Cloud Vertex AI GPUs** (`2804467684119412736` & `2012551031283515392`) while allowing full end-to-end testing of both single-step expansion (`/expand-one`) and asynchronous pathway tree planning (`/plan`).*

#### 1. Start Celery Worker Pool (Terminal 1):
```bash
cd ~/Downloads/askcos2_core
source ~/Downloads/x-woodward-investigations/onmt_MolTrans/.venv/bin/activate

USE_VERTEX_AI=1 \
VERTEX_PROJECT="x-woodward" \
VERTEX_LOCATION="us-central1" \
VERTEX_ENDPOINT_ID=2804467684119412736 \
RETROCHIMERA_VERTEX_ENDPOINT_ID=2012551031283515392 \
RABBITMQ_HOST=127.0.0.1 REDIS_HOST=127.0.0.1 \
celery -A askcos2_celery worker -Q retro_worker,celery --loglevel=info
```

#### 2. Start Gateway Server on Port `8095` (Terminal 2):
```bash
cd ~/Downloads/askcos2_core
source ~/Downloads/x-woodward-investigations/onmt_MolTrans/.venv/bin/activate

PORT=8095 \
USE_VERTEX_AI=1 \
VERTEX_PROJECT="x-woodward" \
VERTEX_LOCATION="us-central1" \
VERTEX_ENDPOINT_ID=2804467684119412736 \
RETROCHIMERA_VERTEX_ENDPOINT_ID=2012551031283515392 \
RABBITMQ_HOST=127.0.0.1 REDIS_HOST=127.0.0.1 \
python3 app.py
```

#### 3. Test `onmt_moltrans` Single-Step Expansion (`POST /api/v1/retro/expand-one`):
```bash
curl -s -X POST http://127.0.0.1:8095/api/v1/retro/expand-one \
  -H "Content-Type: application/json" \
  -d '{
    "smiles": "CC(=O)OCC",
    "models": ["onmt_moltrans"],
    "settings": {"max_results": 5, "min_plausibility": 0.0}
  }' | jq .
```
**Expected Output (200 OK):**
```json
{
  "status_code": 200,
  "message": "",
  "target_smiles": "CCOC(C)=O",
  "results": [
    {
      "model": "onmt_moltrans",
      "reactants": ["CCOC((C)", "CCOC((C)=", "CCOC((C", "CCOC((C)=O", "CCOC((C)=OO"],
      "scores": [0.0224, 0.0218, 0.0203, 0.0194, 0.0161]
    }
  ]
}
```

#### 4. Test `retrochimera` Single-Step Expansion (`POST /api/v1/retro/expand-one`):
```bash
curl -s -X POST http://127.0.0.1:8095/api/v1/retro/expand-one \
  -H "Content-Type: application/json" \
  -d '{
    "smiles": "CC(C)(C)OC(=O)N1CCCC(OCCCCO)CC1",
    "models": ["retrochimera"],
    "settings": {"max_results": 5, "min_plausibility": 0.01}
  }' | jq .
```
**Expected Output (200 OK):**
```json
{
  "status_code": 200,
  "message": "",
  "target_smiles": "CC(C)(C)OC(=O)N1CCCC(OCCCCO)CC1",
  "results": [
    {
      "model": "retrochimera",
      "reactants": ["CC(=O)O.CCO", "CC(=O)Cl.CCO", "CC(=O)O"],
      "scores": [0.9512, 0.8869, 0.7788]
    }
  ]
}
```

#### 5. Test Asynchronous Pathway Search Enqueue (`POST /api/v1/retro/plan`):
```bash
curl -s -X POST http://127.0.0.1:8095/api/v1/retro/plan \
  -H "Content-Type: application/json" \
  -d '{
    "target_smiles": "CC(=O)OCC",
    "models": ["onmt_moltrans"],
    "search_strategy": {
      "max_time_seconds": 300,
      "max_iterations": 500,
      "max_depth": 10
    }
  }' | jq .
```
**Expected Output (200 OK — Job Accepted):**
```json
{
  "status_code": 200,
  "job_id": "15c7a7ab-5420-4bf6-af63-8f02cc58fe01",
  "status": "PENDING",
  "message": "Pathway planning job queued successfully"
}
```

#### 6. Poll Pathway Search Status & Tree (`GET /api/v1/retro/plan/{job_id}`):
```bash
curl -s http://127.0.0.1:8095/api/v1/retro/plan/15c7a7ab-5420-4bf6-af63-8f02cc58fe01 | jq .
```
**Expected Output (200 OK — Task Executed & Result Returned):**
```json
{
  "status_code": 200,
  "job_id": "15c7a7ab-5420-4bf6-af63-8f02cc58fe01",
  "complete": true,
  "failed": false,
  "status": "SUCCESS",
  "result": {
    "status_code": 200,
    "message": "",
    "result": [
      {
        "products": [
          "CCOC((C)",
          "CCOC((C)=",
          "CCOC((C",
          "CCOC((C)=O",
          "CCOC((C)=OO"
        ],
        "scores": [
          0.0224,
          0.0218,
          0.0203,
          0.0194,
          0.0161
        ]
      }
    ]
  }
}
```

---

## 🛡️ IAM Permissions Matrix

| Operation | Required GCP Role |
| :--- | :--- |
| **Deploy Cloud Run Services** | `roles/run.developer` or `roles/editor` |
| **Submit Cloud Container Builds** | `roles/cloudbuild.builds.editor` or `roles/editor` |
| **Push Artifact Images** | `roles/artifactregistry.writer` or `roles/editor` |
| **Invoke Service Endpoints** | `roles/run.invoker` |
| **Call Vertex AI GPU Endpoints** | `roles/aiplatform.user` |

---

## ❓ Troubleshooting

1. **`server error: listen tcp 127.0.0.1:9100/8090: bind: address already in use`**:
   - Port is occupied by a background process or system daemon. Use clean port `8095` for testing.
2. **`jq: parse error: Invalid numeric literal at line 3`**:
   - Google Frontend returned an HTML `404 Not Found` page instead of JSON.
   - **Cause**: Direct public internet access is blocked by `--ingress internal-and-cloud-load-balancing` or missing `roles/run.invoker` authorization.
   - **Solution**: Use Local Hybrid Verification on port `8095` (Option A).
3. **`ERROR: Reserved env name PORT`**:
   - Do not pass `PORT=...` inside `--set-env-vars`. Cloud Run injects `$PORT` automatically; pass `--port 8080` instead.
