"""OUTPUT-VISUAL-COVERAGE-52C — deterministic tests for travel visual reinforcement.

Run inside the worker venv:
  docker exec viraclip-worker /app/.venv/bin/python /tmp/test_visual_coverage_52c.py
"""
import sys
sys.path.insert(0, "/app")

from src.services.vpi_object_2d import (  # noqa: E402
    classify_visual_intent, select_object_2d_icon, place_object_best_phrase,
    place_object_on_phrase, _OBJECT_2D_ICON_MAP,
)

FAIL = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAIL.append(name)


def words_from(pairs):
    """pairs: list of (text, start, end)"""
    return [{"text": t, "start": s, "end": e, "confidence": 1.0} for t, s, e in pairs]


TRAVEL = ("La poliza de asistencia en viaje desde que pisas el aeropuerto. "
          "Antes de viajar revisa el pasaporte. Cuando uno viaja cambia el contexto.")

# 1. travel intent classifies + has a real local icon (object fallback exists)
c = classify_visual_intent(TRAVEL, editorial_type_prior="travel_assistance")
check("1 travel intent classified", c["intent"] == "travel_assistance")
check("1 travel icon exists", select_object_2d_icon("travel_assistance") is not None)
check("1 travel maps to suitcase/passport", _OBJECT_2D_ICON_MAP["travel_assistance"] == ["vpi/travel_suitcase.svg", "vpi/travel_passport.svg"])

# 2. candidate_phrases exposes multiple explicit travel phrases (FASE 5)
check("2 multiple candidate phrases", len(c.get("candidate_phrases") or []) >= 2)

# 3. family_relief / generic family text is NOT travel (FASE 11.5)
fam = classify_visual_intent("Proteger a tu familia y a los tuyos da tranquilidad y respaldo.", editorial_type_prior="emotional_protection")
check("3 family text != travel", fam["intent"] != "travel_assistance")

# 4. generic risk ('por si acaso') does NOT activate travel (FASE 11.6)
risk = classify_visual_intent("Conviene tenerlo por si acaso, ante cualquier imprevisto o problema.", editorial_type_prior="")
check("4 generic risk != travel", risk["intent"] != "travel_assistance")

# 5. multi-phrase retry: top phrase 'aeropuerto' in hook -> next clean phrase used, not skip
# aeropuerto at 1.0-2.0 (inside hook_end=3.0); viajar at 12.0; viaja at 20.0
ws = words_from([
    ("La", 0.2, 0.4), ("poliza", 0.4, 0.8), ("de", 0.8, 1.0), ("asistencia", 1.0, 1.6),
    ("aeropuerto", 1.6, 2.4),  # in hook
    ("Antes", 11.0, 11.4), ("de", 11.4, 11.6), ("viajar", 11.8, 12.4), ("revisa", 12.4, 13.0),
    ("Cuando", 19.5, 20.0), ("uno", 20.0, 20.3), ("viaja", 20.3, 20.9), ("cambia", 20.9, 21.4),
])
best = place_object_best_phrase(ws, c.get("candidate_phrases") or [], clip_duration=30.0, hook_end=3.0, avoid=[])
check("5 multi-phrase yields a clean window", bool(best.get("window")))
check("5 chosen phrase is not the hook 'aeropuerto'", (best.get("chosen_norm") or "") != "aeropuerto")

# 6. single-phrase placement WOULD skip 'aeropuerto' (proves the retry mattered)
single = place_object_on_phrase(ws, "aeropuerto", "aeropuerto", clip_duration=30.0, hook_end=3.0, avoid=[])
check("6 single-phrase 'aeropuerto' skips (in hook)", single.get("window") is None and single.get("phrase_window_skip_reason") == "phrase_in_hook")

# 7. no candidate phrases at all -> graceful skip, no crash
empty = place_object_best_phrase(ws, [], clip_duration=30.0, hook_end=3.0, avoid=[])
check("7 no candidates -> no window, no crash", empty.get("window") is None)

# 8. all phrases in closure tail -> skip (no forced relocation)
ws_close = words_from([("relleno", 1.0, 1.4)] + [("viaje", 28.6, 29.0)])
close = place_object_best_phrase(ws_close, [{"matched_phrase": "viaje", "matched_norm": "viaje"}], clip_duration=30.0, hook_end=3.0, avoid=[])
check("8 closure-only phrase -> skip", close.get("window") is None)

print()
if FAIL:
    print("RESULT: FAIL ->", FAIL); sys.exit(1)
print("RESULT: ALL GREEN")
