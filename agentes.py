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

from crewai import LLM, Agent, Crew, Process, Task
from crewai.tools import tool
from dotenv import load_dotenv

from gmail_tool import enviar_correo as _enviar_correo
from stock import (
    consultar_stock,
    historial_producto,
    productos_bajo_minimo,
    registrar_reposicion,
    registrar_venta,
)

load_dotenv()


class LLMGroq(LLM):
    """Groq rechaza con 400 el `cache_breakpoint` que CrewAI 1.15 agrega
    al mensaje de sistema para el prompt caching de Anthropic."""

    def _format_messages_for_provider(self, messages):
        limpios = [{k: v for k, v in m.items() if k != "cache_breakpoint"} for m in messages]
        return super()._format_messages_for_provider(limpios)


def modelo() -> LLMGroq:
    return LLMGroq(
        model=f"groq/{os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b')}",
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
        f"#{p.id} {p.nombre} — stock {p.stock_actual} (min {p.stock_minimo})"
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
        f"#{p.id} {p.nombre} — stock {p.stock_actual} — proveedor {p.proveedor_email}"
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
    """Descuenta stock por una venta. Falla si no alcanza el stock."""
    p = registrar_venta(producto_id, cantidad)
    return f"Venta registrada. {p.nombre} queda en {p.stock_actual} unidades."


@tool("registrar reposicion")
def tool_registrar_reposicion(producto_id: int, cantidad: int) -> str:
    """Suma stock cuando llega un pedido del proveedor."""
    p = registrar_reposicion(producto_id, cantidad)
    return f"Reposicion registrada. {p.nombre} queda en {p.stock_actual} unidades."


@tool("enviar correo a proveedor")
def tool_enviar_correo(destinatario: str, asunto: str, cuerpo: str) -> str:
    """Envia un correo real al proveedor (orden de reposicion)."""
    id_msg = _enviar_correo(destinatario, asunto, cuerpo)
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
