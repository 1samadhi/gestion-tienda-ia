# Medición de tokens y latencia (corrida representativa)

`uv run python medir.py` — 3 casos reales contra `openai/gpt-oss-120b` (Groq),
mismo proceso, memoria nativa activada (`memory=True`).

| caso | descripción | tiempo | tokens |
|---|---|---|---|
| 1 | Consulta de stock (solo lectura, manager → Inventario) | 57.3s | 16 651 |
| 2 | Venta simple (no dispara reposición) | 81.6s | 20 316 |
| 3 | Venta crítica (dispara reposición + correo real) | 78.3s | 15 389 |

## Lectura honesta de los números, no la esperada

El caso 3 hace **más trabajo real** que el caso 2 (ademas de vender, decide
reponer y manda un correo real) y aun así usa **menos tokens**. No es que
sea más eficiente — es que el costo de una corrida con `memory=True` y
`Process.hierarchical` está dominado por llamadas de soporte que no se ven
en el resultado final:

- `search_memory` (el manager consulta la memoria antes de actuar)
- extracción y consolidación de memoria al terminar cada tarea (falla
  seguido contra Groq — ver más abajo — y cada intento fallido cuenta
  tokens igual)
- reintentos por rate limit (ver abajo)

El llamado a "capa 2, Compras" del caso 3 agrega relativamente poco porque
es un crew de un solo agente (`generar_orden_compra`), no otro ciclo
completo de manager jerárquico.

## Restricción real encontrada durante la medición: cuota compartida de Groq

Las tres corridas chocaron reiteradamente contra el límite gratuito de Groq
(8000 tokens/minuto, por modelo, compartido por toda la organización) y
tuvieron que reintentar varias veces cada una (`litellm.RateLimitError`,
visible en los logs). El sistema **no se cayó** — litellm reintenta solo —
pero la latencia real que ve el usuario es mayor a la que tomaría el
modelo sin la limitante.

Es una restricción legítima de operar en el tier gratuito, documentada acá
en vez de ocultada: con una key de pago (Dev Tier) o rotando a otro
proveedor (Cerebras, OpenRouter) desaparecería.

## Falla recurrente de CrewAI con Groq, ya conocida mitigada

La extracción/consolidación de memoria de CrewAI fuerza tool calls con un
schema estricto; Groq devuelve seguido `tool_use_failed` o
`BadRequestError` ahi (visto en los tres casos). CrewAI degrada con
gracia: guarda el contenido igual, sin estructurar, y sigue — no bloquea
la tarea principal. Mismo patrón que el hallazgo de `gpt-oss-20b` del
día 2, ahora confirmado también en `120b` para este tipo de llamada
interna especifica (no la llamada principal del agente, que funciona
bien).
