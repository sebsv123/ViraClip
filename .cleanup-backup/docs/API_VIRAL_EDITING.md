# Viral Editing API Documentation

## 🎯 Overview

All viral editing features are now **fully accessible via API** and will execute during video processing.

---

## 📡 API Endpoint

### POST `/api/tasks`

**Request Body (JSON):**

```json
{
  "source": {
    "url": "https://youtube.com/watch?v=VIDEO_ID"
  },
  "target_platform": "tiktok",
  "caption_template": "tiktok_viral",
  "add_subtitles": true,
  
  // 🔥 VIRAL EDITING FEATURES (NEW)
  "jump_cut": true,
  "jump_cut_min_silence": 0.3,
  "zoom_on_cuts": true,
  "cut_zoom_factor": 1.08,
  "denoise_audio": false
}
```

---

## 🎛️ Parameters Reference

### Core Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source.url` | string | **required** | Video URL or file path |
| `target_platform` | string | `"all"` | `tiktok`, `reels`, `shorts`, or `all` |
| `caption_template` | string | `"default"` | Caption style (see below) |
| `add_subtitles` | boolean | `true` | Enable/disable captions |
| `num_clips` | integer | `6` | Number of clips to generate (3-10) |

### 🔥 Viral Editing Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `jump_cut` | boolean | `false` | **Enable jump cuts + zoom transitions** |
| `jump_cut_min_silence` | float | `0.3` | Minimum silence gap to remove (seconds) |
| `zoom_on_cuts` | boolean | `true` | Add zoom punch at every cut |
| `cut_zoom_factor` | float | `1.08` | Zoom intensity (1.0 = none, 1.15 = 15%) |
| `denoise_audio` | boolean | `false` | Apply noise reduction + voice isolation |

### Caption Styles

- `tiktok_viral` → Bold, large, drop shadow
- `reels_drama` → Highlight box behind words
- `youtube_shorts` → Karaoke word-by-word
- `minimal` → Clean, professional
- `default` → Auto-select based on platform

---

## 🚀 Usage Examples

### 1. Maximum Viral Energy (TikTok)

```json
{
  "source": {"url": "https://youtube.com/watch?v=VIDEO_ID"},
  "target_platform": "tiktok",
  "caption_template": "tiktok_viral",
  "add_subtitles": true,
  "jump_cut": true,
  "jump_cut_min_silence": 0.3,
  "zoom_on_cuts": true,
  "cut_zoom_factor": 1.08,
  "denoise_audio": false
}
```

**Result:**
- Aggressive 0.3s silence removal
- Zoom punch at every cut (8%)
- Large bold animated captions
- Professional audio normalization
- B-roll overlays on keywords
- Background music + SFX

---

### 2. Clean Professional (YouTube Shorts)

```json
{
  "source": {"url": "https://youtube.com/watch?v=VIDEO_ID"},
  "target_platform": "shorts",
  "caption_template": "minimal",
  "add_subtitles": true,
  "jump_cut": true,
  "jump_cut_min_silence": 0.5,
  "zoom_on_cuts": false,
  "denoise_audio": true
}
```

**Result:**
- Moderate 0.5s cuts (less aggressive)
- No zoom transitions
- Clean minimal captions
- Noise reduction enabled
- Professional finish

---

### 3. Instagram Reels (Balanced)

```json
{
  "source": {"url": "https://youtube.com/watch?v=VIDEO_ID"},
  "target_platform": "reels",
  "caption_template": "reels_drama",
  "add_subtitles": true,
  "jump_cut": true,
  "jump_cut_min_silence": 0.4,
  "zoom_on_cuts": true,
  "cut_zoom_factor": 1.06,
  "denoise_audio": false
}
```

**Result:**
- Balanced 0.4s cuts
- Subtle 6% zoom
- Highlight-style captions
- Polished aesthetic

---

### 4. No Viral Editing (Classic Mode)

```json
{
  "source": {"url": "https://youtube.com/watch?v=VIDEO_ID"},
  "target_platform": "all",
  "caption_template": "default",
  "add_subtitles": true,
  "jump_cut": false,
  "denoise_audio": false
}
```

**Result:**
- No cuts or zooms
- Standard captions only
- Original pacing preserved

---

## 🎯 Parameter Tuning Guide

### Jump Cut Aggressiveness

| `jump_cut_min_silence` | Style | Use Case |
|------------------------|-------|----------|
| `0.2` - `0.3` | **Ultra aggressive** | TikTok, viral shorts, fast content |
| `0.4` - `0.5` | **Moderate** | YouTube, professional content |
| `0.6` - `0.8` | **Conservative** | Educational, interviews |

### Zoom Intensity

| `cut_zoom_factor` | Effect | Use Case |
|-------------------|--------|----------|
| `1.04` - `1.06` | **Subtle** | Professional, clean look |
| `1.08` | **Standard** | Balanced viral energy (recommended) |
| `1.10` - `1.15` | **Aggressive** | Maximum attention grab |

---

## 📊 Response Format

**Success Response (202 Accepted):**

```json
{
  "task_id": "abc123...",
  "status": "queued",
  "message": "Task created successfully"
}
```

**Monitor Progress:**

```
GET /api/progress/{task_id}

Server-Sent Events stream:
event: progress
data: {"task_id": "abc123", "progress": 45, "message": "Rendering clips..."}

event: clip_ready
data: {"clip_index": 0, "total": 6, "clip_data": {...}}
```

**Get Results:**

```
GET /api/tasks/{task_id}

Response:
{
  "id": "abc123",
  "status": "completed",
  "clips": [
    {
      "id": "clip_1",
      "path": "/uploads/clips/clip_1.mp4",
      "duration": 58.2,
      "jump_cut_applied": true,
      "jump_cut_time_saved": 12.5,
      "zoom_transitions_applied": 8,
      "creative_enhanced": true,
      "viral_score": 78,
      "broll_overlays": 2,
      "sfx_injected": 5
    }
  ]
}
```

---

## 🔍 Clip Metadata Fields

When `jump_cut: true`, each clip includes:

```json
{
  "jump_cut_applied": true,
  "jump_cut_time_saved": 12.5,
  "jump_cut_fillers_removed": 8,
  "jump_cut_silences_removed": 15,
  "zoom_transitions_applied": 8,
  "cut_zoom_enabled": true
}
```

When `denoise_audio: true`:

```json
{
  "audio_denoised": true,
  "audio_lufs_before": -18.5,
  "audio_lufs_after": -14.0
}
```

Creative pipeline (always runs):

```json
{
  "creative_enhanced": true,
  "viral_score": 78,
  "hook_score": 82,
  "preset_used": "tiktok_viral",
  "zoom_punch_applied": true,
  "broll_overlays": 2,
  "sfx_injected": 5,
  "loudnorm_applied": true,
  "qa_passed": true
}
```

---

## 🐛 Troubleshooting

### Issue: Jump cuts not applied

**Check response metadata:**
```json
{
  "jump_cut_applied": false
}
```

**Possible causes:**
1. `jump_cut: false` in request (default is `false`)
2. No silence gaps detected
3. Video too short (<15s)
4. Error in processing (check logs)

**Fix:**
```json
{
  "jump_cut": true  // Must be explicitly enabled
}
```

### Issue: Zoom transitions missing

**Check:**
```json
{
  "zoom_transitions_applied": 0,
  "cut_zoom_enabled": false
}
```

**Causes:**
- `zoom_on_cuts: false`
- No cut points detected
- Video processing error

### Issue: No metadata fields

**Cause:** Old request before viral editing was exposed

**Fix:** Make new request with viral editing parameters

---

## 💡 Best Practices

### 1. Platform-Specific Recommendations

**TikTok:**
```json
{
  "target_platform": "tiktok",
  "jump_cut": true,
  "jump_cut_min_silence": 0.3,
  "zoom_on_cuts": true,
  "cut_zoom_factor": 1.08
}
```

**YouTube Shorts:**
```json
{
  "target_platform": "shorts",
  "jump_cut": true,
  "jump_cut_min_silence": 0.5,
  "zoom_on_cuts": false
}
```

**Instagram Reels:**
```json
{
  "target_platform": "reels",
  "jump_cut": true,
  "jump_cut_min_silence": 0.4,
  "zoom_on_cuts": true,
  "cut_zoom_factor": 1.06
}
```

### 2. Content-Type Recommendations

**Educational/Tutorial:**
- `jump_cut_min_silence`: 0.6-0.8
- `zoom_on_cuts`: false
- `caption_template`: "minimal"

**Entertainment/Viral:**
- `jump_cut_min_silence`: 0.3
- `zoom_on_cuts`: true
- `caption_template`: "tiktok_viral"

**Professional/Business:**
- `jump_cut_min_silence`: 0.5
- `zoom_on_cuts`: false
- `denoise_audio`: true

---

## 📝 Example cURL Commands

### Windows PowerShell

```powershell
$body = @{
    source = @{ url = "https://youtube.com/watch?v=VIDEO_ID" }
    target_platform = "tiktok"
    jump_cut = $true
    jump_cut_min_silence = 0.3
    zoom_on_cuts = $true
    cut_zoom_factor = 1.08
    add_subtitles = $true
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/tasks" `
    -Method POST `
    -ContentType "application/json" `
    -Body $body `
    -Headers @{ Authorization = "Bearer YOUR_TOKEN" }
```

### Using Docker exec + curl

```powershell
docker exec viraclip-backend curl -X POST http://localhost:8000/api/tasks `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer YOUR_TOKEN" `
  -d '{
    "source": {"url": "https://youtube.com/watch?v=VIDEO_ID"},
    "jump_cut": true,
    "jump_cut_min_silence": 0.3,
    "zoom_on_cuts": true,
    "cut_zoom_factor": 1.08,
    "add_subtitles": true,
    "target_platform": "tiktok"
  }'
```

---

## 🔗 Related Documentation

- **VIRAL_EDITING_FEATURES.md** - Complete technical documentation
- **QUICK_START_VIRAL_EDITING.md** - Testing guide
- **TEST_VIRAL_EDITING.md** - Step-by-step verification

---

## ⚡ Performance Notes

### Processing Time Impact

| Feature | Time Impact | Worth It? |
|---------|-------------|-----------|
| Jump cuts | +5-15s per clip | ✅ Yes (saves viewer time) |
| Zoom transitions | +3-8s per clip | ✅ Yes (adds energy) |
| Audio denoise | +10-20s per clip | ⚠️ Only if noisy |
| Creative pipeline | +15-30s per clip | ✅ Yes (full enhancement) |

### Recommended Settings for Speed

```json
{
  "jump_cut": true,           // Fast
  "zoom_on_cuts": true,       // Fast
  "denoise_audio": false,     // Skip if not needed
  "add_subtitles": true       // Standard speed
}
```

---

**All features are now production-ready and accessible via API!** 🚀
