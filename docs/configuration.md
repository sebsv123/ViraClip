# Configuration Reference

All configuration is driven by environment variables. Copy `.env.example` to `.env` and fill in the values you need.

---

## Minimum Required

```env
# Transcription (pick one)
ASSEMBLY_AI_API_KEY=your_key        # AssemblyAI (recommended)
# or use faster-whisper locally — no key needed

# LLM for scoring + creative pipeline (pick one)
LLM=google-gla:gemini-2.0-flash
GOOGLE_API_KEY=your_key

# or OpenAI
# LLM=openai:gpt-4o
# OPENAI_API_KEY=your_key

# or fully local (no API cost)
# LLM=ollama:qwen2.5:7b
# OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

---

## Full Reference

### Database & Cache

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://viraclip:viraclip_password@postgres:5432/viraclip` | PostgreSQL connection string |
| `REDIS_HOST` | `redis` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_PASSWORD` | — | Redis password (leave empty for local dev) |

### Authentication

| Variable | Default | Description |
|---|---|---|
| `BETTER_AUTH_SECRET` | **required** | Secret for better-auth session signing |
| `BACKEND_AUTH_SECRET` | **required** | Backend-to-backend auth secret |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret |

### LLM Providers

| Variable | Description |
|---|---|
| `LLM` | Active LLM in format `provider:model` (e.g. `google-gla:gemini-2.0-flash`) |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Google Gemini API key |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key |
| `GROQ_API_KEY` | Groq API key (used for fast viral scoring) |
| `OLLAMA_BASE_URL` | Local Ollama base URL |

### Transcription

| Variable | Description |
|---|---|
| `ASSEMBLY_AI_API_KEY` | AssemblyAI key for cloud transcription |
| `WHISPER_MODEL` | Local Whisper model size: `tiny`/`base`/`small`/`medium`/`large-v3` |
| `WHISPER_DEVICE` | `cuda` or `cpu` |
| `TRANSCRIPTION_PROVIDER` | `assemblyai` or `whisper` |

### B-roll

| Variable | Description |
|---|---|
| `PEXELS_API_KEY` | Pexels stock video API key |
| `PIXABAY_API_KEY` | Pixabay stock video API key |
| `STABILITY_API_KEY` | Stability AI for generative B-roll |
| `REPLICATE_API_TOKEN` | Replicate for generative B-roll |
| `COMFYUI_URL` | ComfyUI base URL (default: `http://comfyui:8188`) |
| `BROLL_PROVIDER` | `pexels` / `comfyui` / `stability` / `replicate` |

### Audio

| Variable | Description |
|---|---|
| `ELEVENLABS_API_KEY` | ElevenLabs for AI voice/SFX |
| `SUNO_API_KEY` | Suno for AI music generation |
| `BGM_VOLUME_DB` | Background music volume relative to voice (default: `-12`) |
| `TARGET_LUFS` | Loudness normalization target (default: `-14`) |

### Storage & CDN

| Variable | Description |
|---|---|
| `STORAGE_BACKEND` | `local` / `s3` / `r2` |
| `AWS_ACCESS_KEY_ID` | AWS / R2 access key |
| `AWS_SECRET_ACCESS_KEY` | AWS / R2 secret key |
| `AWS_S3_BUCKET` | S3 bucket name |
| `CLOUDFLARE_R2_ENDPOINT` | R2 endpoint URL |
| `CDN_BASE_URL` | Public CDN base URL for clip delivery |

### Publishing

| Variable | Description |
|---|---|
| `TIKTOK_CLIENT_KEY` | TikTok API client key |
| `TIKTOK_CLIENT_SECRET` | TikTok API client secret |
| `INSTAGRAM_APP_ID` | Meta Graph API app ID |
| `INSTAGRAM_APP_SECRET` | Meta Graph API app secret |
| `YOUTUBE_CLIENT_ID` | YouTube Data API v3 client ID |
| `YOUTUBE_CLIENT_SECRET` | YouTube Data API v3 client secret |

### Billing

| Variable | Description |
|---|---|
| `STRIPE_SECRET_KEY` | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook endpoint secret |
| `RESEND_API_KEY` | Resend API key for transactional emails |

### Feature Flags

| Variable | Default | Description |
|---|---|---|
| `SELF_HOST` | `false` | Disable billing + multi-tenant features for self-hosted installs |
| `ENABLE_COMFYUI` | `true` | Enable generative B-roll via ComfyUI |
| `ENABLE_BEAT_SYNC` | `true` | Enable beat-synced BGM |
| `ENABLE_A_B_VARIANTS` | `true` | Generate A/B clip variants |
| `MAX_CLIPS_PER_JOB` | `5` | Maximum clips generated per video |
| `MAX_CONCURRENT_RENDERS` | `3` | Parallel clip renders per worker |

---

For getting each API key: [`API_KEYS_SETUP.md`](../API_KEYS_SETUP.md)  
For production deployment: [`DEPLOY_GUIDE.md`](../DEPLOY_GUIDE.md)
