#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_retention_editing_service import (  # noqa: E402
    build_clean_take_candidates,
    build_delivery_contract,
    evaluate_content_quality,
    filter_content_quality_candidates,
)


TRANSCRIPT = """
[00:03 - 00:04] ¡Claro!
[00:06 - 00:06] ¡Papá!
[00:11 - 00:13] Ok, chéverísima.
[00:13 - 00:14] ¡Ahí está!
[00:14 - 00:15] ¡Chéverísimos!
[00:16 - 00:17] ¡Ya sí!
[00:17 - 00:19] Tenemos así el plano, está en cuadrado.
[00:49 - 00:51] Hola, soy Rosa Valentín.
[00:51 - 00:54] Hoy vengo a hablarte del Seguro de Decesos.
[00:54 - 00:56] Este seguro no va de miedo.
[00:56 - 00:57] Va de alivio para la familia.
[00:57 - 01:00] Quiero romper una idea muy típica.
[01:00 - 01:03] El Seguro de Decesos no existe para asustar a nadie.
[01:03 - 01:06] Existe para facilitar un momento difícil.
[01:06 - 01:08] Para que la familia no tenga que gestionar más de la cuenta.
[01:24 - 01:28] Pero proteger también es facilitar y dejar menos carga.
[01:39 - 01:43] Deja de sonar triste y empieza a sonar responsable.
[01:56 - 01:57] Dale de nuevo con eso.
[02:36 - 02:40] No es un tema fácil, pero sí muy humano.
[02:44 - 02:48] Que un tema sea delicado no significa que no sea importante.
[02:53 - 02:56] El Seguro de Decesos es uno de ellos.
[02:56 - 03:00] Pero precisamente por eso merece una explicación serena y humana.
[03:00 - 03:06] La realidad es que hay momentos en los que una familia necesita acompañamiento y organización.
[03:08 - 03:10] Y ahí es donde este tipo de protección cobra sentido.
[03:17 - 03:21] A veces la mejor ayuda no es la más visible. Es la que aparece cuando más falta hace.
[03:40 - 03:41] Bien.
[05:07 - 05:10] Tener un seguro de salud no es un postureo. Es organización.
[05:11 - 05:14] Para mucha gente un seguro de salud no es lujo, es orden.
[05:23 - 05:27] Va de poder revisar algo sin eternizarlo.
[05:27 - 05:32] De sentir que si necesitas orientación o especialistas o pruebas tienes un camino más claro.
[05:41 - 05:49] Antes de mirar nombres o precios conviene mirar tu vida real, qué valoras y qué tranquilidad estás buscando.
[06:45 - 06:53] Muchas personas empiezan a valorar ciertas decisiones justo cuando ya les hubiera gustado tenerlas. Y no digo esto para generar alarma.
[06:53 - 07:03] Lo digo porque en la vida real las cosas no siempre llegan con cita previa. Cuando algo ocurre lo que más se agradece es claridad y respaldo.
[07:03 - 07:13] Un seguro de salud bien entendido es una herramienta de tranquilidad para quien valora cuidar tiempos, opciones y acompañamiento.
[07:29 - 07:37] Cuidarse no siempre significa reaccionar cuando algo pasa. Muchas veces significa prepararse mejor para vivir más tranquilo.
[07:38 - 07:38] Bien.
[08:27 - 08:31] Si eres autónomo tú no eres solo una persona. Eres el motor.
[08:32 - 08:35] Cuando todo depende de ti protegerte ya no es un capricho. Es una estrategia.
[08:35 - 08:44] Si eres autónomo seguramente ya lo sabes. Eres quien factura, quien responde, quien organiza y sostiene.
[08:44 - 08:51] Cuando toda esta estructura depende de una sola persona, protegerse deja de ser un lujo y empieza a ser sentido común.
[08:52 - 09:04] A veces el autónomo se ocupa de todo menos de sí mismo. Del cliente, de los plazos, de los pagos y de los imprevistos.
[09:04 - 09:14] Esa reflexión no es pesimismo. Es estrategia. Porque cuando depende de ti, proteger tu estabilidad es proteger mucho más que tu bolsillo.
[09:27 - 09:29] Bien. Ataca esto.
[10:11 - 10:16] Si eres autónomo esta reflexión te interesa. Seguramente sostienes mucho más que tu trabajo.
[10:17 - 10:22] Sostienes ingresos, clientes, facturas, ritmo de vida y muchas veces la estabilidad de otras personas.
[10:22 - 10:29] Por eso hay una pregunta que conviene hacerse antes de que aparezca un imprevisto si mañana no puedes trabajar durante un tiempo.
[10:29 - 10:32] La economía sigue respirando o se queda sin aire.
[10:40 - 10:48] No lo digo para generar miedo. Lo digo porque en el día a día del autónomo lo importante se deja para más adelante.
[10:48 - 10:53] Proteger tu capacidad de seguir adelante no es exagerar. Es organizarte con cabeza.
[11:02 - 11:12] A veces pensamos en seguro como un gasto más. Cuando en realidad algunos sirven para proteger justo lo que mantiene en pie a los demás.
[11:22 - 11:33] Tu continuidad, tu estabilidad y tu margen para reaccionar. Revisar tu protección no es dramatizar. Es dejar de improvisar con una parte delicada de tu vida.
[11:47 - 11:48] Ok, gracias.
"""


def main() -> int:
    pool = build_clean_take_candidates(TRANSCRIPT, transcript_duration_s=712.0, num_clips=3)
    segments = list(pool["segments"])
    accepted, rejected = filter_content_quality_candidates(segments, requested=3)
    topics = {str(item.get("clean_take_topic")) for item in accepted}

    assert int(pool["generated_before_filter"]) >= 8
    assert len(accepted) >= 4
    assert {"decesos", "salud", "autonomos"}.issubset(topics)

    initial_bts = {
        "text": "¡Claro! ¡Papá! Ok, chéverísima. ¡Ahí está! ¡Chéverísimos! ¡Ya sí!",
        "start_time": "00:00",
        "end_time": "00:30",
        "bts_contamination_ratio": 1.0,
        "useful_content_ratio": 0.0,
    }
    assert evaluate_content_quality(initial_bts)["content_quality_label"] == "reject"

    assert any(item.get("clean_take_topic") == "salud" for item in accepted)
    assert any(item.get("clean_take_topic") == "autonomos" for item in accepted)

    selected = []
    for topic in ("decesos", "salud", "autonomos"):
        match = next(item for item in accepted if item.get("clean_take_topic") == topic)
        selected.append(match)
    contract = build_delivery_contract(requested=3, delivered=len(selected), rejected_reasons=rejected)
    assert contract["delivered_num_clips"] == 3
    assert contract["shortage_reason"] == ""

    print(f"generated_before_filter={pool['generated_before_filter']}")
    print(f"clean_takes_generated={len(accepted)}")
    print(f"topics_detected={','.join(sorted(topics))}")
    print("bts_initial_rejected=true")
    print("salud_accepted=true")
    print("autonomos_accepted=true")
    print("requested_3_simulated_delivered_3=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
