"""OUTPUT-SELECTION-52B — deterministic unit tests for the core helpers.

Run inside the worker venv:
  docker exec viraclip-worker /app/.venv/bin/python /app/tests/test_selection_52b.py
"""
import sys

sys.path.insert(0, "/app")

from src.services.vpi_source_window_history import (  # noqa: E402
    canonical_source_id,
    normalize_transcript,
    window_fingerprint,
    transcript_similarity,
    temporal_overlap_ratio,
    evaluate_candidate_against_history,
    build_delivered_window_history,
)

FAIL = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAIL.append(name)


# FASE 13.1 — same URL, different query → same identity
a, _ = canonical_source_id("https://youtu.be/3wgwaxIfUJQ")
b, _ = canonical_source_id("https://youtu.be/3wgwaxIfUJQ?si=aNslWhTyQ19zv5B4")
c, _ = canonical_source_id("https://www.youtube.com/watch?v=3wgwaxIfUJQ&t=10s&feature=share")
check("13.1 canonical equal across query params", a == b == c == "youtube:3wgwaxIfUJQ")

# FASE 13.6 / 11.6 — different source → different identity
d, dtype = canonical_source_id("https://youtu.be/DHSigj8uPnE")
check("13.6 different source different id", d == "youtube:DHSigj8uPnE" and d != a)

# upload uses physical hash, not filename
up, uptype = canonical_source_id("/uploads/myvideo.mp4", physical_hash="abc123")
check("upload uses hash", up == "upload:abc123" and uptype == "upload")

# Build a history from one delivered clip (window 04:04 -> 04:25.06)
rows = [
    {
        "task_id": "prev-1",
        "clip_order": 1,
        "start_time": "04:04",
        "end_time": "04:25.06",
        "duration": 26.82,
        "text": "Hablar de un seguro de vida no trae nada malo. Hablar de proteger a tu familia.",
        "source_url": "https://youtu.be/3wgwaxIfUJQ?si=aNslWhTyQ19zv5B4",
    }
]
history = build_delivered_window_history(rows, "youtube:3wgwaxIfUJQ")
check("history built for matching canonical", len(history) == 1)
history_other = build_delivered_window_history(rows, "youtube:DHSigj8uPnE")
check("13.7 history empty for other source", len(history_other) == 0)

prev_text = rows[0]["text"]

# 13.2 — same source, same window → reject
same = {"start_time": "04:04", "end_time": "04:25.06", "text": prev_text}
check("13.2 same window rejected", evaluate_candidate_against_history(same, history) is not None)

# 13.3 — same source, ~75% overlap → reject (rule A)
# previous duration ~21.06s; a window overlapping >=70% of the shorter duration
overlap_cand = {"start_time": "04:10", "end_time": "04:31", "text": "contenido distinto sin parecido alguno xyz"}
res_ov = evaluate_candidate_against_history(overlap_cand, history)
check("13.3 strong temporal overlap rejected", res_ov is not None and "temporal_overlap" in (res_ov or {}).get("reasons", []))

# 13.4 — same source, clearly different window → allow
diff = {"start_time": "08:10", "end_time": "08:40", "text": "un tema completamente diferente sobre ahorro mensual planificado"}
check("13.4 different window allowed", evaluate_candidate_against_history(diff, history) is None)

# 13.5 — transcript 95% similar (rule C) at a disjoint time → reject
# same words, shifted far in time so temporal/near-equal rules do NOT fire
simlike = {"start_time": "20:00", "end_time": "20:21", "text": prev_text}
res_sim = evaluate_candidate_against_history(simlike, history)
check("13.5 transcript similarity rejected", res_sim is not None and "transcript_similarity" in (res_sim or {}).get("reasons", []))
check("13.5 reason not temporal (disjoint time)", res_sim is not None and "temporal_overlap" not in res_sim.get("reasons", []))

# 13.7 — candidate from a different source compared against empty history → allow
check("13.7 empty history allows everything", evaluate_candidate_against_history(same, history_other) is None)

# normalize + fingerprint determinism
n1 = normalize_transcript("Hola,  MUNDO!!")
check("normalize deterministic", n1 == "hola mundo" and normalize_transcript("hola mundo") == n1)
fp1 = window_fingerprint(244.0, 265.06, prev_text)
fp2 = window_fingerprint(244.0, 265.06, prev_text)
check("fingerprint deterministic", fp1 == fp2 and len(fp1) == 16)

# transcript similarity bounds
check("similarity identical=1.0", abs(transcript_similarity(n1, n1) - 1.0) < 1e-9)
check("similarity disjoint=0.0", transcript_similarity("aaa bbb", "ccc ddd") == 0.0)

# temporal overlap ratio uses min(duration) denominator (rule A semantics)
# candidate fully inside previous → ratio 1.0
check("overlap contained=1.0", abs(temporal_overlap_ratio(245, 260, 244, 265.06) - 1.0) < 1e-9)
check("overlap disjoint=0.0", temporal_overlap_ratio(300, 320, 244, 265.06) == 0.0)

# near-equal window rule B (start<=2.0, end<=3.0) at otherwise low overlap text
nearcand = {"start_time": "04:05", "end_time": "04:27", "text": "texto totalmente distinto qqq"}
res_near = evaluate_candidate_against_history(nearcand, history)
check("rule B near-equal window rejected", res_near is not None and "near_equal_window" in (res_near or {}).get("reasons", []))

print()
if FAIL:
    print("RESULT: FAIL ->", FAIL)
    sys.exit(1)
print("RESULT: ALL GREEN")
