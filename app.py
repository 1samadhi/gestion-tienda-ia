"""Front-end (Streamlit) para el dueno de la tienda.

Cuatro pestanas, cada una con costo deliberadamente distinto:

    Stock              directo a stock.py — sin LLM, instantaneo, gratis.
                       Aqui se aprueban las operaciones pendientes.
    Chat               crear_crew() completo, con una linea de estado en vivo
    Logs y costos      lo que ya gasto ESTA sesion (tokens, segundos) —
                       no llama a nada, solo muestra lo acumulado
    Estado del sistema chequeos de archivos locales (token Gmail, DB,
                       memoria) sin tocar la red; el ping a Groq es un
                       boton aparte, nunca automatico — no hay que gastar
                       cupo solo por mirar la pestana

No se uso el tracing nativo de CrewAI a proposito: sube los eventos a
CrewAI Enterprise (su nube), otra cuenta externa que no hace falta.

Uso:
    uv run streamlit run app.py
"""

import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

import pendientes
from agentes import modelo
from db import DB as RUTA_DB
from gmail_tool import enviar_correo
from guardrails import neutralizar_salida, sanitizar_entrada
from observabilidad import observar
from stock import consultar_stock, historial_producto, productos_bajo_minimo

RAIZ = Path(__file__).parent
TOKEN_GMAIL = RAIZ / "gmail_token.json"
MEMORIA_DIR = Path.home() / ".local" / "share" / "gestion-tienda-ia" / "memory"

st.set_page_config(page_title="Gestion de Tienda IA", page_icon="📦", layout="wide")
st.title("📦 Gestion de Tienda IA")

if "conversacion_id" not in st.session_state:
    st.session_state.conversacion_id = str(uuid.uuid4())[:8]
if "mensajes" not in st.session_state:
    st.session_state.mensajes = []
if "registro" not in st.session_state:
    st.session_state.registro = []  # [{hora, mensaje, segundos, tokens}]

tab_stock, tab_chat, tab_logs, tab_estado = st.tabs(
    ["📋 Stock", "💬 Chat", "📊 Logs y costos", "🩺 Estado del sistema"]
)

# --- Pestana 1: stock directo a la base, sin LLM -----------------------

with tab_stock:
    por_aprobar = pendientes.listar()
    if por_aprobar:
        st.subheader(f"Pendientes de aprobación ({len(por_aprobar)})")
        st.caption("Lo propuso un agente. No se ejecuta hasta que lo apruebes.")
        for op in por_aprobar:
            if op["tipo"] == "reposicion":
                texto = f"Reponer **{op['cantidad']}** unidades de **{op['producto']}**"
            else:
                texto = f"Enviar correo a **{op['destinatario']}** — {op['asunto']}"
            col_t, col_a, col_d = st.columns([6, 1, 1])
            col_t.markdown(f"#{op['id']} · {texto}")
            if op["tipo"] == "correo":
                with col_t.expander("Ver correo"):
                    st.text(op["cuerpo"])
            if col_a.button("Aprobar", key=f"ok{op['id']}"):
                try:
                    st.toast(pendientes.aprobar(op["id"], enviar_correo))
                except Exception as e:
                    st.toast(f"No se pudo: {e}")
                st.rerun()
            if col_d.button("Descartar", key=f"no{op['id']}"):
                pendientes.descartar(op["id"])
                st.rerun()
        st.divider()

    col_stock, col_alerta = st.columns(2)

    with col_stock:
        st.subheader("Stock actual")
        productos = consultar_stock("")
        st.dataframe(
            [
                {
                    "ID": p.id,
                    "Producto": p.nombre,
                    "Stock": p.stock_actual,
                    "Minimo": p.stock_minimo,
                    "Bajo minimo": "si" if p.bajo_minimo else "",
                }
                for p in productos
            ],
            width="stretch",
            hide_index=True,
        )

    with col_alerta:
        st.subheader("Bajo el minimo")
        bajos = productos_bajo_minimo()
        if not bajos:
            st.success("Ningun producto esta bajo su minimo.")
        else:
            for p in bajos:
                st.warning(
                    f"**{p.nombre}** — {p.stock_actual}/{p.stock_minimo} "
                    f"— proveedor {p.proveedor_email}"
                )

        with st.expander("Historial de un producto"):
            opciones = {p.nombre: p.id for p in productos}
            elegido = st.selectbox("Producto", list(opciones), label_visibility="collapsed")
            if elegido:
                movs = historial_producto(opciones[elegido])
                if not movs:
                    st.caption("Sin movimientos registrados.")
                else:
                    for m in movs:
                        st.caption(f"{m['fecha']} — {m['tipo']} de {m['cantidad']}")

# --- Pestana 2: chat, pasa por los agentes (CrewAI + Groq) --------------

with tab_chat:
    st.caption(
        "Cada mensaje pasa por el gerente y los agentes (Groq). Para solo mirar "
        "el stock usa la pestaña Stock: es gratis e instantáneo."
    )

    for autor, texto, resumen in st.session_state.mensajes:
        with st.chat_message(autor):
            st.markdown(neutralizar_salida(texto) if autor == "assistant" else texto)
            if resumen:
                st.caption(resumen)

    mensaje = st.chat_input("Ej: Vende 2 unidades del Taladro percutor")
    if mensaje:
        mensaje_limpio = sanitizar_entrada(mensaje)
        st.session_state.mensajes.append(("user", mensaje_limpio, None))
        with st.chat_message("user"):
            st.text(mensaje_limpio)

        with st.chat_message("assistant"):
            linea = st.empty()
            avisos: queue.Queue[str] = queue.Queue()
            resultado = {}
            conversacion = st.session_state.conversacion_id

            def trabajar():
                resultado["traza"] = observar(
                    mensaje_limpio,
                    caso="chat",
                    conversacion_id=conversacion,
                    al_progreso=avisos.put,
                )

            # El crew corre en otro hilo; este hilo solo pinta la linea de
            # estado (Streamlit no deja escribir en la pagina desde otro hilo).
            hilo = threading.Thread(target=trabajar, daemon=True)
            inicio = time.time()
            ultimo = "Leyendo el pedido"
            pedido = mensaje_limpio if len(mensaje_limpio) <= 60 else mensaje_limpio[:57] + "…"
            hilo.start()
            while hilo.is_alive():
                while not avisos.empty():
                    ultimo = avisos.get()
                linea.markdown(
                    f"⏳ «{neutralizar_salida(pedido)}» — {ultimo}… · {time.time() - inicio:.0f} s"
                )
                time.sleep(0.3)
            hilo.join()
            linea.empty()
            traza = resultado["traza"]

            if traza.estado == "bloqueado":
                respuesta = (
                    "⚠️ Mensaje bloqueado: parece un intento de cambiar las "
                    "instrucciones del sistema. No se llamó al modelo."
                )
            elif traza.estado == "error" and "tope" in (traza.error or ""):
                respuesta = (
                    "El pedido superó el tope de consumo por mensaje y se cortó. "
                    "Prueba con un pedido más acotado."
                )
            elif traza.estado == "error":
                respuesta = (
                    f"No se pudo completar el pedido: `{traza.error}`\n\n"
                    "Si dice *rate limit*, Groq está sin cupo por minuto: reintenta en un minuto."
                )
            else:
                respuesta = traza.respuesta_final or ""

            resumen = (
                f"{traza.duracion_ms / 1000:.0f} s · {traza.tokens_totales:,} tokens · "
                f"{traza.llamadas_llm} llamadas · traza {traza.trace_id}"
            )
            st.markdown(neutralizar_salida(respuesta))
            st.caption(resumen)
        st.session_state.mensajes.append(("assistant", respuesta, resumen))
        st.session_state.registro.append(
            {
                "hora": datetime.now().strftime("%H:%M:%S"),
                "mensaje": traza.mensaje_entrada[:60],
                "estado": traza.estado,
                "segundos": round(traza.duracion_ms / 1000, 1),
                "tokens": traza.tokens_totales,
                "trace_id": traza.trace_id,
            }
        )
        st.rerun()

# --- Pestana 3: logs y costos acumulados de ESTA sesion -----------------

with tab_logs:
    st.subheader("Gasto de esta sesion")
    st.caption(
        "Solo muestra lo que ya se gasto — no llama a nada, no cuesta "
        "mirar esta pestaña."
    )
    if not st.session_state.registro:
        st.info("Todavia no mandaste ningun mensaje por el chat.")
    else:
        total_tokens = sum(r["tokens"] for r in st.session_state.registro)
        total_segundos = sum(r["segundos"] for r in st.session_state.registro)
        c1, c2, c3 = st.columns(3)
        c1.metric("Mensajes", len(st.session_state.registro))
        c2.metric("Tokens totales", f"{total_tokens:,}")
        c3.metric("Tiempo total", f"{total_segundos:.0f}s")

        st.dataframe(
            list(reversed(st.session_state.registro)),
            width="stretch",
            hide_index=True,
        )

    st.caption("Detalle de cada traza: `uv run python observabilidad.py <trace_id>`")

# --- Pestana 4: estado del sistema, sin gastar tokens -------------------

with tab_estado:
    st.subheader("Chequeos locales (gratis, no llaman a Groq)")

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        st.markdown("**Token de Gmail**")
        if not TOKEN_GMAIL.exists():
            st.error("No existe gmail_token.json")
        else:
            import json

            datos = json.loads(TOKEN_GMAIL.read_text())
            expira = datetime.fromisoformat(datos["expiry"].replace("Z", "+00:00"))
            ahora = datetime.now(timezone.utc)
            if expira > ahora:
                st.success(f"Vigente hasta {expira.strftime('%Y-%m-%d %H:%M UTC')}")
            else:
                st.warning(
                    f"Expirado desde {expira.strftime('%Y-%m-%d %H:%M UTC')} — "
                    "se refresca solo al primer uso (tiene refresh_token)."
                )

    with col_b:
        st.markdown("**Base de datos**")
        if RUTA_DB.exists():
            kb = RUTA_DB.stat().st_size / 1024
            st.success(f"tienda.db — {kb:.1f} KB")
        else:
            st.error("No existe tienda.db — correr: uv run python db.py")

    with col_c:
        st.markdown("**Memoria vectorial**")
        if MEMORIA_DIR.exists():
            archivos = list(MEMORIA_DIR.rglob("*.lance"))
            st.success(f"{len(archivos)} fragmento(s) en LanceDB")
        else:
            st.info("Todavia no se genero memoria (correr un chat primero)")

    st.divider()
    st.markdown("**Conexion con Groq** (esto SI gasta unos tokens — es manual, a proposito)")
    if st.button("Probar conexion ahora"):
        with st.spinner("Probando..."):
            try:
                llm = modelo()
                t0 = time.perf_counter()
                llm.call([{"role": "user", "content": "Responde solo: OK"}])
                seg = time.perf_counter() - t0
                st.success(f"Groq responde — {seg:.1f}s")
            except Exception as e:
                st.error(f"{type(e).__name__}: {e}")
