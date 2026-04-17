# Test Viral Editing - Step by Step

## ✅ Pre-flight Check (30 seconds)

Run the automated verification:
```powershell
docker exec viraclip-backend .venv/bin/python /app/scripts/verify_viral_features.py
```

**Expected:** `✅ ALL SYSTEMS OPERATIONAL - Ready for video processing!`

---

## 🎬 Test Option 1: Upload via Frontend (Easiest - 2 minutes)

### Step 1: Open Frontend
```powershell
# Make sure frontend is running
docker-compose ps frontend

# If not, start it
docker-compose up -d frontend
```

Navigate to: http://localhost:3000

### Step 2: Upload Video
- Click "Upload Video"
- Choose a **30-60 second talking head video** (works best)
- Wait for upload to complete

### Step 3: Configure Settings
Check these options:
- ✅ **Jump Cuts** - Enable
- ✅ **Add Subtitles** - Enable  
- Platform: **TikTok**
- (Other settings can stay default)

### Step 4: Process & Monitor
1. Click "Process Video"
2. Watch real-time progress (SSE events)
3. Wait 2-5 minutes depending on video length

### Step 5: Verify Output
Download the processed video and check:
- ❓ Is video shorter than original?
- ❓ Are there zoom punches at cuts?
- ❓ Do captions animate word-by-word?
- ❓ Can you hear background music faintly?

---

## 🔧 Test Option 2: Direct API Call (Advanced - 5 minutes)

### Step 1: Prepare Test Video
```powershell
# Example: download a sample video
# Or use your own video file
$testVideo = "C:\path\to\your\test_video.mp4"
```

### Step 2: Upload & Create Task
```powershell
# Copy video into container
docker cp $testVideo viraclip-backend:/tmp/test.mp4

# Create task via curl inside container
docker exec viraclip-backend bash -c @"
curl -X POST http://localhost:8000/api/tasks \
  -F 'file=@/tmp/test.mp4' \
  -F 'target_platform=tiktok' \
  -F 'jump_cut=true' \
  -F 'add_subtitles=true' \
  -F 'caption_template=tiktok_viral'
"@
```

### Step 3: Get Task ID from Response
```json
{
  "task_id": "abc123...",
  "status": "queued"
}
```

### Step 4: Monitor Progress
```powershell
$taskId = "abc123..."  # Replace with actual task ID

# Watch progress in real-time
docker exec viraclip-backend curl -N http://localhost:8000/api/progress/$taskId
```

### Step 5: Check Task Status
```powershell
# Get task details
docker exec viraclip-backend curl http://localhost:8000/api/tasks/$taskId

# Get clip metadata
docker exec viraclip-backend curl http://localhost:8000/api/tasks/$taskId/clips/0
```

Look for these fields in clip metadata:
```json
{
  "jump_cut_applied": true,
  "jump_cut_time_saved": 15.3,
  "zoom_transitions_applied": 12,
  "creative_enhanced": true,
  "viral_score": 78,
  "broll_overlays": 2,
  "sfx_injected": 5,
  "text_pops_applied": 3,
  "caption_style": "tiktok"
}
```

---

## 📊 Test Option 3: Check Logs (Debug - 1 minute)

### Watch Worker Processing in Real-Time
```powershell
# Open worker logs
docker logs viraclip-worker -f
```

### What to Look For (in order):

**1. Task Received:**
```
[Worker] Processing task abc123...
```

**2. Transcription:**
```
[Whisper] Transcribing audio...
N words with confidence scores
```

**3. Creative Pipeline (This is the important part!):**
```
[Creative] Starting 8-step enhancement pipeline
[Creative] Step 1/8: Multimodal timeline...
[Creative] ✓ Step 1/8: 15 timeline events
[Creative] Step 2/8: Virality scoring...
[Creative] ✓ Step 2/8: viral_score=78
[Creative] Step 5/8: B-roll overlay...
[Creative] ✓ Step 5/8: B-roll: 2 overlays applied
[Creative] Step 6/8: Video effects (zoom + grade)...
[Creative] ✓ Step 6/8: VFX: zoom_punch=True grade=True
[Creative] Step 7/8: Audio mastering (loudnorm + SFX)...
[Creative] ✓ Step 7/8: Audio: 5 SFX injected
```

**4. Jump Cuts + Zoom:**
```
[JumpCut+Zoom] 15.3s saved, 12 cuts, 12 zooms, 5 fillers, 8 silences
```

**5. Caption Rendering:**
```
Burning ASS captions (125 words)...
CaptionService: style=tiktok, platform=tiktok
```

**6. Completion:**
```
[Worker] Task abc123 completed successfully
```

### Red Flags (What NOT to See):
```
❌ "Creative pipeline import failed"
❌ "Creative pipeline FAILED"
❌ "Module not found"
❌ "Jump-cut+zoom service failed"
❌ "CaptionService failed"
```

If you see any red flags, check health:
```powershell
docker exec viraclip-backend curl http://localhost:8000/health/creative-services
```

---

## 🎯 Success Criteria Checklist

After processing a test video, verify:

### Visual Changes:
- [ ] Video is noticeably shorter (15-35% typical)
- [ ] Zoom transitions visible at cuts (subtle 8% scale)
- [ ] Captions animate word-by-word
- [ ] Captions are large, bold, and positioned above UI
- [ ] B-roll footage overlays appear (if keywords detected)

### Audio Changes:
- [ ] Silence gaps removed (no awkward pauses)
- [ ] Filler words gone (um, uh, like)
- [ ] Background music faintly audible under speech
- [ ] Whoosh/impact sounds on transitions (subtle)
- [ ] Overall audio normalized (consistent volume)

### Metadata Verification:
```powershell
# Check clip has viral editing applied
docker exec viraclip-backend curl http://localhost:8000/api/tasks/$taskId/clips/0 | python -m json.tool
```

Look for:
- [ ] `"jump_cut_applied": true`
- [ ] `"jump_cut_time_saved": > 0`
- [ ] `"zoom_transitions_applied": > 0`
- [ ] `"creative_enhanced": true`
- [ ] `"viral_score": 50-100`
- [ ] `"sfx_injected": > 0`

---

## 🐛 Troubleshooting Quick Reference

### Issue: Nothing Happens After Upload

**Check 1: Worker Running?**
```powershell
docker-compose ps worker
# Should show "Up"
```

**Check 2: Task Created?**
```powershell
docker logs viraclip-backend | grep "POST /api/tasks"
# Should show recent upload
```

**Check 3: Worker Processing?**
```powershell
docker logs viraclip-worker | tail -50
# Should show task processing
```

### Issue: Creative Pipeline Skipped

**Check health:**
```powershell
docker exec viraclip-backend curl http://localhost:8000/health/creative-services
```

If not healthy, rebuild:
```powershell
docker-compose build backend
docker-compose up -d backend worker worker-2
```

### Issue: Jump Cuts Not Applied

**Check logs for:**
```powershell
docker logs viraclip-worker | grep -i "jumpcut"
```

**Verify flag set:**
```powershell
# In task config, should have:
"jump_cut": true
```

### Issue: Captions Not Visible

**Check:**
1. `add_subtitles: true` in request
2. Whisper transcription succeeded
3. Word timestamps exist in clip metadata

**Verify:**
```powershell
docker logs viraclip-worker | grep "words_with_confidence"
# Should show: "N words with confidence scores"
```

---

## 📈 Performance Benchmarks

### Expected Processing Times

**30-second video:**
- Transcription: ~15s
- Creative pipeline: ~20s
- Jump cuts + zoom: ~10s
- Caption rendering: ~5s
- **Total: ~50 seconds**

**60-second video:**
- Transcription: ~25s
- Creative pipeline: ~35s
- Jump cuts + zoom: ~15s
- Caption rendering: ~8s
- **Total: ~90 seconds**

### Resource Usage

Normal processing should use:
- CPU: 50-80% (bursts to 100% during FFmpeg)
- Memory: 2-4 GB
- Disk: +500MB temp files (auto-cleaned)

---

## 💡 Test Video Recommendations

### Best Test Videos (Fastest Results):
1. **Talking head** - 30-60 seconds
2. **Tutorial/educational** - lots of pauses to remove
3. **Interview/podcast clip** - natural conversation flow
4. **Product review** - clear speech with emphasis words

### Avoid for First Test:
- Music videos (no speech)
- Action scenes (no clear pauses)
- Multiple speakers (complex transcription)
- Very short clips <15s (not enough content)

---

## 🎓 What "Good Output" Looks Like

### Jump Cuts Working:
- Natural conversation flow
- No awkward silences
- Fast-paced (TikTok style)
- "um" and "uh" removed
- Time saved: 15-35%

### Zoom Transitions Working:
- Subtle scale effect at cuts
- Not jarring or nauseating
- Adds energy without distraction
- ~8% zoom (barely noticeable but impactful)

### Captions Working:
- Large bold text
- Changes color/highlights as words are spoken
- Positioned above platform UI
- Easy to read
- Synced perfectly with audio

### Audio Working:
- Consistent volume throughout
- Faint background music
- Subtle transition sounds
- No clipping or distortion
- Professional polish

---

## 🚀 Quick Commands Cheat Sheet

```powershell
# Verify system ready
docker exec viraclip-backend .venv/bin/python /app/scripts/verify_viral_features.py

# Check health
docker exec viraclip-backend curl http://localhost:8000/health/creative-services

# Watch worker logs
docker logs viraclip-worker -f

# Check task status
docker exec viraclip-backend curl http://localhost:8000/api/tasks/{task_id}

# Get clip metadata
docker exec viraclip-backend curl http://localhost:8000/api/tasks/{task_id}/clips/0

# Restart if needed
docker-compose restart backend worker worker-2
```

---

**Ready to test?** Pick Option 1 (frontend) for easiest testing, or Option 2 (API) for more control! 🎬
