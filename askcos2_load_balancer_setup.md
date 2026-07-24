# 🌐 ASKCOS2 GCP Load Balancer & Serverless NEG Setup Guide

This guide provides the combined commands and single copy-paste script to create an External HTTP(S) Load Balancer with a Serverless Network Endpoint Group (NEG) for `askcos2-core-app` in GCP project `x-woodward`.

---

## 🚀 One-Click Combined Setup Script

Run this single combined command block in your terminal:

```bash
#!/usr/bin/env bash
set -e

PROJECT_ID="x-woodward"
REGION="us-central1"
SERVICE_NAME="askcos2-core-app"

NEG_NAME="askcos2-core-neg"
BACKEND_NAME="askcos2-core-backend"
URLMAP_NAME="askcos2-core-urlmap"
PROXY_NAME="askcos2-core-http-proxy"
IP_NAME="askcos2-core-ip"
FORWARDING_RULE_NAME="askcos2-core-forwarding-rule"

echo "=== 1. Setting GCP Project to ${PROJECT_ID} ==="
gcloud config set project ${PROJECT_ID}

echo "=== 2. Creating Serverless Network Endpoint Group (NEG) ==="
gcloud compute network-endpoint-groups create ${NEG_NAME} \
    --region=${REGION} \
    --network-endpoint-type=serverless \
    --cloud-run-service=${SERVICE_NAME} \
    --project=${PROJECT_ID} || true

echo "=== 3. Creating Global Backend Service ==="
gcloud compute backend-services create ${BACKEND_NAME} \
    --global \
    --protocol=HTTP \
    --project=${PROJECT_ID} || true

echo "=== 4. Attaching Serverless NEG to Backend Service ==="
gcloud compute backend-services add-backend ${BACKEND_NAME} \
    --global \
    --network-endpoint-group=${NEG_NAME} \
    --network-endpoint-group-region=${REGION} \
    --project=${PROJECT_ID} || true

echo "=== 5. Creating URL Map & Target HTTP Proxy ==="
gcloud compute url-maps create ${URLMAP_NAME} \
    --default-service=${BACKEND_NAME} \
    --project=${PROJECT_ID} || true

gcloud compute target-http-proxies create ${PROXY_NAME} \
    --url-map=${URLMAP_NAME} \
    --project=${PROJECT_ID} || true

echo "=== 6. Reserving Global Static Public IP & Forwarding Rule ==="
gcloud compute addresses create ${IP_NAME} \
    --global \
    --project=${PROJECT_ID} || true

gcloud compute forwarding-rules create ${FORWARDING_RULE_NAME} \
    --global \
    --target-http-proxy=${PROXY_NAME} \
    --address=${IP_NAME} \
    --ports=80 \
    --project=${PROJECT_ID} || true

echo "=== 🎉 Load Balancer Setup Complete! ==="
PUBLIC_IP=$(gcloud compute addresses describe ${IP_NAME} --global --format="value(address)" --project=${PROJECT_ID})
echo "Public Frontend IP Address: http://${PUBLIC_IP}"
```

---

## 🧪 Verifying & Testing the Public Load Balancer

Once the setup completes, test your public REST endpoints directly from any terminal or workstation:

### 1. Single-Step Precursor Expansion (`POST /expand-one`):
```bash
PUBLIC_IP=$(gcloud compute addresses describe askcos2-core-ip --global --format="value(address)" --project=x-woodward)
HOST_HEADER="askcos2-core-app-324499629735.us-central1.run.app"

curl -s -X POST "http://${PUBLIC_IP}/api/v1/retro/expand-one" \
  -H "Host: ${HOST_HEADER}" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "smiles": "CC(=O)OCC",
    "models": ["onmt_moltrans"],
    "settings": {"max_results": 5, "min_plausibility": 0.0}
  }' | jq .
```

### 2. Automated Pathway Search Enqueue (`POST /plan`):
```bash
PUBLIC_IP=$(gcloud compute addresses describe askcos2-core-ip --global --format="value(address)" --project=x-woodward)
HOST_HEADER="askcos2-core-app-324499629735.us-central1.run.app"

curl -s -X POST "http://${PUBLIC_IP}/api/v1/retro/plan" \
  -H "Host: ${HOST_HEADER}" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "target_smiles": "CC(=O)OCC",
    "models": ["onmt_moltrans"]
  }' | jq .
```

