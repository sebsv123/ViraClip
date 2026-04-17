"""
Quick diagnostic test script for Week 1 features.

Run inside Docker container:
    docker-compose exec backend python /app/scripts/test_diagnostics.py

Or from host (requires httpx):
    python backend/scripts/test_diagnostics.py
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_diagnostics():
    """Test the comprehensive diagnostics endpoint."""
    print("🔍 Testing Diagnostics Endpoint...")
    print("-" * 50)
    
    try:
        import httpx
        
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get("http://localhost:8000/health/diagnostics")
            
            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "unknown")
                checks = data.get("checks", {})
                
                print(f"Overall Status: {status.upper()}")
                print()
                
                # Print each check
                for check_name, check_data in checks.items():
                    if isinstance(check_data, dict):
                        ok = check_data.get("ok", False)
                        icon = "✅" if ok else "❌"
                        print(f"{icon} {check_name}")
                        
                        # Print details
                        for key, value in check_data.items():
                            if key != "ok":
                                print(f"   {key}: {value}")
                    else:
                        print(f"   {check_name}: {check_data}")
                
                print()
                print("=" * 50)
                return status == "healthy"
            else:
                print(f"❌ HTTP {response.status_code}: {response.text}")
                return False
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


async def test_pydantic_validation():
    """Test Pydantic validation models."""
    print("\n🧪 Testing Pydantic Validation...")
    print("-" * 50)
    
    try:
        from src.models.viral_segment import ViralSegment, ScoringResponse
        
        # Test 1: Valid segment
        print("Test 1: Valid segment")
        segment = ViralSegment(
            start="0:30",
            end="1:15",
            hook_strength=8.0,
            emotional_peak=7.5,
            shareability=9.0,
            retention=8.5,
            viral_score=8.25,
            reason="Strong opening hook"
        )
        print(f"  ✅ Created segment: {segment.start} - {segment.end}")
        
        # Test 2: Invalid duration (should fail)
        print("\nTest 2: Invalid duration (should fail)")
        try:
            bad_segment = ViralSegment(
                start="0:00",
                end="0:20",  # Only 20 seconds
                hook_strength=8.0,
                emotional_peak=7.5,
                shareability=9.0,
                retention=8.5,
                viral_score=8.25,
                reason="Too short"
            )
            print("  ❌ Should have failed!")
            return False
        except Exception as e:
            print(f"  ✅ Correctly rejected: {str(e)[:50]}...")
        
        # Test 3: Valid scoring response
        print("\nTest 3: Valid scoring response")
        response = ScoringResponse(segments=[segment])
        print(f"  ✅ Created response with {len(response.segments)} segment(s)")
        
        print("\n✅ All Pydantic tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Pydantic test failed: {e}")
        return False


async def test_cache_checker():
    """Test cache checker logic."""
    print("\n📦 Testing Cache Checker...")
    print("-" * 50)
    
    try:
        from src.services.cache_checker import get_cache_checker
        import tempfile
        import time
        
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = get_cache_checker(temp_dir=tmpdir)
            
            # Create fake video
            video_path = Path(tmpdir) / "test.mp4"
            video_path.write_text("fake video")
            
            # Test cache miss (no clips exist)
            result = await checker.check_existing_clips(
                task_id="test-123",
                video_path=str(video_path)
            )
            
            if result is None:
                print("  ✅ Cache miss detected (no clips)")
            else:
                print("  ❌ Should have been cache miss")
                return False
            
            # Create clips directory
            clips_dir = Path(tmpdir) / "clips"
            clips_dir.mkdir()
            
            # Wait to ensure newer mtime
            time.sleep(0.1)
            
            # Create fake clips
            clip1 = clips_dir / "clip_1_viral_test-123.mp4"
            clip1.write_text("fake clip")
            
            # Test cache hit
            result = await checker.check_existing_clips(
                task_id="test-123",
                video_path=str(video_path),
                min_clips=1
            )
            
            if result and len(result) >= 1:
                print("  ✅ Cache hit detected (1 clip found)")
            else:
                print("  ❌ Should have been cache hit")
                return False
            
            # Get stats
            stats = await checker.get_cache_stats()
            print(f"  ✅ Cache stats: {stats.get('total_clips', 0)} clips")
            
        print("\n✅ Cache checker tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Cache test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_prompts():
    """Test AI prompt generation."""
    print("\n💬 Testing AI Prompts...")
    print("-" * 50)
    
    try:
        from src.services.ai_prompts import (
            VIRAL_SCORER_SYSTEM_PROMPT,
            build_dynamic_user_prompt
        )
        
        # Test static prompt
        print("Test 1: Static system prompt")
        print(f"  Length: {len(VIRAL_SCORER_SYSTEM_PROMPT)} chars")
        print(f"  ✅ Static prompt defined")
        
        # Test dynamic prompt
        print("\nTest 2: Dynamic user prompt")
        prompt = build_dynamic_user_prompt(
            transcript="Test transcript",
            language="es",
            num_clips=3
        )
        print(f"  Length: {len(prompt)} chars")
        print(f"  Contains transcript: {'Test transcript' in prompt}")
        print(f"  ✅ Dynamic prompt generated")
        
        # Test with error context
        print("\nTest 3: Dynamic prompt with error")
        prompt_with_error = build_dynamic_user_prompt(
            transcript="Test",
            language="en",
            num_clips=2,
            previous_error="Duration too short"
        )
        
        if "Duration too short" in prompt_with_error:
            print("  ✅ Error context included")
        else:
            print("  ❌ Error context missing")
            return False
        
        print("\n✅ Prompt tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Prompt test failed: {e}")
        return False


async def main():
    """Run all diagnostic tests."""
    print("=" * 50)
    print("🧪 Week 1 Foundation - Diagnostic Tests")
    print("=" * 50)
    
    results = []
    
    # Run tests
    results.append(("Diagnostics Endpoint", await test_diagnostics()))
    results.append(("Pydantic Validation", await test_pydantic_validation()))
    results.append(("Cache Checker", await test_cache_checker()))
    results.append(("AI Prompts", await test_prompts()))
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Summary")
    print("=" * 50)
    
    passed = 0
    for name, result in results:
        icon = "✅" if result else "❌"
        print(f"{icon} {name}")
        if result:
            passed += 1
    
    print()
    print(f"Passed: {passed}/{len(results)}")
    print("=" * 50)
    
    return all(r for _, r in results)


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
