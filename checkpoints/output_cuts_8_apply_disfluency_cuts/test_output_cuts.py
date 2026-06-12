"""OUTPUT-CUTS-8 — minimal tests for the applied cut plan + backstage hard-ban."""
import sys
sys.path.insert(0, "backend")

from src.services.vpi_disfluency_editor import build_output_cut_plan
from src.services.vpi_silence_editor import (
    classify_pause,
    remap_word_timestamps,
    _build_offset_map,
)
from src.services.vpi_retention_editing_service import filter_content_quality_candidates

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"PASS {name}")
    else:
        FAIL += 1
        print(f"FAIL {name} {detail}")

def W(text, start, end):
    return {"text": text, "start": start, "end": end}

# ── Case 1: repetition A A toma buena → first take cut, last (good) kept ──
words1 = (
    [W(w, 0.4 + i * 0.4, 0.7 + i * 0.4) for i, w in enumerate("por eso se trata de pagar menos,".split())]
    # retake: same phrase again after a short breath (good take)
    + [W(w, 3.6 + i * 0.4, 3.9 + i * 0.4) for i, w in enumerate("por eso se trata de pagar menos, sino de pagar mejor.".split())]
    + [W(w, 8.4 + i * 0.4, 8.7 + i * 0.4) for i, w in enumerate("la clave es entender la cobertura real.".split())]
)
dur1 = max(w["end"] for w in words1) + 0.4
plan1 = build_output_cut_plan(words=words1, clip_duration=dur1, source_start_s=100.0)
rep_cuts = [c for c in plan1["cuts"] if c["reason"].startswith("retake_repetition")]
check("case1_repetition_cut_exists", len(rep_cuts) >= 1, str(plan1["cuts"]))
check(
    "case1_first_take_cut_good_take_kept",
    rep_cuts and rep_cuts[0]["start_s"] <= 0.5 and rep_cuts[0]["end_s"] < 3.6,
    str(rep_cuts),
)
check("case1_keep_segments_continuous",
      all(abs(plan1["keep_segments"][i]["end_s"] - plan1["keep_segments"][i+1]["start_s"]) < 0.001
          for i in range(len(plan1["keep_segments"]) - 1)),
      str(plan1["keep_segments"]))

# ── Case 2: false start + clean phrase → false start cut ──
words2 = (
    [W("cuando", 0.3, 0.6), W("tienes", 0.65, 0.9)]
    + [W(w, 2.2 + i * 0.35, 2.5 + i * 0.35) for i, w in enumerate("cuando tienes un seguro de viaje completo todo cambia de verdad.".split())]
    + [W(w, 7.2 + i * 0.35, 7.5 + i * 0.35) for i, w in enumerate("y eso te da una tranquilidad enorme cada dia.".split())]
)
dur2 = max(w["end"] for w in words2) + 0.4
plan2 = build_output_cut_plan(words=words2, clip_duration=dur2)
fs_cuts = [c for c in plan2["cuts"] if c["reason"].startswith(("false_start", "retake_repetition"))]
check("case2_false_start_cut", any(c["start_s"] <= 0.4 and c["end_s"] <= 2.2 for c in fs_cuts), str(plan2["cuts"]))

# ── Case 3: dead air 2.7s → compressed ──
words3 = (
    [W(w, 0.3 + i * 0.35, 0.6 + i * 0.35) for i, w in enumerate("la salud tiene una costumbre rebelde y peculiar".split())]
    + [W(w, 6.0 + i * 0.35, 6.3 + i * 0.35) for i, w in enumerate("no siempre avisa cuando llega el problema importante.".split())]
)
# gap: last end of first group = 0.6+6*0.35=2.7 ; next start 6.0 → 3.3s gap
dur3 = max(w["end"] for w in words3) + 0.5
plan3 = build_output_cut_plan(words=words3, clip_duration=dur3)
da_cuts = [c for c in plan3["cuts"] if c["treatment"] == "COMPRESS_SILENCE"]
check("case3_dead_air_compressed", len(da_cuts) >= 1, str(plan3["cuts"]))
if da_cuts:
    c = da_cuts[0]
    gap_start3 = max(w["end"] for w in words3 if w["end"] < 5.0)
    check("case3_leaves_short_pause", abs(c["start_s"] - (gap_start3 + 0.30)) < 0.05, str(c))
    check("case3_cut_ends_at_next_word", abs(c["end_s"] - 6.0) < 0.05, str(c))

# classify_pause: 2.7s with strong keyword after must now be dead_air shorten
seg = classify_pause(
    {"start_s": 10.0, "end_s": 12.7, "duration_s": 2.7,
     "before_text": "tenerlas pensadas.", "after_text": "no siempre avisa."},
    editorial_type="myth_debunk",
)
check("case3_classifier_dead_air_priority", seg.pause_type == "dead_air" and seg.action == "shorten",
      f"{seg.pause_type}/{seg.action}")

# ── Case 4: short editorial pause 0.6s → preserved (no cut) ──
words4 = (
    [W(w, 0.3 + i * 0.35, 0.6 + i * 0.35) for i, w in enumerate("proteger a tu familia es una responsabilidad seria".split())]
    + [W(w, 3.3 + i * 0.35, 3.6 + i * 0.35) for i, w in enumerate("porque la realidad es que nadie avisa nunca.".split())]
)
dur4 = max(w["end"] for w in words4) + 0.4
plan4 = build_output_cut_plan(words=words4, clip_duration=dur4)
gap_cut = [c for c in plan4["cuts"] if c["treatment"] == "COMPRESS_SILENCE" and c["start_s"] > 2.0 and c["start_s"] < 3.4]
check("case4_short_editorial_pause_kept", len(gap_cut) == 0, str(plan4["cuts"]))
seg4 = classify_pause(
    {"start_s": 2.7, "end_s": 3.3, "duration_s": 0.6,
     "before_text": "responsabilidad seria", "after_text": "porque la realidad es"},
    editorial_type="emotional_protection",
)
check("case4_classifier_preserves", "preserve" in seg4.action, f"{seg4.pause_type}/{seg4.action}")

# ── Case 5: captions post-cut → removed text absent, timeline continuous ──
cuts5 = [{"start_s": c["start_s"], "end_s": c["end_s"],
          "removed_s": round(c["end_s"] - c["start_s"], 3)} for c in plan1["cuts"]]
offset_map5 = _build_offset_map(cuts5)
ranges5 = [(c["start_s"], c["end_s"]) for c in cuts5]
kept_words = [w for w in words1
              if not any(r0 <= (w["start"] + w["end"]) / 2.0 < r1 for r0, r1 in ranges5)]
remapped = remap_word_timestamps(kept_words, offset_map5)
removed_total = sum(c["removed_s"] for c in cuts5)
removed_words = [w for w in words1 if w not in kept_words]
check("case5_removed_text_absent", all(w not in kept_words for w in removed_words), "")
gaps = [round(remapped[i+1]["start"] - remapped[i]["end"], 3) for i in range(len(remapped)-1)]
check("case5_timeline_continuous_no_big_gaps", all(g < 1.2 for g in gaps), str(gaps))
check("case5_first_word_near_zero", remapped[0]["start"] <= 0.5, str(remapped[0]))
ends_ok = all(remapped[i]["end"] <= remapped[i+1]["start"] + 0.001 for i in range(len(remapped)-1))
check("case5_no_overlaps", ends_ok, "")

# ── Case 6: backstage candidate cannot be rescued as final ──
bts_text = ("el seguro de salud protege a tu familia con una cobertura completa "
            "y unos precios razonables para todas las personas que dependen de ti")
bts_seg = {
    "text": bts_text,
    "start_time": "02:48", "end_time": "03:18",
    "duration": 30.0, "start_seconds": 168.0, "end_seconds": 198.0,
    "vpi_score": 70.0, "editorial_score": 0.7,
    "matched_patterns": ["seguro"],
    "bts_contamination_ratio": 0.6,
    "final_rank_score": 0.9,
}
accepted, rejected = filter_content_quality_candidates([bts_seg], requested=1)
check("case6_backstage_not_rescued", bts_seg not in accepted, f"accepted={len(accepted)}")
check("case6_marked_blocked_or_rejected",
      bool(bts_seg.get("backstage_rescue_blocked")) or any(r.get("reason","").startswith(("bts","behind","meta")) for r in rejected),
      str(rejected))
check("case6_no_override_flag", not bts_seg.get("bts_override_used"), "")

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
