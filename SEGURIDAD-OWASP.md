# Mapa OWASP 2026 — gestion-tienda-ia

Controles del proyecto contra OWASP Top 10 for LLM Applications 2026, OWASP Top 10
for Agentic Applications 2026 y A05:2025 Injection.

Estados: **aplicado** = el control corre y un test lo prueba · **parcial** = corre una
parte, se dice el hueco · **en la defensa** = no se cierra; se nombra, no se simula.

Tests: `uv run pytest -q` (sin red).

## LLM01–LLM10:2026

| Código | Riesgo | Estado | Dónde | Evidencia |
|---|---|---|---|---|
| LLM01:2026 | Prompt Injection | parcial | `guardrails.detecto_injection` antes del crew: normaliza (NFKC, tildes, invisibles, homoglifos) y decodifica base64, rot13 y letras separadas. Bloqueado = 0 llamadas al LLM | `test_detecta_formas_directas`, `test_detecta_disfraces_mecanicos`, `test_no_bloquea_preguntas_legitimas`. Hueco: `test_limites_documentados_siguen_abiertos` (hex, texto invertido, idioma no listado, paráfrasis nueva) |
| LLM02:2026 | Sensitive Information Disclosure | parcial | `sanitizar_pii` (correo, RUT, celular) e id de organización de Groq redactados en `logs/trazas.jsonl`; claves solo en `.env` | Trazas guardadas sin PII. Hueco: el chat muestra al dueño el texto técnico del error |
| LLM03:2026 | Excessive Agency | aplicado | Herramientas por rol (Inventario lee; Ventas vende; Compras propone; Gerente solo delega). Reponer stock y escribir a proveedores quedan pendientes hasta que el dueño aprueba (`pendientes.py`) | `test_reponer_1000_taladros_queda_pendiente_del_taladro_y_no_se_repite`, `test_aprobar_reposicion_suma_una_vez`, `test_aprobar_correo_lo_envia_y_descartar_no` |
| LLM04:2026 | Supply Chain | parcial | `uv.lock` fija versiones | Sin escaneo de vulnerabilidades (pip-audit) |
| LLM05:2026 | Data and Model Poisoning | en la defensa | Sin fine-tuning; el modelo es de Groq | — |
| LLM06:2026 | Unbounded Consumption | aplicado | Tope por mensaje: 40 000 tokens y 12 rate limits (`PresupuestoAgotado`). Ante rate limit se espera lo que indica Groq y se rota entre 3 modelos | `test_tope_de_tokens_por_mensaje`, `test_tope_de_rechazos_por_limite`. Caso real antes del tope: 47 rate limits y 45k tokens en un mensaje |
| LLM07:2026 | Misinformation | parcial | Lo pendiente se informa leyendo la base, no lo que dice el modelo. La batería compara cada respuesta contra SQLite | El modelo dijo "correo enviado" cuando solo quedó preparado; el aviso de la app sale de `pendientes.listar()`. Hueco: en el chat la respuesta no se verifica antes de mostrarla |
| LLM08:2026 | Hidden Context Exposure | parcial | El filtro bloquea pedidos directos del prompt; el prompt no tiene secretos | Prueba en vivo: con una paráfrasis el gerente describió sus roles y restricciones (sin texto literal ni claves) |
| LLM09:2026 | Vector and Embedding Weaknesses | en la defensa | Memoria vectorial de CrewAI apagada por defecto (`MEMORIA_CREW`); no hay RAG | — |
| LLM10:2026 | Improper Output Handling | aplicado | `neutralizar_salida` escapa HTML y quita imágenes markdown y enlaces antes de `st.markdown` | `test_neutralizar_salida_no_deja_imagenes_ni_html_ni_enlaces`, `test_neutralizar_salida_respeta_markdown_comun` |

## ASI01–ASI10:2026

| Código | Riesgo | Estado | Dónde | Evidencia |
|---|---|---|---|---|
| ASI01:2026 | Agent Goal Hijack | parcial | Filtro de entrada; un nombre de producto con instrucciones no llega al prompt de otro agente (`dato_seguro`) | `test_nombre_envenenado_no_llega_al_prompt_de_otro_agente`. Prueba en vivo: correo a dirección ajena rechazado. Mismos huecos que LLM01 |
| ASI02:2026 | Tool Misuse and Exploitation | aplicado | Validan las herramientas, no el prompt: cantidad > 0, destinatario solo proveedor registrado, producto por nombre sin adivinar, sin repetir la misma operación en un mensaje | `test_venta_y_reposicion_rechazan_cantidades_no_positivas`, `test_correo_solo_a_proveedores_registrados`, `test_resolver_producto_no_adivina`, `test_venta_repetida_en_el_mismo_pedido_no_descuenta_dos_veces` |
| ASI03:2026 | Identity and Privilege Abuse | parcial | Sin sesión de dueño las herramientas que escriben se niegan (el permiso lo fija la app, no el LLM); clave como hash scrypt con sal en `.env` y 5 intentos por sesión (`acceso.py`); mínimo privilegio por rol; Gmail con scope `gmail.send` | `test_sin_sesion_las_herramientas_que_escriben_se_niegan`, `test_hash_con_sal_y_verificacion`. Hueco: una sola cuenta (dueño), sin usuarios por persona ni registro de quién aprobó |
| ASI04:2026 | Agentic Supply Chain | parcial | `uv.lock`; sin servidores MCP ni herramientas de terceros | Sin verificación de hashes ni escaneo |
| ASI05:2026 | Unexpected Code Execution | en la defensa | Ninguna herramienta ejecuta código ni SQL armado por el modelo | — |
| ASI06:2026 | Memory and Context Poisoning | parcial | Memoria vectorial apagada; el historial corto (3 turnos) pasa por el filtro y descarta turnos con inyección | `test_turno_con_inyeccion_no_se_arrastra`. Hueco: un ataque repartido en varios turnos inocentes |
| ASI07:2026 | Insecure Inter-Agent Communication | en la defensa | Los agentes corren en el mismo proceso; no hay mensajes entre servicios | — |
| ASI08:2026 | Cascading Failures | parcial | Fallback entre 3 modelos y topes: un mensaje que falla se corta sin arrastrar a los siguientes | Sin circuit breaker entre mensajes |
| ASI09:2026 | Human-Agent Trust Exploitation | parcial | Aprobación humana para reposición y correo; la app avisa "Nada de esto se ha ejecutado todavía" | Las ventas no piden confirmación |
| ASI10:2026 | Rogue Agents | en la defensa | Cada traza queda registrada (etapas, herramientas, tokens) para auditoría | Sin detección automática de desvíos |

## A05:2025 Injection, por intérprete

| Intérprete | Control | Evidencia |
|---|---|---|
| SQLite | Consultas parametrizadas; `LIKE` con `ESCAPE` | `test_sql_parametrizado_no_interpreta_el_texto`, `test_comodines_de_like_se_buscan_literales` |
| Cabeceras de correo | La librería `email` rechaza CRLF (CWE-93); destinatario de una lista blanca | `test_cabeceras_de_correo_rechazan_crlf`, `test_correo_solo_a_proveedores_registrados` |
| Prompt | Filtro de entrada; datos de la base limpiados antes de volver al modelo | `test_detecta_formas_directas`, `test_dato_seguro_reemplaza_un_nombre_con_instrucciones` |
| HTML de salida | Escape, sin imágenes ni enlaces | `test_neutralizar_salida_no_deja_imagenes_ni_html_ni_enlaces` |
| Argumentos de herramientas | Validación positiva (CWE-20): cantidad entera > 0, producto existente y único | `test_venta_y_reposicion_rechazan_cantidades_no_positivas`, `test_resolver_producto_no_adivina` |

## Lo que no cubre

- Usuarios individuales: hay una sola clave de dueño, sin registro de quién aprobó (ASI03).
- Inyección en hex, texto invertido, idiomas no listados o paráfrasis nuevas (LLM01).
- Ataques repartidos en varios turnos (ASI06).
- Verificar la respuesta del chat contra la base antes de mostrarla (LLM07).
- Escaneo de dependencias (LLM04, ASI04).

## Referencias

OWASP Foundation. (2025). *A05:2025 Injection*. OWASP Top 10:2025. https://owasp.org/Top10/2025/A05_2025-Injection/

OWASP GenAI Security Project. (2025). *OWASP Top 10 for agentic applications 2026*. https://genai.owasp.org/

OWASP GenAI Security Project. (2025). *OWASP Top 10 for LLM applications 2026*. https://genai.owasp.org/
