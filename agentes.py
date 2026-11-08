"""Agentes de la tienda, con roles y tools acotadas.

Reparto de herramientas (nadie tiene mas de lo que necesita):
    Inventario  -> solo lectura de stock
    Ventas      -> registrar_venta
    Compras     -> registrar_reposicion + preparar correo (unico que llega a Gmail)
    Manager     -> sin tools, solo delega

Reponer y escribir a un proveedor quedan pendientes hasta que el dueño los
aprueba (pendientes.py); el envio real lo hace la app, no un agente.

CrewAI en vez de LangGraph: los tres roles tienen prompts de sistema
incompatibles entre si (vender no es lo mismo que negociar con un
proveedor), que es el caso que la plantilla del curso acepta para
justificar el framework (ver ADR en el README).
"""

import os
import re
import threading
import time

import litellm
from crewai import LLM, Agent, Crew, Process, Task
from crewai.tools import tool
from dotenv import load_dotenv

import pendientes
from guardrails import dato_seguro
from stock import (
    consultar_stock,
    historial_producto,
    productos_bajo_minimo,
    proveedores_registrados,
    registrar_venta,
    resolver_producto,
)


def _nombre(p) -> str:
    """El nombre de un producto es un dato de la base, no una instruccion: si
    trae una (inyeccion indirecta), al prompt llega solo su id."""
    return dato_seguro(p.nombre, f"[producto #{p.id}: nombre con instrucciones, omitido]")

load_dotenv()

# Observabilidad (opcional, no rompe nada si no hay key): litellm manda cada
# llamada real a Groq a LangSmith -- input/output completo (el "thinking"),
# tokens y latencia por paso. No es migrar a LangChain, es usar su
# herramienta de trazas por debajo de CrewAI, que ya corre sobre litellm.
# Activar: LANGSMITH_API_KEY + LANGSMITH_TRACING=true en el .env.
if os.getenv("LANGSMITH_TRACING", "").lower() == "true" and os.getenv("LANGSMITH_API_KEY"):
    litellm.success_callback = ["langsmith"]
    litellm.failure_callback = ["langsmith"]


def forzar_envio_a_langsmith() -> None:
    """litellm encola las trazas y las manda cada 5s, pero solo si hay un
    event loop de asyncio corriendo -- CrewAI corre sincronico (kickoff()),
    asi que la cola nunca se vacia sola. Llamar despues de cada kickoff()
    para vaciarla a mano. No hace nada si LangSmith esta apagado."""
    if os.getenv("LANGSMITH_TRACING", "").lower() != "true":
        return
    import asyncio

    from litellm.integrations.langsmith import LangsmithLogger
    from litellm.litellm_core_utils.litellm_logging import _in_memory_loggers

    logger = next((c for c in _in_memory_loggers if isinstance(c, LangsmithLogger)), None)
    if logger is not None and logger.log_queue:
        asyncio.run(logger.async_send_batch())


class LLMGroq(LLM):
    """Groq rechaza con 400 el `cache_breakpoint` que CrewAI 1.15 agrega
    al mensaje de sistema para el prompt caching de Anthropic."""

    def _format_messages_for_provider(self, messages):
        limpios = [{k: v for k, v in m.items() if k != "cache_breakpoint"} for m in messages]
        return super()._format_messages_for_provider(limpios)


# Modelos de Groq con cupo SEPARADO (8000 tokens/minuto es por modelo, no
# por cuenta). Si el principal se queda sin cupo, salta al siguiente antes
# de darse por vencido.
MODELOS_FALLBACK = [
    os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
]


# Topes por mensaje (LLM06:2026, Unbounded Consumption). Sin ellos, un solo
# pedido largo agoto el cupo por minuto de los tres modelos: 47 rechazos y
# 45 000 tokens antes de caerse.
PRESUPUESTO_TOKENS = int(os.getenv("PRESUPUESTO_TOKENS_MENSAJE", "40000"))
MAX_LIMITES = int(os.getenv("MAX_RATE_LIMITS_MENSAJE", "12"))


class PresupuestoAgotado(RuntimeError):
    pass


_peticion = {"tokens": 0, "limites": 0}
_hechas: set[tuple] = set()
_lock = threading.Lock()


def nueva_peticion() -> None:
    """Reinicia los topes y el registro de operaciones de un mensaje."""
    with _lock:
        _peticion.update(tokens=0, limites=0)
        _hechas.clear()


def _espera_sugerida(error: Exception) -> float:
    m = re.search(r"try again in ([\d.]+)s", str(error))
    return min(float(m.group(1)), 10.0) if m else 2.0


class LLMConFallback(LLMGroq):
    """Si Groq devuelve rate limit, reintenta con el siguiente modelo de
    MODELOS_FALLBACK. Si los tres estan sin cupo espera lo que Groq sugiere
    (maximo 10 s) una sola vez, en vez de que CrewAI reintente en rafaga.

    Cada intento se reporta a OBSERVADORES_LLM con su modelo y sus tokens:
    los eventos de CrewAI llegan sin `usage` en la mayoria de las llamadas."""

    def call(self, messages, **kwargs):
        import litellm as _litellm

        rol = getattr(kwargs.get("from_agent"), "role", None)
        errores = []
        for ronda in range(2):
            espera = 2.0
            for modelo_intento in MODELOS_FALLBACK:
                with _lock:
                    if _peticion["tokens"] >= PRESUPUESTO_TOKENS:
                        raise PresupuestoAgotado(
                            f"Se alcanzo el tope de {PRESUPUESTO_TOKENS} tokens para este mensaje"
                        )
                    if _peticion["limites"] >= MAX_LIMITES:
                        raise PresupuestoAgotado(
                            f"Groq rechazo {MAX_LIMITES} llamadas por limite en este mensaje"
                        )
                self.model = f"groq/{modelo_intento}"
                for avisar in AL_EMPEZAR_LLM:
                    avisar(rol)
                antes = dict(self._token_usage)
                inicio = time.time()
                try:
                    respuesta = super().call(messages, **kwargs)
                except _litellm.RateLimitError as e:
                    with _lock:
                        _peticion["limites"] += 1
                    _avisar(rol, modelo_intento, inicio, "rate_limit", antes, self._token_usage, str(e))
                    errores.append(f"{modelo_intento}: rate limit")
                    espera = _espera_sugerida(e)
                    continue
                except Exception as e:
                    _avisar(rol, modelo_intento, inicio, "error", antes, self._token_usage,
                            f"{type(e).__name__}: {e}")
                    raise
                usados = (self._token_usage["prompt_tokens"] - antes["prompt_tokens"]
                          + self._token_usage["completion_tokens"] - antes["completion_tokens"])
                with _lock:
                    _peticion["tokens"] += usados
                _avisar(rol, modelo_intento, inicio, "ok", antes, self._token_usage)
                return respuesta
            if ronda == 0:
                time.sleep(espera)
        raise RuntimeError(
            f"Los {len(MODELOS_FALLBACK)} modelos de fallback estan sin cupo: "
            + "; ".join(errores)
        )


OBSERVADORES_LLM: list = []
AL_EMPEZAR_LLM: list = []


def _avisar(rol, modelo_usado, inicio, estado, antes, despues, detalle=""):
    for observador in OBSERVADORES_LLM:
        observador(
            rol=rol,
            modelo=modelo_usado,
            inicio=inicio,
            fin=time.time(),
            estado=estado,
            tokens_entrada=despues["prompt_tokens"] - antes["prompt_tokens"],
            tokens_salida=despues["completion_tokens"] - antes["completion_tokens"],
            detalle=detalle,
        )


def modelo() -> LLMConFallback:
    return LLMConFallback(
        model=f"groq/{MODELOS_FALLBACK[0]}",
        temperature=0.2,
    )


# --- Tools, una por rol ------------------------------------------------

@tool("consultar stock")
def tool_consultar_stock(nombre_parcial: str = "") -> str:
    """Busca productos por nombre parcial. Vacio devuelve todo el stock."""
    productos = consultar_stock(nombre_parcial)
    if not productos:
        return "No hay productos que coincidan."
    return "\n".join(
        f"#{p.id} {_nombre(p)} — stock {p.stock_actual} (min {p.stock_minimo})"
        for p in productos
    )


@tool("productos bajo minimo")
def tool_bajo_minimo(filtro: str = "") -> str:
    """Lista los productos cuyo stock esta en o bajo el minimo, con el
    correo de su proveedor (necesario para generar la orden de compra).

    No necesita argumentos reales; `filtro` existe solo porque Groq
    rechaza el JSON Schema de una tool sin parametros ('required'
    presente pero 'properties' ausente). Un nombre con guion bajo
    inicial (`_filtro`) no sirve: pydantic lo trata como atributo
    privado y lo excluye del schema igual.
    """
    productos = productos_bajo_minimo()
    if not productos:
        return "Ningun producto esta bajo su minimo."
    return "\n".join(
        f"#{p.id} {_nombre(p)} — stock {p.stock_actual} — proveedor {p.proveedor_email}"
        for p in productos
    )


def _una_vez(*clave) -> bool:
    """False si esta misma operacion ya se hizo en este mensaje. Un agente
    que reintenta no debe registrar dos veces la misma venta o reposicion."""
    with _lock:
        if clave in _hechas:
            return False
        _hechas.add(clave)
        return True


@tool("historial de movimientos del producto")
def tool_historial_producto(producto: str) -> str:
    """Ventas e ingresos pasados de un producto (nombre o #id), para decidir
    si conviene reponer ahora o esperar."""
    p = resolver_producto(producto)
    movs = historial_producto(p.id)
    if not movs:
        return f"Sin movimientos registrados para {_nombre(p)}."
    return "\n".join(f"{m['fecha']} — {m['tipo']} de {m['cantidad']}" for m in movs)


@tool("registrar venta")
def tool_registrar_venta(producto: str, cantidad: int) -> str:
    """Descuenta stock por una venta. `producto` es el nombre o el #id.
    Falla si no alcanza el stock.

    Planificacion adaptativa: si la venta deja el producto en su minimo o
    por debajo, se prepara sola la orden al proveedor (la decide un numero,
    no el LLM) y queda pendiente de aprobacion del dueño.
    """
    p = resolver_producto(producto)
    if not _una_vez("venta", p.id, cantidad):
        return f"Esa venta de {_nombre(p)} ya se registro en este pedido. No se repite."
    p = registrar_venta(p.id, cantidad)
    mensaje = f"Venta registrada. {_nombre(p)} queda en {p.stock_actual} unidades."

    if p.stock_actual <= p.stock_minimo:
        cantidad_pedido = max(p.stock_minimo * 2 - p.stock_actual, p.stock_minimo)
        resultado_compra = generar_orden_compra(_nombre(p), cantidad_pedido, p.proveedor_email)
        mensaje += (
            f" Quedo en el minimo ({p.stock_minimo}) o bajo el, se preparo la "
            f"orden de reposicion: {resultado_compra}"
        )
    return mensaje


@tool("registrar reposicion")
def tool_registrar_reposicion(producto: str, cantidad: int) -> str:
    """Registra la llegada de un pedido del proveedor. `producto` es el nombre
    o el #id. No suma stock: queda pendiente hasta que el dueño la apruebe."""
    p = resolver_producto(producto)
    if not _una_vez("reposicion", p.id, cantidad):
        return f"Esa reposicion de {_nombre(p)} ya quedo pendiente en este pedido. No se repite."
    op = pendientes.proponer_reposicion(p.id, cantidad)
    return (
        f"Reposicion de {cantidad} unidades de {_nombre(p)} pendiente de aprobacion "
        f"del dueño (operacion #{op}). El stock no cambio todavia."
    )


@tool("preparar correo a proveedor")
def tool_enviar_correo(destinatario: str, asunto: str, cuerpo: str) -> str:
    """Prepara un correo a un proveedor registrado. No se envia hasta que el
    dueño lo apruebe en la app."""
    # El destinatario lo escribe el LLM: una inyeccion que llegue hasta Compras
    # podria apuntar el correo a cualquier parte. Se decide contra la base.
    if destinatario.strip().lower() not in proveedores_registrados():
        return f"Rechazado: {destinatario!r} no es un proveedor registrado. No se preparo nada."
    if not _una_vez("correo", destinatario.strip().lower()):
        return "Ya hay un correo preparado para ese proveedor en este pedido. No se repite."
    op = pendientes.proponer_correo(destinatario.strip(), asunto, cuerpo)
    return f"Correo preparado para {destinatario.strip()}, pendiente de aprobacion del dueño (operacion #{op})."


# --- Agentes ------------------------------------------------------------

def crear_agentes() -> dict[str, Agent]:
    llm = modelo()

    inventario = Agent(
        role="Encargado de inventario",
        goal="Informar el estado del stock con precision, sin modificar nada",
        backstory="Solo consultas. Nunca decides ventas ni compras.",
        tools=[tool_consultar_stock, tool_bajo_minimo, tool_historial_producto],
        llm=llm,
        max_iter=6,
        verbose=False,
    )
    ventas = Agent(
        role="Vendedor",
        goal="Registrar ventas y avisar si el stock queda bajo el minimo",
        backstory="Atiendes al cliente. No contactas proveedores.",
        tools=[tool_registrar_venta, tool_bajo_minimo],
        llm=llm,
        max_iter=6,
        verbose=False,
    )
    compras = Agent(
        role="Encargado de compras",
        goal="Registrar reposiciones y preparar correos a proveedores",
        backstory=(
            "Redactas ordenes de reposicion claras. Lo que preparas queda "
            "pendiente: el dueño lo aprueba antes de que se ejecute."
        ),
        tools=[tool_registrar_reposicion, tool_enviar_correo],
        llm=llm,
        max_iter=6,
        verbose=False,
    )
    return {"inventario": inventario, "ventas": ventas, "compras": compras}


def memoria_activa() -> bool:
    """MEMORIA_CREW=false apaga la memoria de CrewAI (para medir su costo)."""
    return os.getenv("MEMORIA_CREW", "true").lower() != "false"


def crear_crew(mensaje: str, conversacion_id: str = "default") -> Crew:
    """Crew general: el manager delega entre Inventario, Ventas y Compras.

    La orden automatica al proveedor no pasa por aqui: ver
    `generar_orden_compra`. Lo que cambia stock fuera de una venta, o le
    escribe a un proveedor, queda pendiente de aprobacion (`pendientes.py`).

    Memoria corto plazo (IE3): nativa de CrewAI (`memory=True`), con
    `root_scope` por `conversacion_id` — mismo rol que el `thread_id` de
    LangGraph, aisla lo que un cliente pregunto de lo que pregunto otro.
    Embedder local (`sentence-transformer`): Groq no ofrece endpoint de
    embeddings, mismo motivo por el que el curso usa HuggingFace en el RAG.
    """
    nueva_peticion()
    agentes = crear_agentes()
    llm = modelo()

    manager = Agent(
        role="Gerente de tienda",
        goal="Delegar cada tarea al único rol que tiene la herramienta correcta",
        backstory=(
            "No ejecutas tareas tu mismo, solo delegas. Las ventas van al "
            "Vendedor. Las consultas de stock van al Encargado de inventario. "
            "Las reposiciones y correos a proveedores van al Encargado de compras."
        ),
        allow_delegation=True,
        llm=llm,
        max_iter=8,
        verbose=False,
    )

    # Sin `agent`: con un agente asignado, CrewAI le da al manager herramientas
    # para delegar SOLO a ese agente (crewai/crew.py, _update_manager_tools).
    tarea = Task(
        description=mensaje,
        expected_output="Resultado de la operacion, en lenguaje claro para el dueno.",
    )
    return Crew(
        agents=list(agentes.values()),
        tasks=[tarea],
        process=Process.hierarchical,
        manager_agent=manager,
        memory=memoria_activa(),
        embedder={
            "provider": "sentence-transformer",
            "config": {"model_name": "all-MiniLM-L6-v2"},
        },
        name=f"tienda-{conversacion_id}",
        verbose=os.getenv("CREW_VERBOSE", "").lower() == "true",
    )


def generar_orden_compra(producto_nombre: str, cantidad: int, proveedor_email: str) -> str:
    """Ruta directa al agente de Compras para una accion obligatoria.

    No pasa por el manager: la orden se prepara siempre que la regla lo
    pide, no cuando el LLM decide delegarla. El correo queda pendiente de
    aprobacion del dueño.
    """
    compras = crear_agentes()["compras"]
    tarea = Task(
        description=(
            f"Redacta una orden de reposicion de {cantidad} unidades de "
            f"'{producto_nombre}' para el proveedor {proveedor_email} y dejala "
            f"preparada con la herramienta de correo. Es obligatorio usar la "
            f"herramienta, no basta con redactar el texto."
        ),
        expected_output="Confirmacion de que el correo quedo preparado, con su numero de operacion.",
        agent=compras,
    )
    crew = Crew(agents=[compras], tasks=[tarea],
                verbose=os.getenv("CREW_VERBOSE", "").lower() == "true")
    return str(crew.kickoff())


if __name__ == "__main__":
    crew = crear_crew("Vende 2 unidades del producto #4 y dime como queda el stock.")
    print(crew.kickoff())
    forzar_envio_a_langsmith()
