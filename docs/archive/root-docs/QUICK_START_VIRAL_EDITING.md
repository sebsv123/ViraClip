# Quick Start: Viral Video Editing

## ✅ System Status

**All features are ready to use!** Run this command to verify:

```powershell
docker exec viraclip-backend curl -s http://localhost:8000/health/creative-services | python -m json.tool
```

**Expected output:**
```json
{
  "status": "healthy",
  "services_ok": 9,
  "dependencies_ok": 6,
  "sfx_count": 7,
  "bgm_count": 10
}
```

---

## 🚀 Test with a Video

### Option 1: Via Frontend (Easiest)

1. Open http://localhost:3000
2. Upload a video (talking head works best)
3. In processing options, enable:
   - ✅ **Jump Cuts** (removes silence)
   - ✅ **Subtitles** (animated captions)
   - Platform: **TikTok**
4. Click "Process"
5. Watch the progress - you should see:
   - "Transcription" stage
   - "Scoring" stage
   - "Render" stage (with creative enhancements)

### Option 2: Via API (Direct Control)

```powershell
# Upload and process a video with all viral features enabled
$video = "path/to/your/video.mp4"

# Using curl (from inside Docker):
docker exec viraclip-backend curl -X POST http://localhost:8000/api/tasks \
  -F "video=@$video" \
  -F "target_platform=tiktok" \
  -F "caption_template=tiktok_viral" \
  -F "jump_cut=true" \
  -F "zoom_on_cuts=true" \
  -F "add_subtitles=true"
```

### Option 3: Test Script (Verify Each Feature)

Create a test file to verify each feature individually:

```python
# test_viral_features.py
import asyncio
from pathlib import Path

async def test_features():
    from src.services.cut_zoom_service import apply_jump_cuts_with_zoom
    from src.services.caption_service import CaptionService
    from src.services.creative_pipeline import get_creative_pipeline
    
    test_video = Path("/path/to/test.mp4")
    
    # 1. Test jump cuts with zoom
    result = await apply_jump_cuts_with_zoom(
        video_path=str(test_video),
        output_path="/tmp/test_jumpcut.mp4",
        min_silence_sec=0.3,
        zoom_on_cuts=True,
    )
    print(f"Jump cuts: {result}")
    
    # 2. Test caption styles
    styles = CaptionService.STYLES
    print(f"Available caption styles: {styles}")
    
    # 3. Test creative pipeline
    cp = get_creative_pipeline()
    print(f"Creative pipeline loaded: {cp}")

if __name__ == "__main__":
    asyncio.run(test_features())
```

Run inside Docker:
```powershell
docker exec viraclip-backend .venv/bin/python /app/test_viral_features.py
```

---

## 🎛️ Feature Configuration

### Enable All Viral Features (Maximum Quality)

```json
{
  "target_platform": "tiktok",
  "caption_template": "tiktok_viral",
  "jump_cut": true,
  "jump_cut_min_silence": 0.3,
  "zoom_on_cuts": true,
  "cut_zoom_factor": 1.08,
  "add_subtitles": true
}
```

### Conservative (Professional YouTube)

```json
{
  "target_platform": "youtube",
  "caption_template": "minimal",
  "jump_cut": true,
  "jump_cut_min_silence": 0.5,
  "zoom_on_cuts": false,
  "add_subtitles": true
}
```

### Moderate (Instagram Reels)

```json
{
  "target_platform": "reels",
  "caption_template": "highlight",
  "jump_cut": true,
  "jump_cut_min_silence": 0.4,
  "zoom_on_cuts": true,
  "cut_zoom_factor": 1.06,
  "add_subtitles": true
}
```

---

## 📊 What to Look For in Output

### Jump Cuts Working:
- Video is shorter than original (15-35% reduction typical)
- No awkward pauses or "um/uh" sounds
- Logs show: `[JumpCut+Zoom] X.Xs saved, Y cuts, Z zooms`

### Zoom Transitions Working:
- Quick zoom punches at cut points (subtle 8% scale)
- Smooth transitions, not jarring
- Logs show: `zoom_transitions_applied: N`

### Animated Captions Working:
- Captions appear word-by-word
- Karaoke style: words change color as spoken
- TikTok style: large bold text with pop effect
- Positioned above platform UI (not hidden)

### B-roll Working:
- Keyword-relevant footage overlays at 2-3 points
- Full-screen or corner overlay
- Logs show: `broll_overlays: N`

### Sound Effects Working:
- Whoosh sounds on transitions
- Background music faintly audible under speech
- Audio normalized (no clipping or too-quiet sections)
- Logs show: `sfx_injected: N, loudnorm_applied: true`

---

## 🐛 Troubleshooting

### Nothing is Happening

**Check worker logs:**
```powershell
docker logs viraclip-worker -f
```

Look for:
- ✅ "Starting worker for 3 functions"
- ✅ "Worker starting up..."
- ✅ "Whisper warm-up: loading model"
- ❌ Any Python import errors

### Jump Cuts Not Applied

**Verify config flag:**
```powershell
# Check task config
docker exec viraclip-backend curl http://localhost:8000/api/tasks/{task_id}
```

Look for `"jump_cut": true` in the response.

**Check if feature failed:**
```powershell
docker logs viraclip-worker | grep -i "jumpcut"
```

### Creative Pipeline Skipped

**Check health endpoint:**
```powershell
docker exec viraclip-backend curl http://localhost:8000/health/creative-services
```

If status is not "healthy", rebuild container:
```powershell
docker-compose build backend
docker-compose up -d backend worker worker-2
```

### Captions Not Rendering

**Verify subtitles enabled:**
- Frontend: Check "Add Subtitles" toggle
- API: Include `"add_subtitles": true` in request

**Check word timestamps exist:**
```powershell
docker logs viraclip-worker | grep -i "words_with_confidence"
```

Should show: `N words with confidence scores`

---

## 📝 Monitoring Progress

### Real-Time Progress (SSE)

```powershell
# Watch live progress events
curl -N http://localhost:8000/api/progress/{task_id}
```

Look for these stages:
1. `connected` → Task started
2. `analysis` → Transcribing audio
3. `transcription` → Generating word timestamps
4. `scoring` → Analyzing virality
5. `render` → Processing clips (creative pipeline runs here)
6. `creative` → Applying enhancements
7. `clip_ready` → Individual clips done
8. `done` → All complete

### Check Clip Metadata

```powershell
# Get clip details after processing
curl http://localhost:8000/api/tasks/{task_id}/clips/{clip_index}
```

Look for these fields in response:
```json
{
  "jump_cut_applied": true,
  "jump_cut_time_saved": 12.5,
  "zoom_transitions_applied": 8,
  "creative_enhanced": true,
  "viral_score": 78,
  "broll_overlays": 2,
  "sfx_injected": 5,
  "text_pops_applied": 3
}
```

---

## 🎯 Quick Verification Checklist

Before reporting issues, verify:

- [ ] Health check returns `"status": "healthy"`
- [ ] `services_ok: 9` and `dependencies_ok: 6`
- [ ] Audio assets: `sfx_count: 7, bgm_count: 10`
- [ ] Worker logs show no import errors
- [ ] Backend container rebuilt after dependency fixes
- [ ] Video uploaded successfully (check frontend or API response)
- [ ] Config flags set correctly (`jump_cut: true`, etc.)
- [ ] Logs show creative pipeline steps (1/8 through 8/8)

---

## 🔗 Additional Resources

- **Full Documentation:** `VIRAL_EDITING_FEATURES.md`
- **Health Check:** `GET /health/creative-services`
- **Creative API:** `GET /creative/{task_id}`
- **Logs:** `docker logs viraclip-worker -f`

---

## 💡 Pro Tips

1. **Test with short videos first** (30-60 seconds) - faster iteration
2. **Use talking head footage** - works best for jump cuts and captions
3. **Enable one feature at a time** if debugging issues
4. **Check logs immediately** if output looks wrong
5. **Try different caption styles** for your content type
6. **Adjust zoom intensity** based on video energy level

---

**Ready to test?** Upload a video with viral features enabled and check the output! 🚀
