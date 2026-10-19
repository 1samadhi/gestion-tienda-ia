# Esquema de planificación (IE5)

Secuencia de decisión del sistema, de mayor a menor prioridad. No es el LLM
quien fija este orden — está en el código, es la arquitectura misma.

```
mensaje del dueño de la tienda
        │
        ▼
┌───────────────────────┐
│ 1. Manager (LLM)       │  decide a que rol corresponde — flexible,
│    Process.hierarchical│  razona en lenguaje natural
└───────────┬────────────┘
            │
   ┌────────┼────────────┐
   ▼        ▼             ▼
Inventario Ventas       (correos NUNCA llegan aca directo,
(lectura)  (venta)        ver punto 3)
            │
            ▼
┌────────────────────────────┐
│ 2. Disparo determinista     │  if stock_actual <= stock_minimo:
│    (Python, sin LLM)        │  decide SIN el LLM si hay que reponer
└───────────┬──────────────────┘
            │ si
            ▼
┌────────────────────────────┐
│ 3. Compras (LLM, ruta fija) │  generar_orden_compra() — no pasa por
│    redacta + envia correo   │  el manager (hallazgo dia 1: el manager
└────────────────────────────┘  razona bien pero no siempre delega)
```

## Por que esta prioridad y no otra

1. **Lo reversible (consultar, razonar) se le confía al LLM.** El manager
   jerárquico de CrewAI decide con lenguaje natural a quien corresponde
   la tarea — si se equivoca, el peor caso es una respuesta rehecha.
2. **Lo irreversible (gastar stock, mandar un correo real a un proveedor)
   nunca depende de que el LLM se acuerde de ejecutarlo.** Se probó en el
   día 1 que un manager LLM puede razonar correctamente sobre qué hacer
   y aun así no invocar la tool — ver `generar_orden_compra` en
   `agentes.py`.
3. **La cantidad a pedir tampoco la inventa el modelo** — es una fórmula
   (`stock_minimo*2 - stock_actual`), para que la decisión de "cuánto
   pedir" sea auditable y repetible, no una alucinación numérica.

## Evidencia de que ajusta el comportamiento ante condiciones cambiantes (IE6)

| condición | comportamiento del sistema |
|---|---|
| Venta deja el stock arriba del mínimo | Solo confirma la venta. Nada más. |
| Venta deja el stock en o bajo el mínimo | Dispara sola la reposición + correo real, sin que nadie pregunte |
| Tarea de correo, manager automático (`manager_llm`) | Delegó mal, al rol equivocado (Vendedor) |
| Misma tarea, manager con instrucciones explícitas | Razonó correcto pero no ejecutó la delegación — se quedó en el diagnóstico |
| Misma tarea, por `generar_orden_compra()` (ruta fija) | Correo real enviado, confirmado con ID de Gmail |

Los tres últimos renglones son la misma tarea, tres implementaciones
distintas — es la evidencia de por qué se llegó al esquema de arriba y no
a "todo por el manager".
