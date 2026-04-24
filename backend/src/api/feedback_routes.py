"""
Feedback Loop API Routes — Phase 5.3
=====================================
Endpoints para reentrenamiento manual y monitoreo del feedback loop.
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import Dict, Any, Optional
import logging

from ..domains.feedback.feedback_loop_service import get_feedback_service, FeedbackLoopService
from ..database import get_db
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


@router.post("/retrain")
async def trigger_retraining(
    background_tasks: BackgroundTasks,
    days_back: int = 30,
    validate: bool = True,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Trigger manual retraining of virality scorer.
    
    Args:
        days_back: Days of feedback data to collect
        validate: Whether to validate against current model
        
    Returns:
        Training metrics and deployment status
    """
    logger.info(f"[feedback] Manual retraining triggered (days_back={days_back})")
    
    service = get_feedback_service(db)
    
    try:
        # Run in background to avoid timeout
        background_tasks.add_task(
            service.retrain_model,
            df=None,
            validate=validate
        )
        
        return {
            "status": "training_started",
            "message": "Model retraining started in background",
            "days_back": days_back,
            "validate": validate
        }
        
    except Exception as e:
        logger.error(f"[feedback] Retraining failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retrain/sync")
async def trigger_retraining_sync(
    days_back: int = 30,
    validate: bool = True,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Trigger synchronous retraining (blocks until complete).
    Use for testing or when immediate result is needed.
    """
    logger.info(f"[feedback] Sync retraining triggered")
    
    service = get_feedback_service(db)
    
    try:
        result = await service.retrain_model(df=None, validate=validate)
        return result
        
    except Exception as e:
        logger.error(f"[feedback] Sync retraining failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_feedback_stats(
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get feedback loop statistics and current model info.
    
    Returns:
        - Model version
        - Training metrics
        - Number of feedback samples
        - Last retraining timestamp
    """
    service = get_feedback_service(db)
    
    try:
        stats = await service.get_training_stats()
        return stats
        
    except Exception as e:
        logger.error(f"[feedback] Stats retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collect")
async def collect_feedback_batch(
    days_back: int = 7,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Manually collect feedback batch without retraining.
    Useful for inspection and debugging.
    """
    logger.info(f"[feedback] Collecting feedback batch (days_back={days_back})")
    
    service = get_feedback_service(db)
    
    try:
        df = await service.collect_feedback_batch(days_back=days_back)
        
        return {
            "status": "success",
            "n_samples": len(df),
            "days_back": days_back,
            "columns": list(df.columns),
            "sample_stats": {
                "avg_predicted_score": float(df["predicted_score"].mean()) if "predicted_score" in df.columns else None,
                "avg_actual_score": float(df["actual_score"].mean()) if "actual_score" in df.columns else None,
                "avg_user_rating": float(df["user_rating"].mean()) if "user_rating" in df.columns else None
            }
        }
        
    except Exception as e:
        logger.error(f"[feedback] Batch collection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/predict")
async def predict_virality(
    features: Dict[str, float],
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Predict virality score using current trained model.
    
    Args:
        features: {
            "duration": 30.0,
            "hook_strength": 85.0,
            "engagement_score": 72.0,
            "has_captions": 1,
            "has_broll": 0
        }
        
    Returns:
        Predicted score and model version
    """
    service = get_feedback_service(db)
    
    try:
        score = service.predict(features)
        
        return {
            "predicted_score": score,
            "model_version": service.model_version,
            "features_used": features
        }
        
    except Exception as e:
        logger.error(f"[feedback] Prediction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/model/reload")
async def reload_model(
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Manually reload current model from disk.
    Useful after external model updates.
    """
    service = get_feedback_service(db)
    
    try:
        model = service.load_current_model()
        
        if model is None:
            raise HTTPException(status_code=404, detail="No model found")
        
        return {
            "status": "reloaded",
            "model_version": service.model_version,
            "metadata": service.model_metadata
        }
        
    except Exception as e:
        logger.error(f"[feedback] Model reload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
