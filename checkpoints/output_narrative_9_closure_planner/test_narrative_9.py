"""OUTPUT-NARRATIVE-9 — tests de refrain protection + narrative closure planner."""
import sys
sys.path.insert(0, "backend")
sys.path.insert(0, "/app")

from src.services.vpi_disfluency_editor import build_output_cut_plan
from src.services.task_service import _apply_narrative_closure_planner

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"PASS {name}")
    else:
        FAIL += 1; print(f"FAIL {name} {detail}")

def words_from(phrases):
    out = []
    for text, start in phrases:
        t = start
        for w in text.split():
            out.append({"text": w, "start": round(t, 2), "end": round(t + 0.3, 2)})
            t += 0.35
    return out

# ── 1. Motivo retórico separado por contenido útil → proteger ──
# Réplica de la estructura real: instancia final PARTIDA por una pausa
# ("La salud" + [dead air] + "no siempre avisa.")
w1 = words_from([
    ("La salud no siempre avisa.", 0.3),
    ("La salud tiene una costumbre rebelde.", 2.6),
    ("No siempre avisa.", 5.4),
    ("Muchas personas empiezan a valorar ciertas decisiones importantes tarde.", 7.0),
    ("La salud", 11.6),
    ("no siempre avisa.", 14.4),
])
p1 = build_output_cut_plan(words=w1, clip_duration=16.5)
rep_cuts1 = [c for c in p1["cuts"] if c["reason"].startswith("retake_repetition")]
check("n1_refrain_not_cut", len(rep_cuts1) == 0, str(p1["cuts"]))
check("n1_refrain_metadata", p1.get("narrative_refrain_detected") is True and p1.get("repetition_cut_blocked_count", 0) >= 1,
      str({k: p1.get(k) for k in ("narrative_refrain_detected", "protected_refrain_text", "repetition_cut_blocked_count")}))

# ── 2. Final en "tenerlas" y la siguiente palabra es "pensadas" → extender ──
def planner_words(phrases):
    return [{"text": w["text"], "start": w["start"], "end": w["end"]} for w in words_from(phrases)]

seg2 = {"start_time": "00:00", "end_time": "00:07.5"}
cw2 = planner_words([
    ("justo cuando ya les hubiera gustado tenerlas", 4.5),  # ends ~7.3
    ("pensadas.", 7.65),
    ("La salud no siempre avisa.", 8.6),
])
_apply_narrative_closure_planner(task_id="t2", segment=seg2, cached_words=cw2, clip_order=1, video_duration_s=60.0)
check("n2_extends_past_tenerlas", float(seg2.get("narrative_final_end_s") or 0) >= 7.9,
      str({k: seg2.get(k) for k in ("narrative_final_end_s", "narrative_closure_reason")}))

# ── 3. Final en "sino de" → extender o needs_review ──
seg3 = {"start_time": "00:00", "end_time": "00:06.0"}
cw3 = planner_words([
    ("no se trata de pagar mas por reflejo, sino de", 1.0),  # ends ~5.0
    ("pagar con criterio y entender la cobertura.", 6.3),
])
_apply_narrative_closure_planner(task_id="t3", segment=seg3, cached_words=cw3, clip_order=1, video_duration_s=60.0)
ext3 = float(seg3.get("narrative_extended_seconds") or 0) > 0
weak3 = seg3.get("needs_review_reason") == "narrative_closure_weak"
check("n3_sino_de_extends_or_review", ext3 or weak3,
      str({k: seg3.get(k) for k in ("narrative_closure_reason", "narrative_extended_seconds", "needs_review_reason")}))

# ── 4. "No me gusta explicarlo desde el susto." + contraste después, sin BTS → extender ──
seg4 = {"start_time": "00:00", "end_time": "00:08.3"}
cw4 = planner_words([
    ("Y ahi es donde este tipo de proteccion cobra el sentido.", 1.0),
    ("No me gusta explicarlo desde el susto.", 6.0),   # ends ~8.1
    ("Pero prefiero explicarlo desde el cuidado.", 8.7),
    ("A veces la mejor ayuda no es la mas visible.", 11.6),
])
_apply_narrative_closure_planner(task_id="t4", segment=seg4, cached_words=cw4, clip_order=1, video_duration_s=60.0)
check("n4_contrast_payoff_extended",
      seg4.get("narrative_closure_reason") == "contrast_payoff_completed" and float(seg4.get("narrative_extended_seconds") or 0) >= 1.5,
      str({k: seg4.get(k) for k in ("narrative_closure_reason", "narrative_extended_seconds", "narrative_closure_preview")}))

# ── 5. Repetición basura inmediata sin contenido entre medias → puede cortar una ──
w5 = words_from([
    ("La salud no siempre avisa.", 0.3),
    ("La salud no siempre avisa.", 2.6),
    ("Muchas personas lo descubren tarde y con sustos importantes.", 5.2),
])
p5 = build_output_cut_plan(words=w5, clip_duration=10.0)
rep5 = [c for c in p5["cuts"] if c["reason"].startswith("retake_repetition")]
check("n5_adjacent_junk_repetition_cut", len(rep5) == 1, str(p5["cuts"]))

# ── 6. Retake explícito → sigue cortando ──
w6 = words_from([
    ("La poliza cubre la asistencia completa en el extranjero.", 0.3),
    ("me equivoqué, repito.", 4.6),
    ("La poliza cubre la asistencia medica completa en el extranjero.", 6.4),
])
p6 = build_output_cut_plan(words=w6, clip_duration=11.5)
check("n6_explicit_retake_still_cut",
      any("equivoqué" in c["text_preview"] for c in p6["cuts"]), str(p6["cuts"]))

# ── 7. Backstage después del final → no extender hacia backstage ──
seg7 = {"start_time": "00:00", "end_time": "00:08.3"}
cw7 = planner_words([
    ("No me gusta explicarlo desde el susto.", 6.0),   # ends ~8.1, open contrast
    ("Pero espera, estoy leyendo el titulo y tal.", 8.6),  # backstage right after
])
_apply_narrative_closure_planner(task_id="t7", segment=seg7, cached_words=cw7, clip_order=1, video_duration_s=60.0)
end7 = float(seg7.get("narrative_final_end_s") or 0)
check("n7_no_extension_into_bts",
      end7 <= 8.4 and seg7.get("needs_review_reason") == "narrative_closure_weak",
      str({k: seg7.get(k) for k in ("narrative_final_end_s", "narrative_closure_reason", "needs_review_reason")}))

# ── extra: simulación FASE 4 — corte al final que deja fragmento se descarta ──
w8 = words_from([
    ("El seguro te protege de verdad en los momentos importantes.", 0.3),
    ("no, no, espera, lo digo otra vez.", 5.0),
    ("El seguro te protege de verdad cuando llega un imprevisto serio.", 8.2),
])
p8 = build_output_cut_plan(words=w8, clip_duration=13.5)
check("n8_simulation_passed_metadata", p8.get("needs_review_reason", "") == "" and p8["cuts"], str(p8.get("needs_review_reason")))

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
