"""
Test Image Providers Script

Tests all available image generation providers to verify:
1. API keys are configured correctly
2. Providers can generate images
3. Fallback chain works properly
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.google_imagen_service import get_imagen_service
from src.services.replicate_service import get_replicate_service
from src.services.stability_service import get_stability_service
from src.services.image_gen_service import ImageGenService
from src.services.overlay_content_source import OverlayContentSource


async def test_google_imagen():
    """Test Google Imagen 3."""
    print("\n" + "="*60)
    print("Testing Google Imagen 3")
    print("="*60)
    
    service = get_imagen_service()
    
    # Check availability
    available = await service.is_available()
    print(f"Available: {available}")
    
    if not available:
        print("❌ GOOGLE_API_KEY not configured")
        return False
    
    # Test generation
    try:
        prompt = "A serene mountain landscape at sunset"
        print(f"Generating: {prompt}")
        
        result = await service.generate_image(prompt, aspect_ratio="9:16")
        
        if result and Path(result).exists():
            print(f"✅ SUCCESS: Generated image at {result}")
            print(f"   Size: {Path(result).stat().st_size / 1024:.1f} KB")
            return True
        else:
            print("❌ FAILED: No image generated")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


async def test_replicate():
    """Test Replicate Flux.1."""
    print("\n" + "="*60)
    print("Testing Replicate Flux.1")
    print("="*60)
    
    service = get_replicate_service()
    
    # Check availability
    available = await service.is_available()
    print(f"Available: {available}")
    
    if not available:
        print("❌ REPLICATE_API_TOKEN not configured")
        return False
    
    # Test generation
    try:
        prompt = "A modern cityscape with neon lights"
        print(f"Generating: {prompt}")
        
        result = await service.generate_image(prompt, aspect_ratio="9:16")
        
        if result and Path(result).exists():
            print(f"✅ SUCCESS: Generated image at {result}")
            print(f"   Size: {Path(result).stat().st_size / 1024:.1f} KB")
            return True
        else:
            print("❌ FAILED: No image generated")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


async def test_stability():
    """Test Stability AI SDXL."""
    print("\n" + "="*60)
    print("Testing Stability AI SDXL")
    print("="*60)
    
    service = get_stability_service()
    
    # Check availability
    available = await service.is_available()
    print(f"Available: {available}")
    
    if not available:
        print("❌ STABILITY_API_KEY not configured")
        return False
    
    # Test generation
    try:
        prompt = "A futuristic robot in a cyberpunk setting"
        print(f"Generating: {prompt}")
        
        result = await service.generate_image(prompt, aspect_ratio="9:16")
        
        if result and Path(result).exists():
            print(f"✅ SUCCESS: Generated image at {result}")
            print(f"   Size: {Path(result).stat().st_size / 1024:.1f} KB")
            return True
        else:
            print("❌ FAILED: No image generated")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


async def test_dalle():
    """Test DALL-E 3."""
    print("\n" + "="*60)
    print("Testing DALL-E 3")
    print("="*60)
    
    service = ImageGenService(provider="dalle")
    
    # Check API key
    if not service.config.openai_api_key:
        print("❌ OPENAI_API_KEY not configured")
        return False
    
    print("Available: True")
    
    # Test generation
    try:
        prompt = "A peaceful zen garden with cherry blossoms"
        print(f"Generating: {prompt}")
        
        result = await service.generate_image(prompt, aspect_ratio="9:16")
        
        if result and Path(result).exists():
            print(f"✅ SUCCESS: Generated image at {result}")
            print(f"   Size: {Path(result).stat().st_size / 1024:.1f} KB")
            return True
        else:
            print("❌ FAILED: No image generated")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


async def test_auto_fallback():
    """Test auto-fallback in ImageGenService."""
    print("\n" + "="*60)
    print("Testing Auto-Fallback Chain")
    print("="*60)
    
    service = ImageGenService(provider="auto")
    
    print(f"Provider order: {service.provider_order}")
    
    try:
        prompt = "A tropical beach at golden hour"
        print(f"Generating: {prompt}")
        
        result = await service.generate_image(prompt, aspect_ratio="9:16")
        
        if result and Path(result).exists():
            print(f"✅ SUCCESS: Auto-fallback generated image at {result}")
            print(f"   Size: {Path(result).stat().st_size / 1024:.1f} KB")
            return True
        else:
            print("❌ FAILED: No image generated by any provider")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


async def test_overlay_content_source():
    """Test full OverlayContentSource with multi-provider."""
    print("\n" + "="*60)
    print("Testing OverlayContentSource (Full Chain)")
    print("="*60)
    
    source = OverlayContentSource()
    
    try:
        keyword = "success"
        print(f"Getting content for keyword: {keyword}")
        
        asset = await source.get_content(keyword, category="business", prefer_video=False)
        
        if asset:
            print(f"✅ SUCCESS: Got asset from source '{asset.source}'")
            print(f"   Path: {asset.path}")
            print(f"   Type: {'Video' if asset.is_video else 'Image'}")
            return True
        else:
            print("❌ FAILED: No asset retrieved")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


async def main():
    """Run all tests."""
    print("\n" + "#"*60)
    print("# ViraClip Image Providers Test Suite")
    print("#"*60)
    
    results = {}
    
    # Test individual providers
    results["Google Imagen"] = await test_google_imagen()
    results["Replicate"] = await test_replicate()
    results["Stability AI"] = await test_stability()
    results["DALL-E 3"] = await test_dalle()
    
    # Test auto-fallback
    results["Auto-Fallback"] = await test_auto_fallback()
    
    # Test full overlay source
    results["Overlay Source"] = await test_overlay_content_source()
    
    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for provider, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {provider}")
    
    passed = sum(results.values())
    total = len(results)
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
    elif passed > 0:
        print(f"\n⚠️ PARTIAL SUCCESS: {passed}/{total} providers working")
    else:
        print("\n❌ ALL TESTS FAILED - Check your API keys")
    
    return passed > 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
