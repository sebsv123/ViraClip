"""Re-export shim so tasks.py can import periodic_model_retraining cleanly."""
from ..domains.feedback.feedback_loop_service import periodic_model_retraining  # noqa: F401
