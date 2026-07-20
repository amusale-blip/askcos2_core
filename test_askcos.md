# `askcos2_core` End-to-End Testing & Command Execution Guide

This comprehensive reference document captures exact, step-by-step terminal commands to launch the `askcos2_core` server and test all retrosynthesis API endpoints (both low-level wrappers and high-level Section 3 v1 REST interfaces).

---

## 1. Environment Activation & Dependencies Setup

### 1.1 Activate Python Virtual Environment
Before starting the gateway or running tests, ensure your virtual environment is activated:
```bash
source ~/Downloads/x-woodward-investigations/onmt_MolTrans/.venv/bin/activate
cd ~/Downloads/askcos2_core
```

### 1.2 Start Message Broker Daemons (RabbitMQ & Redis)
For asynchronous Celery queues (`/call-async` and `/api/v1/retro/plan`), ensure RabbitMQ and Redis services are running locally on loopback interfaces:
```bash
# Start Redis daemon
sudo redis-server --daemonize yes

# Start RabbitMQ daemon
sudo service rabbitmq-server start || sudo -u rabbitmq rabbitmq-server -detached
```

---

## 2. Launching Server Processes

### Terminal 1: Launch FastAPI Gateway Server (`app.py`)
Run Uvicorn with loopback host variables so Celery Kombu brokers connect over `127.0.0.1`:
```bash
cd ~/Downloads/askcos2_core
source ~/Downloads/x-woodward-investigations/onmt_MolTrans/.venv/bin/activate

RABBITMQ_HOST=127.0.0.1 REDIS_HOST=127.0.0.1 python3 app.py
```
*(Server listens on `http://0.0.0.0:9100` and automatically mounts all wrapper routes and `/api/v1/retro/*` endpoints)*

### Terminal 2: Launch Celery Background Worker Pool
Run Celery worker process listening on `retro_worker` and default `celery` task queues:
```bash
cd ~/Downloads/askcos2_core
source ~/Downloads/x-woodward-investigations/onmt_MolTrans/.venv/bin/activate

RABBITMQ_HOST=127.0.0.1 REDIS_HOST=127.0.0.1 celery -A askcos2_celery worker -Q retro_worker,celery --loglevel=info
```

---

## 3. Testing Section 3 v1 REST API Endpoints (`Terminal 3`)

These are the primary standardized REST endpoints specified in Section 3 of `project_requirement.txt`.

### 3.1. Interactive Single-Step Expansion (`POST /api/v1/retro/expand-one`)
Evaluates a single target SMILES string and returns immediate precursor candidates using requested models (`onmt_moltrans`).

**Command (`cURL`):**
```bash
curl -s -X POST http://0.0.0.0:9100/api/v1/retro/expand-one \
  -H "Content-Type: application/json" \
  -d '{
    "smiles": "CC(=O)OCC",
    "models": ["onmt_moltrans"],
    "settings": {
      "max_results": 5,
      "min_plausibility": 0.0
    }
  }'
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
      "reactants": [
        "CCOC((C)",
        "CCOC((C)=",
        "CCOC((C)"
      ],
      "scores": [
        0.0224,
        0.0218,
        0.0203
      ]
    }
  ]
}
```

---

### 3.2. Automated Pathway Generation Queue (`POST /api/v1/retro/plan`)
Dispatches automated pathway search to Celery background queue and returns an immediate tracking `job_id`.

**Command (`cURL`):**
```bash
curl -s -X POST http://0.0.0.0:9100/api/v1/retro/plan \
  -H "Content-Type: application/json" \
  -d '{
    "target_smiles": "CC(C)(C)OC(=O)N1CCCC(OCCCCO)CC1",
    "models": ["onmt_moltrans"],
    "search_strategy": {
      "max_time_seconds": 300,
      "max_iterations": 500,
      "max_depth": 10
    },
    "termination_criteria": {
      "buyables_db": "internal_inventory_v1"
    }
  }'
```
**Expected Output (HTTP 200 OK):**
```json
{
  "status_code": 200,
  "job_id": "b5512bdb-9d95-43ec-a348-64a64d169d80",
  "status": "PENDING",
  "message": "Pathway planning job queued successfully"
}
```

---

### 3.3. Job Status & Pathway Retrieval (`GET /api/v1/retro/plan/{job_id}`)
Polls real-time task status and retrieves completed reaction trees once complete.

**Command (`cURL`):**
```bash
curl -s http://0.0.0.0:9100/api/v1/retro/plan/b5512bdb-9d95-43ec-a348-64a64d169d80
```
**Expected Output (HTTP 200 OK):**
```json
{
  "status_code": 200,
  "job_id": "b5512bdb-9d95-43ec-a348-64a64d169d80",
  "complete": false,
  "failed": false,
  "status": "PENDING"
}
```

---

## 4. Testing Low-Level Model Wrapper Routes

Directly query model wrapper endpoints (`/api/retro/onmt-moltrans/*`).

### 4.1. Synchronous Direct Wrapper Query (`/call-sync`)
```bash
curl -s -X POST http://0.0.0.0:9100/api/retro/onmt-moltrans/call-sync \
  -H "Content-Type: application/json" \
  -d '{
    "smiles": ["CC(=O)OCC"],
    "model_name": "onmt-moltrans-service-model",
    "n_best": 3
  }'
```

### 4.2. Asynchronous Direct Wrapper Query (`/call-async`)
```bash
curl -s -X POST http://0.0.0.0:9100/api/retro/onmt-moltrans/call-async \
  -H "Content-Type: application/json" \
  -d '{
    "smiles": ["CC(=O)OCC"],
    "model_name": "onmt-moltrans-service-model",
    "n_best": 3
  }'
```

### 4.3. Poll Direct Task Status (`/celery/task/get`)
```bash
curl -s "http://0.0.0.0:9100/api/celery/task/get?task_id=[YOUR_TASK_ID_OUTPUT_FROM_4.2]"
```

---

## 5. Running Automated Integration Test Suites (`pytest`)

Execute automated integration tests directly against the live server:

### 5.1. Test `onmt_moltrans` Low-Level Wrapper
```bash
cd ~/Downloads/askcos2_core
pytest -s tests/wrappers/retro/retro_onmt_moltrans_test.py
```

### 5.2. Test Standardized Section 3 v1 REST Endpoints
```bash
cd ~/Downloads/askcos2_core
pytest -s tests/routes/test_v1_retro.py
```
