"""
Dataset collection for LLM optimization.

Collects user feedback (👍/👎) on clip quality to build training dataset.
Format: JSONL with Claude outputs + user ratings for DSPy/fine-tuning.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)


class DatasetCollector:
    """Collect and manage training data for LLM optimization."""
    
    def __init__(self, dataset_dir: str = "/app/datasets"):
        self.dataset_dir = Path(dataset_dir)
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        
        self.dataset_file = self.dataset_dir / "viraclip_llm_training.jsonl"
        self.metadata_file = self.dataset_dir / "metadata.json"
    
    async def record_interaction(
        self,
        task_id: str,
        transcript: str,
        llm_output: Dict[str, Any],
        user_rating: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record an LLM interaction for potential training data.
        
        Args:
            task_id: Unique task identifier
            transcript: Video transcript
            llm_output: LLM's scoring output (segments)
            user_rating: User feedback (positive/negative/neutral)
            metadata: Additional context (language, video_url, etc.)
            
        Returns:
            Example ID (hash)
        """
        example_id = hashlib.sha256(
            f"{task_id}:{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        example = {
            "id": example_id,
            "task_id": task_id,
            "timestamp": datetime.utcnow().isoformat(),
            "transcript": transcript,
            "llm_output": llm_output,
            "user_rating": user_rating,
            "metadata": metadata or {},
        }
        
        # Append to JSONL
        with open(self.dataset_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
        
        logger.info(f"📊 Recorded example {example_id} (rating: {user_rating})")
        
        # Update metadata
        await self._update_metadata()
        
        return example_id
    
    async def add_user_feedback(
        self,
        task_id: str,
        clip_id: str,
        rating: str,
        feedback_text: Optional[str] = None
    ):
        """
        Add user feedback to existing example.
        
        Args:
            task_id: Task identifier
            clip_id: Clip identifier
            rating: thumbs_up, thumbs_down, or neutral
            feedback_text: Optional text feedback
        """
        # Read existing examples
        examples = []
        if self.dataset_file.exists():
            with open(self.dataset_file, "r", encoding="utf-8") as f:
                examples = [json.loads(line) for line in f if line.strip()]
        
        # Find matching example
        updated = False
        for example in examples:
            if example.get("task_id") == task_id:
                if "user_feedback" not in example:
                    example["user_feedback"] = []
                
                example["user_feedback"].append({
                    "clip_id": clip_id,
                    "rating": rating,
                    "feedback_text": feedback_text,
                    "timestamp": datetime.utcnow().isoformat()
                })
                
                # Update overall rating based on feedback
                positive = sum(1 for f in example["user_feedback"] if f["rating"] == "thumbs_up")
                negative = sum(1 for f in example["user_feedback"] if f["rating"] == "thumbs_down")
                
                if positive > negative:
                    example["user_rating"] = "positive"
                elif negative > positive:
                    example["user_rating"] = "negative"
                else:
                    example["user_rating"] = "neutral"
                
                updated = True
                break
        
        if updated:
            # Rewrite file
            with open(self.dataset_file, "w", encoding="utf-8") as f:
                for example in examples:
                    f.write(json.dumps(example, ensure_ascii=False) + "\n")
            
            logger.info(f"👍 Updated feedback for task {task_id}")
            await self._update_metadata()
        else:
            logger.warning(f"Task {task_id} not found in dataset")
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get dataset statistics."""
        if not self.dataset_file.exists():
            return {
                "total_examples": 0,
                "positive": 0,
                "negative": 0,
                "neutral": 0,
                "ready_for_dspy": False,
                "ready_for_finetuning": False
            }
        
        examples = []
        with open(self.dataset_file, "r", encoding="utf-8") as f:
            examples = [json.loads(line) for line in f if line.strip()]
        
        positive = sum(1 for e in examples if e.get("user_rating") == "positive")
        negative = sum(1 for e in examples if e.get("user_rating") == "negative")
        neutral = sum(1 for e in examples if e.get("user_rating") == "neutral")
        
        return {
            "total_examples": len(examples),
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "ready_for_dspy": len(examples) >= 50,  # DSPy threshold
            "ready_for_finetuning": len(examples) >= 200,  # Fine-tuning threshold
            "dataset_file": str(self.dataset_file)
        }
    
    async def export_for_dspy(self, output_file: Optional[str] = None) -> str:
        """
        Export dataset in DSPy-compatible format.
        
        Args:
            output_file: Optional output path
            
        Returns:
            Path to exported file
        """
        if output_file is None:
            output_file = str(self.dataset_dir / "dspy_dataset.json")
        
        examples = []
        with open(self.dataset_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    example = json.loads(line)
                    # Only include rated examples
                    if example.get("user_rating") in ["positive", "negative"]:
                        examples.append({
                            "question": f"Score this video transcript for virality:\n{example['transcript']}",
                            "answer": json.dumps(example["llm_output"]),
                            "rating": example["user_rating"]
                        })
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(examples, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📦 Exported {len(examples)} examples for DSPy to {output_file}")
        return output_file
    
    async def export_for_finetuning(self, output_file: Optional[str] = None) -> str:
        """
        Export dataset in fine-tuning format (JSONL with prompts/completions).
        
        Args:
            output_file: Optional output path
            
        Returns:
            Path to exported file
        """
        if output_file is None:
            output_file = str(self.dataset_dir / "finetuning_dataset.jsonl")
        
        from ...services.ai_prompts import VIRAL_SCORER_SYSTEM_PROMPT
        
        exported = 0
        with open(output_file, "w", encoding="utf-8") as out_f:
            with open(self.dataset_file, "r", encoding="utf-8") as in_f:
                for line in in_f:
                    if line.strip():
                        example = json.loads(line)
                        
                        # Only positive examples for fine-tuning
                        if example.get("user_rating") == "positive":
                            training_example = {
                                "messages": [
                                    {"role": "system", "content": VIRAL_SCORER_SYSTEM_PROMPT},
                                    {
                                        "role": "user",
                                        "content": f"Transcript:\n{example['transcript']}\n\nProvide viral scoring."
                                    },
                                    {
                                        "role": "assistant",
                                        "content": json.dumps(example["llm_output"])
                                    }
                                ]
                            }
                            out_f.write(json.dumps(training_example, ensure_ascii=False) + "\n")
                            exported += 1
        
        logger.info(f"📦 Exported {exported} examples for fine-tuning to {output_file}")
        return output_file
    
    async def _update_metadata(self):
        """Update dataset metadata file."""
        stats = await self.get_stats()
        stats["last_updated"] = datetime.utcnow().isoformat()
        
        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)


# Singleton instance
_dataset_collector: Optional[DatasetCollector] = None


def get_dataset_collector(dataset_dir: str = "/app/datasets") -> DatasetCollector:
    """Get or create dataset collector singleton."""
    global _dataset_collector
    if _dataset_collector is None:
        _dataset_collector = DatasetCollector(dataset_dir)
    return _dataset_collector
