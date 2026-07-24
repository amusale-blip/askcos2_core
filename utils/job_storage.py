import json
import os
from typing import Any, Optional

# Thread-safe in-memory cache for fast local retrieval
_MEMORY_JOBS: dict[str, dict[str, Any]] = {}


class JobStorage:
    """
    Serverless Job and Pathway Storage Manager.
    Uses Google Cloud Firestore as the primary persistent task database
    (replacing Redis) with in-memory caching and optional Cloud Storage backup.
    """

    @staticmethod
    def save_job(
        job_id: str,
        status: str = "PENDING",
        message: str = "",
        target_smiles: Optional[str] = None,
        results: Optional[list[dict[str, Any]]] = None
    ) -> dict[str, Any]:
        """Save or update job state and pathway results in Firestore & Memory."""
        is_complete = status in ("SUCCESS", "COMPLETED", "FAILURE")
        is_failed = status == "FAILURE"

        job_data = {
            "status_code": 500 if is_failed else 200,
            "job_id": job_id,
            "complete": is_complete,
            "failed": is_failed,
            "status": status,
            "message": message,
            "result": {
                "target_smiles": target_smiles,
                "expansions": results or []
            } if is_complete and not is_failed else None
        }

        # 1. Update fast in-memory cache
        _MEMORY_JOBS[job_id] = job_data

        # 2. Persist to GCP Datastore/Firestore database (Replacing Redis)
        project_id = os.environ.get("VERTEX_PROJECT", "x-woodward")
        try:
            from google.cloud import datastore
            ds = datastore.Client(project=project_id)
            key = ds.key("askcos2_jobs", job_id)
            entity = datastore.Entity(key=key, exclude_from_indexes=("result",))
            entity.update(job_data)
            ds.put(entity)
        except Exception as e1:
            try:
                from google.cloud import firestore
                db = firestore.Client(project=project_id)
                doc_ref = db.collection("askcos2_jobs").document(job_id)
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
                blob = bucket.blob(f"jobs/{job_id}.json")
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

        # 2. Check GCP Datastore/Firestore database (Replacing Redis)
        project_id = os.environ.get("VERTEX_PROJECT", "x-woodward")
        try:
            from google.cloud import datastore
            ds = datastore.Client(project=project_id)
            key = ds.key("askcos2_jobs", job_id)
            entity = ds.get(key)
            if entity:
                data = dict(entity)
                _MEMORY_JOBS[job_id] = data
                return data
        except Exception as e1:
            try:
                from google.cloud import firestore
                db = firestore.Client(project=project_id)
                doc_ref = db.collection("askcos2_jobs").document(job_id)
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
