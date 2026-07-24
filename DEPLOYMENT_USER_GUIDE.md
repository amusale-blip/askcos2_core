# ASKCOSv2 Core App Deployment & Testing User Guide

This guide documents the complete end-to-end workflow to build, deploy, and verify the `askcos2-core-app` service on **Google Cloud Run** behind the **External Public Load Balancer (`8.232.102.201`)** with **Vertex AI** integration.

---

## 🛠️ Step 1: Code & Dockerfile Synchronization

Ensure `Dockerfile` matches `Dockerfile_app` so Cloud Build compiles all required dependencies (`google-auth`, `gcloud` CLI, `/opt/conda/bin/python` environment):

```bash
# Sync Dockerfile_app to Dockerfile
cp Dockerfile_app Dockerfile

# Commit and Push to feature branch
git add Dockerfile Dockerfile_app
git commit -m "ci: sync Dockerfile with Dockerfile_app for Cloud Build"
git push origin feature/retrochimera-integration
```

---

## 📦 Step 2: Build Image on GCP Cloud Build

Compile the container image in Google Cloud Build tagged with the current Git commit SHA:

```bash
# Capture short Git commit SHA
COMMIT_SHA=$(git rev-parse --short HEAD)
echo "Building version tag: ${COMMIT_SHA}"

# Submit build to Artifact Registry
gcloud builds submit \
    --tag us-central1-docker.pkg.dev/x-woodward/moltrans-containers/askcos2-core-app:${COMMIT_SHA} .
```

---

## 🚀 Step 3: Deploy Image Revision to Cloud Run

Deploy the container image to Cloud Run service `askcos2-core-app` in region `us-central1` with Vertex AI environment variables:

```bash
COMMIT_SHA=$(git rev-parse --short HEAD)

gcloud run deploy askcos2-core-app \
    --image us-central1-docker.pkg.dev/x-woodward/moltrans-containers/askcos2-core-app:${COMMIT_SHA} \
    --region us-central1 \
    --project x-woodward \
    --ingress internal-and-cloud-load-balancing \
    --set-env-vars USE_VERTEX_AI=1,VERTEX_PROJECT=x-woodward,VERTEX_LOCATION=us-central1,VERTEX_ENDPOINT_ID=2804467684119412736,RETROCHIMERA_VERTEX_ENDPOINT_ID=2012551031283515392
```

---

## 🧪 Step 4: Test `/expand-one` (Single-Step Retrosynthesis)

Execute `cURL` test over the **Public Load Balancer Static IP (`8.232.102.201`)**:

```bash
PUBLIC_IP="8.232.102.201"
HOST_HEADER="askcos2-core-app-324499629735.us-central1.run.app"

curl -s -X POST "http://${PUBLIC_IP}/api/v1/retro/expand-one" \
  -H "Host: ${HOST_HEADER}" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "smiles": "CC(=O)OCC",
    "models": ["onmt_moltrans", "retrochimera"],
    "settings": {"max_results": 5, "min_plausibility": 0.0}
  }' | jq .
```

### Expected Output:
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
    },
    {
      "model": "retrochimera",
      "reactants": [
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
```

---

## 🌳 Step 5: Queue `/plan` (Full Route Tree Search)

Execute full retrosynthetic tree planning search (Note: expects key `"target_smiles"`):

```bash
PUBLIC_IP="8.232.102.201"
HOST_HEADER="askcos2-core-app-324499629735.us-central1.run.app"

curl -s -X POST "http://${PUBLIC_IP}/api/v1/retro/plan" \
  -H "Host: ${HOST_HEADER}" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "target_smiles": "CC(=O)OCC",
    "models": ["onmt_moltrans", "retrochimera"]
  }' | jq .
```

### Expected Output:
```json
{
  "status_code": 200,
  "job_id": "f5a22574-e1e3-4697-9647-bc544c098f6b",
  "status": "PENDING",
  "message": "Pathway planning job queued successfully"
}
```

---

## 🔄 Step 6: Poll `/plan/{job_id}` (Retrieve Job Status & Pathway Tree)

Poll the job status endpoint using the `job_id` returned from Step 5:

```bash
PUBLIC_IP="8.232.102.201"
HOST_HEADER="askcos2-core-app-324499629735.us-central1.run.app"
JOB_ID="f5a22574-e1e3-4697-9647-bc544c098f6b"

curl -s -X GET "http://${PUBLIC_IP}/api/v1/retro/plan/${JOB_ID}" \
  -H "Host: ${HOST_HEADER}" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq .
```

### Response Statuses:
- **Pending/Processing**:
  ```json
  {
    "status_code": 200,
    "job_id": "f5a22574-e1e3-4697-9647-bc544c098f6b",
    "complete": false,
    "failed": false,
    "status": "PENDING"
  }
  ```
- **Completed (Success)**:
  ```json
  {
    "status_code": 200,
    "job_id": "f5a22574-e1e3-4697-9647-bc544c098f6b",
    "complete": true,
    "failed": false,
    "status": "SUCCESS",
    "result": { ... }
  }
  ```

---

## 📋 Step 7: Inspect Cloud Run Service Logs

To view live application logs from Cloud Run:

```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=askcos2-core-app" \
  --limit=30 \
  --project=x-woodward \
  --format="value(textPayload,jsonPayload.message)"
```
