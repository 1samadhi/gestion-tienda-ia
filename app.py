"""Front-end minimo (Streamlit) para el dueno de la tienda.

Dos zonas separadas, mismo principio que el resto del proyecto:

    arriba   consultas directas a stock.py — instantaneo, cero tokens
    abajo    chat en lenguaje natural -> crear_crew() — pasa por los
             agentes, cuesta tokens reales (ver MEDICION.md: 60-80s,
             15-20k tokens por mensaje). No conviene rutear un "ver
             stock" simple por ahi.

Uso:
    uv run streamlit run app.py
"""

import uuid

import streamlit as st

from agentes import crear_crew
from stock import consultar_stock, historial_producto, productos_bajo_minimo

st.set_page_config(page_title="Gestion de Tienda IA", page_icon="📦", layout="wide")
st.title("📦 Gestion de Tienda IA")

if "conversacion_id" not in st.session_state:
    st.session_state.conversacion_id = str(uuid.uuid4())[:8]
if "mensajes" not in st.session_state:
    st.session_state.mensajes = []

# --- Panel de stock: directo a la base, sin LLM -----------------------

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
            st.warning(f"**{p.nombre}** — {p.stock_actual}/{p.stock_minimo} — proveedor {p.proveedor_email}")

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

st.divider()

# --- Chat: pasa por los agentes (CrewAI + Groq) ------------------------

st.subheader("Hablar con el equipo (Inventario / Ventas / Compras)")
st.caption(
    "Cada mensaje corre el manager jerarquico completo: ~60-80s y "
    "15 000-20 000 tokens (ver MEDICION.md). Para solo mirar el stock, "
    "usa el panel de arriba — es gratis e instantaneo."
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
            try:
                crew = crear_crew(mensaje, conversacion_id=st.session_state.conversacion_id)
                respuesta = str(crew.kickoff())
            except Exception as e:
                respuesta = (
                    "No se pudo completar el pedido. Causa tecnica: "
                    f"`{type(e).__name__}: {e}`\n\n"
                    "Si el mensaje dice *rate limit*, Groq se quedo sin cupo "
                    "del tier gratuito (8000 tokens/minuto) — reintenta en "
                    "un minuto, o cambia `GROQ_MODEL` en `.env` por otro "
                    "modelo (tiene su propio cupo separado)."
                )
        st.markdown(respuesta)
    st.session_state.mensajes.append(("assistant", respuesta))
    st.rerun()
