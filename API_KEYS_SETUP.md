# ViraClip API Keys Setup Guide

This guide walks you through obtaining and configuring the required API keys for ViraClip's viral editing features.

---

## Required API Keys

### 1. AssemblyAI (REQUIRED)
**Purpose:** High-accuracy transcription (97%+ accuracy)

**Get Your Key:**
1. Visit: https://www.assemblyai.com/
2. Sign up for free account
3. Go to Dashboard → API Keys
4. Copy your API key

**Add to `.env`:**
```bash
ASSEMBLY_AI_API_KEY=your_assemblyai_key_here
```

**Free Tier:** 5 hours/month

---

### 2. LLM Provider (REQUIRED - Choose One)

ViraClip requires at least one LLM provider for virality analysis.

#### Option A: OpenAI (Recommended)
**Get Your Key:**
1. Visit: https://platform.openai.com/
2. Sign up and add payment method
3. Go to API Keys → Create new key
4. Copy your API key

**Add to `.env`:**
```bash
OPENAI_API_KEY=your_openai_key_here
LLM=openai:gpt-4
```

**Cost:** ~$0.01-0.05 per video

#### Option B: Anthropic Claude
**Get Your Key:**
1. Visit: https://console.anthropic.com/
2. Sign up and add payment method
3. Go to API Keys → Create key
4. Copy your API key

**Add to `.env`:**
```bash
ANTHROPIC_API_KEY=your_anthropic_key_here
LLM=anthropic:claude-3-sonnet-20240229
```

#### Option C: Google Gemini
**Get Your Key:**
1. Visit: https://makersuite.google.com/app/apikey
2. Sign in with Google account
3. Create API key
4. Copy your API key

**Add to `.env`:**
```bash
GOOGLE_API_KEY=your_google_key_here
LLM=google:gemini-pro
```

#### Option D: Ollama (Self-Hosted, Free)
**Setup:**
1. Install Ollama: https://ollama.ai/
2. Pull model: `ollama pull llama2`
3. Start server: `ollama serve`

**Add to `.env`:**
```bash
LLM=ollama:llama2
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

**Note:** Requires local GPU for good performance

---

## Optional API Keys (Enhanced Features)

### 3. Contextual Overlays (RECOMMENDED)

Enables the #1 viral feature: full-screen contextual overlays with speaker bubble.

#### Option A: Unsplash (Recommended)
**Purpose:** High-quality stock photos

**Get Your Key:**
1. Visit: https://unsplash.com/developers
2. Create account
3. Create new application
4. Copy Access Key

**Add to `.env`:**
```bash
UNSPLASH_ACCESS_KEY=your_unsplash_access_key_here
CONTEXTUAL_OVERLAYS_ENABLED=true
```

**Free Tier:** 50 requests/hour (plenty for most use cases)

#### Option B: Pexels
**Purpose:** Stock photos + videos

**Get Your Key:**
1. Visit: https://www.pexels.com/api/
2. Sign up
3. Generate API key
4. Copy API key

**Add to `.env`:**
```bash
PEXELS_API_KEY=your_pexels_key_here
CONTEXTUAL_OVERLAYS_ENABLED=true
```

**Free Tier:** Unlimited (rate-limited)

#### Both (Best Coverage)
```bash
UNSPLASH_ACCESS_KEY=your_unsplash_key
PEXELS_API_KEY=your_pexels_key
CONTEXTUAL_OVERLAYS_ENABLED=true
```

**Fallback:** If no API keys provided, system uses placeholder overlays (degraded experience)

---

### 4. Enhanced Tracking (OPTIONAL)

Enables SAM2-based multi-subject tracking (face, person, object).

**Requirements:**
- GPU with 8GB+ VRAM
- SAM2 models downloaded

**Setup:**
1. Download SAM2 models:
   ```bash
   mkdir -p /app/models/sam2
   # Download from Meta AI
   ```

**Add to `.env`:**
```bash
SAM2_ENABLED=true
TRACKING_MODE=auto  # auto | face | person | object
SAM2_MODELS_DIR=/app/models/sam2
```

**Note:** Falls back to MediaPipe FaceMesh if disabled (works great for face-only)

---

### 5. ElevenLabs (OPTIONAL)

Enables premium AI voiceover (alternative to OpenAI TTS).

**Get Your Key:**
1. Visit: https://elevenlabs.io/
2. Sign up
3. Go to Profile → API Keys
4. Copy API key

**Add to `.env`:**
```bash
ELEVENLABS_API_KEY=your_elevenlabs_key_here
```

**Free Tier:** 10,000 characters/month

---

### 6. Social Publishing (OPTIONAL)

Enables one-click publishing to TikTok, Instagram, YouTube.

#### TikTok
**Get Your Token:**
1. Visit: https://developers.tiktok.com/
2. Create app
3. Get access token

**Add to `.env`:**
```bash
TIKTOK_ACCESS_TOKEN=your_tiktok_token
```

#### Instagram
**Get Your Token:**
1. Visit: https://developers.facebook.com/
2. Create app with Instagram Graph API
3. Get access token and account ID

**Add to `.env`:**
```bash
INSTAGRAM_ACCESS_TOKEN=your_instagram_token
INSTAGRAM_ACCOUNT_ID=your_account_id
```

#### YouTube
**Get Your Token:**
1. Visit: https://console.cloud.google.com/
2. Enable YouTube Data API v3
3. Create OAuth 2.0 credentials

**Add to `.env`:**
```bash
YOUTUBE_ACCESS_TOKEN=your_youtube_token
```

---

## Complete .env Template

```bash
# ==========================================
# REQUIRED: Core Transcription
# ==========================================
ASSEMBLY_AI_API_KEY=your_assemblyai_key_here

# ==========================================
# REQUIRED: LLM Provider (choose one)
# ==========================================
# Option 1: OpenAI (recommended)
OPENAI_API_KEY=your_openai_key_here
LLM=openai:gpt-4

# Option 2: Anthropic
# ANTHROPIC_API_KEY=your_anthropic_key_here
# LLM=anthropic:claude-3-sonnet-20240229

# Option 3: Google
# GOOGLE_API_KEY=your_google_key_here
# LLM=google:gemini-pro

# Option 4: Ollama (self-hosted)
# LLM=ollama:llama2
# OLLAMA_BASE_URL=http://host.docker.internal:11434

# ==========================================
# RECOMMENDED: Contextual Overlays
# ==========================================
UNSPLASH_ACCESS_KEY=your_unsplash_key_here
PEXELS_API_KEY=your_pexels_key_here
CONTEXTUAL_OVERLAYS_ENABLED=true

# ==========================================
# OPTIONAL: Enhanced Features
# ==========================================
# Enhanced Tracking (SAM2)
SAM2_ENABLED=false
TRACKING_MODE=auto
SAM2_MODELS_DIR=/app/models/sam2

# Premium Voiceover
ELEVENLABS_API_KEY=your_elevenlabs_key_here

# Social Publishing
TIKTOK_ACCESS_TOKEN=your_tiktok_token
INSTAGRAM_ACCESS_TOKEN=your_instagram_token
INSTAGRAM_ACCOUNT_ID=your_account_id
YOUTUBE_ACCESS_TOKEN=your_youtube_token

# ==========================================
# Other Settings
# ==========================================
# Audio Library
AUDIO_LIBRARY_PATH=/app/assets/sounds

# Speed Control
SPEED_CONTROL_ENABLED=true

# Scene Detection
SCENE_DETECTION_ENABLED=true

# Audio Ducking
AUDIO_DUCKING_ENABLED=true

# Overlay Settings
MAX_OVERLAYS_PER_CLIP=8
OVERLAY_MIN_VIRALITY=60.0
OVERLAY_CACHE_DIR=/app/storage/overlay_cache
```

---

## Quick Setup Checklist

### Minimum Viable Setup (5 minutes)
- [x] Get AssemblyAI key (free 5 hours/month)
- [x] Get OpenAI key (or Anthropic/Google/Ollama)
- [x] Copy `.env.example` to `.env`
- [x] Add both keys to `.env`
- [x] Run `docker-compose up -d`

**Result:** Core clipping works, but overlays use placeholders

### Recommended Setup (10 minutes)
- [x] Minimum viable setup
- [x] Get Unsplash key (free, unlimited photos)
- [x] Get Pexels key (free, photos + videos)
- [x] Add overlay keys to `.env`
- [x] Restart: `docker-compose restart backend`

**Result:** Full viral editing with contextual overlays ✅

### Complete Setup (15 minutes)
- [x] Recommended setup
- [x] Get ElevenLabs key (premium voiceover)
- [x] Setup social publishing tokens
- [x] Download SAM2 models (if GPU available)
- [x] Restart: `docker-compose restart backend`

**Result:** All features unlocked 🚀

---

## Testing Your Setup

### 1. Test Transcription
```bash
# Check AssemblyAI key
curl -H "authorization: YOUR_ASSEMBLYAI_KEY" https://api.assemblyai.com/v2/upload
# Should return: {"upload_url": "..."}
```

### 2. Test LLM Provider
```bash
# OpenAI
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer YOUR_OPENAI_KEY"
# Should list models

# Anthropic
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: YOUR_ANTHROPIC_KEY" \
  -H "content-type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-3-sonnet-20240229","max_tokens":10,"messages":[{"role":"user","content":"Hi"}]}'
# Should return response
```

### 3. Test Overlays
```bash
# Unsplash
curl "https://api.unsplash.com/photos/random?client_id=YOUR_UNSPLASH_KEY"
# Should return photo data

# Pexels
curl "https://api.pexels.com/v1/search?query=ocean&per_page=1" \
  -H "Authorization: YOUR_PEXELS_KEY"
# Should return photo data
```

### 4. End-to-End Test
```bash
# Submit test task
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "source": {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    "contextual_overlays": true,
    "viral_template": "mrbeast"
  }'
```

---

## Troubleshooting

### "AssemblyAI authentication failed"
- ✅ Check key is correct in `.env`
- ✅ Verify no extra spaces in key
- ✅ Check free tier hasn't expired (5 hours/month)
- ✅ Restart backend: `docker-compose restart backend`

### "Contextual overlays falling back to placeholders"
- ✅ Check `UNSPLASH_ACCESS_KEY` or `PEXELS_API_KEY` set
- ✅ Check `CONTEXTUAL_OVERLAYS_ENABLED=true`
- ✅ Test API keys with curl commands above
- ✅ Check rate limits not exceeded

### "LLM provider error"
- ✅ Check correct LLM format: `openai:gpt-4` not `gpt-4`
- ✅ Verify API key is valid
- ✅ Check account has credits/payment method
- ✅ Try alternative provider (Ollama for testing)

---

## Cost Estimates

### Free Tier (Recommended for Testing)
- AssemblyAI: 5 hours/month FREE
- Unsplash: 50 requests/hour FREE
- Pexels: Unlimited FREE
- OpenAI: ~$5-10/month for 100-200 videos

**Total:** ~$5-10/month for 100-200 videos

### Production Tier
- AssemblyAI: $0.00025/second (~$15/hr)
- OpenAI GPT-4: $0.01-0.05 per video
- ElevenLabs: $5/month (30K characters)
- Unsplash Pro: Free or $9/month for commercial

**Total:** ~$20-50/month for 1000 videos

---

## Security Best Practices

1. ✅ **Never commit `.env` to Git** (already in `.gitignore`)
2. ✅ **Use environment variables** (not hardcoded keys)
3. ✅ **Rotate keys regularly** (every 3-6 months)
4. ✅ **Use separate keys** for dev/staging/production
5. ✅ **Monitor API usage** (set up billing alerts)
6. ✅ **Restrict API key permissions** (minimum required access)

---

## Next Steps

1. ✅ Get required API keys (AssemblyAI + LLM provider)
2. ✅ Get recommended keys (Unsplash + Pexels)
3. ✅ Copy `.env.example` to `.env`
4. ✅ Add all keys to `.env`
5. ✅ Run audio library expansion (optional)
6. ✅ Test with sample video
7. ✅ Monitor costs and usage

**You're ready to create viral videos! 🚀**
