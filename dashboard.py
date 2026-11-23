"""Agregaciones para el tablero de app.py (pestaña Logs y costos).

Funciones puras sobre `Traza`: sin streamlit, para poder testearlas.
"""

from statistics import mean

from observabilidad import Traza, _percentil

# Envuelven a otras etapas (la delegacion contiene la llamada del otro agente,
# kickoff contiene todo): sumarlas contaria el mismo tiempo dos veces.
_ENVOLTORIOS = {"crew:kickoff", "tool:delegate_work_to_coworker", "tool:ask_question_to_coworker"}


def configuracion(t: Traza) -> str:
    return t.etiqueta or "chat / sin etiqueta"


def caso_base(t: Traza) -> str:
    return t.caso.split(":")[0]


def rate_limits(t: Traza) -> int:
    return sum(1 for e in t.eventos if e.etapa.startswith("llm:") and e.detalle == "rate limit")


def filtrar(trazas: list[Traza], configuraciones: list[str] | None = None,
            casos: list[str] | None = None) -> list[Traza]:
    return [
        t for t in trazas
        if (not configuraciones or configuracion(t) in configuraciones)
        and (not casos or caso_base(t) in casos)
    ]


def _segundos(valores_ms: list[float], p: float) -> float:
    return round(_percentil(valores_ms, p) / 1000, 1) if valores_ms else 0.0


def kpis(trazas: list[Traza]) -> dict:
    if not trazas:
        return {}
    corridas = [t for t in trazas if t.estado != "bloqueado"]
    tiempos = [t.duracion_ms for t in corridas]
    verificadas = [t for t in trazas if t.correcto is not None]
    return {
        "peticiones": len(trazas),
        "precision_pct": round(100 * sum(t.correcto is True for t in verificadas) / len(verificadas), 1)
        if verificadas else None,
        "p50_s": _segundos(tiempos, 50),
        "p95_s": _segundos(tiempos, 95),
        "tokens_prom": round(mean(t.tokens_totales for t in corridas)) if corridas else 0,
        "error_pct": round(100 * sum(t.estado == "error" for t in trazas) / len(trazas), 1),
        "bloqueadas": sum(t.estado == "bloqueado" for t in trazas),
        "rate_limits_prom": round(mean(rate_limits(t) for t in trazas), 1),
    }


def por_caso(trazas: list[Traza]) -> list[dict]:
    grupos: dict[str, list[Traza]] = {}
    for t in trazas:
        grupos.setdefault(caso_base(t), []).append(t)
    filas = []
    for caso, grupo in sorted(grupos.items()):
        tiempos = [t.duracion_ms for t in grupo]
        verificadas = [t for t in grupo if t.correcto is not None]
        filas.append({
            "caso": caso,
            "corridas": len(grupo),
            "p50_s": _segundos(tiempos, 50),
            "p95_s": _segundos(tiempos, 95),
            "tokens_prom": round(mean(t.tokens_totales for t in grupo)),
            "rate_limits": sum(rate_limits(t) for t in grupo),
            "errores": sum(t.estado == "error" for t in grupo),
            "precision_pct": round(100 * sum(t.correcto is True for t in verificadas) / len(verificadas))
            if verificadas else None,
        })
    return filas


def grupo_etapa(etapa: str) -> str | None:
    if etapa in _ENVOLTORIOS:
        return None
    if etapa.startswith("llm:"):
        return "modelo (LLM)"
    if etapa.startswith("tool:"):
        return "herramientas"
    if etapa.startswith("memoria"):
        return "memoria"
    return {
        "crew:preparacion": "preparar el crew",
        "crew:cierre": "cierre",
        "validacion_entrada": "filtro de entrada",
    }.get(etapa)


def tiempo_por_etapa(trazas: list[Traza]) -> list[dict]:
    """Segundos promedio por traza en cada grupo de etapas (cuello de botella)."""
    corridas = [t for t in trazas if t.estado != "bloqueado"]
    if not corridas:
        return []
    totales: dict[str, float] = {}
    for t in corridas:
        for e in t.eventos:
            g = grupo_etapa(e.etapa)
            if g:
                totales[g] = totales.get(g, 0.0) + e.duracion_ms
    filas = [{"etapa": g, "segundos_prom": round(ms / len(corridas) / 1000, 2)}
             for g, ms in totales.items()]
    return sorted(filas, key=lambda f: -f["segundos_prom"])


def tokens_por_rol(trazas: list[Traza]) -> list[dict]:
    totales: dict[str, int] = {}
    for t in trazas:
        for e in t.eventos:
            if e.etapa.startswith("llm:"):
                rol = e.etapa.removeprefix("llm:")
                totales[rol] = totales.get(rol, 0) + e.tokens_entrada + e.tokens_salida
    n = len(trazas) or 1
    filas = [{"rol": r, "tokens_prom": round(v / n)} for r, v in totales.items()]
    return sorted(filas, key=lambda f: -f["tokens_prom"])


def serie(trazas: list[Traza]) -> list[dict]:
    return [
        {"hora": t.timestamp, "segundos": round(t.duracion_ms / 1000, 1),
         "tokens": t.tokens_totales, "configuracion": configuracion(t)}
        for t in sorted(trazas, key=lambda t: t.timestamp)
    ]


def tabla_trazas(trazas: list[Traza]) -> list[dict]:
    marca = {True: "OK", False: "MAL", None: "-"}
    return [
        {"trace_id": t.trace_id, "hora": t.timestamp.replace("T", " "), "caso": t.caso,
         "configuracion": configuracion(t), "estado": t.estado,
         "s": round(t.duracion_ms / 1000, 1), "tokens": t.tokens_totales,
         "llamadas": t.llamadas_llm, "rate_limits": rate_limits(t),
         "verificado": marca[t.correcto], "detalle": t.verificacion or t.error or ""}
        for t in sorted(trazas, key=lambda t: t.timestamp, reverse=True)
    ]


def eventos_de(t: Traza) -> list[dict]:
    return [
        {"etapa": e.etapa, "inicio_s": round(e.inicio_ms / 1000, 2),
         "duracion_s": round(e.duracion_ms / 1000, 2), "estado": e.estado,
         "modelo": e.modelo or "", "tokens": e.tokens_entrada + e.tokens_salida,
         "detalle": e.detalle}
        for e in sorted(t.eventos, key=lambda e: e.inicio_ms)
    ]
