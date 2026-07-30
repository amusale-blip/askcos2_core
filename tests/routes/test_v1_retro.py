from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def test_validate_endpoint_valid():
    response = client.post(
        "/api/v1/retro/validate",
        json={"smiles": "CC(=O)Oc1ccccc1C(=O)O"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["canonical_smiles"] == "CC(=O)Oc1ccccc1C(=O)O"


def test_validate_endpoint_invalid():
    response = client.post(
        "/api/v1/retro/validate",
        json={"smiles": "INVALID_SMILES_STRING_123"}
    )
    assert response.status_code == 422
    data = response.json()
    assert data["valid"] is False


def test_models_endpoint():
    response = client.get("/api/v1/retro/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    model_names = [m["model_name"] for m in data["models"]]
    assert len(model_names) > 0


def test_expand_one_endpoint():
    response = client.post(
        "/api/v1/retro/expand-one",
        json={
            "smiles": "CC(=O)Oc1ccccc1C(=O)O",
            "models": ["aizynthfinder", "onmt_moltrans", "retrochimera"],
            "settings": {
                "max_results": 10,
                "min_plausibility": 0.0
            }
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status_code"] == 200
    assert data["target_smiles"] == "CC(=O)Oc1ccccc1C(=O)O"
    assert "results" in data


def test_plan_and_status_endpoints():
    response = client.post(
        "/api/v1/retro/plan",
        json={
            "target_smiles": "CC(=O)Oc1ccccc1C(=O)O",
            "models": ["aizynthfinder", "onmt_moltrans", "retrochimera"],
            "search_strategy": {
                "max_time_seconds": 60,
                "max_iterations": 100,
                "max_depth": 5
            },
            "termination_criteria": {
                "buyables_db": "internal_inventory_v1"
            }
        }
    )
    assert response.status_code == 200
    plan_data = response.json()
    assert plan_data["status_code"] == 200
    assert "job_id" in plan_data
    job_id = plan_data["job_id"]

    # Poll status
    status_resp = client.get(f"/api/v1/retro/plan/{job_id}")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["job_id"] == job_id
