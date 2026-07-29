from pydantic import BaseModel, Field
from schemas.base import LowerCamelAliasModel
from typing import Any, Literal
from utils.registry import get_util_registry
from wrappers import register_wrapper
from wrappers.base import BaseResponse, BaseWrapper
from wrappers.retro.aizynthfinder import RetroAiZynthFinderInput, RetroAiZynthFinderResponse
from wrappers.retro.onmt_moltrans import RetroOnmtMolTransInput, RetroOnmtMolTransResponse
from wrappers.retro.retrochimera import RetroRetroChimeraInput, RetroRetroChimeraResponse
from wrappers.registry import get_wrapper_registry


class AttributeFilter(BaseModel):
    name: str
    logic: Literal[">", ">=", "<", "<=", "=="]
    value: int | float


class RetroInput(LowerCamelAliasModel):
    backend: Literal[
        "aizynthfinder",
        "onmt_moltrans",
        "retrochimera"
    ] = Field(
        default="onmt_moltrans",
        description="backend for one-step retrosynthesis"
    )
    model_name: str = Field(
        default="onmt-moltrans-service-model",
        description="backend model name for one-step retrosynthesis"
    )
    smiles: list[str] = Field(
        description="list of target SMILES",
        example=["CS(=N)(=O)Cc1cccc(Br)c1", "CN(C)CCOC(c1ccccc1)c1ccccc1"]
    )
    n_best: int = Field(
        default=5,
        description="number of top precursor predictions to retrieve per target"
    )


class RetroOutput(BaseModel):
    placeholder: str


class RetroResult(BaseModel):
    outcome: str
    model_score: float
    normalized_model_score: float


class RetroResponse(BaseResponse):
    result: list[list[RetroResult]]


@register_wrapper(
    name="retro_controller",
    input_class=RetroInput,
    output_class=RetroOutput,
    response_class=RetroResponse
)
class RetroController(BaseWrapper):
    """Retro Controller for AiZynthFinder, ONMT MolTrans, and RetroChimera"""
    prefixes = ["retro/controller", "retro"]
    backend_wrapper_names = {
        "aizynthfinder": "retro_aizynthfinder",
        "onmt_moltrans": "retro_onmt_moltrans",
        "retrochimera": "retro_retrochimera"
    }

    def __init__(self):
        pass

    def call_sync(self, input: RetroInput) -> RetroResponse:
        """
        Endpoint for synchronous call to the retro controller,
        which dispatches the call to target one-step retro backend service
        """
        cache_controller = get_util_registry().get_util(module="cache_controller")
        try:
            response = cache_controller.get(module_name=self.name, input=input)
            if isinstance(response, dict):
                response = RetroResponse(**response)
        except KeyError:
            module = self.backend_wrapper_names[input.backend]
            wrapper = get_wrapper_registry().get_wrapper(module=module)

            wrapper_input = self.convert_input(input=input, backend=input.backend)
            wrapper_response = wrapper.call_sync(wrapper_input)
            response = self.convert_response(wrapper_response=wrapper_response, backend=input.backend)

            if response.status_code == 200:
                cache_controller.add(
                    module_name=self.name,
                    input=input,
                    response=response
                )

        return response

    async def call_async(self, input: RetroInput, priority: int = 0) -> str:
        from askcos2_celery.tasks import retro_task
        async_result = retro_task.apply_async(
            args=(self.name, input.model_dump()), priority=priority)
        task_id = async_result.id
        return task_id

    async def retrieve(self, task_id: str) -> RetroResponse | None:
        return await super().retrieve(task_id=task_id)

    @staticmethod
    def convert_input(
        input: RetroInput, backend: str
    ) -> (
        RetroAiZynthFinderInput |
        RetroOnmtMolTransInput |
        RetroRetroChimeraInput
    ):
        if backend == "aizynthfinder":
            return RetroAiZynthFinderInput(
                model_name=input.model_name,
                smiles=input.smiles,
                n_best=input.n_best
            )
        elif backend == "onmt_moltrans":
            return RetroOnmtMolTransInput(
                model_name=input.model_name,
                smiles=input.smiles,
                n_best=input.n_best
            )
        elif backend == "retrochimera":
            return RetroRetroChimeraInput(
                model_name=input.model_name,
                smiles=input.smiles,
                n_best=input.n_best
            )
        else:
            raise ValueError(f"Unsupported retro backend: {backend}!")

    @staticmethod
    def convert_response(
        wrapper_response:
            RetroAiZynthFinderResponse |
            RetroOnmtMolTransResponse |
            RetroRetroChimeraResponse,
        backend: str
    ) -> RetroResponse:
        status_code = wrapper_response.status_code
        message = wrapper_response.message
        result = []
        for result_per_smi in wrapper_response.result:
            if not result_per_smi.scores:
                result.append([])
                continue
            total_score = sum(result_per_smi.scores) or 1.0
            normalized_scores = [score / total_score for score in result_per_smi.scores]
            result.append(
                [{
                    "outcome": outcome,
                    "model_score": score,
                    "normalized_model_score": float(normalized_score)
                } for outcome, score, normalized_score in zip(
                    result_per_smi.products,
                    result_per_smi.scores,
                    normalized_scores
                )]
            )

        return RetroResponse(status_code=status_code, message=message, result=result)

