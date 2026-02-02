from pydantic import RootModel
from schemas.base import LowerCamelAliasModel
from wrappers import register_wrapper
from wrappers.base import BaseResponse, BaseWrapper


class ContextRecommenderFPInput(LowerCamelAliasModel):
    smiles: str
    reagents: list[str] | None = None
    n_conditions: int = 10


class ContextRecommenderFPOutput(RootModel[list[dict]]):
    pass


class ContextRecommenderFPResponse(BaseResponse):
    result: list[dict]


# FP model condition
@register_wrapper(
    name="context_recommender_pr_fp",
    input_class=ContextRecommenderFPInput,
    output_class=ContextRecommenderFPOutput,
    response_class=ContextRecommenderFPResponse
)
class ContextRecommenderWrapper(BaseWrapper):
    """Wrapper class for Context Recommender Predict FP"""
    prefixes = ["context_recommender/v2/predict/FP"]

    def call_raw(self, input: ContextRecommenderFPInput) -> ContextRecommenderFPOutput:
        response = self.session_sync.post(
            f"{self.prediction_url}/api/v2/predict/FP",
            json=input.model_dump(),
            timeout=self.config["deployment"]["timeout"]
        )
        output = response.json()
        output = ContextRecommenderFPOutput(output)

        return output

    def call_sync(self, input: ContextRecommenderFPInput
                  ) -> ContextRecommenderFPResponse:
        output = self.call_raw(input=input)
        response = self.convert_output_to_response(output)

        return response

    async def call_async(self, input: ContextRecommenderFPInput, priority: int = 0
                         ) -> str:
        from askcos2_celery.tasks import context_recommender_task
        async_result = context_recommender_task.apply_async(
            args=(self.name, input.model_dump()), priority=priority)
        task_id = async_result.id

        return task_id

    async def retrieve(self, task_id: str) -> ContextRecommenderFPResponse | None:
        return await super().retrieve(task_id=task_id)

    @staticmethod
    def convert_output_to_response(output: ContextRecommenderFPOutput
                                   ) -> ContextRecommenderFPResponse:
        response = {
            "status_code": 200,
            "message": "",
            "result": output.root
        }
        response = ContextRecommenderFPResponse(**response)

        return response
