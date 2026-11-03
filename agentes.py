"""Agentes de la tienda, con roles y tools acotadas.

Reparto de herramientas (nadie tiene mas de lo que necesita):
    Inventario  -> solo lectura de stock
    Ventas      -> registrar_venta
    Compras     -> registrar_reposicion + enviar_correo (unico con Gmail)
    Manager     -> sin tools, solo delega

CrewAI en vez de LangGraph: los tres roles tienen prompts de sistema
incompatibles entre si (vender no es lo mismo que negociar con un
proveedor), que es el caso que la plantilla del curso acepta para
justificar el framework (ver ADR en el README).
"""

import os
import time

import litellm
from crewai import LLM, Agent, Crew, Process, Task
from crewai.tools import tool
from dotenv import load_dotenv

from gmail_tool import enviar_correo as _enviar_correo
from guardrails import dato_seguro
from stock import (
    consultar_stock,
    historial_producto,
    productos_bajo_minimo,
    proveedores_registrados,
    registrar_reposicion,
    registrar_venta,
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


class LLMConFallback(LLMGroq):
    """Si Groq devuelve rate limit, reintenta con el siguiente modelo de
    MODELOS_FALLBACK en vez de fallar. Cada modelo tiene su propio balde
    de 8000 tokens/minuto — rotar entre ellos evita la espera, no la cuota
    total (siguen siendo recursos finitos, solo que separados).

    Cada intento se reporta a OBSERVADORES_LLM con su modelo y sus tokens:
    los eventos de CrewAI llegan sin `usage` en la mayoria de las llamadas."""

    def call(self, messages, **kwargs):
        import litellm as _litellm

        rol = getattr(kwargs.get("from_agent"), "role", None)
        errores = []
        for modelo_intento in MODELOS_FALLBACK:
            self.model = f"groq/{modelo_intento}"
            antes = dict(self._token_usage)
            inicio = time.time()
            try:
                respuesta = super().call(messages, **kwargs)
            except _litellm.RateLimitError as e:
                _avisar(rol, modelo_intento, inicio, "rate_limit", antes, self._token_usage, str(e))
                errores.append(f"{modelo_intento}: rate limit")
                continue
            except Exception as e:
                _avisar(rol, modelo_intento, inicio, "error", antes, self._token_usage,
                        f"{type(e).__name__}: {e}")
                raise
            _avisar(rol, modelo_intento, inicio, "ok", antes, self._token_usage)
            return respuesta
        raise RuntimeError(
            f"Los {len(MODELOS_FALLBACK)} modelos de fallback estan sin cupo: "
            + "; ".join(errores)
        )


OBSERVADORES_LLM: list = []


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


@tool("historial de movimientos del producto")
def tool_historial_producto(producto_id: int) -> str:
    """Memoria de largo plazo: ventas e ingresos pasados de un producto,
    para decidir si conviene reponer ahora o esperar."""
    movs = historial_producto(producto_id)
    if not movs:
        return "Sin movimientos registrados para este producto."
    return "\n".join(f"{m['fecha']} — {m['tipo']} de {m['cantidad']}" for m in movs)


@tool("registrar venta")
def tool_registrar_venta(producto_id: int, cantidad: int) -> str:
    """Descuenta stock por una venta. Falla si no alcanza el stock.

    Planificacion adaptativa: si la venta deja el producto en su minimo
    o por debajo, dispara la reposicion sola (no espera a que alguien
    pregunte). El disparo es deterministico — se decide con un numero,
    no con que el LLM se acuerde de avisar — pero el contenido del
    correo lo sigue redactando el agente de Compras.
    """
    p = registrar_venta(producto_id, cantidad)
    mensaje = f"Venta registrada. {_nombre(p)} queda en {p.stock_actual} unidades."

    if p.stock_actual <= p.stock_minimo:
        cantidad_pedido = max(p.stock_minimo * 2 - p.stock_actual, p.stock_minimo)
        resultado_compra = generar_orden_compra(_nombre(p), cantidad_pedido, p.proveedor_email)
        mensaje += (
            f" Quedo en el minimo ({p.stock_minimo}) o bajo el, se genero la "
            f"reposicion automatica: {resultado_compra}"
        )
    return mensaje


@tool("registrar reposicion")
def tool_registrar_reposicion(producto_id: int, cantidad: int) -> str:
    """Suma stock cuando llega un pedido del proveedor."""
    p = registrar_reposicion(producto_id, cantidad)
    return f"Reposicion registrada. {_nombre(p)} queda en {p.stock_actual} unidades."


@tool("enviar correo a proveedor")
def tool_enviar_correo(destinatario: str, asunto: str, cuerpo: str) -> str:
    """Envia un correo real al proveedor (orden de reposicion). Solo a
    direcciones de proveedores registrados en la base."""
    # El destinatario lo escribe el LLM: una inyeccion que llegue hasta Compras
    # podria apuntar el correo a cualquier parte. Se decide contra la base.
    if destinatario.strip().lower() not in proveedores_registrados():
        return f"Rechazado: {destinatario!r} no es un proveedor registrado. No se envio nada."
    id_msg = _enviar_correo(destinatario.strip(), asunto, cuerpo)
    return f"Correo enviado, id={id_msg}"


# --- Agentes ------------------------------------------------------------

def crear_agentes() -> dict[str, Agent]:
    llm = modelo()

    inventario = Agent(
        role="Encargado de inventario",
        goal="Informar el estado del stock con precision, sin modificar nada",
        backstory="Solo consultas. Nunca decides ventas ni compras.",
        tools=[tool_consultar_stock, tool_bajo_minimo, tool_historial_producto],
        llm=llm,
        verbose=False,
    )
    ventas = Agent(
        role="Vendedor",
        goal="Registrar ventas y avisar si el stock queda bajo el minimo",
        backstory="Atiendes al cliente. No contactas proveedores.",
        tools=[tool_registrar_venta, tool_bajo_minimo],
        llm=llm,
        verbose=False,
    )
    compras = Agent(
        role="Encargado de compras",
        goal="Reponer stock y comunicarse con proveedores por correo",
        backstory="Redactas ordenes de reposicion claras y las envias.",
        tools=[tool_registrar_reposicion, tool_enviar_correo],
        llm=llm,
        verbose=False,
    )
    return {"inventario": inventario, "ventas": ventas, "compras": compras}


def crear_crew(mensaje: str, conversacion_id: str = "default") -> Crew:
    """Crew general: el manager delega entre Inventario y Ventas.

    No se usa para enviar correos — ver `generar_orden_compra` para esa ruta.
    El manager razona bien sobre a quien correspondería un correo, pero no
    siempre invoca la delegacion real; una accion con efecto en el mundo
    real (mandar un correo de verdad) no puede depender de que el LLM
    decida ejecutarla.

    Memoria corto plazo (IE3): nativa de CrewAI (`memory=True`), con
    `root_scope` por `conversacion_id` — mismo rol que el `thread_id` de
    LangGraph, aisla lo que un cliente pregunto de lo que pregunto otro.
    Embedder local (`sentence-transformer`): Groq no ofrece endpoint de
    embeddings, mismo motivo por el que el curso usa HuggingFace en el RAG.
    """
    agentes = crear_agentes()
    llm = modelo()

    manager = Agent(
        role="Gerente de tienda",
        goal="Delegar cada tarea al único rol que tiene la herramienta correcta",
        backstory=(
            "No ejecutas tareas tu mismo, solo delegas. Las ventas van al "
            "Vendedor. Las consultas de stock van al Encargado de inventario."
        ),
        allow_delegation=True,
        llm=llm,
        verbose=False,
    )

    tarea = Task(
        description=mensaje,
        expected_output="Resultado de la operacion, en lenguaje claro para el dueno.",
        agent=agentes["ventas"],  # placeholder; el manager reasigna
    )
    return Crew(
        agents=list(agentes.values()),
        tasks=[tarea],
        process=Process.hierarchical,
        manager_agent=manager,
        memory=True,
        embedder={
            "provider": "sentence-transformer",
            "config": {"model_name": "all-MiniLM-L6-v2"},
        },
        name=f"tienda-{conversacion_id}",
        verbose=True,
    )


def generar_orden_compra(producto_nombre: str, cantidad: int, proveedor_email: str) -> str:
    """Ruta directa al agente de Compras para una accion obligatoria.

    No pasa por el manager: enviar un correo real es una accion con
    efecto en el mundo real, no una decision que convenga dejar en manos
    de que el LLM elija delegarla o no (ver hallazgo en el README).
    """
    compras = crear_agentes()["compras"]
    tarea = Task(
        description=(
            f"Redacta y envia (con la herramienta de correo) una orden de "
            f"reposicion de {cantidad} unidades de '{producto_nombre}' al "
            f"proveedor {proveedor_email}. Es obligatorio usar la herramienta "
            f"de enviar correo, no basta con redactar el texto."
        ),
        expected_output="Confirmacion de que el correo se envio, con su id.",
        agent=compras,
    )
    crew = Crew(agents=[compras], tasks=[tarea], verbose=True)
    return str(crew.kickoff())


if __name__ == "__main__":
    crew = crear_crew("Vende 2 unidades del producto #4 y dime como queda el stock.")
    print(crew.kickoff())
    forzar_envio_a_langsmith()
