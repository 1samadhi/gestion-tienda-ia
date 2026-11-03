# OWASP Top 10 LLM 2026 — mapeo contra gestion-tienda-ia

Referencia: `genai.owasp.org`, edición agosto 2026. No es checklist para cumplir de memoria,
es la lista que el profesor puede usar para evaluar seguridad (coincide con IE6 de la EV3:
"protocolos de seguridad y uso responsable... criterios éticos, normativos y de privacidad").

## Estado real, no aspiracional

| # | Riesgo | Estado | Dónde |
|---|---|---|---|
| LLM01 | Prompt Injection | 🟡 Mitigado parcial | `guardrails.py` — detección por patrones, capa 1, documentado como evadible por diseño |
| LLM02 | Sensitive Information Disclosure | 🟡 Parcial | Ningún dato de cliente real en el sistema (es ficticio); falta sanitizar si el LLM repite el contenido de un tool error con detalle interno |
| LLM03 | Excessive Agency | 🟢 Cubierto | Reparto de tools por rol (Inventario solo lee, Ventas solo vende, Compras es el único con Gmail) + `generar_orden_compra()` bypassa al manager para lo irreversible |
| LLM04 | Supply Chain | ⚪ No evaluado | Dependencias de `pyproject.toml` sin pin de hashes ni escaneo de vulnerabilidades (sí hay `uv.lock`) |
| LLM05 | Data and Model Poisoning | ⚪ No aplica | No hay fine-tuning ni entrenamiento propio; memoria de CrewAI es vectorial pero de datos propios del negocio, no de terceros |
| LLM06 | Unbounded Consumption | 🟢 Cubierto | `LLMConFallback` rota entre 3 modelos de Groq al chocar rate limit; sin límite de turnos/reintentos infinitos en el chat |
| LLM07 | Misinformation | 🟡 Parcial | El manager puede alucinar un IE/dato si Inventario no está disponible como delegable (bug real visto: "destornilladores" delegó mal); no hay verificación automática contra la fuente de verdad (SQLite) antes de responder |
| LLM08 | Hidden Context Exposure | ⚪ No evaluado | No se probó pedirle al agente que repita su system prompt o la memoria de otro cliente |
| LLM09 | Vector and Embedding Weaknesses | ⚪ No evaluado | Memoria vectorial (LanceDB) es de un solo negocio, sin multi-tenant; no se probó inyección vía documento indexado |
| LLM10 | Improper Output Handling | 🟡 Parcial | La respuesta del chat se muestra directo en Streamlit con `st.markdown()` — si el LLM devolviera HTML/JS en su respuesta, no hay sanitización explícita antes de renderizar |

## Las dos reglas que ya seguimos sin llamarlas OWASP

1. **Mínimo privilegio por rol** (LLM03) — decisión de arquitectura desde el día 1, no un parche.
2. **Acciones irreversibles no dependen de que el LLM decida ejecutarlas** (LLM03/LLM07) —
   `generar_orden_compra()` bypassa al manager.

## Qué conviene agregar antes de la EV3 (prioridad real, no las 10 por igual)

1. **LLM10 (sanitizar salida antes de `st.markdown()`)** — barato, una línea con un escapador
   de HTML si el contenido no es markdown de confianza.
2. **LLM07 (verificación contra la fuente de verdad)** — cuando el manager delega mal (bug real
   visto con "destornilladores"), la respuesta final debería citar el dato crudo de la tool, no
   la interpretación libre del LLM. Ya pasa parcialmente porque el prompt fuerza "el stock.",
   pero no hay un chequeo automático.
3. **LLM04 (supply chain)** — correr `pip-audit` o `uv pip list --outdated` una vez y documentar
   el resultado, aunque no se arregle nada: demuestra que se pensó en esto.

Las demás (LLM05, LLM08, LLM09) no aplican al tamaño de este proyecto — documentar por qué NO
aplican es tan válido para la IE6 como implementarlas.
