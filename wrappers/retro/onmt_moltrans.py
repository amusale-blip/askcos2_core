import asyncio
import importlib
import json
import os
import subprocess
import tempfile
from pydantic import BaseModel, Field, RootModel, field_validator
from schemas.base import LowerCamelAliasModel
from wrappers import register_wrapper
from wrappers.base import BaseResponse, BaseWrapper


class RetroOnmtMolTransInput(LowerCamelAliasModel):
    model_name: str = Field(
        default="onmt-moltrans-service-model",
        description="model name for Vertex AI service deployment"
    )
    smiles: list[str] = Field(
        description="list of target SMILES",
        example=["CS(=N)(=O)Cc1cccc(Br)c1", "CN(C)CCOC(c1ccccc1)c1ccccc1"]
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

        available_model_names = module_config[
            "retro_onmt_moltrans"]["deployment"]["available_model_names"]
        if v not in available_model_names:
            raise ValueError(f"Unsupported model_name {v} for retro_onmt_moltrans")

        return v


class RetroOnmtMolTransResult(LowerCamelAliasModel):
    products: list[str] = Field(
        description="list of predicted reactant SMILES strings"
    )
    scores: list[float] = Field(
        description="list of model prediction confidence scores"
    )


class RetroOnmtMolTransOutput(RootModel):
    root: list[RetroOnmtMolTransResult]


class RetroOnmtMolTransResponse(BaseResponse):
    result: list[RetroOnmtMolTransResult]


@register_wrapper(
    name="retro_onmt_moltrans",
    input_class=RetroOnmtMolTransInput,
    output_class=RetroOnmtMolTransOutput,
    response_class=RetroOnmtMolTransResponse
)
class RetroOnmtMolTransWrapper(BaseWrapper):
    """
    Wrapper for Sequence-to-Sequence Molecular Transformer (`onmt_MolTrans`)
    running predictions natively or securely via Google Cloud mTLS/CBA transport against Vertex AI.
    """
    prefixes = ["retro/onmt_moltrans"]

    def __init__(self, config: dict):
        super().__init__(config=config)
        self.prediction_url = self.config["deployment"]["default_prediction_url"]

    def is_ready(self) -> bool:
        if self.config["deployment"].get("use_vertex_ai", False):
            return bool(self.config["deployment"].get("vertex_endpoint_id"))
        return super().is_ready()

    def call_raw(self, input: RetroOnmtMolTransInput) -> RetroOnmtMolTransOutput:
        use_vertex = self.config["deployment"].get("use_vertex_ai", False)

        if use_vertex:
            endpoint_id = self.config["deployment"]["vertex_endpoint_id"]
            region = self.config["deployment"].get("vertex_location", "us-central1")
            project = self.config["deployment"].get("vertex_project", "x-woodward")

            payload = {
                "instances": [
                    {"smiles": s, "n_best": input.n_best} for s in input.smiles
                ]
            }

            with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as f:
                json.dump(payload, f)
                tmp_path = f.name

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
                    reactants = [res.get("reactants", "") for res in item_results]
                    scores = [float(res.get("score", 0.0)) for res in item_results]
                    results.append(RetroOnmtMolTransResult(products=reactants, scores=scores))

                return RetroOnmtMolTransOutput(results)
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
                item_results = pred.get("results", [])
                reactants = [res.get("reactants", "") for res in item_results]
                scores = [float(res.get("score", 0.0)) for res in item_results]
                results.append(RetroOnmtMolTransResult(products=reactants, scores=scores))
            return RetroOnmtMolTransOutput(results)

    def call_sync(self, input: RetroOnmtMolTransInput) -> RetroOnmtMolTransResponse:
        """
        Endpoint for synchronous call to one-step retrosynthesis based on
        Sequence-to-Sequence Molecular Transformer.
        """
        output = self.call_raw(input=input)
        response = self.convert_output_to_response(output)
        return response

    async def call_async(self, input: RetroOnmtMolTransInput, priority: int = 0) -> str:
        """
        Endpoint for asynchronous call to one-step retrosynthesis based on
        Sequence-to-Sequence Molecular Transformer without blocking the async event loop.
        """
        from askcos2_celery.tasks import retro_task
        async_result = await asyncio.to_thread(
            retro_task.apply_async,
            args=(self.name, input.model_dump()),
            priority=priority
        )
        task_id = async_result.id
        return task_id

    async def retrieve(self, task_id: str) -> RetroOnmtMolTransResponse | None:
        return await super().retrieve(task_id=task_id)

    @staticmethod
    def convert_output_to_response(output: RetroOnmtMolTransOutput) -> RetroOnmtMolTransResponse:
        response = {
            "status_code": 200,
            "message": "",
            "result": output.root
        }
        return RetroOnmtMolTransResponse(**response)


def get_wrapper_registry():
    from wrappers.registry import get_wrapper_registry as _get_wrapper_registry
    return _get_wrapper_registry()
