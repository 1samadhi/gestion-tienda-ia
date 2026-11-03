"""Guardrails de entrada y salida (IL3.3, OWASP A05:2025 y LLM01:2026).

Primera capa, no la unica. El enfoque sigue `deploy/backend/guardrails.py` del
repo del curso: normalizar antes de comparar, familias verbo+objeto en vez de
frases sueltas, y decodificar tres disfraces baratos (base64, rot13, letras
separadas por puntos).

Lo que sigue abierto, y hay que decirlo en la defensa: un idioma que no este
en las listas, hex, texto invertido, una parafrasis que no este escrita y la
inyeccion indirecta que no pase por `dato_seguro`. Lo que contiene el daño en
este proyecto no es este archivo:

- minimo privilegio por rol (Compras es el unico con Gmail);
- validacion en las tools: cantidades positivas, destinatario solo si es un
  proveedor registrado en la base (stock.py, agentes.py);
- la orden de compra no depende de que el LLM decida emitirla.
"""

import base64
import codecs
import html
import re
import unicodedata

_INVISIBLES = dict.fromkeys(
    map(ord, "\u00ad\u200b\u200c\u200d\u2060\u2061\u2062\u2063\u2064"
             "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff"),
    None,
)

# Cirilico y griego que se dibujan como latinas: "ignоra" con о cirilica.
_HOMOGLIFOS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "һ": "h", "ԛ": "q", "ѵ": "v",
    "ԝ": "w", "ᴏ": "o", "ⅼ": "l", "ɡ": "g",
    "α": "a", "ο": "o", "ρ": "p", "ε": "e", "ι": "i", "ν": "v", "κ": "k",
    "τ": "t", "υ": "u", "χ": "x", "β": "b", "σ": "o",
})


def normalizar(texto: str) -> str:
    """Forma canonica solo para DECIDIR; al modelo nunca se le manda esto."""
    t = unicodedata.normalize("NFKC", texto).translate(_INVISIBLES).lower()
    t = t.translate(_HOMOGLIFOS)
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


_RELLENO = (
    r"(?:\s+(?:de|del|el|la|los|las|un|una|tu|tus|su|sus|mi|mis|todo|toda|todos"
    r"|todas|anterior|anteriores|previo|previa|previos|previas|the|a|an"
    r"|your|my|all|any|previous|prior|above|earlier|of))*"
)
_IGNORAR = (
    r"(?:ignora[rs]?|ignore[sd]?|olvida[rt]?e?|olvidate|omite|omitir|descarta[r]?"
    r"|saltate|disregard|forget|bypass|override|oublie[rz]?)"
)
_REVELAR = (
    r"(?:revela[r]?(?:me)?|muestra[r]?(?:me)?|dime|imprime|repite|escribe|copia[r]?"
    r"|comparte|filtra|reveal|show|print|repeat|output|display|dump)"
)
_OBJETO = (
    r"(?:instrucciones|instruccion|indicaciones|directrices|reglas|restricciones"
    r"|instructions|rules|guidelines|system\s+prompt|prompt\s+del?\s+sistema|backstory)"
)
# "revelar" solo cuenta si el objeto es el prompt del sistema: "dime las reglas
# de reposicion" es una pregunta legitima del dueño de la tienda.
_OBJETO_SISTEMA = (
    r"(?:system\s+prompt|prompt\s+del?\s+sistema|prompt\s+inicial|backstory"
    r"|instrucciones\s+(?:de|del)\s+sistema|instrucciones\s+internas|system\s+message"
    r"|(?:tus|your)\s+(?:instrucciones|reglas|directrices|instructions|rules))"
)
_DATOS = (
    r"(?:todo\s+el\s+stock|el\s+inventario|inventario\s+completo|toda\s+la\s+base"
    r"|la\s+base\s+de\s+datos|todos\s+los\s+(?:datos|productos|proveedores)"
    r"|all\s+(?:the\s+)?(?:stock|inventory|data))"
)

PATRONES_INYECCION = (
    re.compile(rf"\b{_IGNORAR}{_RELLENO}\s+{_OBJETO}\b"),
    re.compile(rf"\b{_IGNORAR}\s+(?:lo\s+que\s+te\s+(?:dijeron|indicaron)|todo\s+lo\s+anterior)\b"),
    re.compile(rf"\b{_REVELAR}\b.{{0,60}}\b{_OBJETO_SISTEMA}\b"),
    re.compile(r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above)\b"),
    re.compile(r"\b(?:eres|seras)\s+ahora\s+(?:un\s+|una\s+|el\s+|la\s+)?(?:administrador|root|sistema|desarrollador)\b"),
    re.compile(r"\bactua\s+como\s+(?:si\s+no\s+tuvieras|administrador|root|el\s+sistema|desarrollador)\b"),
    re.compile(r"\b(?:a\s+partir\s+de\s+ahora|from\s+now\s+on)\s+(?:eres|you\s+are)\b"),
    re.compile(r"\b(?:you\s+are\s+now|modo\s+desarrollador|developer\s+mode|jailbreak|caso\s+omiso)\b"),
    re.compile(r"(?:^|\s)(?:system|sistema)\s*:|\[/?inst\]|<\|im_start\|>|###\s*instruction"),
    re.compile(rf"\b(?:envia|enviame|manda|mandame|reenvia|send|forward)\b.{{0,40}}{_DATOS}"),
)


def _coincide(normalizado: str) -> bool:
    return any(p.search(normalizado) for p in PATRONES_INYECCION)


def _juntar_letras(texto: str) -> str:
    return re.sub(r"\b(?:[a-z]\.){2,}[a-z]\b", lambda m: m.group(0).replace(".", ""), texto)


def _bloques_base64(texto: str):
    for m in re.finditer(r"[A-Za-z0-9+/]{16,}={0,2}", texto):
        blob = m.group(0)
        try:
            yield base64.b64decode(blob + "=" * (-len(blob) % 4)).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue


def detecto_injection(texto: str) -> bool:
    """¿El texto parece un intento de prompt injection?"""
    n = normalizar(texto)
    if _coincide(n):
        return True
    junto = _juntar_letras(n)
    if junto != n and _coincide(junto):
        return True
    if _coincide(normalizar(codecs.encode(n, "rot13"))):
        return True
    return any(_coincide(normalizar(d)) for d in _bloques_base64(texto))


def sanitizar_entrada(texto: str, largo_maximo: int = 2000) -> str:
    """Trunca y quita caracteres de control e invisibles. No decide nada:
    eso lo hace `detecto_injection`, antes de llamar al crew."""
    texto = texto[:largo_maximo]
    texto = re.sub(r"[\x00-\x09\x0b\x0c\x0e-\x1f]", "", texto).translate(_INVISIBLES)
    return texto.strip()


def dato_seguro(texto: str, reemplazo: str) -> str:
    """Para texto que viene de la base y va al prompt (inyeccion indirecta):
    un nombre de producto con instrucciones no llega al modelo."""
    return reemplazo if detecto_injection(texto) else texto


# Mismos marcadores que deploy/backend/guardrails.py del curso. El orden
# importa: el RUT va antes que el telefono porque sus digitos tambien calzan.
PATRONES_PII = (
    ("CORREO_ELECTRONICO_REDACTADO", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("RUT_CHILE_REDACTADO", re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")),
    ("TELEFONO_REDACTADO", re.compile(r"(?:\+?56\s?)?\b9\s?\d{4}\s?\d{4}\b")),
)


def sanitizar_pii(texto: str) -> str:
    """Reemplaza correos, RUT y celulares chilenos antes de guardar un log."""
    for marcador, patron in PATRONES_PII:
        texto = patron.sub(marcador, texto)
    return texto


def neutralizar_salida(texto: str) -> str:
    """Respuesta del modelo antes de `st.markdown` (LLM10:2026, CWE-79/116).

    Una imagen markdown se carga sola al renderizar: `![](https://x/?d=...)`
    saca datos sin que nadie haga clic. Se escapa el HTML, las imagenes se
    reemplazan por su texto y los enlaces quedan como texto plano.
    """
    t = html.escape(texto, quote=False)
    t = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"[imagen omitida: \1]", t)
    t = re.sub(r"\[([^\]]+)\]\(\s*(?:https?|javascript|data|vbscript):[^)]*\)", r"\1", t)
    return t
