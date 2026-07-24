# ASKCOSv2 Core App - Master Retrosynthesis API & Testing Guide

This guide documents the REST API specification, available retrosynthesis models (`onmt_moltrans` and `retrochimera`), request payloads, and testing commands over the Public Load Balancer (`8.232.102.201`).

---

## 🧪 1. Single-Step Retrosynthesis (`POST /api/v1/retro/expand-one`)

Evaluates a target SMILES string synchronously and returns candidate precursor reactant molecules and probability confidence scores.

### Request Command:
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

### Response Payload:
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

## 🌳 2. Automated Pathway Generation (`POST /api/v1/retro/plan`)

Initiates pathway search for a target molecule (`target_smiles`) across models.

### Request Command:
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

### Response Payload:
```json
{
  "status_code": 200,
  "job_id": "f5a22574-e1e3-4697-9647-bc544c098f6b",
  "status": "PENDING",
  "message": "Pathway planning job queued successfully"
}
```

---

## 🔄 3. Poll Job Status (`GET /api/v1/retro/plan/{job_id}`)

Retrieves the execution status and resolved pathway tree for a queued plan job:

```bash
PUBLIC_IP="8.232.102.201"
HOST_HEADER="askcos2-core-app-324499629735.us-central1.run.app"
JOB_ID="f5a22574-e1e3-4697-9647-bc544c098f6b"

curl -s -X GET "http://${PUBLIC_IP}/api/v1/retro/plan/${JOB_ID}" \
  -H "Host: ${HOST_HEADER}" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq .
```

---

## 🔍 4. Dynamic Model Discovery (`GET /api/v1/retro/models`)

Returns all available active retrosynthesis models for frontend dropdown population:

### Request Command:
```bash
PUBLIC_IP="8.232.102.201"
HOST_HEADER="askcos2-core-app-324499629735.us-central1.run.app"

curl -s -X GET "http://${PUBLIC_IP}/api/v1/retro/models" \
  -H "Host: ${HOST_HEADER}" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" | jq .
```

### Response Payload:
```json
{
  "status_code": 200,
  "models": [
    {
      "model_name": "onmt_moltrans",
      "display_name": "ONMT MolTrans",
      "type": "seq2seq_transformer",
      "status": "active"
    },
    {
      "model_name": "retrochimera",
      "display_name": "RetroChimera",
      "type": "hybrid_ensemble",
      "status": "active"
    }
  ]
}
```

---

## ✅ 5. Pre-flight SMILES Validation (`POST /api/v1/retro/validate`)

Validates, cleans, and canonicalizes input SMILES before submitting heavy searches:

### Request Command:
```bash
PUBLIC_IP="8.232.102.201"
HOST_HEADER="askcos2-core-app-324499629735.us-central1.run.app"

curl -s -X POST "http://${PUBLIC_IP}/api/v1/retro/validate" \
  -H "Host: ${HOST_HEADER}" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "smiles": "CC(=O)OCC"
  }' | jq .
```

### Response Payload:
```json
{
  "status_code": 200,
  "valid": true,
  "input_smiles": "CC(=O)OCC",
  "canonical_smiles": "CCOC(C)=O",
  "message": "SMILES validated and canonicalized successfully"
}
```

