#!/usr/bin/env python
"""Test API keys for ViraClip production setup"""
import os
import asyncio
import httpx


async def test_api_keys():
    """Test Unsplash and Pexels API keys"""
    print("=" * 60)
    print("ViraClip API Key Verification")
    print("=" * 60)
    
    client = httpx.AsyncClient(timeout=10.0)
    
    # Test Unsplash
    unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    if unsplash_key:
        try:
            response = await client.get(
                "https://api.unsplash.com/photos/random",
                params={"client_id": unsplash_key, "query": "money", "count": 1}
            )
            if response.status_code == 200:
                print("Unsplash: OK (200)")
            else:
                print(f"Unsplash: FAILED ({response.status_code})")
                print(f"  Error: {response.text[:200]}")
        except Exception as e:
            print(f"Unsplash: ERROR - {e}")
    else:
        print("Unsplash: NO API KEY")
    
    # Test Pexels
    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    if pexels_key:
        try:
            response = await client.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": pexels_key},
                params={"query": "money", "per_page": 1}
            )
            if response.status_code == 200:
                print("Pexels: OK (200)")
            else:
                print(f"Pexels: FAILED ({response.status_code})")
                print(f"  Error: {response.text[:200]}")
        except Exception as e:
            print(f"Pexels: ERROR - {e}")
    else:
        print("Pexels: NO API KEY")
    
    await client.aclose()
    
    print("=" * 60)
    if unsplash_key and pexels_key:
        print("Both API keys configured!")
        print("Contextual overlays: HIGH QUALITY (real photos/videos)")
    else:
        print("Using fallback overlays (gradients + emojis)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_api_keys())
