# VPI Baseline Change Policy

This policy applies after `v0.4.0-vpi-production-baseline`.

## Observation Period

- Do not add new features during the next real outputs.
- Only fix reproducible blockers.
- Keep selection, SFX, B-roll, visual cards, icons, captions, music, and timeline behavior stable unless a blocker proves the current behavior is wrong.

## Required Bug Workflow

Every new bug must follow this chain:

1. Bad file.
2. Bad stage.
3. Exact writer.
4. Minimal fix.
5. Microtest.
6. One targeted smoke.

## Do Not Change Baseline For

- Isolated cosmetic preferences.
- One-off ASR transcript errors.
- Desire to add more effects.
- Variety gaps that do not block publication.
- New providers or generated media experiments.

## Open A New Feature Phase Only After

- Several real VPI reels have been produced.
- Human QC feedback is collected.
- A repeated pattern is documented.
- The proposed change has a clear production benefit and a bounded test plan.
