"""
Federated Learning Service
Privacy-preserving machine learning across distributed clients.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import numpy as np

logger = logging.getLogger(__name__)


class FLStatus(Enum):
    """Federated learning round status."""
    IDLE = "idle"
    COLLECTING = "collecting"
    AGGREGATING = "aggregating"
    TRAINING = "training"
    COMPLETED = "completed"


class FLModelType(Enum):
    """Types of federated models."""
    VIRALITY_PREDICTOR = "virality_predictor"
    CONTENT_CLASSIFIER = "content_classifier"
    OPTIMAL_TIMING = "optimal_timing"
    HOOK_ANALYZER = "hook_analyzer"


@dataclass
class ClientUpdate:
    """Model update from a client."""
    client_id: str
    round_number: int
    model_weights: Dict[str, np.ndarray]
    sample_count: int
    metrics: Dict[str, float]
    timestamp: str


@dataclass
class FLRound:
    """Federated learning round."""
    round_id: str
    model_type: FLModelType
    round_number: int
    status: FLStatus
    participating_clients: List[str]
    client_updates: List[ClientUpdate]
    global_weights: Optional[Dict[str, np.ndarray]]
    aggregated_metrics: Dict[str, float]
    start_time: str
    end_time: Optional[str]
    min_clients: int
    target_clients: int


class FederatedLearningService:
    """
    Federated Learning service for privacy-preserving model training.
    """
    
    def __init__(self):
        self._active_rounds: Dict[str, FLRound] = {}
        self._global_models: Dict[FLModelType, Dict[str, np.ndarray]] = {}
        self._client_registry: Dict[str, Dict[str, Any]] = {}
        self._training_history: List[Dict[str, Any]] = []
        self._current_round_number: Dict[FLModelType, int] = {}
        
        # FL parameters
        self.aggregation_threshold = 0.8
        self.min_clients_per_round = 3
        self.target_clients_per_round = 10
        self.round_timeout_seconds = 300
    
    async def register_client(
        self,
        client_id: str,
        model_types: List[FLModelType],
        capabilities: Dict[str, Any]
    ) -> bool:
        """Register a client for federated learning."""
        self._client_registry[client_id] = {
            "client_id": client_id,
            "models": model_types,
            "capabilities": capabilities,
            "registered_at": datetime.now().isoformat(),
            "last_participation": None,
            "total_contributions": 0
        }
        
        logger.info(f"Registered FL client {client_id}")
        return True
    
    async def start_round(
        self,
        model_type: FLModelType,
        base_weights: Optional[Dict[str, np.ndarray]] = None
    ) -> FLRound:
        """Start a new federated learning round."""
        import uuid
        
        round_number = self._current_round_number.get(model_type, 0) + 1
        self._current_round_number[model_type] = round_number
        
        # Use existing global model or provided weights
        initial_weights = base_weights or self._global_models.get(model_type)
        
        # Find eligible clients
        eligible_clients = [
            cid for cid, client in self._client_registry.items()
            if model_type in client["models"]
        ]
        
        round_id = str(uuid.uuid4())
        
        fl_round = FLRound(
            round_id=round_id,
            model_type=model_type,
            round_number=round_number,
            status=FLStatus.COLLECTING,
            participating_clients=eligible_clients,
            client_updates=[],
            global_weights=initial_weights,
            aggregated_metrics={},
            start_time=datetime.now().isoformat(),
            end_time=None,
            min_clients=self.min_clients_per_round,
            target_clients=self.target_clients_per_round
        )
        
        self._active_rounds[round_id] = fl_round
        
        logger.info(
            f"Started FL round {round_number} for {model_type.value} "
            f"with {len(eligible_clients)} eligible clients"
        )
        
        return fl_round
    
    async def submit_client_update(
        self,
        round_id: str,
        client_id: str,
        model_weights: Dict[str, np.ndarray],
        sample_count: int,
        metrics: Dict[str, float]
    ) -> bool:
        """Submit model update from a client."""
        if round_id not in self._active_rounds:
            return False
        
        round_data = self._active_rounds[round_id]
        
        if round_data.status != FLStatus.COLLECTING:
            return False
        
        # Check if client already submitted
        existing = [u for u in round_data.client_updates if u.client_id == client_id]
        if existing:
            return False
        
        update = ClientUpdate(
            client_id=client_id,
            round_number=round_data.round_number,
            model_weights=model_weights,
            sample_count=sample_count,
            metrics=metrics,
            timestamp=datetime.now().isoformat()
        )
        
        round_data.client_updates.append(update)
        
        # Update client stats
        if client_id in self._client_registry:
            self._client_registry[client_id]["total_contributions"] += 1
            self._client_registry[client_id]["last_participation"] = datetime.now().isoformat()
        
        logger.info(f"Received update from client {client_id} for round {round_id}")
        
        # Check if we have enough updates
        if len(round_data.client_updates) >= round_data.target_clients:
            await self._aggregate_round(round_id)
        
        return True
    
    async def _aggregate_round(self, round_id: str) -> bool:
        """Aggregate client updates for a round."""
        if round_id not in self._active_rounds:
            return False
        
        round_data = self._active_rounds[round_id]
        round_data.status = FLStatus.AGGREGATING
        
        if len(round_data.client_updates) < round_data.min_clients:
            logger.warning(f"Round {round_id} has insufficient clients, aborting")
            round_data.status = FLStatus.COMPLETED
            return False
        
        # Federated averaging
        aggregated_weights = self._federated_average(round_data.client_updates)
        
        # Update global model
        round_data.global_weights = aggregated_weights
        self._global_models[round_data.model_type] = aggregated_weights
        
        # Calculate aggregated metrics
        total_samples = sum(u.sample_count for u in round_data.client_updates)
        round_data.aggregated_metrics = {
            "participating_clients": len(round_data.client_updates),
            "total_samples": total_samples,
            "avg_loss": np.mean([u.metrics.get("loss", 0) for u in round_data.client_updates]),
            "avg_accuracy": np.mean([u.metrics.get("accuracy", 0) for u in round_data.client_updates])
        }
        
        round_data.status = FLStatus.COMPLETED
        round_data.end_time = datetime.now().isoformat()
        
        # Record in history
        self._training_history.append({
            "round_id": round_id,
            "model_type": round_data.model_type.value,
            "round_number": round_data.round_number,
            "metrics": round_data.aggregated_metrics,
            "timestamp": round_data.end_time
        })
        
        logger.info(
            f"Completed FL round {round_data.round_number} for {round_data.model_type.value} "
            f"with accuracy {round_data.aggregated_metrics['avg_accuracy']:.4f}"
        )
        
        return True
    
    def _federated_average(
        self,
        updates: List[ClientUpdate]
    ) -> Dict[str, np.ndarray]:
        """Perform federated averaging of client weights."""
        if not updates:
            return {}
        
        # Calculate total samples
        total_samples = sum(u.sample_count for u in updates)
        
        # Initialize aggregated weights
        aggregated = {}
        
        # Get weight keys from first update
        first_weights = updates[0].model_weights
        
        for key in first_weights.keys():
            # Weighted average
            weighted_sum = np.zeros_like(first_weights[key], dtype=np.float64)
            
            for update in updates:
                weight = update.sample_count / total_samples
                weighted_sum += update.model_weights[key] * weight
            
            aggregated[key] = weighted_sum.astype(first_weights[key].dtype)
        
        return aggregated
    
    async def get_global_model(
        self,
        model_type: FLModelType
    ) -> Optional[Dict[str, np.ndarray]]:
        """Get current global model weights."""
        return self._global_models.get(model_type)
    
    async def evaluate_model(
        self,
        model_type: FLModelType,
        test_data: Any
    ) -> Dict[str, float]:
        """Evaluate global model performance."""
        # In production, this would run actual evaluation
        # Placeholder metrics
        return {
            "accuracy": 0.85,
            "precision": 0.83,
            "recall": 0.87,
            "f1_score": 0.85
        }
    
    def get_round_status(self, round_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a FL round."""
        if round_id not in self._active_rounds:
            return None
        
        round_data = self._active_rounds[round_id]
        
        return {
            "round_id": round_id,
            "model_type": round_data.model_type.value,
            "round_number": round_data.round_number,
            "status": round_data.status.value,
            "updates_received": len(round_data.client_updates),
            "target_clients": round_data.target_clients,
            "elapsed_time": (
                datetime.now() - datetime.fromisoformat(round_data.start_time)
            ).total_seconds() if round_data.start_time else 0
        }
    
    def get_training_history(
        self,
        model_type: Optional[FLModelType] = None
    ) -> List[Dict[str, Any]]:
        """Get training history."""
        history = self._training_history
        
        if model_type:
            history = [h for h in history if h["model_type"] == model_type.value]
        
        return sorted(history, key=lambda x: x["timestamp"], reverse=True)
    
    def get_client_stats(self) -> Dict[str, Any]:
        """Get client participation statistics."""
        total_clients = len(self._client_registry)
        active_clients = len([c for c in self._client_registry.values() if c["total_contributions"] > 0])
        
        return {
            "total_registered": total_clients,
            "active_contributors": active_clients,
            "total_contributions": sum(c["total_contributions"] for c in self._client_registry.values()),
            "average_contributions_per_client": (
                sum(c["total_contributions"] for c in self._client_registry.values()) / total_clients
                if total_clients > 0 else 0
            )
        }
    
    def get_model_performance(self, model_type: FLModelType) -> Dict[str, Any]:
        """Get model performance over time."""
        history = [h for h in self._training_history if h["model_type"] == model_type.value]
        
        if not history:
            return {"error": "No training history available"}
        
        accuracies = [h["metrics"]["avg_accuracy"] for h in history if "avg_accuracy" in h["metrics"]]
        
        return {
            "model_type": model_type.value,
            "total_rounds": len(history),
            "latest_accuracy": accuracies[-1] if accuracies else 0,
            "average_accuracy": np.mean(accuracies) if accuracies else 0,
            "improvement": (accuracies[-1] - accuracies[0]) if len(accuracies) > 1 else 0
        }


# Global instance
_fl_service: Optional[FederatedLearningService] = None


def get_federated_learning_service() -> FederatedLearningService:
    """Get global federated learning service."""
    global _fl_service
    if _fl_service is None:
        _fl_service = FederatedLearningService()
    return _fl_service


# Convenience functions
async def start_federated_round(model_type: str) -> str:
    """Start a federated learning round."""
    service = get_federated_learning_service()
    model_enum = FLModelType(model_type)
    round_data = await service.start_round(model_enum)
    return round_data.round_id


async def submit_fl_update(
    round_id: str,
    client_id: str,
    weights: Dict[str, np.ndarray],
    samples: int
) -> bool:
    """Submit a client update to a federated round."""
    service = get_federated_learning_service()
    return await service.submit_client_update(
        round_id, client_id, weights, samples, {}
    )
