"""OUTPUT-CUTS-8B — tests del guard de falsos positivos de false start."""
import sys
sys.path.insert(0, "backend")

from src.services.vpi_disfluency_editor import build_output_cut_plan

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"PASS {name}")
    else:
        FAIL += 1; print(f"FAIL {name} {detail}")

def words_from(phrases):
    """phrases: list of (text, start). Words spaced 0.35s, 0.3s long."""
    out = []
    for text, start in phrases:
        t = start
        for w in text.split():
            out.append({"text": w, "start": round(t, 2), "end": round(t + 0.3, 2)})
            t += 0.35
    return out

def hard_cuts(plan, contains=None):
    cuts = [c for c in plan["cuts"] if c["treatment"] == "HARD_CUT"]
    if contains is not None:
        cuts = [c for c in cuts if contains.lower() in c["text_preview"].lower()]
    return cuts

# 1. "No todos los seguros sirven para lo mismo" (apertura retórica) → NO cortar
w1 = words_from([
    ("No todos los seguros sirven para lo mismo.", 0.3),
    ("Cada persona necesita una cobertura distinta para su familia.", 4.2),
    ("Por eso conviene revisar las condiciones con calma.", 8.5),
])
p1 = build_output_cut_plan(words=w1, clip_duration=13.0)
check("g1_rhetorical_no_preserved", not hard_cuts(p1, "No todos"), str(p1["cuts"]))
check("g1_guard_metadata", p1.get("false_start_guard_version") == "8b" and p1.get("protected_cut_candidates_count", 0) >= 1,
      str({k: p1.get(k) for k in ("protected_cut_candidates_count", "protected_cut_reasons")}))

# 2. "No es vender miedo, es dar claridad" → NO cortar
w2 = words_from([
    ("No es vender miedo, es dar claridad.", 0.3),
    ("La claridad permite decidir mejor cada cobertura del seguro.", 4.0),
    ("Y eso se nota cuando llega un imprevisto de verdad.", 8.2),
])
p2 = build_output_cut_plan(words=w2, clip_duration=13.0)
check("g2_no_es_preserved", not hard_cuts(p2, "No es vender"), str(p2["cuts"]))

# 3. "¿Qué necesitas?" pregunta corta completa → NO cortar
w3 = words_from([
    ("¿Qué valoras de un seguro completo hoy?", 0.3),
    ("¿Qué necesitas?", 3.4),
    ("¿Y qué tranquilidad estás buscando para tu familia?", 4.6),
    ("Esas preguntas son la base de una buena decisión.", 9.0),
])
p3 = build_output_cut_plan(words=w3, clip_duration=13.5)
check("g3_short_question_preserved", not hard_cuts(p3, "necesitas"), str(p3["cuts"]))

# 4. "no, no, espera, lo digo otra vez" → SÍ cortar
w4 = words_from([
    ("no, no, espera, lo digo otra vez.", 0.3),
    ("Un seguro de viaje te respalda desde que sales de casa.", 4.0),
    ("Y esa tranquilidad cambia la forma de viajar.", 9.0),
])
p4 = build_output_cut_plan(words=w4, clip_duration=13.5)
check("g4_explicit_no_no_cut", len(hard_cuts(p4, "espera")) >= 1, str(p4["cuts"]))

# 5. "me equivoqué, repito" → SÍ cortar
w5 = words_from([
    ("La póliza cubre la asistencia completa en el extranjero.", 0.3),
    ("me equivoqué, repito.", 4.5),
    ("La póliza cubre la asistencia médica completa en el extranjero.", 6.2),
    ("Y eso incluye también el regreso anticipado.", 11.0),
])
p5 = build_output_cut_plan(words=w5, clip_duration=15.0)
check("g5_me_equivoque_cut", len(hard_cuts(p5, "equivoqué")) >= 1, str(p5["cuts"]))

# 6. dead air 2.7s → cortar/comprimir (sigue funcionando)
w6 = words_from([
    ("La salud tiene una costumbre muy rebelde siempre.", 0.3),
    ("no siempre avisa cuando llega el problema importante.", 6.5),
])
p6 = build_output_cut_plan(words=w6, clip_duration=11.0)
check("g6_dead_air_still_cut", any(c["treatment"] == "COMPRESS_SILENCE" for c in p6["cuts"]), str(p6["cuts"]))

# 7. repetición clara A A toma buena → cortar una repetición (sigue funcionando)
w7 = words_from([
    ("Entiendo perfectamente que el precio importe mucho.", 0.3),
    ("Entiendo perfectamente que el precio importe mucho a todo el mundo.", 4.2),
    ("Pero cuando es el único criterio se pierden cosas esenciales.", 9.5),
])
p7 = build_output_cut_plan(words=w7, clip_duration=14.5)
rep = [c for c in p7["cuts"] if c["reason"].startswith("retake_repetition")]
check("g7_retake_still_cut", len(rep) == 1 and rep[0]["start_s"] < 4.0, str(p7["cuts"]))

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
