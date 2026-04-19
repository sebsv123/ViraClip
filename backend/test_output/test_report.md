# ViraClip Integration Test Report
**Date**: 2026-04-18 10:51:50 UTC
**Input video**: https://youtu.be/3wgwaxIfUJQ
**Status**: FAILED (FATAL)

## Environment
- Python version: 3.14.4
- FFmpeg version: ffmpeg version n8.1 Copyright (c) 2000-2026 the FFmpeg developers
- Redis: redis Python package not installed
- Backend startup: Backend OK (HTTP 200)

## Pipeline Results
- Task ID: None
- Processing time: 0.4s
- Clips generated: 0

## Clips Output
| Clip | Duration | Size | Valid MP4 | Subtitles |
|------|----------|------|-----------|-----------|

## Errors Found
### FATAL (pipeline stopped here)
- **2026-04-18T10:51:50.040159+00:00**: API returned error status: HTTP 500
Response: {"detail":"An internal server error occurred. Contact support with the trace ID.","trace_id":"-"}

### NON-FATAL (warnings / degraded features)
- **2026-04-18T10:51:50.003506+00:00**: Redis check failed: redis Python package not installed

## Missing Configuration
- Redis Python package (pip install redis)
