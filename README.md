# Gestion de Tienda IA

Agentes sobre stock de una tienda generica (productos, movimientos, proveedores).
No es especifico de un rubro: sirve para ferreteria, almacen, libreria, etc.

EP2 ISY0101 Duoc UC. Evolucion del enfoque sobre `asistente-pedidos360`, sin la
infraestructura AWS que ese proyecto necesitaba.

## Estado

En construccion. Por ahora: autenticacion OAuth de escritorio con Gmail para
que el agente de compras pueda enviar ordenes de reposicion.

```bash
uv sync
uv run python autenticar_gmail.py   # una vez, abre el navegador para el login
```

`credentials.json` y `gmail_token.json` no se versionan (`.gitignore`).
