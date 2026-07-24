# 🧪 ASKCOS2 Retrosynthesis Testing Guide

This guide is structured into two distinct sections depending on your setup level:

1. **🌟 Part 1: Zero-Setup Testing Guide** *(Zero Code / Zero Setup — GCP Terminal Access Only)*
2. **🛠️ Part 2: Full Setup Testing Guide** *(Repository Cloning, Dependency Installation, Local Hybrid Gateway & Celery Worker Pool)*

---

# 🌟 Part 1: Zero-Setup Testing Guide (GCP Terminal Access Only)

*Use this section if you have **no local code, no python, no redis, and no rabbitmq**, and only have a terminal authenticated with GCP project `x-woodward`.*

---

## ⚡ Method A: Direct Cloud Prediction via `gcloud` CLI (No Server Required)

No python, docker, or local server required! Send predictions directly to the remote Google Cloud Vertex AI GPU nodes:

### 1. Set Google Cloud Project:
```bash
gcloud config set project x-woodward
```

### 2. Predict Precursor Reactions — ONMT Transformer Model:
```bash
gcloud ai endpoints predict 2804467684119412736 \
    --region=us-central1 \
    --json-request=<(echo '{"instances": [{"smiles": "CC(=O)OCC", "n_best": 5}]}')
```

### 3. Predict Precursor Reactions — RetroChimera Hybrid Model:
```bash
gcloud ai endpoints predict 2012551031283515392 \
    --region=us-central1 \
    --json-request=<(echo '{"instances": [{"smiles": "CC(C)(C)OC(=O)N1CCCC(OCCCCO)CC1", "model_name": "retrochimera-service-model", "n_best": 5}]}')
```

---

## 🌉 Method B: Deployed Cloud Run REST API Gateway (`cURL` + Identity Token)

Call the deployed Cloud Run service URL directly using Google OAuth Identity Token:

```bash
# 1. Get Cloud Run Service URL
SERVICE_URL=$(gcloud run services describe askcos2-core-app --region us-central1 --format="value(status.url)")

# 2. Send Single-Step Expansion Request (/expand-one)
curl -s -X POST "${SERVICE_URL}/api/v1/retro/expand-one" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "smiles": "CC(=O)OCC",
    "models": ["onmt_moltrans", "retrochimera"],
    "settings": {"max_results": 5, "min_plausibility": 0.0}
  }' | jq .
```

---
---

# 🛠️ Part 2: Full Setup Testing Guide (Repository Cloning & Environment Build)

*Use this section if you are setting up the repository codebase from scratch.*

---

## 📥 Step 1: Clone Repository & Checkout Branch

Clone the `askcos2_core` repository and checkout the integration branch:

```bash
# 1. Clone repository
git clone git@github.com:amusale-blip/askcos2_core.git
cd askcos2_core

# 2. Checkout integration branch
git checkout feature/retrochimera-integration
```

---

## 🐍 Step 2: Create Python Virtual Environment & Install Dependencies

Set up a clean Python 3.10 virtual environment and install project dependencies:

```bash
# 1. Create virtual environment
python3 -m venv .venv

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Upgrade pip & install dependencies
pip install --upgrade pip
pip install \
    rdkit \
    fastapi \
    "fastapi[standard]" \
    uvicorn \
    celery[amqp,redis] \
    redis \
    pydantic \
    requests \
    python-dotenv \
    google-cloud-aiplatform \
    pytest
```

---

## 📦 Step 3: Install & Start Message Brokers (Redis & RabbitMQ)

Install and launch local Redis and RabbitMQ daemons for Celery background task routing:

```bash
# 1. Install Redis & RabbitMQ (Linux Debian/Ubuntu)
sudo apt-get update && sudo apt-get install -y redis-server rabbitmq-server

# 2. Start Redis in background
sudo redis-server --daemonize yes

# 3. Start RabbitMQ service
sudo service rabbitmq-server start || sudo -u rabbitmq rabbitmq-server -detached
```

---

## 🔑 Step 4: Configure GCP Application Credentials & Environment Variables

Authenticate with Google Cloud and export Cloud Vertex AI endpoint IDs:

```bash
# 1. Authenticate Google Cloud CLI & ADC
gcloud auth login
gcloud auth application-default login
gcloud config set project x-woodward

# 2. Export GCP Vertex AI Environment Variables
export USE_VERTEX_AI=1
export VERTEX_PROJECT="x-woodward"
export VERTEX_LOCATION="us-central1"
export VERTEX_ENDPOINT_ID=2804467684119412736
export RETROCHIMERA_VERTEX_ENDPOINT_ID=2012551031283515392
export RABBITMQ_HOST=127.0.0.1
export REDIS_HOST=127.0.0.1
```

---

## ⚡ Step 5: Launch Backend Services

### Terminal 1 — Start Celery Worker Pool:
```bash
cd ~/Downloads/askcos2_core
source .venv/bin/activate

USE_VERTEX_AI=1 \
VERTEX_PROJECT="x-woodward" \
VERTEX_LOCATION="us-central1" \
VERTEX_ENDPOINT_ID=2804467684119412736 \
RETROCHIMERA_VERTEX_ENDPOINT_ID=2012551031283515392 \
RABBITMQ_HOST=127.0.0.1 REDIS_HOST=127.0.0.1 \
celery -A askcos2_celery worker -Q retro_worker,celery --loglevel=info
```

### Terminal 2 — Start FastAPI Gateway (Port `8095`):
```bash
cd ~/Downloads/askcos2_core
source .venv/bin/activate

PORT=8095 \
USE_VERTEX_AI=1 \
VERTEX_PROJECT="x-woodward" \
VERTEX_LOCATION="us-central1" \
VERTEX_ENDPOINT_ID=2804467684119412736 \
RETROCHIMERA_VERTEX_ENDPOINT_ID=2012551031283515392 \
RABBITMQ_HOST=127.0.0.1 REDIS_HOST=127.0.0.1 \
python3 app.py
```
*Wait until output shows:* `INFO: Uvicorn running on http://0.0.0.0:8095`

---

## 🚀 Step 6: Execute Test Suite (Terminal 3)

### 6.1 Single-Step Precursor Expansion (`POST /api/v1/retro/expand-one`)
Evaluates target molecule and queries ONMT & RetroChimera models simultaneously:

```bash
curl -s -X POST http://127.0.0.1:8095/api/v1/retro/expand-one \
  -H "Content-Type: application/json" \
  -d '{
    "smiles": "CC(=O)OCC",
    "models": ["onmt_moltrans", "retrochimera"],
    "settings": {"max_results": 5, "min_plausibility": 0.0}
  }' | jq .
```
**Expected Output (HTTP 200 OK):**
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
    },
    {
      "model": "retrochimera",
      "reactants": ["CC(=O)O.CCO", "CC(=O)Cl.CCO", "CC(=O)O"],
      "scores": [0.9512, 0.8869, 0.7788]
    }
  ]
}
```

---

### 6.2 Asynchronous Pathway Search Enqueue (`POST /api/v1/retro/plan`)
Triggers an MCTS tree search to synthesize target molecule back to available starting materials:

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
**Expected Output (HTTP 200 OK — Job Queued):**
```json
{
  "status_code": 200,
  "job_id": "15c7a7ab-5420-4bf6-af63-8f02cc58fe01",
  "status": "PENDING",
  "message": "Pathway planning job queued successfully"
}
```

---

### 6.3 Poll Pathway Search Status & Tree (`GET /api/v1/retro/plan/{job_id}`)
Retrieve the full completed retrosynthetic pathway tree:

```bash
curl -s http://127.0.0.1:8095/api/v1/retro/plan/<YOUR_JOB_ID> | jq .
```
**Expected Output (HTTP 200 OK — Task Executed):**
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

### 6.4 Interactive OpenAPI / Swagger UI (Browser)
Open your web browser and navigate to:
```text
http://127.0.0.1:8095/docs
```

---

### 6.5 Automated Pytest Test Suite
Run automated unit and integration tests across wrappers and routes:

```bash
python3 -m pytest -s \
  tests/routes/test_v1_retro.py \
  tests/wrappers/retro/retro_onmt_moltrans_test.py \
  tests/wrappers/retro/retro_retrochimera_test.py
```
---

# 🖥️ Part 3: Interactive Web Application UI (`http://127.0.0.1:8095/`)

A modern, responsive single-page web workspace built specifically for researchers to explore retrosynthesis predictions visually without writing code:

### 🌟 Key Web UI Features:
1. **Dynamic Gateway Connection Status**: Automatically polls active model discovery on launch.
2. **Molecule SMILES Preset Pills**: Instant presets (`Ethyl Acetate`, `Boc-Protected Amine`, `Aspirin`, `Paracetamol`).
3. **Interactive Pre-flight Validator (`⚡ Validate`)**: Validates structure and renders canonical 2D chemical structure diagrams.
4. **Multi-Model Selector**: Checkbox toggles for `ONMT MolTrans` and `RetroChimera`.
5. **Interactive Single-step Expansion (`🔬 Expand One Step`)**: Displays predicted precursor cards with model confidence scores.
6. **MCTS Pathway Tree Visualizer (`🌳 Plan Pathway Tree`)**: Asynchronous job queue launcher and live status polling.
7. **Swagger OpenAPI Spec Link**: One-click navigation to interactive browser docs (`http://127.0.0.1:8095/docs`).

---

### 🚀 How to Access the Web UI:

1. Launch Gateway Server:
   ```bash
   PORT=8095 python3 app.py
   ```
2. Open your web browser and navigate to:
   ```text
   http://127.0.0.1:8095/
   ```


