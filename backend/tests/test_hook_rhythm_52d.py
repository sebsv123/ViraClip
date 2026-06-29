"""OUTPUT-HOOK-RHYTHM-52D — deterministic tests for the contextual hook fallback."""
import sys
sys.path.insert(0, "/app")
from src.services.vpi_production_safe_edit import build_hook_fallback_text

FAIL = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond: FAIL.append(name)

BANNED = {"cuidado con esto", "atencion", "atención", "no te lo pierdas", "esto es importante"}
def banned(s): return s.strip().lower() in BANNED

TRAVEL = ("La poliza de asistencia en viaje desde que pisas el aeropuerto. Antes de viajar revisa "
          "el pasaporte. Cuando uno viaja cambia la forma de reaccionar ante cualquier problema.")

# 1. travel editorial_type -> contextual travel hook, not generic
h = build_hook_fallback_text(TRAVEL, editorial_type="travel_assistance")
check("1 travel -> ANTES DE VIAJAR", h == "ANTES DE VIAJAR")
check("1 not banned", not banned(h))

# 2. THE REFERENCE BUG: travel text containing 'problema' must NOT become 'Cuidado con esto'
h2 = build_hook_fallback_text(TRAVEL, editorial_type="")
check("2 travel text (no etype) -> travel hook, not 'Cuidado con esto'", h2 == "ANTES DE VIAJAR" and h2 != "Cuidado con esto")

# 3. health
h3 = build_hook_fallback_text("La salud no avisa, acudir al medico a tiempo importa.", editorial_type="health_access")
check("3 health -> CUANDO LA SALUD NO AVISA", h3 == "CUANDO LA SALUD NO AVISA" and not banned(h3))

# 4. family / emotional protection
h4 = build_hook_fallback_text("Proteger a tu familia y a los tuyos.", editorial_type="emotional_protection")
check("4 family -> PROTEGER TAMBIEN ES PREVER", h4 == "PROTEGER TAMBIEN ES PREVER" and not banned(h4))

# 5. coverage explanation
h5 = build_hook_fallback_text("Esta cobertura de la poliza cambia segun el caso.", editorial_type="coverage_explanation")
check("5 coverage -> ESTO CAMBIA LA COBERTURA", h5 == "ESTO CAMBIA LA COBERTURA")

# 6. every output is 3-7 words and never banned, across intents
for et in ("travel_assistance","health_access","emotional_protection","documents_admin","coverage_explanation","financial_planning","advisor_explanation",""):
    out = build_hook_fallback_text("contenido generico sin pistas claras", editorial_type=et)
    n = len(out.split())
    check(f"6 [{et or 'none'}] 3-7 words & not banned", 3 <= n <= 7 and not banned(out))

# 7. risk-only generic text without any VPI intent -> neutral, still not a banned attention phrase
h7 = build_hook_fallback_text("Cuidado con esto, mucho problema y riesgo.", editorial_type="")
check("7 generic risk -> not banned attention phrase", not banned(h7))

print()
if FAIL:
    print("RESULT: FAIL ->", FAIL); sys.exit(1)
print("RESULT: ALL GREEN")
