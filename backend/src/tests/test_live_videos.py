"""
ViraClip Live Testing Script
Test video processing with real YouTube videos.
"""

import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
import json
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Configure logging — force UTF-8 on all handlers so emoji characters
# don't crash on Windows cp1252 console.
import io as _io
_utf8_stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
_log_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
_handlers = [
    logging.StreamHandler(_utf8_stdout),
    logging.FileHandler(f'test_run_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log', encoding='utf-8'),
]
logging.basicConfig(level=logging.INFO, format=_log_fmt, handlers=_handlers)
logger = logging.getLogger(__name__)

# Test videos
TEST_VIDEOS = [
    {
        "id": "video_1",
        "url": "https://youtu.be/DHSigj8uPnE",
        "title": "Test Video 1 - Short educational content",
        "expected_duration": "2-5 min"
    },
    {
        "id": "video_2", 
        "url": "https://youtu.be/3wgwaxIfUJQ",
        "title": "Test Video 2 - Tutorial content",
        "expected_duration": "5-15 min"
    }
]


class ViraClipTester:
    """Test runner for ViraClip video processing."""
    
    def __init__(self):
        self.results = []
        self.errors = []
        self.start_time = None
        
    async def progress_callback(self, progress: int, message: str, status: str):
        """Track processing progress."""
        logger.info(f"[{progress}%] {status}: {message}")
        
    async def test_video(self, video_config: dict) -> dict:
        """Test processing of a single video."""
        video_id = video_config["id"]
        url = video_config["url"]
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing {video_id}: {video_config['title']}")
        logger.info(f"URL: {url}")
        logger.info(f"{'='*60}\n")
        
        start_time = time.time()
        result = {
            "video_id": video_id,
            "url": url,
            "start_time": datetime.now().isoformat(),
            "status": "pending",
            "stages": {},
            "errors": [],
            "clips_generated": 0,
            "metrics": {}
        }
        
        try:
            # Import here to catch import errors
            logger.info("[IMPORT] Importing ViraClip services...")
            try:
                from src.services.video_service import VideoService
                from src.services.metrics_service import get_metrics_collector
                from src.services.cache_manager import get_cache_manager
                result["stages"]["imports"] = "SUCCESS"
            except ImportError as e:
                error_msg = f"Import failed: {str(e)}"
                logger.error(error_msg)
                result["errors"].append(error_msg)
                result["status"] = "failed"
                return result
            
            # Test 1: Source type detection
            logger.info("[TEST] Testing source type detection...")
            try:
                source_type = VideoService.determine_source_type(url)
                logger.info(f"   Source type: {source_type}")
                result["stages"]["source_detection"] = f"OK - {source_type}"
            except Exception as e:
                error_msg = f"Source detection failed: {str(e)}"
                logger.error(error_msg)
                result["errors"].append(error_msg)
                result["stages"]["source_detection"] = f"ERROR: {str(e)}"
            
            # Test 2: Video info retrieval
            logger.info("[TEST] Testing video info retrieval...")
            try:
                from src.youtube_utils import async_get_youtube_video_info
                video_info = await async_get_youtube_video_info(url, task_id=video_id)
                if video_info:
                    logger.info(f"   Title: {video_info.get('title', 'N/A')}")
                    logger.info(f"   Duration: {video_info.get('duration', 0)} seconds")
                    logger.info(f"   Author: {video_info.get('author', 'N/A')}")
                    result["stages"]["video_info"] = "SUCCESS"
                    result["video_info"] = video_info
                else:
                    error_msg = "No video info returned"
                    logger.warning(error_msg)
                    result["stages"]["video_info"] = f"WARNING: {error_msg}"
            except Exception as e:
                error_msg = f"Video info failed: {str(e)}"
                logger.error(error_msg)
                result["errors"].append(error_msg)
                result["stages"]["video_info"] = f"ERROR: {str(e)}"
            
            # Test 3: Video download
            logger.info("[TEST] Testing video download...")
            try:
                video_path = await VideoService.download_video(url, task_id=video_id)
                if video_path and video_path.exists():
                    file_size = video_path.stat().st_size
                    logger.info(f"   Downloaded to: {video_path}")
                    logger.info(f"   File size: {file_size / (1024*1024):.2f} MB")
                    result["stages"]["download"] = f"OK - {file_size / (1024*1024):.1f} MB"
                    result["video_path"] = str(video_path)
                else:
                    error_msg = "Download failed - no file created"
                    logger.error(error_msg)
                    result["errors"].append(error_msg)
                    result["status"] = "failed"
                    return result
            except Exception as e:
                error_msg = f"Download failed: {str(e)}"
                logger.error(error_msg)
                result["errors"].append(error_msg)
                result["status"] = "failed"
                return result
            
            # Test 4: Transcription
            transcript = None
            logger.info("[TEST] Testing transcription...")
            try:
                transcript = await VideoService.generate_transcript(
                    video_path, 
                    processing_mode="fast"
                )
                transcript_length = len(transcript) if transcript else 0
                word_count = len(transcript.split()) if transcript else 0
                logger.info(f"   Transcript length: {transcript_length} chars")
                logger.info(f"   Word count: {word_count} words")
                logger.info(f"   Preview: {transcript[:200]}...")
                result["stages"]["transcription"] = f"OK - {word_count} words"
                result["transcript_length"] = transcript_length
                result["transcript_preview"] = transcript[:500] if transcript else ""
            except Exception as e:
                error_msg = f"Transcription failed: {str(e)}"
                logger.error(error_msg)
                result["errors"].append(error_msg)
                result["stages"]["transcription"] = f"ERROR: {str(e)}"
            
            # Test 5: AI Analysis
            logger.info("[TEST] Testing AI content analysis...")
            try:
                if not transcript:
                    raise ValueError("No transcript available for AI analysis")
                analysis = await VideoService.analyze_transcript(
                    transcript,
                    video_duration=video_info.get('duration', 0) if 'video_info' in result else 0
                )
                segments = getattr(analysis, 'most_relevant_segments', []) or []
                logger.info(f"   Segments found: {len(segments)}")
                logger.info(f"   Summary: {getattr(analysis, 'summary', 'N/A')[:200]}...")
                result["stages"]["ai_analysis"] = f"OK - {len(segments)} segments"
                result["segments_found"] = len(segments)
                result["summary"] = getattr(analysis, 'summary', '')[:500]
            except Exception as e:
                error_msg = f"AI analysis failed: {str(e)}"
                logger.error(error_msg)
                result["errors"].append(error_msg)
                result["stages"]["ai_analysis"] = f"ERROR: {str(e)}"
            
            # Test 6: Complete pipeline (if all previous passed)
            if len(result["errors"]) == 0:
                logger.info("[TEST] Testing complete processing pipeline...")
                try:
                    pipeline_result = await VideoService.process_video_complete(
                        url=url,
                        source_type="youtube",
                        task_id=video_id,
                        processing_mode="fast",
                        progress_callback=self.progress_callback
                    )
                    
                    segments = pipeline_result.get('segments', [])
                    metrics = pipeline_result.get('_metrics', {})
                    video_path = Path(pipeline_result.get('video_path', ''))
                    
                    logger.info(f"   PIPELINE COMPLETED!")
                    logger.info(f"   Clips identified: {len(segments)}")
                    logger.info(f"   Processing time: {metrics.get('total_duration_seconds', 'N/A')}s")

                    # Step 7: Render actual video clips (the missing step)
                    rendered_clips = []
                    if segments and video_path.exists():
                        logger.info(f"[TEST] Rendering {min(3, len(segments))} clips to disk...")
                        clips_dir = Path("temp") / "clips"
                        clips_dir.mkdir(parents=True, exist_ok=True)
                        render_segments = segments[:3]
                        try:
                            clips_info = await VideoService.create_video_clips_parallel(
                                video_path=video_path,
                                segments=render_segments,
                                task_id=video_id,
                                add_subtitles=True,
                                caption_template="viral",
                                output_format="vertical",
                            )
                            rendered_clips = [c for c in clips_info if c]
                            for i, ci in enumerate(rendered_clips):
                                cp = Path(ci.get("path", ""))
                                size_mb = cp.stat().st_size / 1024 / 1024 if cp.exists() else 0
                                logger.info(
                                    f"   CLIP {i+1} rendered: {cp.name} "
                                    f"({size_mb:.1f}MB) virality={ci.get('virality_score',0)}"
                                )
                            logger.info(f"   Rendered {len(rendered_clips)}/{len(render_segments)} clips OK")
                        except Exception as render_e:
                            logger.error(f"   Clip render failed: {render_e}", exc_info=True)
                    
                    # Log top segment info
                    for i, clip in enumerate(segments[:3]):
                        logger.info(f"\n   SEGMENT {i+1}:")
                        logger.info(f"      Virality Score: {clip.get('virality_score', 0):.1f}/100")
                        logger.info(f"      Duration: {clip.get('duration', 0):.1f}s")
                        logger.info(f"      Hook Type: {clip.get('hook_type', 'N/A')}")
                    
                    result["stages"]["pipeline"] = "SUCCESS"
                    result["clips_generated"] = len(rendered_clips) if rendered_clips else len(segments)
                    result["clips_rendered"] = len(rendered_clips)
                    result["pipeline_metrics"] = metrics
                    result["top_clips"] = segments[:5]
                    result["status"] = "success"
                    
                except Exception as e:
                    error_msg = f"Pipeline failed: {str(e)}"
                    logger.error(error_msg)
                    result["errors"].append(error_msg)
                    result["stages"]["pipeline"] = f"ERROR: {str(e)}"
                    result["status"] = "partial"
            else:
                result["status"] = "failed"
                logger.warning("Skipping pipeline test due to previous errors")
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.exception(error_msg)
            result["errors"].append(error_msg)
            result["status"] = "failed"
        
        finally:
            elapsed = time.time() - start_time
            result["elapsed_seconds"] = round(elapsed, 2)
            result["end_time"] = datetime.now().isoformat()
            logger.info(f"\n[Test completed in {elapsed:.2f} seconds]")
            logger.info(f"Final status: {result['status']}")
        
        return result
    
    async def run_all_tests(self):
        """Run tests for all configured videos."""
        logger.info("\n" + "="*70)
        logger.info("VIRACLIP LIVE TESTING SUITE")
        logger.info("="*70)
        logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Videos to test: {len(TEST_VIDEOS)}")
        logger.info("="*70 + "\n")
        
        all_results = []
        overall_start = time.time()
        
        for video in TEST_VIDEOS:
            result = await self.test_video(video)
            all_results.append(result)
            
            # Brief pause between tests
            if video != TEST_VIDEOS[-1]:
                logger.info("\nPausing 5 seconds before next test...")
                await asyncio.sleep(5)
        
        total_elapsed = time.time() - overall_start
        
        # Generate summary report
        logger.info("\n" + "="*70)
        logger.info("TEST SUMMARY REPORT")
        logger.info("="*70)
        
        successful = sum(1 for r in all_results if r["status"] == "success")
        partial = sum(1 for r in all_results if r["status"] == "partial")
        failed = sum(1 for r in all_results if r["status"] == "failed")
        
        logger.info(f"\nOverall Results:")
        logger.info(f"   SUCCESS: {successful}")
        logger.info(f"   PARTIAL: {partial}")
        logger.info(f"   FAILED: {failed}")
        logger.info(f"   Total time: {total_elapsed:.2f} seconds")
        
        logger.info(f"\nDetailed Results:")
        for result in all_results:
            status_icon = "[OK]" if result["status"] == "success" else "[PARTIAL]" if result["status"] == "partial" else "[FAIL]"
            logger.info(f"\n   {status_icon} {result['video_id']}:")
            logger.info(f"      Status: {result['status']}")
            logger.info(f"      Time: {result.get('elapsed_seconds', 'N/A')}s")
            logger.info(f"      Clips: {result.get('clips_generated', 0)}")
            logger.info(f"      Errors: {len(result['errors'])}")
            
            if result["errors"]:
                logger.info(f"      Error details:")
                for error in result["errors"]:
                    logger.info(f"         - {error}")
        
        # Save report to file
        report_file = f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump({
                "test_run": {
                    "started": datetime.now().isoformat(),
                    "videos_tested": len(TEST_VIDEOS),
                    "successful": successful,
                    "partial": partial,
                    "failed": failed,
                    "total_duration_seconds": round(total_elapsed, 2)
                },
                "results": all_results
            }, f, indent=2, default=str)
        
        logger.info(f"\nFull report saved to: {report_file}")
        logger.info("="*70)
        
        return all_results


def main():
    """Main entry point."""
    tester = ViraClipTester()
    
    try:
        # Run asyncio event loop
        results = asyncio.run(tester.run_all_tests())
        
        # Exit with appropriate code
        failed_count = sum(1 for r in results if r["status"] == "failed")
        sys.exit(0 if failed_count == 0 else 1)
        
    except KeyboardInterrupt:
        logger.info("\n\nTests interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"\nCritical error in test runner: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
