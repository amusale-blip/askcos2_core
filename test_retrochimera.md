# RetroChimera End-to-End Testing & Execution Guide (`askcos2_core`)

This reference document provides exact step-by-step instructions, terminal commands, and cURL payloads to launch and test the **RetroChimera** retrosynthesis integration within the `askcos2_core` API Gateway.

---

## 1. Testing Modes Overview

The `retro_retrochimera` wrapper supports two distinct operational modes:
1. **Local Microservice / Mock Mode (`USE_VERTEX_AI=0`)**: Connects to a local Docker container or live uvicorn server running the RetroChimera model (or mock predictor) via standard HTTP REST. Ideal for local development, networking verification, and regression testing.
2. **Vertex AI Production Mode (`USE_VERTEX_AI=1`)**: Connects to scalable Google Cloud Vertex AI custom prediction endpoints using corporate mTLS/CBA authentication over `gcloud ai endpoints predict`. Accommodates scale-to-zero cold boots (3–5 minutes) with a 360-second timeout.

---

## 2. 5-Terminal Local Testing Setup (Complete End-to-End Verification)

To verify all gateway networking, Pydantic schemas, SMILES canonicalization, real model inference (or mock mode), and asynchronous Celery/Redis queueing, run the following 5-terminal architecture:

### 🟢 Terminal 1: Start Message Brokers (Redis & RabbitMQ)
Ensure the local message brokers are active and listening for Celery task routing:
```bash
sudo redis-server --daemonize yes
sudo service rabbitmq-server start || sudo -u rabbitmq rabbitmq-server -detached
```

### 🟢 Terminal 2: Start RetroChimera Model Service (`port 8080`)
Start the standalone RetroChimera FastAPI microservice that loads PyTorch checkpoints and evaluates chemistry:
```bash
cd ~/Downloads/retrochimera
source ~/Downloads/x-woodward-investigations/onmt_MolTrans/.venv/bin/activate

# To run real PyTorch model weights (CPU/GPU auto-detect):
AIP_HTTP_PORT=8080 python3 app.py

# (Optional) To run in lightweight memory mock mode without model loading:
# MOCK_TRANSLATOR=1 AIP_HTTP_PORT=8080 python3 app.py
```
⏳ *Wait until you see:* `Uvicorn running on http://0.0.0.0:8080`

### 🟢 Terminal 3: Start `askcos2_core` API Gateway (`port 9100`)
Start Uvicorn on port `9100` with `USE_VERTEX_AI=0` so it routes model requests to your local port `8080` microservice:
```bash
cd ~/Downloads/askcos2_core
source ~/Downloads/x-woodward-investigations/onmt_MolTrans/.venv/bin/activate

USE_VERTEX_AI=0 RETROCHIMERA_PREDICTION_URL=http://127.0.0.1:8080 python3 app.py
```
⏳ *Wait until you see:* `Uvicorn running on http://0.0.0.0:9100`

### 🟢 Terminal 4: Start Celery Worker Daemon
Start the background worker that pulls `/plan` pathway jobs from RabbitMQ and runs MCTS tree searches:
```bash
cd ~/Downloads/askcos2_core
source ~/Downloads/x-woodward-investigations/onmt_MolTrans/.venv/bin/activate

USE_VERTEX_AI=0 RETROCHIMERA_PREDICTION_URL=http://127.0.0.1:8080 RABBITMQ_HOST=127.0.0.1 REDIS_HOST=127.0.0.1 celery -A askcos2_celery worker -Q retro_worker,celery --loglevel=info
```
⏳ *Wait until you see:* `celery@... ready.`

### 🟢 Terminal 5: Execute Automated & Manual Tests!
With Terminals 1 through 4 actively running, use Terminal 5 to run tests or manual curl commands:

#### Option A: Run Automated Pytest / Unittest Suites
```bash
cd ~/Downloads/askcos2_core
source ~/Downloads/x-woodward-investigations/onmt_MolTrans/.venv/bin/activate

python3 -m unittest -v tests/wrappers/retro/retro_retrochimera_test.py tests/routes/test_v1_retro.py
```

#### Option B: Manual cURL Verification
See Section 4 below for step-by-step manual `curl` verification snippets.

---

## 3. Option B: Vertex AI Production Mode Testing

To test live cloud inference against your deployed Vertex AI custom model endpoint:

### Terminal 1: Launch `askcos2_core` API Gateway (Vertex AI Mode)
Ensure you are authenticated with Google Cloud (`gcloud auth login`) and start the gateway with `USE_VERTEX_AI=1`:
```bash
cd ~/Downloads/askcos2_core
source ~/Downloads/x-woodward-investigations/onmt_MolTrans/.venv/bin/activate

USE_VERTEX_AI=1 \
VERTEX_PROJECT="x-woodward" \
VERTEX_LOCATION="us-central1" \
RETROCHIMERA_VERTEX_ENDPOINT_ID="YOUR_VERTEX_ENDPOINT_ID" \
python3 app.py
```
*(Note: Initial requests to cold-started zero-scaled nodes may take 3–5 minutes. The wrapper is configured with a 360s socket timeout to accommodate warmup).*

---

## 4. Manual cURL & API Verification Commands

You can manually trigger and verify individual endpoints using `curl` in a separate terminal while `askcos2_core` is running on port `9100`.

### 4.1. Synchronous Single-Step Expansion (`POST /api/v1/retro/expand-one`)
Standard Section 3.1 interactive single-step planning endpoint:

```bash
curl -s -X POST http://0.0.0.0:9100/api/v1/retro/expand-one \
  -H "Content-Type: application/json" \
  -d '{
    "smiles": "CC(C)(C)OC(=O)N1CCCC(OCCCCO)CC1",
    "models": ["retrochimera"],
    "settings": {
      "max_results": 5,
      "min_plausibility": 0.01
    }
  }' | jq .
```

**Expected JSON Output:**
```json
{
  "status_code": 200,
  "message": "",
  "target_smiles": "CC(C)(C)OC(=O)N1CCCC(OCCCCO)CC1",
  "results": [
    {
      "model": "retrochimera",
      "reactants": [
        "CC(=O)O.CCO",
        "CC(=O)Cl.CCO",
        "CC(=O)O"
      ],
      "scores": [
        0.85,
        0.8,
        0.7
      ]
    }
  ]
}
```

---

### 4.2. Automated Pathway Generation Queue (`POST /api/v1/retro/plan`)
Standard Section 3.2 asynchronous batch planning endpoint:

```bash
curl -s -X POST http://0.0.0.0:9100/api/v1/retro/plan \
  -H "Content-Type: application/json" \
  -d '{
    "target_smiles": "CC(C)(C)OC(=O)N1CCCC(OCCCCO)CC1",
    "models": ["retrochimera"],
    "search_strategy": {
      "max_time_seconds": 300,
      "max_iterations": 500,
      "max_depth": 10
    },
    "termination_criteria": {
      "buyables_db": "internal_inventory_v1"
    }
  }' | jq .
```

**Expected JSON Output:**
```json
{
  "status_code": 200,
  "job_id": "c0c339b1-85c3-48eb-8f6a-3c3fa42603ce",
  "status": "PENDING",
  "message": "Pathway planning job queued successfully"
}
```

---

### 4.3. Job Status & Pathway Retrieval (`GET /api/v1/retro/plan/{job_id}`)
Standard Section 3.3 polling endpoint using the `job_id` returned above:

```bash
# Replace <YOUR_JOB_ID> with the job_id from the /plan response
curl -s -X GET http://0.0.0.0:9100/api/v1/retro/plan/<YOUR_JOB_ID> | jq .
```

**Expected JSON Output (While Exploring):**
```json
{
  "status_code": 200,
  "job_id": "c0c339b1-85c3-48eb-8f6a-3c3fa42603ce",
  "complete": false,
  "failed": false,
  "status": "PENDING"
}
```

**Expected JSON Output (Once Completed):**
```json
{
  "status_code": 200,
  "job_id": "c0c339b1-85c3-48eb-8f6a-3c3fa42603ce",
  "complete": true,
  "failed": false,
  "status": "SUCCESS",
  "result": {
    "status_code": 200,
    "message": "",
    "result": [
      {
        "products": [
          "CC(=O)O.CCO",
          "CC(=O)Cl.CCO",
          "CC(=O)O"
        ],
        "scores": [
          0.9512,
          0.8869,
          0.7788
        ]
      }
    ]
  }
}
```

---

### 4.4. Low-Level Wrapper Synchronous Call (`POST /api/retro/retrochimera/call-sync`)
Direct query to the underlying `RetroChimeraWrapper` implementation without v1 RDKit canonicalization formatting:

```bash
curl -s -X POST http://0.0.0.0:9100/api/retro/retrochimera/call-sync \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "retrochimera-service-model",
    "smiles": ["CC(=O)OCC"],
    "n_best": 3
  }' | jq .
```

**Expected JSON Output:**
```json
{
  "status_code": 200,
  "message": "",
  "result": [
    {
      "products": [
        "CC(=O)O.CCO",
        "CC(=O)Cl.CCO",
        "CC(=O)O"
      ],
      "scores": [
        0.85,
        0.8,
        0.7
      ]
    }
  ]
}
```

---

## 5. Troubleshooting & Common Gotchas

* **`ConnectionRefusedError: [Errno 111] Connection refused` on port 8080:**
  Ensure the local RetroChimera service is actively running in Terminal 1 (`MOCK_TRANSLATOR=1 python3 app.py`).
* **`Unsupported model_name` Error:**
  Check `configs/module_config_retro.py` to ensure `"retrochimera-service-model"` is listed inside `"available_model_names"`.
* **Vertex AI Timeout Error:**
  If zero-scaled GPU VMs take longer than 5 minutes to boot, set `PREDICTION_TIMEOUT=600` in your environment variables when starting `app.py`.