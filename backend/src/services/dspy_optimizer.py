"""
DSPy optimization for local LLM prompting.

Uses Claude as teacher to optimize prompts for local Ollama models.
Requires 50+ examples minimum for meaningful optimization.
"""

import logging
from typing import List, Dict, Any, Optional
import json
from pathlib import Path

logger = logging.getLogger(__name__)


class DSPyOptimizer:
    """Optimize LLM prompts using DSPy with Claude as teacher."""
    
    def __init__(self, dataset_path: str):
        self.dataset_path = Path(dataset_path)
        self.optimized_prompt = None
    
    async def optimize(
        self,
        teacher_model: str = "claude-3-5-sonnet-20241022",
        student_model: str = "ollama/qwen3-vl:8b",
        metric: str = "accuracy",
        trials: int = 10
    ) -> Dict[str, Any]:
        """
        Run DSPy optimization to find best prompt for student model.
        
        Args:
            teacher_model: Teacher LLM (Claude for high quality)
            student_model: Student LLM (local Ollama)
            metric: Optimization metric (accuracy, f1, etc.)
            trials: Number of optimization trials
            
        Returns:
            Optimization results with best prompt
        """
        logger.info(f"🎓 Starting DSPy optimization: {teacher_model} → {student_model}")
        
        try:
            # Import DSPy (only when needed)
            import dspy
            from dspy.teleprompt import BootstrapFewShot
            from dspy.evaluate import Evaluate
            
            # Load dataset
            with open(self.dataset_path, "r", encoding="utf-8") as f:
                examples = json.load(f)
            
            if len(examples) < 50:
                raise ValueError(
                    f"Need at least 50 examples for DSPy, got {len(examples)}. "
                    "Collect more user feedback first."
                )
            
            logger.info(f"📊 Loaded {len(examples)} examples for optimization")
            
            # Split into train/dev
            train_size = int(len(examples) * 0.8)
            train_examples = examples[:train_size]
            dev_examples = examples[train_size:]
            
            # Configure teacher LLM (Claude via Anthropic)
            teacher_lm = dspy.Claude(
                model=teacher_model,
                api_key=self._get_anthropic_key()
            )
            
            # Configure student LLM (Ollama)
            student_lm = dspy.OllamaLocal(
                model=student_model.replace("ollama/", ""),
                base_url=self._get_ollama_url()
            )
            
            # Define signature for viral scoring task
            class ViralScorer(dspy.Signature):
                """Score video transcript for viral potential."""
                transcript = dspy.InputField(desc="Video transcript to analyze")
                segments = dspy.OutputField(desc="JSON with viral segments and scores")
            
            # Create module
            class ViralScoringModule(dspy.Module):
                def __init__(self):
                    super().__init__()
                    self.predictor = dspy.Predict(ViralScorer)
                
                def forward(self, transcript):
                    return self.predictor(transcript=transcript)
            
            # Initialize module with teacher
            dspy.settings.configure(lm=teacher_lm)
            module = ViralScoringModule()
            
            # Define metric
            def accuracy_metric(example, prediction, trace=None):
                """Check if prediction matches expected format."""
                try:
                    pred_json = json.loads(prediction.segments)
                    return "segments" in pred_json and len(pred_json["segments"]) > 0
                except:
                    return False
            
            # Optimize with few-shot learning
            teleprompter = BootstrapFewShot(
                metric=accuracy_metric,
                max_bootstrapped_demos=4,
                max_labeled_demos=8
            )
            
            logger.info("🔄 Running optimization (this may take 5-10 minutes)...")
            
            optimized_module = teleprompter.compile(
                module,
                trainset=train_examples[:50]  # Use subset for faster optimization
            )
            
            # Evaluate on dev set with student model
            dspy.settings.configure(lm=student_lm)
            
            evaluator = Evaluate(
                devset=dev_examples,
                metric=accuracy_metric,
                num_threads=1
            )
            
            dev_score = evaluator(optimized_module)
            
            # Extract optimized prompt
            self.optimized_prompt = optimized_module.predictor.extended_signature
            
            logger.info(f"✅ Optimization complete! Dev accuracy: {dev_score:.2%}")
            
            return {
                "success": True,
                "dev_accuracy": dev_score,
                "train_examples": len(train_examples),
                "dev_examples": len(dev_examples),
                "optimized_prompt": str(self.optimized_prompt),
                "teacher_model": teacher_model,
                "student_model": student_model
            }
            
        except ImportError:
            logger.error("DSPy not installed. Install with: pip install dspy-ai==2.5.2")
            return {
                "success": False,
                "error": "DSPy not installed"
            }
        except Exception as e:
            logger.error(f"DSPy optimization failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    async def save_optimized_prompt(self, output_path: str):
        """Save optimized prompt to file."""
        if self.optimized_prompt is None:
            raise ValueError("No optimized prompt available. Run optimize() first.")
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(str(self.optimized_prompt))
        
        logger.info(f"💾 Saved optimized prompt to {output_path}")
    
    def _get_anthropic_key(self) -> str:
        """Get Anthropic API key from environment."""
        import os
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        return key
    
    def _get_ollama_url(self) -> str:
        """Get Ollama base URL."""
        import os
        return os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")


# Convenience function
async def run_dspy_optimization(dataset_path: str) -> Dict[str, Any]:
    """Run DSPy optimization pipeline."""
    optimizer = DSPyOptimizer(dataset_path)
    return await optimizer.optimize()
