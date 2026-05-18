# short-video-maker (vendor copy)

Selective clone of [short-video-maker](https://github.com/gyoridavid/short-video-maker) by David Gyori.

This directory contains only the Pexels client and music selection logic
extracted from the original project, plus the LICENSE and this README.

## Original project

- Repository: https://github.com/gyoridavid/short-video-maker
- License: MIT (see LICENSE file)
- Purpose: Automated short-form video creation with TTS, captions, Pexels B-roll, and music.

## Extracted components

| File | Original path | Purpose |
|------|---------------|---------|
| `Pexels.ts` | `src/short-creator/libraries/Pexels.ts` | Pexels API client with retry, joker terms, duration/orientation filtering |
| `music.ts` | `src/short-creator/music.ts` | Music library with mood-tagged tracks |
| `types.ts` | `src/types/shorts.ts` | Type definitions (MusicMoodEnum, Video, Music, etc.) |
| `LICENSE` | `LICENSE` | MIT license |
| `README.md` | `README.md` | Original project README |
| `static/music/README.md` | `static/music/README.md` | Music library documentation |

## Usage in ViraClip

These files serve as reference/vendor code. ViraClip's own adapters
(`pexels_client.py`, `background_music_service.py`) are Python ports
inspired by this TypeScript codebase.
