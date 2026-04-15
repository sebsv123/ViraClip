#!/usr/bin/env python3
"""Test single video with full editing pipeline."""
import asyncio
import logging
from pathlib import Path
from src.services.video_service import VideoService

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def main():
    url = "https://youtu.be/3wgwaxIfUJQ"
    
    logger.info(f"\n{'='*70}")
    logger.info(f"TESTING FULL PIPELINE: {url}")
    logger.info(f"{'='*70}\n")
    
    try:
        result = await VideoService.process_video_complete(
            url=url,
            source_type='youtube',
            task_id='full_editing_test',
            processing_mode='fast',
            add_subtitles=True,
            caption_template='viral',
            output_format='vertical'
        )
        
        segments = result.get('segments', [])
        logger.info(f"\n{'='*70}")
        logger.info(f"PIPELINE COMPLETE")
        logger.info(f"{'='*70}")
        logger.info(f"Segments identified: {len(segments)}")
        
        # Check for rendered clips
        clips_dir = Path("temp/clips")
        if clips_dir.exists():
            clips = list(clips_dir.glob("*.mp4"))
            logger.info(f"Clips on disk: {len(clips)}")
            for clip in clips:
                size_mb = clip.stat().st_size / (1024 * 1024)
                logger.info(f"  ✓ {clip.name} ({size_mb:.1f}MB)")
        
        return result
        
    except Exception as e:
        logger.error(f"\n{'='*70}")
        logger.error(f"ERROR IN PIPELINE")
        logger.error(f"{'='*70}")
        logger.exception(e)
        raise


if __name__ == "__main__":
    asyncio.run(main())
