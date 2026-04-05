"""Re-export shim so tasks.py can import periodic_model_retraining cleanly."""
from ..services.feedback_loop_service import periodic_model_retraining  # noqa: F401
