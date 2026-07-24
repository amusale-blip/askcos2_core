from pydantic import BaseModel, Field
from typing import Any, Optional


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
        description="list of retrosynthesis model names to query (e.g. ['onmt_moltrans', 'augmented_transformer', 'retrochimera'])"
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
    results: Optional[list[SingleExpansionResult]] = None
    result: Optional[dict[str, Any]] = None


class ValidateRequest(BaseModel):
    smiles: str = Field(..., description="SMILES string to validate and canonicalize")


class ValidateResponse(BaseModel):
    status_code: int = 200
    valid: bool
    input_smiles: str
    canonical_smiles: Optional[str] = None
    message: str = ""
