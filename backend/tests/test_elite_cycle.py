import asyncio
from pathlib import Path
import logging
from src.services.elite_ai_service import EliteAIService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_full_elite_cycle():
    """
    Internal smoke test for the V4 Elite Master Orchestrator.
    """
    elite_service = EliteAIService()
    test_video = Path("storage/uploads/test_video.mp4")
    
    # Ensure test video exists for simulation
    test_video.parent.mkdir(parents=True, exist_ok=True)
    if not test_video.exists():
        with open(test_video, "w") as f:
            f.write("dummy video content")

    logger.info("🧪 Test: Starting End-to-End Elite Cycle Simulation")
    
    try:
        # P5 Master Cycle Invocation
        result = await elite_service.run_full_elite_cycle(
            task_id="TEST_ELITE_001",
            video_path=test_video,
            target_platforms=["tiktok", "instagram"]
        )
        
        logger.info(f"✅ Test Complete: Generated {result['clips_generated']} clips")
        logger.info(f"📬 Publications: {len(result['publications'])} platforms triggered")
        logger.info(f"🤖 Engagement: {result['engagement']}")
        return True
    except Exception as e:
        logger.error(f"❌ Test Failed: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(test_full_elite_cycle())
