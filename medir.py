"""Mide tokens y segundos de una corrida representativa (dia 3 del plan,
evidencia IE5/IE6). Tres casos, de menor a mayor costo real:

    1. consulta        solo lectura, manager delega a Inventario
    2. venta_simple    escritura, sin disparar reposicion
    3. venta_critica    escritura que SI dispara la planificacion adaptativa
                        (venta + deteccion de minimo + correo real al
                        proveedor) — mide el costo real de la cadena completa

Uso:
    uv run python medir.py
"""

import time

from agentes import crear_crew


def tokens_de(crew) -> int:
    m = getattr(crew, "usage_metrics", None)
    return getattr(m, "total_tokens", 0) or 0


def correr(mensaje: str, etiqueta: str, conversacion_id: str) -> None:
    crew = crear_crew(mensaje, conversacion_id=conversacion_id)
    t0 = time.perf_counter()
    salida = crew.kickoff()
    seg = time.perf_counter() - t0
    tok = tokens_de(crew)
    print(f"\n{'=' * 74}")
    print(f"  {etiqueta}  —  {seg:5.1f}s  {tok:>6} tokens")
    print(f"{'=' * 74}")
    print(str(salida).strip()[:300])


if __name__ == "__main__":
    correr(
        "Cual es el stock del Cuaderno universitario?",
        "1. consulta (solo lectura)",
        "medicion-1",
    )
    correr(
        "Vende 3 unidades del Cuaderno universitario y dime como queda el stock.",
        "2. venta simple (sin disparar reposicion)",
        "medicion-2",
    )
    correr(
        "Vende 1 unidad del Destornillador phillips y dime como queda el stock.",
        "3. venta critica (dispara reposicion + correo real)",
        "medicion-3",
    )
