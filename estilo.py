"""Piezas visuales de app.py: CSS y bloques HTML.

Todo texto que viene de la base (nombres de producto) pasa por
`html.escape`: un nombre con etiquetas no debe convertirse en HTML.
"""

from html import escape

import streamlit as st

ACENTO = "#4F46E5"

CSS = """
<style>
.block-container { padding-top: 3.4rem; max-width: 1180px; }
h1, h2, h3, h4 { letter-spacing: -0.015em; }

[data-testid="stSidebar"] { border-right: 1px solid #E4E4E7; }
[data-testid="stSidebarNav"] a { border-radius: 8px; }
[data-testid="stSidebarNav"] a[aria-current="page"] { background: #EEF0FF; }
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: #4F46E5; font-weight: 600; }
.acceso-titulo { font-size: .72rem; font-weight: 600; color: #71717A; text-transform: uppercase;
  letter-spacing: .06em; margin: .6rem 0 .4rem 0; }
.acceso-ok { font-size: .85rem; color: #15803D; background: #F0FDF4; border: 1px solid #BBF7D0;
  border-radius: 8px; padding: .45rem .7rem; margin-bottom: .5rem; }

.cabecera { display:flex; justify-content:space-between; align-items:flex-start;
  padding-bottom: .9rem; margin-bottom: 1.2rem; border-bottom: 1px solid #E4E4E7; }
.cabecera h1 { font-size: 1.45rem; font-weight: 600; margin: 0; padding: 0; color: #18181B; }
.cabecera p { color: #71717A; font-size: .9rem; margin: .2rem 0 0 0; }
.modo { font-size: .75rem; font-weight: 500; padding: .25rem .65rem; border-radius: 999px;
  border: 1px solid #E4E4E7; color: #52525B; background: #fff; white-space: nowrap; }
.modo i { display:inline-block; width:.45rem; height:.45rem; border-radius:999px; margin-right:.35rem;
  background:#A1A1AA; vertical-align: middle; }
.modo.dueno i { background:#22C55E; }

.indicadores { display:grid; grid-template-columns:repeat(4,1fr); gap:.75rem; margin-bottom:1.4rem; }
.indicador { background:#fff; border:1px solid #E4E4E7; border-radius:10px; padding:.85rem 1rem; }
.indicador .etq { font-size:.78rem; color:#71717A; }
.indicador .dato { font-size:1.5rem; font-weight:600; color:#18181B; margin-top:.15rem; }
.indicador.alerta .dato { color:#DC2626; }

.seccion { display:flex; align-items:baseline; gap:.6rem; margin:1.4rem 0 .6rem 0; }
.seccion h4 { margin:0; padding:0; font-size:.95rem; font-weight:600; color:#18181B; }
.seccion .nota { color:#71717A; font-size:.82rem; }

.tarjetas { display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:.75rem; }
.tarjeta { position:relative; background:#fff; border:1px solid #E4E4E7; border-radius:10px;
  padding:.9rem 1rem; }
.tarjeta .icono { font-size:1.15rem; width:2.1rem; height:2.1rem; border-radius:8px;
  background:#F4F4F5; display:flex; align-items:center; justify-content:center; }
.tarjeta .nombre { font-weight:500; margin-top:.6rem; color:#18181B; font-size:.92rem; }
.tarjeta .id { color:#A1A1AA; font-size:.75rem; }
.tarjeta .stock { font-size:1.35rem; font-weight:600; margin-top:.25rem; color:#18181B; }
.tarjeta .stock small { font-size:.78rem; font-weight:400; color:#71717A; }
.tarjeta .barra { height:4px; background:#F4F4F5; border-radius:999px; margin-top:.5rem; overflow:hidden; }
.tarjeta .barra i { display:block; height:100%; border-radius:999px; }
.tarjeta .min { color:#71717A; font-size:.75rem; margin-top:.35rem; }
.etiqueta { position:absolute; top:.8rem; right:.8rem; font-size:.68rem; font-weight:500;
  padding:.12rem .5rem; border-radius:999px; border:1px solid; }
.etiqueta.bajo { background:#FEF2F2; color:#B91C1C; border-color:#FECACA; }
.etiqueta.ok { background:#F0FDF4; color:#15803D; border-color:#BBF7D0; }

.pendiente { background:#fff; border:1px solid #E4E4E7; border-radius:10px; padding:.65rem .9rem; }
.pendiente .tipo { font-size:.72rem; font-weight:600; color:#B45309; }

[data-testid="stMetric"] { background:#fff; border:1px solid #E4E4E7; border-radius:10px;
  padding:.75rem 1rem; }
[data-testid="stMetricValue"] { font-size:1.45rem; font-weight:600; }
[data-testid="stChatMessage"] { background:#fff; border:1px solid #E4E4E7; border-radius:10px; }
</style>
"""

_ICONOS = [
    (("taladro", "destornillador", "martillo", "llave", "sierra", "tornillo"), "🔧"),
    (("cuaderno", "lapiz", "lápiz", "libro", "papel", "carpeta"), "📓"),
    (("pan", "leche", "arroz", "azucar", "azúcar", "fruta", "queso"), "🍞"),
]


def icono(nombre: str) -> str:
    n = nombre.lower()
    return next((i for claves, i in _ICONOS if any(c in n for c in claves)), "📦")


def encabezado_pagina(titulo: str, descripcion: str, dueno: bool) -> None:
    modo = ('<span class="modo dueno"><i></i>Sesión de dueño</span>' if dueno
            else '<span class="modo"><i></i>Modo consulta</span>')
    st.markdown(
        f'<div class="cabecera"><div><h1>{escape(titulo)}</h1><p>{escape(descripcion)}</p></div>{modo}</div>',
        unsafe_allow_html=True,
    )


def indicadores(datos: list[tuple[str, str]]) -> None:
    celdas = "".join(
        f'<div class="indicador{" alerta" if e == "Bajo el mínimo" and v != "0" else ""}">'
        f'<div class="etq">{escape(e)}</div><div class="dato">{escape(v)}</div></div>'
        for e, v in datos
    )
    st.markdown(f'<div class="indicadores">{celdas}</div>', unsafe_allow_html=True)


def seccion(normal: str, destacado: str = "", nota: str = "") -> str:
    titulo = f"{normal} {destacado}".strip()
    extra = f'<span class="nota">{escape(nota)}</span>' if nota else ""
    return f'<div class="seccion"><h4>{escape(titulo)}</h4>{extra}</div>'


def tarjetas(productos) -> str:
    piezas = []
    for p in productos:
        tope = max(p.stock_minimo * 3, p.stock_actual, 1)
        ancho = min(100, round(100 * p.stock_actual / tope))
        color = "#EF4444" if p.bajo_minimo else ACENTO
        etiqueta = ('<span class="etiqueta bajo">Bajo mínimo</span>' if p.bajo_minimo
                    else '<span class="etiqueta ok">OK</span>')
        piezas.append(
            f'<div class="tarjeta">{etiqueta}'
            f'<div class="icono">{icono(p.nombre)}</div>'
            f'<div class="nombre">{escape(p.nombre)}</div><div class="id">#{p.id}</div>'
            f'<div class="stock">{p.stock_actual} <small>unidades</small></div>'
            f'<div class="barra"><i style="width:{ancho}%;background:{color}"></i></div>'
            f'<div class="min">Mínimo: {p.stock_minimo}</div></div>'
        )
    return f'<div class="tarjetas">{"".join(piezas)}</div>'


def pendiente(op: dict) -> str:
    if op["tipo"] == "reposicion":
        tipo = "Reposición"
        texto = f"Reponer <b>{op['cantidad']}</b> unidades de <b>{escape(op['producto'])}</b>"
    else:
        tipo = "Correo a proveedor"
        texto = f"Para <b>{escape(op['destinatario'])}</b> — {escape(op['asunto'] or '')}"
    return (f'<div class="pendiente"><div class="tipo">#{op["id"]} · {tipo}</div>'
            f"<div>{texto}</div></div>")
