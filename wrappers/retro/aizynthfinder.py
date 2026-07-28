import asyncio
import importlib
import json
import os
import subprocess
import tempfile
from pydantic import Field, RootModel, field_validator
from schemas.base import LowerCamelAliasModel
from wrappers import register_wrapper
from wrappers.base import BaseResponse, BaseWrapper


class RetroAiZynthFinderInput(LowerCamelAliasModel):
    model_name: str = Field(
        default="aizynthfinder-service-model",
        description="model name for Vertex AI service deployment"
    )
    smiles: list[str] = Field(
        description="list of target SMILES",
        example=["CC(=O)Oc1ccccc1C(=O)O"]
    )
    n_best: int = Field(
        default=5,
        description="number of top precursor predictions to retrieve per target"
    )

    @field_validator("model_name")
    @classmethod
    def check_model_name(cls, v: str) -> str:
        default_path = "configs.module_config_full"
        config_path = os.environ.get(
            "MODULE_CONFIG_PATH", default_path
        ).replace("/", ".").rstrip(".py")
        module_config = importlib.import_module(config_path).module_config

        available_model_names = module_config.get(
            "retro_aizynthfinder", {}
        ).get("deployment", {}).get("available_model_names", ["aizynthfinder-service-model"])
        if v not in available_model_names:
            raise ValueError(f"Unsupported model_name {v} for retro_aizynthfinder")

        return v


class RetroAiZynthFinderResult(LowerCamelAliasModel):
    products: list[str] = Field(
        description="list of predicted reactant SMILES strings"
    )
    scores: list[float] = Field(
        description="list of model prediction confidence scores"
    )


class RetroAiZynthFinderOutput(RootModel):
    root: list[RetroAiZynthFinderResult]


class RetroAiZynthFinderResponse(BaseResponse):
    result: list[RetroAiZynthFinderResult]


@register_wrapper(
    name="retro_aizynthfinder",
    input_class=RetroAiZynthFinderInput,
    output_class=RetroAiZynthFinderOutput,
    response_class=RetroAiZynthFinderResponse
)
class RetroAiZynthFinderWrapper(BaseWrapper):
    """
    Wrapper for AiZynthFinder ONNX retrosynthesis template expansion running
    predictions natively or securely via Google Cloud mTLS/CBA transport against Vertex AI.
    """
    prefixes = ["retro/aizynthfinder", "aizynthfinder"]

    def __init__(self, config: dict):
        super().__init__(config=config)
        self.prediction_url = self.config["deployment"]["default_prediction_url"]

    def is_ready(self) -> bool:
        if self.config["deployment"].get("use_vertex_ai", False):
            return bool(self.config["deployment"].get("vertex_endpoint_id"))
        return super().is_ready()

    def call_raw(self, input: RetroAiZynthFinderInput) -> RetroAiZynthFinderOutput:
        from configs.gcp_config import GCPConfig
        use_vertex = GCPConfig.USE_VERTEX_AI or self.config["deployment"].get("use_vertex_ai", False)

        if use_vertex:
            endpoint_id = GCPConfig.AIZYNTHFINDER_ENDPOINT_ID or self.config["deployment"]["vertex_endpoint_id"]
            region = GCPConfig.VERTEX_LOCATION
            project = GCPConfig.VERTEX_PROJECT

            payload = {
                "instances": [
                    {"smiles": s, "n_best": input.n_best} for s in input.smiles
                ]
            }

            with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as f:
                json.dump(payload, f)
                tmp_path = f.name

            try:
                response_data = None
                try:
                    import google.auth
                    import google.auth.transport.requests
                    import requests

                    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
                    auth_req = google.auth.transport.requests.Request()
                    credentials.refresh(auth_req)

                    url = f"https://{region}-prediction-aiplatform.googleapis.com/v1/projects/{project}/locations/{region}/endpoints/{endpoint_id}:predict"
                    headers = {
                        "Authorization": f"Bearer {credentials.token}",
                        "Content-Type": "application/json"
                    }
                    resp = requests.post(url, json=payload, headers=headers, timeout=360)
                    resp.raise_for_status()
                    response_data = resp.json()
                except Exception as auth_err:
                    try:
                        cmd = [
                            "gcloud", "ai", "endpoints", "predict", str(endpoint_id),
                            f"--region={region}",
                            f"--project={project}",
                            f"--json-request={tmp_path}",
                            "--format=json"
                        ]
                        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                        response_data = json.loads(result.stdout)
                    except Exception as sub_err:
                        print(f"Error calling AiZynthFinder Vertex AI endpoint: {auth_err} / {sub_err}")
                        response_data = {}

                raw_predictions = response_data
                if isinstance(response_data, dict):
                    raw_predictions = response_data.get("predictions", [])
                elif isinstance(response_data, list) and len(response_data) > 0 and isinstance(response_data[0], dict) and "predictions" in response_data[0]:
                    raw_predictions = response_data[0]["predictions"]
                elif isinstance(response_data, list):
                    raw_predictions = response_data
                else:
                    raw_predictions = []

                results = []
                for pred in raw_predictions:
                    item_results = pred.get("results", []) if isinstance(pred, dict) else []
                    for item in item_results:
                        reactants = item.get("reactants", [])
                        scores = [float(s) for s in item.get("scores", [])]
                        results.append(RetroAiZynthFinderResult(products=reactants, scores=scores))

                return RetroAiZynthFinderOutput(results)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        else:
            response = self.session_sync.post(
                f"{self.prediction_url}/predict",
                json={"instances": [{"smiles": s, "n_best": input.n_best} for s in input.smiles]},
                timeout=self.config["deployment"]["timeout"]
            )
            raw_data = response.json()
            predictions = raw_data.get("predictions", [])
            results = []
            for pred in predictions:
                item_results = pred.get("results", []) if isinstance(pred, dict) else []
                for item in item_results:
                    reactants = item.get("reactants", [])
                    scores = [float(s) for s in item.get("scores", [])]
                    results.append(RetroAiZynthFinderResult(products=reactants, scores=scores))
            return RetroAiZynthFinderOutput(results)

    def call_sync(self, input: RetroAiZynthFinderInput) -> RetroAiZynthFinderResponse:
        output = self.call_raw(input=input)
        response = self.convert_output_to_response(output)
        return response

    async def call_async(self, input: RetroAiZynthFinderInput, priority: int = 0) -> str:
        import uuid
        from askcos2_celery.tasks import retro_task
        task_id = str(uuid.uuid4())
        await asyncio.to_thread(
            retro_task.apply_async,
            args=(self.name, input.model_dump()),
            task_id=task_id,
            priority=priority
        )
        return task_id

    async def retrieve(self, task_id: str) -> RetroAiZynthFinderResponse | None:
        return await super().retrieve(task_id=task_id)

    @staticmethod
    def convert_output_to_response(output: RetroAiZynthFinderOutput) -> RetroAiZynthFinderResponse:
        response = {
            "status_code": 200,
            "message": "",
            "result": output.root
        }
        return RetroAiZynthFinderResponse(**response)


def get_wrapper_registry():
    from wrappers.registry import get_wrapper_registry as _get_wrapper_registry
    return _get_wrapper_registry()
