# Diseño

Bocetos de la interfaz y del recorrido de un pedido.

## Pantallas

```mermaid
flowchart TB
  L["🔐 Barra lateral<br/>clave del dueño"] --> H
  H["Encabezado · pastilla de modo: consulta o dueño"]
  H --> S & C & O & E
  S["<b>📋 Stock</b><br/>franja de resumen<br/>pendientes de aprobación<br/>tarjetas de producto<br/>historial"]
  C["<b>💬 Chat</b><br/>conversación<br/>línea de estado en vivo<br/>segundos · tokens · traza"]
  O["<b>📊 Observabilidad</b><br/>filtros<br/>salud de la llamada<br/>volumen y abuso<br/>gráficos y trazas"]
  E["<b>🩺 Estado</b><br/>token de Gmail<br/>base de datos<br/>prueba de Groq"]
```

| Pestaña | Usa IA | Para qué |
|---|---|---|
| Stock | no | ver el inventario y aprobar lo que propusieron los agentes |
| Chat | sí | pedir ventas, consultas y reposiciones en lenguaje natural |
| Observabilidad | no | métricas y trazas guardadas |
| Estado | solo el botón de Groq | revisar que todo esté conectado |

## Recorrido de un pedido y sus controles

```mermaid
flowchart TD
  P["Pedido en el chat"] --> F{"Filtro de entrada"}
  F -- "inyección" --> B["Bloqueado, sin llamar al modelo"]
  F --> G["Gerente: decide a quién delegar"]
  G --> R["Rol con su herramienta"]
  R --> T{"Controles de la herramienta"}
  T -- "sin sesión de dueño" --> N["Rechazado"]
  T -- "cantidad que no está en el pedido" --> N
  T -- "producto ambiguo o inexistente" --> N
  T -- "correo a quien no es proveedor" --> N
  T -- "venta" --> V["Stock descontado"]
  T -- "reposición o correo" --> Q["Pendiente de aprobación"]
  Q -- "el dueño aprueba" --> X["Se ejecuta"]
  V & N & Q --> S["Respuesta escapada + aviso de pendientes leído de la base"]
```

Los rechazos los decide el código de la herramienta, no el modelo.
