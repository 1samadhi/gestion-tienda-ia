# Pruebas

## Tests sin red

```bash
uv run pytest -q
```

Resultado: `119 passed`. No llaman a Groq ni a Gmail.

| Archivo | Tests | Qué prueba |
|---|---|---|
| `test_stock.py` | 10 | ventas, reposiciones y alertas de stock |
| `test_guardrails.py` | 36 | filtro de inyección, sus límites conocidos, salida segura |
| `test_seguridad.py` | 13 | SQL parametrizado, cantidades, correo solo a proveedores, CRLF |
| `test_pendientes.py` | 25 | aprobación humana, productos sin adivinar, sin duplicados, topes, cantidad del pedido |
| `test_acceso.py` | 5 | clave del dueño y permiso en las herramientas |
| `test_historial.py` | 5 | historial corto y descarte de turnos con inyección |
| `test_observabilidad.py` | 20 | trazas, métricas, redacción de datos personales |
| `test_dashboard.py` | 5 | cálculos del tablero |

## Batería con el modelo real

```bash
uv run python bateria.py --todos --repeticiones 3
```

Cada caso parte de una base limpia y se verifica contra SQLite. Corrida del
22-nov-2026, 15 casos × 3, sin memoria vectorial, `openai/gpt-oss-120b`:

| Escenario | Peticiones | Precisión | p50 | p95 | Tokens prom. |
|---|---|---|---|---|---|
| Lectura | 12 | 100 % | 5,1 s | 7,8 s | 3 121 |
| Escritura | 12 | 100 % | 7,6 s | 9,7 s | 3 994 |
| Error del usuario | 9 | 88,9 % | 7,2 s | 10,2 s | 4 281 |
| Ataque | 12 | 100 % | 6,6 s | 10,5 s | 3 025 |
| **Total** | **45** | **97,8 %** | **6,7 s** | **10,2 s** | **3 643** |

0 errores, 6 ataques bloqueados antes del modelo, 0,1 rechazos por cupo por petición.

La falla: con "Vende -5 cuadernos" el modelo pasó 5 a la herramienta y vendió
en 1 de 3 corridas. Desde entonces la cantidad tiene que estar escrita en el
pedido; en 21 re-corridas de casos de escritura la base no se modificó de
forma indebida. Después se agregó `venta_sin_sesion` (3/3 rechazadas).

## Memoria vectorial: con y sin

Mismos 5 casos, 10 corridas por configuración:

| | Precisión | p50 | p95 | Tokens prom. |
|---|---|---|---|---|
| Con memoria | 100 % | 35,1 s | 55,8 s | 6 472 |
| Sin memoria | 90 % | 6,2 s | 8,4 s | 4 393 |

El fallo sin memoria fue una respuesta ambigua sobre un producto inexistente
(dijo "stock cero" sin aclarar que no existe), sin cambios en la base.

## Ver las trazas

```bash
uv run python observabilidad.py             # últimas trazas y métricas
uv run python observabilidad.py <trace_id>  # etapas de una traza
uv run python observabilidad.py --comparar  # una fila por configuración
```

O en la pestaña Observabilidad de la app.
