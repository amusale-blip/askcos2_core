import json
import os
import requests
import time
import unittest

V2_HOST = os.environ.get("V2_HOST", "http://0.0.0.0")
V2_PORT = os.environ.get("V2_PORT", "9100")


class RetroOnmtMolTransTest(unittest.TestCase):
    """Test suite for Retro Sequence-to-Sequence Molecular Transformer wrapper"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = requests.Session()
        cls.base_url = f"{V2_HOST}:{V2_PORT}/api"
        cls.module_url = f"{V2_HOST}:{V2_PORT}/api/retro/onmt-moltrans"

    def get_async_result(self, task_id: str, timeout: int = 60):
        for _ in range(timeout):
            response = self.session.get(
                f"{self.base_url}/celery/task/get?task_id={task_id}"
            ).json()
            if response.get("complete"):
                return response
            elif response.get("failed"):
                print("Celery task failed!")
                return response
            time.sleep(1)
        print("Celery task timeout!")
        return response

    def test_1(self):
        case_file = "tests/wrappers/retro/retro_onmt_moltrans_test_case_1.json"
        with open(case_file, "r") as f:
            data = json.load(f)

        print(f"\nSending synchronous query to {self.module_url}/call-sync...")
        t0 = time.time()
        response_sync = self.session.post(
            f"{self.module_url}/call-sync", json=data
        ).json()
        dt = time.time() - t0
        print(f"✅ Received successful prediction response in {dt:.2f}s!")

        if response_sync.get("status_code") == 200:
            results = response_sync.get("result", [])
            if results and isinstance(results[0], dict):
                reactants = results[0].get("products", results[0].get("reactants", []))
                scores = results[0].get("scores", [])
                print("\nPredicted reactants from Vertex AI:")
                for r, s in zip(reactants, scores):
                    print(f"  -> {r} (Score: {s:.4f})")

        self.assertEqual(response_sync["status_code"], 200)
        self.assertIsInstance(response_sync["result"], list)
        self.assertIsInstance(response_sync["result"][0], dict)
        scores = response_sync["result"][0]["scores"]
        self.assertIsInstance(scores, list)
        self.assertGreater(len(scores), 0)
        self.assertIsInstance(scores[0], float)


if __name__ == "__main__":
    unittest.main()
