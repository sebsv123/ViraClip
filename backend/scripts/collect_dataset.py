"""
Dataset Collector Utility - extracts viral data for LLM fine-tuning.
"""
import asyncio
import json
import logging
from sqlalchemy import text
from src.database import AsyncSessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def collect_viral_dataset(output_file: str = "viral_dataset.jsonl", min_score: int = 80):
    """
    Export segments with high virality scores to JSONL for Unsloth/Llama-3 fine-tuning.
    """
    logger.info(f"Collecting dataset with virality_score >= {min_score}...")
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("""
                SELECT text, virality_score, hook_type, reasoning, suggested_title
                FROM generated_clips
                WHERE virality_score >= :min_score
            """),
            {"min_score": min_score}
        )
        
        rows = result.fetchall()
        count = 0
        
        with open(output_file, 'w', encoding='utf-8') as f:
            for row in rows:
                # Format for instruction fine-tuning
                item = {
                    "instruction": "Analyze this transcript segment for viral potential and suggest editing cues.",
                    "input": f"Transcript: {row.text}",
                    "output": json.dumps({
                        "virality_score": row.virality_score,
                        "hook_type": row.hook_type,
                        "suggested_title": row.suggested_title,
                        "strategy": row.reasoning
                    })
                }
                f.write(json.dumps(item) + '\n')
                count += 1
        
    logger.info(f"Successfully exported {count} training examples to {output_file}")

if __name__ == "__main__":
    asyncio.run(collect_viral_dataset())
