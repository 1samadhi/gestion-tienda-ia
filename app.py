"""Front-end (Streamlit) para el dueno de la tienda.

Cuatro pestanas, cada una con costo deliberadamente distinto:

    Stock              directo a stock.py — sin LLM, instantaneo, gratis
    Chat               crear_crew() completo — costo real, ver MEDICION.md
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

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from agentes import crear_crew, modelo
from db import DB as RUTA_DB
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
        "Cada mensaje corre el manager jerarquico completo: ~60-80s y "
        "15 000-20 000 tokens (ver pestaña de Logs y MEDICION.md). Para "
        "solo mirar el stock, usa la pestaña de Stock — es gratis e "
        "instantaneo."
    )

    for autor, texto in st.session_state.mensajes:
        with st.chat_message(autor):
            st.markdown(texto)

    mensaje = st.chat_input("Ej: Vende 2 unidades del Taladro percutor")
    if mensaje:
        st.session_state.mensajes.append(("user", mensaje))
        with st.chat_message("user"):
            st.markdown(mensaje)

        with st.chat_message("assistant"):
            with st.spinner("El manager esta delegando la tarea... (puede tardar un minuto)"):
                t0 = time.perf_counter()
                try:
                    crew = crear_crew(mensaje, conversacion_id=st.session_state.conversacion_id)
                    respuesta = str(crew.kickoff())
                    m = getattr(crew, "usage_metrics", None)
                    tokens = getattr(m, "total_tokens", 0) or 0
                except Exception as e:
                    tokens = 0
                    respuesta = (
                        "No se pudo completar el pedido. Causa tecnica: "
                        f"`{type(e).__name__}: {e}`\n\n"
                        "Si el mensaje dice *rate limit*, Groq se quedo sin cupo "
                        "del tier gratuito (8000 tokens/minuto) — reintenta en "
                        "un minuto, o cambia `GROQ_MODEL` en `.env` por otro "
                        "modelo (tiene su propio cupo separado)."
                    )
                segundos = time.perf_counter() - t0
            st.markdown(respuesta)
        st.session_state.mensajes.append(("assistant", respuesta))
        st.session_state.registro.append(
            {
                "hora": datetime.now().strftime("%H:%M:%S"),
                "mensaje": mensaje[:60],
                "segundos": round(segundos, 1),
                "tokens": tokens,
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

    st.divider()
    st.caption(
        "Medicion de referencia (3 casos representativos, corridos fuera "
        "de esta sesion, ver MEDICION.md): consulta simple 57.3s/16 651 "
        "tok · venta simple 81.6s/20 316 tok · venta con reposicion "
        "78.3s/15 389 tok."
    )

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
