"""Observabilidad del crew: metricas (IL3.1) y trazas (IL3.2) con datos reales.

`RegistroMetrica`/`RecolectorMetricas` siguen `RA3/IL3.1/1-observability_tools.py`
y `Evento`/`Traza`/`AnalizadorTrazas` siguen `RA3/IL3.2/1-traceability_analysis.py`
del repo del curso. La diferencia es la fuente: alla el azar simula la espera,
aca cada evento sale del bus de eventos de CrewAI (llamada al LLM, tool,
consulta o guardado de memoria) y cada traza queda en `logs/trazas.jsonl`.

Equivalencias con el grafo del curso: `trace_id` = un `kickoff()`,
`thread_id` = `conversacion_id`, nodo = agente / tool / memoria.
"""

from __future__ import annotations

import json
import re
import statistics
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from crewai.events import crewai_event_bus
from crewai.events.types.memory_events import (
    MemoryQueryCompletedEvent,
    MemoryQueryFailedEvent,
    MemoryQueryStartedEvent,
    MemorySaveCompletedEvent,
    MemorySaveFailedEvent,
    MemorySaveStartedEvent,
)
from crewai.events.types.tool_usage_events import (
    ToolUsageErrorEvent,
    ToolUsageFinishedEvent,
    ToolUsageStartedEvent,
)

from guardrails import detecto_injection, sanitizar_pii

RAIZ = Path(__file__).parent
ARCHIVO_TRAZAS = RAIZ / "logs" / "trazas.jsonl"


# --- IL3.1: metricas de la llamada -------------------------------------

@dataclass
class RegistroMetrica:
    timestamp: str
    tiempo_respuesta_ms: float
    tokens_entrada: int
    tokens_salida: int
    exitoso: bool
    modelo: str
    correcto: bool | None = None


class RecolectorMetricas:
    """Mismo contrato que el de IL3.1, mas precision (`correcto`) y percentiles."""

    def __init__(self):
        self.registros: list[RegistroMetrica] = []

    def registrar(self, tiempo_ms: float, tokens_in: int, tokens_out: int,
                  exitoso: bool, modelo: str, correcto: bool | None = None):
        self.registros.append(RegistroMetrica(
            timestamp=datetime.now().isoformat(),
            tiempo_respuesta_ms=round(tiempo_ms, 2),
            tokens_entrada=tokens_in,
            tokens_salida=tokens_out,
            exitoso=exitoso,
            modelo=modelo,
            correcto=correcto,
        ))

    def resumen(self) -> dict:
        if not self.registros:
            return {"total_peticiones": 0}

        tiempos = [r.tiempo_respuesta_ms for r in self.registros]
        errores = sum(1 for r in self.registros if not r.exitoso)
        verificados = [r.correcto for r in self.registros if r.correcto is not None]

        return {
            "total_peticiones": len(self.registros),
            "tiempo_promedio_ms": round(statistics.mean(tiempos), 2),
            "tiempo_p50_ms": round(_percentil(tiempos, 50), 2),
            "tiempo_p95_ms": round(_percentil(tiempos, 95), 2),
            "tiempo_maximo_ms": round(max(tiempos), 2),
            "tiempo_minimo_ms": round(min(tiempos), 2),
            "total_tokens": sum(r.tokens_entrada + r.tokens_salida for r in self.registros),
            "tasa_errores_pct": round(errores / len(self.registros) * 100, 2),
            "precision_pct": (
                round(sum(verificados) / len(verificados) * 100, 2) if verificados else None
            ),
        }


def _percentil(valores: list[float], p: float) -> float:
    ordenados = sorted(valores)
    if len(ordenados) == 1:
        return ordenados[0]
    k = (len(ordenados) - 1) * p / 100
    bajo = int(k)
    alto = min(bajo + 1, len(ordenados) - 1)
    return ordenados[bajo] + (ordenados[alto] - ordenados[bajo]) * (k - bajo)


# --- IL3.2: trazas -----------------------------------------------------

@dataclass
class Evento:
    etapa: str
    inicio_ms: float
    duracion_ms: float
    estado: str = "ok"
    agente: str | None = None
    modelo: str | None = None
    tokens_entrada: int = 0
    tokens_salida: int = 0
    detalle: str = ""


@dataclass
class Traza:
    trace_id: str
    conversacion_id: str
    caso: str
    timestamp: str
    mensaje_entrada: str
    eventos: list[Evento] = field(default_factory=list)
    estado: str = "ok"  # ok | error | bloqueado
    error: str | None = None
    respuesta_final: str | None = None
    duracion_ms: float = 0.0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    llamadas_llm: int = 0
    tokens_reportados_crewai: int = 0
    correcto: bool | None = None
    verificacion: str | None = None
    etiqueta: str = ""

    def agregar_evento(self, **datos) -> None:
        self.eventos.append(Evento(**datos))

    @property
    def tokens_totales(self) -> int:
        return self.tokens_entrada + self.tokens_salida

    @property
    def modelos(self) -> list[str]:
        return sorted({e.modelo for e in self.eventos if e.modelo})

    def a_dict(self) -> dict:
        d = asdict(self)
        d["tokens_totales"] = self.tokens_totales
        d["modelos"] = self.modelos
        return d

    def a_json(self) -> str:
        return json.dumps(self.a_dict(), ensure_ascii=False)

    @classmethod
    def desde_dict(cls, d: dict) -> "Traza":
        d = {k: v for k, v in d.items() if k not in ("tokens_totales", "modelos")}
        d["eventos"] = [Evento(**e) for e in d.get("eventos", [])]
        return cls(**d)


class AnalizadorTrazas:
    """Tasa de exito y etapa mas lenta, como IL3.2, mas el reparto de tokens
    por etapa: es lo que muestra que el costo no esta en el trabajo visible."""

    @staticmethod
    def resumir(trazas: list[Traza]) -> dict:
        total = len(trazas)
        if not total:
            return {"total_trazas": 0, "tasa_exito_pct": 0, "duracion_promedio_ms": 0}

        # Una traza falla si el crew no termino. Los errores internos que
        # CrewAI absorbe (memoria contra Groq) se cuentan aparte, por etapa.
        errores = sum(1 for t in trazas if t.estado == "error")
        duraciones = [t.duracion_ms for t in trazas]

        tiempos: dict[str, list[float]] = {}
        tokens: dict[str, int] = {}
        fallos: dict[str, int] = {}
        for t in trazas:
            for e in t.eventos:
                tiempos.setdefault(e.etapa, []).append(e.duracion_ms)
                tokens[e.etapa] = tokens.get(e.etapa, 0) + e.tokens_entrada + e.tokens_salida
                if e.estado == "error":
                    fallos[e.etapa] = fallos.get(e.etapa, 0) + 1

        promedio = {k: round(statistics.mean(v), 2) for k, v in tiempos.items()}
        # crew:kickoff contiene a todas las demas: no cuenta como cuello de botella.
        hojas = {k: v for k, v in promedio.items() if k != "crew:kickoff"}
        total_tokens_etapas = sum(tokens.values()) or 1

        return {
            "total_trazas": total,
            "trazas_con_error": errores,
            "trazas_bloqueadas": sum(1 for t in trazas if t.estado == "bloqueado"),
            "tasa_exito_pct": round((total - errores) / total * 100, 1),
            "duracion_promedio_ms": round(statistics.mean(duraciones), 2),
            "duracion_maxima_ms": round(max(duraciones), 2),
            "promedio_por_etapa_ms": promedio,
            "etapa_mas_lenta": max(hojas, key=lambda k: hojas[k]) if hojas else None,
            "tokens_por_etapa_pct": {
                k: round(v / total_tokens_etapas * 100, 1)
                for k, v in sorted(tokens.items(), key=lambda kv: -kv[1])
            },
            "eventos_con_error": fallos,
        }


# --- Captura ----------------------------------------------------------
# Las llamadas al LLM llegan desde LLMConFallback (agentes.OBSERVADORES_LLM),
# que conoce el modelo de cada intento y sus tokens. Tools y memoria salen del
# bus de eventos de CrewAI.

_activa: Traza | None = None
_t0: float = 0.0
_lock = threading.Lock()
_ORG = re.compile(r"org_[0-9a-z]{10,}")


_progreso: Callable[[str], None] | None = None

_FRASES_TOOL = {
    "consultar_stock": "Consultando el stock",
    "productos_bajo_minimo": "Revisando productos bajo el mínimo",
    "historial": "Revisando el historial del producto",
    "registrar_venta": "Registrando la venta",
    "registrar_reposicion": "Preparando la reposición",
    "correo": "Redactando la orden al proveedor",
    "search_memory": "Revisando el contexto de la conversación",
}

_FRASES_DELEGACION = {
    "inventario": "Buscando el producto en el inventario",
    "vendedor": "Preparando la venta",
    "compras": "Preparando la compra",
}

_analisis_hechos = 0


def _avisar_progreso(texto: str) -> None:
    """Una frase corta de lo que esta pasando, para la linea de estado del chat."""
    funcion = _progreso
    if funcion is not None and _activa is not None:
        try:
            funcion(texto)
        except Exception:
            pass


def _limpio(texto: str, largo: int = 300) -> str:
    """PII fuera y sin el id de organizacion que Groq incluye en cada 429."""
    return _ORG.sub("org_REDACTADA", sanitizar_pii(texto))[:largo]


def _ms_desde_inicio(momento: datetime) -> float:
    return round((momento.timestamp() - _t0) * 1000, 2)


def _llamada_llm(rol, modelo, inicio, fin, estado, tokens_entrada, tokens_salida, detalle):
    if estado == "rate_limit":
        _avisar_progreso("Esperando disponibilidad del modelo")
    with _lock:
        if _activa is None:
            return
        _activa.agregar_evento(
            etapa=f"llm:{rol}" if rol else "llm:interno",
            inicio_ms=round((inicio - _t0) * 1000, 2),
            duracion_ms=round((fin - inicio) * 1000, 2),
            estado="ok" if estado == "ok" else "error",
            agente=rol,
            modelo=modelo,
            tokens_entrada=tokens_entrada,
            tokens_salida=tokens_salida,
            detalle="rate limit" if estado == "rate_limit" else _limpio(detalle),
        )


def _fase(traza: Traza, etapa: str, inicio: float, estado: str = "ok", detalle: str = "") -> None:
    with _lock:
        traza.agregar_evento(
            etapa=etapa,
            inicio_ms=round((inicio - _t0) * 1000, 2),
            duracion_ms=round((time.time() - inicio) * 1000, 2),
            estado=estado,
            detalle=detalle,
        )


def _llm_empieza(rol: str | None) -> None:
    """El gerente piensa al principio (entender el pedido) y al final (armar
    la respuesta). Los demas roles ya quedan descritos por su herramienta, y
    las llamadas sin rol son internas de la memoria: no se anuncian."""
    global _analisis_hechos
    if rol != "Gerente de tienda":
        return
    _analisis_hechos += 1
    _avisar_progreso("Analizando el pedido" if _analisis_hechos == 1 else "Preparando la respuesta")


@crewai_event_bus.on(ToolUsageStartedEvent)
def _tool_inicio(_, evento):
    nombre = evento.tool_name.lower().replace(" ", "_")
    if "coworker" in nombre:
        args = evento.tool_args if isinstance(evento.tool_args, dict) else {}
        destino = str(args.get("coworker") or "").lower()
        frase = next((f for clave, f in _FRASES_DELEGACION.items() if clave in destino), None)
        _avisar_progreso(frase or "Asignando la tarea")
        return
    frase = next((f for clave, f in _FRASES_TOOL.items() if clave in nombre), None)
    _avisar_progreso(frase or f"Usando {evento.tool_name}")


@crewai_event_bus.on(MemoryQueryStartedEvent)
def _mem_consulta_inicio(_, e):
    _avisar_progreso("Revisando el contexto de la conversación")


@crewai_event_bus.on(MemorySaveStartedEvent)
def _mem_guardado_inicio(_, e):
    _avisar_progreso("Actualizando la memoria")


@crewai_event_bus.on(ToolUsageFinishedEvent)
def _tool_fin(_, evento):
    with _lock:
        if _activa is None:
            return
        _activa.agregar_evento(
            etapa=f"tool:{evento.tool_name}",
            inicio_ms=_ms_desde_inicio(evento.started_at),
            duracion_ms=round((evento.finished_at - evento.started_at).total_seconds() * 1000, 2),
            agente=evento.agent_role,
            detalle=_limpio(str(evento.output), 200),
        )


@crewai_event_bus.on(ToolUsageErrorEvent)
def _tool_error(_, evento):
    with _lock:
        if _activa is None:
            return
        _activa.agregar_evento(
            etapa=f"tool:{evento.tool_name}",
            inicio_ms=_ms_desde_inicio(evento.timestamp),
            duracion_ms=0.0,
            estado="error",
            agente=evento.agent_role,
            detalle=_limpio(str(evento.error)),
        )


def _memoria(evento, etapa: str, estado: str, duracion_ms: float, detalle: str = "") -> None:
    with _lock:
        if _activa is None:
            return
        _activa.agregar_evento(
            etapa=etapa,
            inicio_ms=round(_ms_desde_inicio(evento.timestamp) - duracion_ms, 2),
            duracion_ms=round(duracion_ms, 2),
            estado=estado,
            agente=getattr(evento, "agent_role", None),
            detalle=detalle,
        )


@crewai_event_bus.on(MemoryQueryCompletedEvent)
def _mem_consulta(_, e):
    _memoria(e, "memoria:consulta", "ok", e.query_time_ms)


@crewai_event_bus.on(MemoryQueryFailedEvent)
def _mem_consulta_falla(_, e):
    _memoria(e, "memoria:consulta", "error", 0.0, _limpio(str(getattr(e, "error", ""))))


@crewai_event_bus.on(MemorySaveCompletedEvent)
def _mem_guardado(_, e):
    _memoria(e, "memoria:guardado", "ok", e.save_time_ms)


@crewai_event_bus.on(MemorySaveFailedEvent)
def _mem_guardado_falla(_, e):
    _memoria(e, "memoria:guardado", "error", 0.0, _limpio(str(getattr(e, "error", ""))))


# --- Ejecucion observada -----------------------------------------------

Verificador = Callable[[str], tuple[bool, str]]


def observar(mensaje: str, caso: str = "chat", conversacion_id: str | None = None,
             verificar: Verificador | None = None, guardar: bool = True,
             al_progreso: Callable[[str], None] | None = None, etiqueta: str = "") -> Traza:
    """Corre el crew sobre `mensaje` y devuelve su traza.

    Una inyeccion detectada corta antes del crew: la traza queda `bloqueado`
    con `validacion_entrada` en error y cero llamadas al LLM. `verificar`
    recibe la respuesta y compara contra la base (precision, IE1).
    """
    global _activa, _t0, _progreso, _analisis_hechos
    import agentes

    if _llamada_llm not in agentes.OBSERVADORES_LLM:
        agentes.OBSERVADORES_LLM.append(_llamada_llm)
    if _llm_empieza not in agentes.AL_EMPEZAR_LLM:
        agentes.AL_EMPEZAR_LLM.append(_llm_empieza)

    traza = Traza(
        trace_id=uuid.uuid4().hex[:12],
        conversacion_id=conversacion_id or uuid.uuid4().hex[:8],
        caso=caso,
        timestamp=datetime.now().isoformat(timespec="seconds"),
        mensaje_entrada=sanitizar_pii(mensaje),
        etiqueta=etiqueta,
    )
    t0 = time.perf_counter()
    _t0 = time.time()

    bloqueado = detecto_injection(mensaje)
    _fase(traza, "validacion_entrada", _t0, "error" if bloqueado else "ok",
          "patron de inyeccion" if bloqueado else f"{len(mensaje)} caracteres")

    if bloqueado:
        traza.estado = "bloqueado"
        traza.respuesta_final = "Mensaje bloqueado por el filtro de entrada."
    else:
        inicio = time.time()
        crew = agentes.crear_crew(mensaje, conversacion_id=traza.conversacion_id)
        _fase(traza, "crew:preparacion", inicio)

        with _lock:
            _activa, _progreso, _analisis_hechos = traza, al_progreso, 0
        _avisar_progreso("Leyendo el pedido")
        inicio = time.time()
        try:
            traza.respuesta_final = str(crew.kickoff())
            _fase(traza, "crew:kickoff", inicio)
        except Exception as e:
            traza.estado = "error"
            traza.error = _limpio(f"{type(e).__name__}: {e}", 500)
            _fase(traza, "crew:kickoff", inicio, "error", traza.error)
        finally:
            inicio = time.time()
            crewai_event_bus.flush(timeout=30)
            with _lock:
                _activa, _progreso = None, None
            agentes.forzar_envio_a_langsmith()
            _fase(traza, "crew:cierre", inicio, detalle="flush de eventos y de LangSmith")

        # crew.usage_metrics suma el LLM una vez por agente que lo usa y al
        # manager dos veces (crewai/crew.py, calculate_usage_metrics): con un
        # LLM compartido infla el total ~2,5x. Se guarda solo como referencia.
        uso = getattr(crew, "usage_metrics", None)
        traza.tokens_reportados_crewai = getattr(uso, "total_tokens", 0) or 0
        llamadas = [e for e in traza.eventos if e.etapa.startswith("llm:")]
        traza.tokens_entrada = sum(e.tokens_entrada for e in llamadas)
        traza.tokens_salida = sum(e.tokens_salida for e in llamadas)
        traza.llamadas_llm = sum(1 for e in llamadas if e.estado == "ok")

    traza.duracion_ms = round((time.perf_counter() - t0) * 1000, 2)
    traza.eventos.sort(key=lambda e: e.inicio_ms)

    if verificar is not None and traza.respuesta_final is not None:
        traza.correcto, traza.verificacion = verificar(traza.respuesta_final)

    if guardar:
        guardar_traza(traza)
    return traza


def guardar_traza(traza: Traza, archivo: Path = ARCHIVO_TRAZAS) -> None:
    """La respuesta se redacta al guardar, no antes: al dueño se le muestra
    completa (el correo de su proveedor es dato del negocio), al log no."""
    datos = traza.a_dict()
    if datos.get("respuesta_final"):
        datos["respuesta_final"] = sanitizar_pii(datos["respuesta_final"])
    archivo.parent.mkdir(parents=True, exist_ok=True)
    with archivo.open("a", encoding="utf-8") as f:
        f.write(json.dumps(datos, ensure_ascii=False) + "\n")


def cargar_trazas(archivo: Path = ARCHIVO_TRAZAS) -> list[Traza]:
    if not archivo.exists():
        return []
    with archivo.open(encoding="utf-8") as f:
        return [Traza.desde_dict(json.loads(linea)) for linea in f if linea.strip()]


def metricas_de(trazas: list[Traza]) -> RecolectorMetricas:
    recolector = RecolectorMetricas()
    for t in trazas:
        recolector.registrar(
            t.duracion_ms, t.tokens_entrada, t.tokens_salida,
            exitoso=t.estado != "error",
            modelo=",".join(t.modelos) or "-",
            correcto=t.correcto,
        )
    return recolector


def comparar(trazas: list[Traza]) -> list[dict]:
    """Una fila por etiqueta (configuracion medida): para la tabla de IE7."""
    grupos: dict[str, list[Traza]] = {}
    for t in trazas:
        if t.etiqueta:
            grupos.setdefault(t.etiqueta, []).append(t)
    filas = []
    for etiqueta, grupo in grupos.items():
        resumen = metricas_de(grupo).resumen()
        limites = [sum(1 for e in t.eventos if e.etapa.startswith("llm:") and e.detalle == "rate limit")
                   for t in grupo]
        filas.append({
            "configuracion": etiqueta,
            "corridas": len(grupo),
            "precision_pct": resumen["precision_pct"],
            "errores_pct": resumen["tasa_errores_pct"],
            "p50_s": round(resumen["tiempo_p50_ms"] / 1000, 1),
            "p95_s": round(resumen["tiempo_p95_ms"] / 1000, 1),
            "tokens_prom": round(resumen["total_tokens"] / len(grupo)),
            "llamadas_prom": round(statistics.mean(t.llamadas_llm for t in grupo), 1),
            "rate_limits_prom": round(statistics.mean(limites), 1),
        })
    return filas


if __name__ == "__main__":
    import sys

    trazas = cargar_trazas()
    if not trazas:
        print(f"No hay trazas en {ARCHIVO_TRAZAS}. Corre bateria.py o usa el chat de app.py.")
        sys.exit(0)

    if "--comparar" in sys.argv:
        filas = comparar(trazas)
        if not filas:
            print("No hay corridas con etiqueta. Corre bateria.py primero.")
            sys.exit(0)
        columnas = list(filas[0])
        print(" | ".join(columnas))
        for f in filas:
            print(" | ".join(str(f[c]) for c in columnas))
        sys.exit(0)

    print(f"{len(trazas)} trazas en {ARCHIVO_TRAZAS}\n")
    for t in trazas[-10:]:
        marca = {True: "OK ", False: "MAL", None: " - "}[t.correcto]
        print(f"[{marca}] {t.timestamp}  {t.trace_id}  {t.caso:<22} {t.estado:<9} "
              f"{t.duracion_ms / 1000:6.1f}s {t.tokens_totales:>7} tok  {t.verificacion or ''}")

    if len(sys.argv) > 1:
        elegida = next((t for t in trazas if t.trace_id.startswith(sys.argv[1])), None)
        if elegida:
            print(f"\nEventos de {elegida.trace_id}:")
            for e in elegida.eventos:
                print(f"  {e.inicio_ms / 1000:7.1f}s {e.duracion_ms / 1000:6.1f}s {e.estado:5} "
                      f"{e.etapa:<34} {e.modelo or '':<22} {e.tokens_entrada + e.tokens_salida:>6} tok")
            print(f"\nRespuesta: {elegida.respuesta_final}")

    print("\nMetricas (IL3.1):")
    print(json.dumps(metricas_de(trazas).resumen(), indent=2, ensure_ascii=False))
    print("\nAnalisis de trazas (IL3.2):")
    print(json.dumps(AnalizadorTrazas.resumir(trazas), indent=2, ensure_ascii=False))
