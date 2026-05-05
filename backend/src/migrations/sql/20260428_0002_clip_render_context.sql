-- Persist the full render context per clip so the Suggestion Studio applicator
-- can reconstruct the original render call (segment dict, source video path,
-- task config) when re-rendering with a subset of approved suggestions.

ALTER TABLE generated_clips
    ADD COLUMN IF NOT EXISTS render_context JSONB;
