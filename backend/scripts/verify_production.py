#!/usr/bin/env python
"""Verify ViraClip production configuration"""
import os


print("=" * 60)
print("ViraClip Production Configuration")
print("=" * 60)

# Check API keys
unsplash = os.environ.get("UNSPLASH_ACCESS_KEY", "")
pexels = os.environ.get("PEXELS_API_KEY", "")
groq = os.environ.get("GROQ_API_KEY", "")

print("\nAPI Keys:")
print(f"  Unsplash: {'YES' if unsplash else 'NO'}")
print(f"  Pexels: {'YES' if pexels else 'NO'}")
print(f"  Groq LLM: {'YES' if groq else 'NO'}")

# Check feature flags
overlays = os.environ.get("CONTEXTUAL_OVERLAYS_ENABLED", "false").lower() == "true"
speed = os.environ.get("SPEED_CONTROL_ENABLED", "false").lower() == "true"
scene = os.environ.get("SCENE_DETECTION_ENABLED", "false").lower() == "true"
ducking = os.environ.get("AUDIO_DUCKING_ENABLED", "false").lower() == "true"

print("\nViral Features:")
print(f"  Contextual Overlays: {'ENABLED' if overlays else 'disabled'}")
print(f"  Speed Control: {'ENABLED' if speed else 'disabled'}")
print(f"  Scene Detection: {'ENABLED' if scene else 'disabled'}")
print(f"  Audio Ducking: {'ENABLED' if ducking else 'disabled'}")

# Check Whisper model
whisper_size = os.environ.get("WHISPER_MODEL_SIZE", "tiny")
print(f"\nWhisper Model: {whisper_size}")

print("\n" + "=" * 60)
if unsplash and pexels:
    print("Status: PRODUCTION READY - High quality overlays")
elif overlays:
    print("Status: PRODUCTION READY - Gradient fallback overlays")
else:
    print("Status: Ready (offline mode)")
print("=" * 60)
