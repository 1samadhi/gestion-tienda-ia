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

import acceso
import estilo
import pendientes
from agentes import modelo
from db import DB as RUTA_DB
from gmail_tool import enviar_correo
from guardrails import neutralizar_salida, sanitizar_entrada
from observabilidad import acciones_rechazadas, observar
from stock import consultar_stock, historial_producto, productos_bajo_minimo

RAIZ = Path(__file__).parent
TOKEN_GMAIL = RAIZ / "gmail_token.json"
MEMORIA_DIR = Path.home() / ".local" / "share" / "gestion-tienda-ia" / "memory"

st.set_page_config(page_title="Tienda IA", page_icon=":material/storefront:", layout="wide")
st.markdown(estilo.CSS, unsafe_allow_html=True)

if "conversacion_id" not in st.session_state:
    st.session_state.conversacion_id = str(uuid.uuid4())[:8]
if "mensajes" not in st.session_state:
    st.session_state.mensajes = []
if "registro" not in st.session_state:
    st.session_state.registro = []  # [{hora, mensaje, segundos, tokens}]
if "dueno" not in st.session_state:
    st.session_state.dueno = False
    st.session_state.intentos = 0

# --- Stock: directo a la base, sin LLM -------------------------------------

def pagina_stock():
    estilo.encabezado_pagina("Stock", "Inventario y operaciones por aprobar.", st.session_state.dueno)
    productos = consultar_stock("")
    bajos = productos_bajo_minimo()
    por_aprobar = pendientes.listar()
    estilo.indicadores([
        ("Productos", str(len(productos))),
        ("Unidades en stock", f"{sum(p.stock_actual for p in productos):,}".replace(",", ".")),
        ("Bajo el mínimo", str(len(bajos))),
        ("Por aprobar", str(len(por_aprobar))),
    ])

    if por_aprobar:
        nota = ("Propuestas por un agente; no se ejecutan hasta que las apruebes."
                if st.session_state.dueno else "Inicia sesión de dueño para aprobarlas.")
        st.markdown(estilo.seccion("Pendientes de", "aprobación", nota), unsafe_allow_html=True)
        for op in por_aprobar:
            col_t, col_a, col_d = st.columns([7, 1.2, 1.2], vertical_alignment="center")
            col_t.markdown(estilo.pendiente(op), unsafe_allow_html=True)
            if op["tipo"] == "correo":
                with col_t.expander("Ver correo"):
                    st.text(op["cuerpo"])
            if not st.session_state.dueno:
                continue
            if col_a.button("Aprobar", key=f"ok{op['id']}", type="primary", width="stretch"):
                try:
                    st.toast(pendientes.aprobar(op["id"], enviar_correo))
                except Exception as e:
                    st.toast(f"No se pudo: {e}")
                st.rerun()
            if col_d.button("Descartar", key=f"no{op['id']}", width="stretch"):
                pendientes.descartar(op["id"])
                st.rerun()

    st.markdown(estilo.seccion("Productos"), unsafe_allow_html=True)
    st.markdown(estilo.tarjetas(productos), unsafe_allow_html=True)

    st.markdown(estilo.seccion("Historial de", "movimientos"), unsafe_allow_html=True)
    opciones = {p.nombre: p.id for p in productos}
    elegido = st.selectbox("Producto", list(opciones))
    if elegido:
        movs = historial_producto(opciones[elegido])
        if not movs:
            st.caption("Sin movimientos registrados.")
        else:
            st.dataframe(
                [{"Fecha": m["fecha"], "Tipo": m["tipo"], "Cantidad": m["cantidad"]} for m in movs],
                width="stretch", hide_index=True,
            )

# --- Chat: pasa por los agentes (CrewAI + Groq) ---------------------------

def pagina_chat():
    estilo.encabezado_pagina("Chat", "Pedidos en lenguaje natural. Cada mensaje usa IA (Groq).", st.session_state.dueno)

    for autor, texto, resumen in st.session_state.mensajes:
        with st.chat_message(autor):
            st.markdown(neutralizar_salida(texto) if autor == "assistant" else texto)
            if resumen:
                st.caption(resumen)

    mensaje = st.chat_input("Ej: Vende 2 unidades del Taladro percutor")
    if mensaje:
        mensaje_limpio = sanitizar_entrada(mensaje)
        historial = [
            ("usuario" if autor == "user" else "asistente", texto)
            for autor, texto, _ in st.session_state.mensajes
        ]
        st.session_state.mensajes.append(("user", mensaje_limpio, None))
        with st.chat_message("user"):
            st.text(mensaje_limpio)

        with st.chat_message("assistant"):
            linea = st.empty()
            avisos: queue.Queue[str] = queue.Queue()
            resultado = {}
            conversacion = st.session_state.conversacion_id
            es_dueno = st.session_state.dueno
            ya_pendientes = {op["id"] for op in pendientes.listar()}

            def trabajar():
                resultado["traza"] = observar(
                    mensaje_limpio,
                    caso="chat",
                    conversacion_id=conversacion,
                    al_progreso=avisos.put,
                    historial=historial,
                    dueno=es_dueno,
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

            # Lo que quedo pendiente se informa desde la base, no desde lo que
            # el modelo diga: puede afirmar "ya se envio" cuando solo se preparo.
            nuevas = [op for op in pendientes.listar() if op["id"] not in ya_pendientes]
            if nuevas:
                detalle = "; ".join(
                    f"reponer {op['cantidad']} de {op['producto']}" if op["tipo"] == "reposicion"
                    else f"correo a {op['destinatario']}"
                    for op in nuevas
                )
                respuesta += (
                    f"\n\n> 🔒 **Esperando tu aprobación** (pestaña Stock): {detalle}. "
                    "Nada de esto se ha ejecutado todavía."
                )

            rechazos = acciones_rechazadas(traza)
            if rechazos:
                detalle = " · ".join(f"{accion} ({motivo})" for accion, motivo in rechazos)
                respuesta += f"\n\n> ⚠️ **No se ejecutó:** {detalle}."

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

# --- Observabilidad: tablero sobre logs/trazas.jsonl ----------------------

def pagina_observabilidad():
    estilo.encabezado_pagina("Observabilidad", "Métricas y trazas guardadas. Mirar no gasta tokens.", st.session_state.dueno)
    import pandas as pd

    import dashboard as tablero
    from observabilidad import ARCHIVO_TRAZAS, cargar_trazas

    trazas = cargar_trazas()
    if not trazas:
        st.info("Todavía no hay trazas. Usa el chat o corre `uv run python bateria.py --todos`.")
    else:
        st.caption(f"{len(trazas)} trazas en `{ARCHIVO_TRAZAS.name}`")
        f1, f2 = st.columns(2)
        configs = sorted({tablero.configuracion(t) for t in trazas})
        casos = sorted({tablero.caso_base(t) for t in trazas})
        elegidas = f1.multiselect("Configuración", configs, placeholder="Todas")
        casos_elegidos = f2.multiselect("Caso", casos, placeholder="Todos")
        vista = tablero.filtrar(trazas, elegidas, casos_elegidos)

        if not vista:
            st.warning("Ninguna traza con esos filtros.")
        else:
            k = tablero.kpis(vista)
            st.markdown(estilo.seccion("Salud de las", "llamadas"), unsafe_allow_html=True)
            c = st.columns(4)
            c[0].metric("Precisión", "-" if k["precision_pct"] is None else f"{k['precision_pct']}%")
            c[1].metric("Latencia p50", f"{k['p50_s']} s")
            c[2].metric("Latencia p95", f"{k['p95_s']} s")
            c[3].metric("Tokens por petición", f"{k['tokens_prom']:,}")
            st.markdown(estilo.seccion("Volumen y", "abuso"), unsafe_allow_html=True)
            c = st.columns(4)
            c[0].metric("Peticiones", k["peticiones"])
            c[1].metric("Bloqueadas por el filtro", k["bloqueadas"])
            c[2].metric("Tasa de error", f"{k['error_pct']}%")
            c[3].metric("Rate limits por petición", k["rate_limits_prom"])

            st.markdown(estilo.seccion("Latencia por", "caso", "segundos"), unsafe_allow_html=True)
            casos_df = pd.DataFrame(tablero.por_caso(vista)).set_index("caso").rename(columns={
                "corridas": "Corridas", "p50_s": "p50 (s)", "p95_s": "p95 (s)",
                "tokens_prom": "Tokens prom.", "rate_limits": "Rate limits",
                "errores": "Errores", "precision_pct": "Precisión %",
            })
            casos_df.index.name = "Caso"
            st.bar_chart(casos_df[["p50 (s)", "p95 (s)"]], stack=False, horizontal=True,
                         color=["#4F46E5", "#C7D2FE"], y_label="", x_label="segundos",
                         height=max(260, 34 * len(casos_df)))

            g1, g2 = st.columns(2)
            with g1:
                st.markdown(estilo.seccion("Dónde se va el", "tiempo", "s promedio por petición"),
                            unsafe_allow_html=True)
                etapas = pd.DataFrame(tablero.tiempo_por_etapa(vista))
                if not etapas.empty:
                    st.bar_chart(etapas.set_index("etapa"), horizontal=True, color="#4F46E5",
                                 y_label="", x_label="segundos")
            with g2:
                st.markdown(estilo.seccion("Tokens por", "rol", "promedio por petición"),
                            unsafe_allow_html=True)
                roles = pd.DataFrame(tablero.tokens_por_rol(vista))
                if not roles.empty:
                    st.bar_chart(roles.set_index("rol"), horizontal=True, color="#71717A",
                                 y_label="", x_label="tokens")

            st.markdown(estilo.seccion("Cada petición en el", "tiempo",
                                       "tamaño = tokens"), unsafe_allow_html=True)
            serie = pd.DataFrame(tablero.serie(vista))
            serie["hora"] = pd.to_datetime(serie["hora"])
            st.scatter_chart(serie, x="hora", y="segundos", color="configuracion", size="tokens")

            st.markdown(estilo.seccion("Detalle por", "caso"), unsafe_allow_html=True)
            st.dataframe(casos_df, width="stretch")

            from observabilidad import comparar

            comparacion = comparar(vista)
            if len(comparacion) > 1:
                st.markdown(estilo.seccion("Comparación de", "configuraciones"),
                            unsafe_allow_html=True)
                st.dataframe(comparacion, width="stretch", hide_index=True)

            st.markdown(estilo.seccion("Trazas", "recientes"), unsafe_allow_html=True)
            st.dataframe(tablero.tabla_trazas(vista), width="stretch", hide_index=True)
            por_id = {t.trace_id: t for t in vista}
            elegida = st.selectbox(
                "Ver las etapas de una traza", list(reversed(list(por_id))),
                format_func=lambda i: f"{i} · {por_id[i].caso} · {por_id[i].duracion_ms / 1000:.1f} s",
            )
            if elegida:
                t = por_id[elegida]
                st.caption(f"Mensaje: {neutralizar_salida(t.mensaje_entrada)}")
                st.dataframe(tablero.eventos_de(t), width="stretch", hide_index=True)

    with st.expander("Gasto de esta sesión"):
        if not st.session_state.registro:
            st.caption("Todavía no mandaste ningún mensaje por el chat.")
        else:
            total_tokens = sum(r["tokens"] for r in st.session_state.registro)
            total_segundos = sum(r["segundos"] for r in st.session_state.registro)
            st.caption(f"{len(st.session_state.registro)} mensajes · {total_tokens:,} tokens · "
                       f"{total_segundos:.0f} s")
            st.dataframe(list(reversed(st.session_state.registro)), width="stretch", hide_index=True)

# --- Estado del sistema: chequeos locales ---------------------------------

def pagina_estado():
    estilo.encabezado_pagina("Estado del sistema", "Chequeos locales. Solo el botón de Groq gasta tokens.", st.session_state.dueno)

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
                    f"Acceso vencido el {expira.strftime('%Y-%m-%d %H:%M UTC')}. Se renueva solo "
                    "mientras el permiso siga vigente; con la app de Google en modo prueba el permiso "
                    "dura 7 días. Si un envío falla: `uv run python autenticar_gmail.py`."
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
            st.info("Apagada (MEMORIA_CREW=false): el contexto va por historial corto.")

    st.divider()
    st.markdown("**Conexión con Groq** (esto sí gasta unos tokens; es manual a propósito)")
    if not st.session_state.dueno:
        st.caption("Disponible con sesión de dueño.")
    elif st.button("Probar conexión ahora"):
        with st.spinner("Probando..."):
            try:
                llm = modelo()
                t0 = time.perf_counter()
                llm.call([{"role": "user", "content": "Responde solo: OK"}])
                seg = time.perf_counter() - t0
                st.success(f"Groq responde — {seg:.1f}s")
            except Exception as e:
                st.error(f"{type(e).__name__}: {e}")


# --- Navegacion y acceso ----------------------------------------------------

st.logo(str(RAIZ / "logo.svg"), size="large")
navegacion = st.navigation([
    st.Page(pagina_stock, title="Stock", icon=":material/inventory_2:", url_path="stock", default=True),
    st.Page(pagina_chat, title="Chat", icon=":material/forum:", url_path="chat"),
    st.Page(pagina_observabilidad, title="Observabilidad", icon=":material/monitoring:", url_path="observabilidad"),
    st.Page(pagina_estado, title="Estado del sistema", icon=":material/settings_heart:", url_path="estado"),
])

with st.sidebar:
    st.markdown('<div class="acceso-titulo">Acceso</div>', unsafe_allow_html=True)
    if st.session_state.dueno:
        st.markdown('<div class="acceso-ok">Sesión de dueño activa</div>', unsafe_allow_html=True)
        if st.button("Cerrar sesión", icon=":material/logout:", width="stretch"):
            st.session_state.dueno = False
            st.rerun()
    elif not acceso.hay_clave():
        st.caption("Modo consulta. Para habilitar ventas: `uv run python acceso.py`.")
    elif st.session_state.intentos >= acceso.MAX_INTENTOS:
        st.error("Demasiados intentos. Recarga la página para reintentar.")
    else:
        st.caption("Sin sesión el chat solo consulta el stock.")
        with st.form("login", border=False):
            clave = st.text_input("Clave del dueño", type="password", label_visibility="collapsed",
                                  placeholder="Clave del dueño")
            if st.form_submit_button("Entrar", type="primary", icon=":material/lock_open:", width="stretch"):
                if acceso.verificar_clave(clave):
                    st.session_state.dueno, st.session_state.intentos = True, 0
                    st.rerun()
                st.session_state.intentos += 1
                st.error("Clave incorrecta.")

navegacion.run()
