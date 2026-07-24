import json
import os
from typing import Any, Optional

# Thread-safe in-memory cache for fast local retrieval
_MEMORY_JOBS: dict[str, dict[str, Any]] = {}


from datetime import datetime, timezone


class JobStorage:
    """
    Serverless Job and Pathway Storage Manager.
    Uses Google Cloud Datastore/Firestore as the primary persistent task database
    (replacing Redis) with Data Studio / BigQuery optimized analytics fields.
    """

    @staticmethod
    def save_job(
        job_id: str,
        status: str = "PENDING",
        message: str = "",
        target_smiles: Optional[str] = None,
        results: Optional[list[dict[str, Any]]] = None
    ) -> dict[str, Any]:
        """Save or update job state and pathway results with Data Studio analytics indexing."""
        is_complete = status in ("SUCCESS", "COMPLETED", "FAILURE")
        is_failed = status == "FAILURE"

        # Compute Data Studio & Datastore friendly metrics
        max_score = 0.0
        top_candidate = None
        if results:
            for item in results:
                scores = item.get("scores", [])
                reactants = item.get("reactants", [])
                if scores and max(scores) > max_score:
                    max_score = float(max(scores))
                    if reactants:
                        top_candidate = reactants[0]

        now_iso = datetime.now(timezone.utc).isoformat()
        existing_created = _MEMORY_JOBS.get(job_id, {}).get("created_at", now_iso)

        job_data = {
            "status_code": 500 if is_failed else 200,
            "job_id": job_id,
            "complete": is_complete,
            "failed": is_failed,
            "status": status,
            "message": message,
            "target_smiles": target_smiles,
            "created_at": existing_created,
            "updated_at": now_iso,
            "max_confidence_score": round(max_score, 4) if is_complete else None,
            "top_precursor_candidate": top_candidate if is_complete else None,
            "result": {
                "target_smiles": target_smiles,
                "expansions": results or []
            } if is_complete and not is_failed else None
        }

        # 1. Update fast in-memory cache
        _MEMORY_JOBS[job_id] = job_data

        # 2. Persist to GCP Datastore/Firestore database in dedicated namespace and collection
        project_id = os.environ.get("VERTEX_PROJECT", "x-woodward")
        namespace = os.environ.get("DATASTORE_NAMESPACE", "askcos2_core")
        kind_name = "retrosynthesis_jobs"

        try:
            from google.cloud import datastore
            ds = datastore.Client(project=project_id, namespace=namespace)
            key = ds.key(kind_name, job_id)
            entity = datastore.Entity(key=key, exclude_from_indexes=("result",))
            entity.update(job_data)
            ds.put(entity)
        except Exception as e1:
            try:
                from google.cloud import firestore
                db = firestore.Client(project=project_id)
                doc_ref = db.collection(namespace).document("jobs").collection(kind_name).document(job_id)
                doc_ref.set(job_data, merge=True)
            except Exception as e2:
                print(f"Warning: Datastore/Firestore job persistence deferred: {e1} / {e2}")

        # 3. Optional backup to GCP Cloud Storage bucket if configured
        bucket_name = os.environ.get("GCP_JOB_BUCKET")
        if bucket_name:
            try:
                from google.cloud import storage
                client = storage.Client()
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(f"{namespace}/jobs/{job_id}.json")
                blob.upload_from_string(json.dumps(job_data), content_type="application/json")
            except Exception as e:
                print(f"Warning: Cloud Storage backup deferred: {e}")

        return job_data

    @staticmethod
    def get_job(job_id: str) -> dict[str, Any]:
        """Retrieve job status and pathway results from Datastore/Firestore or Memory."""
        # 1. Check in-memory cache
        if job_id in _MEMORY_JOBS:
            return _MEMORY_JOBS[job_id]

        # 2. Check GCP Datastore/Firestore database in dedicated namespace and collection
        project_id = os.environ.get("VERTEX_PROJECT", "x-woodward")
        namespace = os.environ.get("DATASTORE_NAMESPACE", "askcos2_core")
        kind_name = "retrosynthesis_jobs"

        try:
            from google.cloud import datastore
            ds = datastore.Client(project=project_id, namespace=namespace)
            key = ds.key(kind_name, job_id)
            entity = ds.get(key)
            if entity:
                data = dict(entity)
                _MEMORY_JOBS[job_id] = data
                return data
        except Exception as e1:
            try:
                from google.cloud import firestore
                db = firestore.Client(project=project_id)
                doc_ref = db.collection(namespace).document("jobs").collection(kind_name).document(job_id)
                doc = doc_ref.get()
                if doc.exists:
                    data = doc.to_dict()
                    _MEMORY_JOBS[job_id] = data
                    return data
            except Exception as e2:
                print(f"Warning: Datastore/Firestore job retrieval deferred: {e1} / {e2}")

        # 3. Default fallback response for unknown or pending jobs
        return {
            "status_code": 200,
            "job_id": job_id,
            "complete": False,
            "failed": False,
            "status": "PENDING",
            "message": "Job is queued or processing"
        }
