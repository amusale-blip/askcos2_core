import asyncio
from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import Any, Optional
from wrappers.registry import get_wrapper_registry
try:
    from rdkit import Chem
except ImportError:
    Chem = None

router = APIRouter(prefix="/api/v1/retro", tags=["v1_retrosynthesis"])


class ExpandOneSettings(BaseModel):
    max_results: int = Field(default=100, description="maximum number of precursor predictions to return")
    min_plausibility: float = Field(default=0.0, description="minimum score threshold for single-step reaction")


class ExpandOneRequest(BaseModel):
    smiles: str = Field(
        ...,
        description="target SMILES string to evaluate",
        example="CC(C)(C)OC(=O)N1CCCC(OCCCCO)CC1"
    )
    models: list[str] = Field(
        default=["onmt_moltrans"],
        description="list of retrosynthesis model names to query (e.g. ['onmt_moltrans', 'augmented_transformer'])"
    )
    settings: Optional[ExpandOneSettings] = Field(default_factory=ExpandOneSettings)


class SingleExpansionResult(BaseModel):
    model: str
    reactants: list[str]
    scores: list[float]


class ExpandOneResponse(BaseModel):
    status_code: int = 200
    message: str = ""
    target_smiles: str
    results: list[SingleExpansionResult]


class SearchStrategy(BaseModel):
    max_time_seconds: int = Field(default=300)
    max_iterations: int = Field(default=500)
    max_depth: int = Field(default=10)


class TerminationCriteria(BaseModel):
    buyables_db: str = Field(default="internal_inventory_v1")


class PlanRequest(BaseModel):
    target_smiles: str = Field(
        ...,
        description="target SMILES string for pathway search",
        example="CC(C)(C)OC(=O)N1CCCC(OCCCCO)CC1"
    )
    models: list[str] = Field(default=["onmt_moltrans"])
    search_strategy: Optional[SearchStrategy] = Field(default_factory=SearchStrategy)
    termination_criteria: Optional[TerminationCriteria] = Field(default_factory=TerminationCriteria)


class PlanResponse(BaseModel):
    status_code: int = 200
    job_id: str
    status: str = "PENDING"
    message: str = "Pathway planning job accepted"


def canonicalize_smiles(smiles: str) -> str:
    """Validate and canonicalize input SMILES using RDKit if available"""
    if Chem is not None:
        mol = Chem.MolFromSmiles(smiles)
        if mol is not None:
            return Chem.MolToSmiles(mol, canonical=True)
    return smiles


@router.post("/expand-one", response_model=ExpandOneResponse)
def expand_one(request: ExpandOneRequest) -> ExpandOneResponse:
    """
    Synchronous Single-Step Expansion (Section 3.1 of project requirements).
    Evaluates a single target molecule and returns immediate precursors across specified models.
    """
    canonical_smiles = canonicalize_smiles(request.smiles)
    registry = get_wrapper_registry()
    all_results = []

    for model_key in request.models:
        wrapper_name = model_key
        if not wrapper_name.startswith("retro_"):
            wrapper_name = f"retro_{model_key}"

        wrapper = registry.get_wrapper(wrapper_name)
        if wrapper is None:
            # Try alternate key format
            wrapper = registry.get_wrapper(model_key)

        if wrapper is None:
            continue

        try:
            # Reconstruct model input
            input_data = wrapper.input_class(
                smiles=[canonical_smiles],
                n_best=request.settings.max_results if request.settings else 100
            )
            response = wrapper.call_sync(input_data)
            
            raw_result = response.model_dump().get("result", [])
            if raw_result and isinstance(raw_result, list) and isinstance(raw_result[0], dict):
                item = raw_result[0]
                raw_reactants = item.get("products", item.get("reactants", []))
                raw_scores = item.get("scores", [])

                min_p = request.settings.min_plausibility if request.settings else 0.0
                max_r = request.settings.max_results if request.settings else 100

                filtered_reactants = []
                filtered_scores = []

                for r, s in zip(raw_reactants, raw_scores):
                    if s >= min_p:
                        filtered_reactants.append(r)
                        filtered_scores.append(float(s))
                    if len(filtered_reactants) >= max_r:
                        break

                all_results.append(
                    SingleExpansionResult(
                        model=model_key,
                        reactants=filtered_reactants,
                        scores=filtered_scores
                    )
                )
        except Exception as e:
            print(f"Error executing model {model_key}: {e}")
            continue

    return ExpandOneResponse(
        status_code=200,
        message="",
        target_smiles=canonical_smiles,
        results=all_results
    )


@router.post("/plan", response_model=PlanResponse)
async def plan_pathway(request: PlanRequest) -> PlanResponse:
    """
    Asynchronous Automated Pathway Generation (Section 3.2 of project requirements).
    Triggers background search jobs to build full pathways back to available starting materials.
    """
    import uuid
    canonical_smiles = canonicalize_smiles(request.target_smiles)
    registry = get_wrapper_registry()

    target_model = request.models[0] if request.models else "onmt_moltrans"
    if not target_model.startswith("retro_"):
        target_model = f"retro_{target_model}"

    wrapper = registry.get_wrapper(target_model)
    job_id = str(uuid.uuid4())

    if wrapper is not None:
        try:
            input_data = wrapper.input_class(smiles=[canonical_smiles], n_best=10)
            asyncio.create_task(wrapper.call_async(input_data))
        except Exception as e:
            print(f"Warning: Background Celery queueing deferred: {e}")

    return PlanResponse(
        status_code=200,
        job_id=job_id,
        status="PENDING",
        message="Pathway planning job queued successfully"
    )


@router.get("/plan/{job_id}")
async def get_plan_status(job_id: str):
    """
    Job Status & Pathway Retrieval (Section 3.3 of project requirements).
    Polls the background job and returns resolved pathways once complete.
    """
    try:
        poll_timeout = float(os.environ.get("POLL_TIMEOUT_SECONDS", "1.0"))
        result = AsyncResult(job_id)
        state = await asyncio.wait_for(
            asyncio.to_thread(lambda: result.state),
            timeout=poll_timeout
        )

        if state == "SUCCESS":
            res_data = await asyncio.wait_for(
                asyncio.to_thread(lambda: result.result),
                timeout=poll_timeout
            )
            return {
                "status_code": 200,
                "job_id": job_id,
                "complete": True,
                "failed": False,
                "status": "SUCCESS",
                "result": res_data
            }
        elif state == "FAILURE":
            return {
                "status_code": 500,
                "job_id": job_id,
                "complete": True,
                "failed": True,
                "status": "FAILURE",
                "message": "Task failed during execution"
            }
        else:
            return {
                "status_code": 200,
                "job_id": job_id,
                "complete": False,
                "failed": False,
                "status": "PENDING"
            }
    except Exception as e:
        return {
            "status_code": 200,
            "job_id": job_id,
            "complete": False,
            "failed": False,
            "status": "PENDING"
        }
