"""
Federated Learning API Routes
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...services.federated_learning import (
    FLModelType,
    get_federated_learning_service,
)

router = APIRouter(prefix="/federated", tags=["Federated Learning"])


class RegisterClientRequest(BaseModel):
    client_id: str
    model_types: List[str] = Field(..., min_length=1)
    capabilities: Optional[Dict[str, Any]] = None


class StartRoundRequest(BaseModel):
    model_type: str


class SubmitUpdateRequest(BaseModel):
    round_id: str
    client_id: str
    weights: Dict[str, List[float]]
    metrics: Optional[Dict[str, Any]] = None


@router.post("/clients/register")
async def register_client(body: RegisterClientRequest) -> Dict[str, Any]:
    """Register a new federated learning client."""
    svc = get_federated_learning_service()
    try:
        model_types = [FLModelType(mt) for mt in body.model_types]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid model_type: {e}")
    try:
        success = await svc.register_client(
            client_id=body.client_id,
            model_types=model_types,
            capabilities=body.capabilities or {},
        )
        return {"client_id": body.client_id, "registered": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/clients/stats")
async def get_client_stats() -> Dict[str, Any]:
    """Get client participation statistics."""
    svc = get_federated_learning_service()
    try:
        return svc.get_client_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rounds/start")
async def start_round(body: StartRoundRequest) -> Dict[str, Any]:
    """Start a new federated learning round for a model type."""
    svc = get_federated_learning_service()
    try:
        model_type = FLModelType(body.model_type)
    except ValueError:
        valid = [m.value for m in FLModelType]
        raise HTTPException(status_code=422, detail=f"model_type must be one of {valid}")
    try:
        fl_round = await svc.start_round(model_type=model_type)
        return {
            "round_id": fl_round.round_id,
            "model_type": fl_round.model_type.value,
            "status": fl_round.status.value,
            "target_clients": fl_round.target_clients,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rounds/{round_id}/status")
async def get_round_status(round_id: str) -> Dict[str, Any]:
    """Get status of a federated learning round."""
    svc = get_federated_learning_service()
    status = svc.get_round_status(round_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Round {round_id} not found")
    return status


@router.post("/rounds/update")
async def submit_client_update(body: SubmitUpdateRequest) -> Dict[str, Any]:
    """Submit a client model update for a training round."""
    svc = get_federated_learning_service()
    try:
        success = await svc.submit_client_update(
            round_id=body.round_id,
            client_id=body.client_id,
            weights=body.weights,
            metrics=body.metrics or {},
        )
        return {"round_id": body.round_id, "client_id": body.client_id, "accepted": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_training_history(
    model_type: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Get federated learning training history."""
    svc = get_federated_learning_service()
    try:
        mt = FLModelType(model_type) if model_type else None
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid model_type: {model_type}")
    try:
        history = svc.get_training_history(model_type=mt)
        return {"model_type": model_type, "event_count": len(history), "history": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/{model_type}/performance")
async def get_model_performance(model_type: str) -> Dict[str, Any]:
    """Get performance metrics over time for a specific model type."""
    svc = get_federated_learning_service()
    try:
        mt = FLModelType(model_type)
    except ValueError:
        valid = [m.value for m in FLModelType]
        raise HTTPException(status_code=422, detail=f"model_type must be one of {valid}")
    try:
        return svc.get_model_performance(mt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
