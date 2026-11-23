"""Agregaciones del tablero sobre trazas sinteticas. Sin red."""

import dashboard as tablero
from observabilidad import Evento, Traza


def _t(tid, caso="c", ms=1000.0, etiqueta="", correcto=None, estado="ok", eventos=()):
    t = Traza(trace_id=tid, conversacion_id="x", caso=caso, timestamp=f"2026-11-16T10:00:0{tid[-1]}",
              mensaje_entrada="m", duracion_ms=ms, etiqueta=etiqueta, correcto=correcto, estado=estado)
    t.eventos = [Evento(etapa=e, inicio_ms=0, duracion_ms=d, tokens_entrada=tok, detalle=det)
                 for e, d, tok, det in eventos]
    t.tokens_entrada = sum(e.tokens_entrada for e in t.eventos)
    return t


def test_filtrar_por_configuracion_y_caso_base():
    a = _t("a1", caso="conv:previo", etiqueta="memoria-no")
    b = _t("b2", caso="conv", etiqueta="memoria-si")
    c = _t("c3", caso="venta")
    assert tablero.filtrar([a, b, c], ["memoria-no"], None) == [a]
    assert tablero.filtrar([a, b, c], None, ["conv"]) == [a, b]
    assert tablero.filtrar([a, b, c], ["chat / sin etiqueta"], None) == [c]


def test_kpis():
    trazas = [
        _t("a1", ms=2000, correcto=True, eventos=[("llm:G", 10, 100, "rate limit")]),
        _t("b2", ms=4000, correcto=False),
        _t("c3", ms=0, estado="bloqueado"),
        _t("d4", ms=6000, estado="error"),
    ]
    k = tablero.kpis(trazas)
    assert k["peticiones"] == 4 and k["bloqueadas"] == 1
    assert k["precision_pct"] == 50.0 and k["error_pct"] == 25.0
    assert k["p50_s"] == 4.0  # el bloqueado no cuenta en la latencia
    assert k["rate_limits_prom"] == 0.2  # 1 rate limit en 4 peticiones, redondeado


def test_tiempo_por_etapa_no_cuenta_envoltorios():
    t = _t("a1", eventos=[
        ("crew:kickoff", 5000, 0, ""),
        ("tool:delegate_work_to_coworker", 3000, 0, ""),
        ("llm:Gerente de tienda", 1000, 0, ""),
        ("llm:Vendedor", 2000, 0, ""),
        ("tool:registrar_venta", 500, 0, ""),
        ("memoria:consulta", 1500, 0, ""),
    ])
    etapas = {f["etapa"]: f["segundos_prom"] for f in tablero.tiempo_por_etapa([t])}
    assert etapas == {"modelo (LLM)": 3.0, "memoria": 1.5, "herramientas": 0.5}


def test_tokens_por_rol_y_por_caso():
    a = _t("a1", caso="venta", correcto=True, eventos=[("llm:Vendedor", 1, 300, ""), ("llm:Gerente", 1, 100, "")])
    b = _t("b2", caso="venta", correcto=True, eventos=[("llm:Vendedor", 1, 100, "")])
    assert tablero.tokens_por_rol([a, b]) == [{"rol": "Vendedor", "tokens_prom": 200},
                                              {"rol": "Gerente", "tokens_prom": 50}]
    fila = tablero.por_caso([a, b])[0]
    assert fila["caso"] == "venta" and fila["corridas"] == 2 and fila["precision_pct"] == 100


def test_tabla_y_eventos():
    t = _t("a1", correcto=False, eventos=[("llm:G", 1200, 10, "")])
    fila = tablero.tabla_trazas([t])[0]
    assert fila["verificado"] == "MAL" and fila["s"] == 1.0
    assert tablero.eventos_de(t)[0]["duracion_s"] == 1.2
