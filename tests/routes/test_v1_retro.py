import json
import os
import requests
import time
import unittest

V2_HOST = os.environ.get("V2_HOST", "http://0.0.0.0")
V2_PORT = os.environ.get("V2_PORT", "9100")


class TestV1RetroEndpoints(unittest.TestCase):
    """Test suite for Section 3 v1 REST Retrosynthesis Endpoints"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = requests.Session()
        cls.base_url = f"{V2_HOST}:{V2_PORT}/api/v1/retro"

    def test_expand_one(self):
        payload = {
            "smiles": "CC(C)(C)OC(=O)N1CCCC(OCCCCO)CC1",
            "models": ["onmt_moltrans"],
            "settings": {
                "max_results": 5,
                "min_plausibility": 0.01
            }
        }
        print(f"\n[Test 3.1] Sending POST request to {self.base_url}/expand-one...")
        t0 = time.time()
        resp = self.session.post(f"{self.base_url}/expand-one", json=payload)
        dt = time.time() - t0
        print(f"✅ Received response in {dt:.2f}s! Status: {resp.status_code}")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status_code"], 200)
        self.assertIsInstance(data["results"], list)
        self.assertGreater(len(data["results"]), 0)
        self.assertEqual(data["results"][0]["model"], "onmt_moltrans")
        self.assertIsInstance(data["results"][0]["reactants"], list)
        self.assertIsInstance(data["results"][0]["scores"], list)

        print("\nSingle-step Expansion Results:")
        for r, s in zip(data["results"][0]["reactants"], data["results"][0]["scores"]):
            print(f"  -> Precursor: {r} (Score: {s:.4f})")

    def test_plan_and_retrieve(self):
        payload = {
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
        }
        print(f"\n[Test 3.2] Sending POST request to {self.base_url}/plan...")
        resp = self.session.post(f"{self.base_url}/plan", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        job_id = data.get("job_id")
        self.assertTrue(bool(job_id))
        print(f"✅ Received job_id: {job_id}")

        print(f"\n[Test 3.3] Polling GET request to {self.base_url}/plan/{job_id}...")
        resp_poll = self.session.get(f"{self.base_url}/plan/{job_id}")
        self.assertEqual(resp_poll.status_code, 200)
        poll_data = resp_poll.json()
        print(f"✅ Received poll state: status={poll_data.get('status')}")


if __name__ == "__main__":
    unittest.main()
