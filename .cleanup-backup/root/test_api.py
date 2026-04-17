#!/usr/bin/env python3
"""Quick API test - submit video processing task"""
import requests
import json
import time

BASE_URL = "http://localhost:8000"

# Test 1: Health check
print("=" * 60)
print("1. Testing Backend Health...")
print("=" * 60)
response = requests.get(f"{BASE_URL}/health")
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}\n")

# Test 2: Submit video processing task
print("=" * 60)
print("2. Submitting Video Processing Task...")
print("=" * 60)

task_payload = {
    "video_url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "mode": "fast",
    "max_clips": 2
}

print(f"Payload: {json.dumps(task_payload, indent=2)}")
print("\nSubmitting task...")

try:
    response = requests.post(
        f"{BASE_URL}/api/tasks",
        json=task_payload,
        timeout=30
    )
    print(f"\nStatus Code: {response.status_code}")
    
    if response.status_code in [200, 201]:
        result = response.json()
        print(f"✅ Task Created Successfully!")
        print(f"\nTask ID: {result.get('task_id') or result.get('id')}")
        print(f"\nFull Response:")
        print(json.dumps(result, indent=2))
        
        # Save task ID for monitoring
        task_id = result.get('task_id') or result.get('id')
        if task_id:
            with open('current_task_id.txt', 'w') as f:
                f.write(str(task_id))
            print(f"\n✅ Task ID saved to current_task_id.txt")
            print(f"\nMonitor progress with:")
            print(f"  curl http://localhost:8000/api/tasks/{task_id}")
    else:
        print(f"❌ Error: {response.status_code}")
        print(f"Response: {response.text}")
        
except Exception as e:
    print(f"❌ Exception: {e}")

print("\n" + "=" * 60)
