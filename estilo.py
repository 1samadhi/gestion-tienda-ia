"""Piezas visuales de app.py: CSS y bloques HTML.

Todo texto que viene de la base (nombres de producto) pasa por
`html.escape`: un nombre con etiquetas no debe convertirse en HTML.
"""

from html import escape

AZUL = "#0B7BD3"

CSS = """
<style>
.block-container { padding-top: 3.4rem; max-width: 1280px; }
h1, h2, h3 { letter-spacing: -0.01em; }

.encabezado { display:flex; align-items:center; justify-content:space-between;
  margin-bottom: .4rem; }
.encabezado .marca { font-size:1.55rem; font-weight:700; color:#1A2433; }
.encabezado .marca span { color:#0B7BD3; }
.encabezado .sub { color:#6B7A90; font-size:.9rem; margin-top:.1rem; }
.pildora { display:inline-block; padding:.28rem .8rem; border-radius:999px;
  font-size:.8rem; font-weight:600; }
.pildora.dueno { background:#E6F4EA; color:#1E7B3C; }
.pildora.consulta { background:#EAF2FB; color:#0B5FA5; }

.franja { background:linear-gradient(120deg,#0B4F8A 0%,#0B7BD3 60%,#3BA4EE 100%);
  border-radius:16px; padding:1.2rem 1.6rem; color:#fff; display:grid;
  grid-template-columns:repeat(4,1fr); gap:1rem; margin:.6rem 0 1.4rem 0;
  box-shadow:0 6px 18px rgba(11,79,138,.18); }
.franja .dato { font-size:1.9rem; font-weight:700; line-height:1.1; }
.franja .etq { font-size:.8rem; opacity:.85; text-transform:uppercase; letter-spacing:.04em; }

.seccion { display:flex; align-items:baseline; gap:.5rem; margin:1.1rem 0 .6rem 0;
  border-bottom:1px solid #E3E9F1; }
.seccion h4 { margin:0; padding-bottom:.45rem; font-weight:600; color:#1A2433; }
.seccion h4 b { color:#0B7BD3; border-bottom:3px solid #0B7BD3; padding-bottom:.4rem; }
.seccion .nota { color:#6B7A90; font-size:.85rem; }

.tarjetas { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:1rem; }
.tarjeta { position:relative; background:#fff; border:1px solid #E3E9F1; border-radius:14px;
  padding:1rem 1.1rem; box-shadow:0 2px 6px rgba(26,36,51,.04); }
.tarjeta.alerta { border-color:#F3B4B4; }
.tarjeta .icono { font-size:1.7rem; width:2.8rem; height:2.8rem; border-radius:12px;
  background:#F0F6FD; display:flex; align-items:center; justify-content:center; }
.tarjeta .nombre { font-weight:600; margin-top:.7rem; color:#1A2433; }
.tarjeta .id { color:#8A97A8; font-size:.78rem; }
.tarjeta .stock { font-size:1.7rem; font-weight:700; margin-top:.3rem; color:#1A2433; }
.tarjeta .stock small { font-size:.8rem; font-weight:500; color:#6B7A90; }
.tarjeta .barra { height:6px; background:#EEF2F7; border-radius:999px; margin-top:.5rem; overflow:hidden; }
.tarjeta .barra i { display:block; height:100%; border-radius:999px; }
.tarjeta .min { color:#6B7A90; font-size:.78rem; margin-top:.35rem; }
.etiqueta { position:absolute; top:.8rem; right:.8rem; font-size:.7rem; font-weight:700;
  padding:.2rem .55rem; border-radius:6px; }
.etiqueta.bajo { background:#FDE8E8; color:#B42318; }
.etiqueta.ok { background:#E6F4EA; color:#1E7B3C; }

.pendiente { background:#fff; border:1px solid #E3E9F1; border-left:4px solid #F5A524;
  border-radius:12px; padding:.75rem 1rem; }
.pendiente .tipo { font-size:.72rem; font-weight:700; color:#B26A00; text-transform:uppercase; }

[data-testid="stMetric"] { background:#fff; border:1px solid #E3E9F1; border-radius:12px;
  padding:.8rem 1rem; }
[data-testid="stChatMessage"] { background:#fff; border:1px solid #E3E9F1; border-radius:14px; }
.stTabs [data-baseweb="tab-list"] { gap:.3rem; }
.stTabs [data-baseweb="tab"] { padding:.4rem .9rem; border-radius:999px; }
.stTabs [aria-selected="true"] { background:#EAF2FB; }
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


def encabezado(dueno: bool) -> str:
    modo = ('<span class="pildora dueno">● Sesión de dueño</span>' if dueno
            else '<span class="pildora consulta">● Modo consulta</span>')
    return (
        '<div class="encabezado"><div>'
        '<div class="marca">📦 Gestión de Tienda <span>IA</span></div>'
        '<div class="sub">Stock, ventas y compras con agentes · CrewAI + Groq</div>'
        f"</div>{modo}</div>"
    )


def franja(datos: list[tuple[str, str]]) -> str:
    celdas = "".join(
        f'<div><div class="dato">{escape(v)}</div><div class="etq">{escape(e)}</div></div>'
        for e, v in datos
    )
    return f'<div class="franja">{celdas}</div>'


def seccion(normal: str, destacado: str, nota: str = "") -> str:
    extra = f'<span class="nota">{escape(nota)}</span>' if nota else ""
    return f'<div class="seccion"><h4>{escape(normal)} <b>{escape(destacado)}</b></h4>{extra}</div>'


def tarjetas(productos) -> str:
    piezas = []
    for p in productos:
        tope = max(p.stock_minimo * 3, p.stock_actual, 1)
        ancho = min(100, round(100 * p.stock_actual / tope))
        color = "#E5484D" if p.bajo_minimo else "#2BA36B"
        etiqueta = ('<span class="etiqueta bajo">BAJO MÍNIMO</span>' if p.bajo_minimo
                    else '<span class="etiqueta ok">OK</span>')
        piezas.append(
            f'<div class="tarjeta{" alerta" if p.bajo_minimo else ""}">{etiqueta}'
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
