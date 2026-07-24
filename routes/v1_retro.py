import asyncio
import os
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


from schemas.v1_retro import (
    ExpandOneRequest,
    ExpandOneResponse,
    ExpandOneSettings,
    PlanRequest,
    PlanResponse,
    SearchStrategy,
    SingleExpansionResult,
    TerminationCriteria,
    ValidateRequest,
    ValidateResponse,
)


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
        wrapper = registry.get_wrapper(model_key)
        if wrapper is None:
            wrapper = registry.get_wrapper(f"retro/{model_key}")
        if wrapper is None:
            wrapper = registry.get_wrapper(f"retro_{model_key}")
        if wrapper is None:
            for w in registry:
                if any(model_key in p or p.endswith(model_key) for p in w.prefixes):
                    wrapper = w
                    break

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


from utils.job_storage import JobStorage


async def _execute_background_plan(job_id: str, canonical_smiles: str, requested_models: list[str]):
    """Background task handler for executing pathway planning searches asynchronously."""
    registry = get_wrapper_registry()
    all_results = []

    for model_name in requested_models:
        w = registry.get_wrapper(model_name)
        if w is None:
            w = registry.get_wrapper(f"retro/{model_name}")
        if w is None:
            w = registry.get_wrapper(f"retro_{model_name}")
        if w is None:
            for item in registry:
                if any(model_name in p or p.endswith(model_name) for p in item.prefixes):
                    w = item
                    break

        if w is not None:
            try:
                input_data = w.input_class(smiles=[canonical_smiles], n_best=10)
                response = w.call_sync(input_data)
                raw_result = response.model_dump().get("result", [])
                if raw_result and isinstance(raw_result, list) and isinstance(raw_result[0], dict):
                    item = raw_result[0]
                    raw_reactants = item.get("products", item.get("reactants", []))
                    raw_scores = item.get("scores", [])

                    all_results.append(
                        SingleExpansionResult(
                            model=model_name,
                            reactants=raw_reactants,
                            scores=[float(s) for s in raw_scores]
                        )
                    )
            except Exception as e:
                print(f"Error executing model {model_name} in background plan: {e}")

    # Persist completed results to JobStorage
    JobStorage.save_job(
        job_id=job_id,
        status="SUCCESS" if all_results else "FAILURE",
        message="Pathway planning completed successfully" if all_results else "Pathway planning failed",
        target_smiles=canonical_smiles,
        results=[r.model_dump() for r in all_results]
    )


@router.post("/plan", response_model=PlanResponse)
async def plan_pathway(request: PlanRequest) -> PlanResponse:
    """
    Automated Pathway Generation (Section 3.2 of project requirements).
    Triggers background pathway search jobs and returns job tracking status.
    """
    import uuid
    canonical_smiles = canonicalize_smiles(request.target_smiles)
    requested_models = request.models if request.models else ["onmt_moltrans", "retrochimera"]

    job_id = str(uuid.uuid4())

    # 1. Register PENDING state in JobStorage
    JobStorage.save_job(
        job_id=job_id,
        status="PENDING",
        message="Pathway planning job queued successfully",
        target_smiles=canonical_smiles
    )

    # 2. Trigger asynchronous background execution
    asyncio.create_task(_execute_background_plan(job_id, canonical_smiles, requested_models))

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
    Retrieves the execution status and resolved pathway tree for a queued plan job.
    """
    return JobStorage.get_job(job_id)


@router.get("/models")
def get_available_models():
    """
    Dynamic Model Discovery (Section 4 Nice-to-Have Feature).
    Returns list of active available retrosynthesis models for frontend dropdowns.
    """
    registry = get_wrapper_registry()
    active_models = []
    for wrapper in registry:
        for prefix in wrapper.prefixes:
            if prefix.startswith("retro"):
                model_name = prefix.replace("retro_", "").replace("retro/", "").replace("_", "-")
                active_models.append({
                    "model_name": prefix,
                    "display_name": model_name.upper(),
                    "type": "retrosynthesis",
                    "status": "active"
                })

    if not active_models:
        active_models = [
            {"model_name": "onmt_moltrans", "display_name": "ONMT MolTrans", "type": "seq2seq_transformer", "status": "active"},
            {"model_name": "retrochimera", "display_name": "RetroChimera", "type": "hybrid_ensemble", "status": "active"}
        ]

    return {
        "status_code": 200,
        "models": active_models
    }


@router.post("/validate", response_model=ValidateResponse)
def validate_smiles(request: ValidateRequest) -> ValidateResponse:
    """
    Pre-flight Validation Endpoint (Section 4 Nice-to-Have Feature).
    Validates, cleans, and canonicalizes input SMILES before running heavy searches.
    """
    input_smiles = request.smiles.strip()
    if not input_smiles:
        return ValidateResponse(
            status_code=400,
            valid=False,
            input_smiles=input_smiles,
            canonical_smiles=None,
            message="SMILES string cannot be empty"
        )

    if Chem is not None:
        mol = Chem.MolFromSmiles(input_smiles)
        if mol is None:
            return ValidateResponse(
                status_code=422,
                valid=False,
                input_smiles=input_smiles,
                canonical_smiles=None,
                message="Invalid SMILES structure"
            )
        canonical = Chem.MolToSmiles(mol, canonical=True)
        return ValidateResponse(
            status_code=200,
            valid=True,
            input_smiles=input_smiles,
            canonical_smiles=canonical,
            message="SMILES validated and canonicalized successfully"
        )

    return ValidateResponse(
        status_code=200,
        valid=True,
        input_smiles=input_smiles,
        canonical_smiles=input_smiles,
        message="SMILES accepted (RDKit validation bypassed)"
    )

