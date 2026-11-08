"""Que el agente no adivine productos, no repita operaciones, no cambie stock
ni escriba a proveedores sin aprobacion, y no gaste sin tope. Sin red.

Regresion de un caso real: "repon 1000 unidades del Taladro" termino en dos
ingresos de 1000 al Cuaderno (el agente adivino el id 1 y lo repitio).
"""

import pytest

import agentes
import db
import pendientes
import stock


@pytest.fixture(autouse=True)
def base_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", tmp_path / "test.db")
    db.crear_esquema()
    db.sembrar_datos_demo()
    agentes.nueva_peticion()


def _tool(t):
    return getattr(t, "func", t)


def _stock(nombre):
    return stock.consultar_stock(nombre)[0].stock_actual


@pytest.mark.parametrize("ref,esperado", [
    ("#2", "Taladro percutor"), ("2", "Taladro percutor"), ("taladro", "Taladro percutor"),
    ("TALADRO PERCUTOR", "Taladro percutor"), ("Pan de molde", "Pan de molde"),
])
def test_resolver_producto(ref, esperado):
    assert stock.resolver_producto(ref).nombre == esperado


@pytest.mark.parametrize("ref,motivo", [("Motosierra", "no existe"), ("#99", "no existe"), ("o", "es ambiguo")])
def test_resolver_producto_no_adivina(ref, motivo):
    with pytest.raises(ValueError, match=motivo):
        stock.resolver_producto(ref)


def test_reponer_1000_taladros_queda_pendiente_del_taladro_y_no_se_repite():
    reponer = _tool(agentes.tool_registrar_reposicion)
    primera = reponer("Taladro percutor", 1000)
    segunda = reponer("Taladro percutor", 1000)

    assert "pendiente de aprobacion" in primera and "No se repite" in segunda
    assert _stock("Taladro") == 3 and _stock("Cuaderno") == 40
    ops = pendientes.listar()
    assert [(o["producto"], o["cantidad"]) for o in ops] == [("Taladro percutor", 1000)]


def test_aprobar_reposicion_suma_una_vez():
    op = pendientes.proponer_reposicion(2, 10)
    assert "13 unidades" in pendientes.aprobar(op, enviar_correo=None)
    with pytest.raises(ValueError, match="ya fue resuelta"):
        pendientes.aprobar(op, enviar_correo=None)
    assert _stock("Taladro") == 13


def test_aprobar_correo_lo_envia_y_descartar_no():
    enviados = []
    a = pendientes.proponer_correo("proveedor1@example.com", "Orden", "20 panes")
    b = pendientes.proponer_correo("proveedor2@example.com", "Orden", "5 taladros")

    pendientes.aprobar(a, lambda d, s, c: enviados.append(d) or "msg-1")
    pendientes.descartar(b)

    assert enviados == ["proveedor1@example.com"]
    assert pendientes.listar() == []
    assert [o["estado"] for o in pendientes.listar("aprobada")] == ["aprobada"]


def test_venta_repetida_en_el_mismo_pedido_no_descuenta_dos_veces():
    vender = _tool(agentes.tool_registrar_venta)
    vender("Cuaderno universitario", 3)
    assert "No se repite" in vender("Cuaderno universitario", 3)
    assert _stock("Cuaderno") == 37


def test_pedido_nuevo_si_permite_la_misma_venta():
    vender = _tool(agentes.tool_registrar_venta)
    vender("Cuaderno universitario", 3)
    agentes.nueva_peticion()
    vender("Cuaderno universitario", 3)
    assert _stock("Cuaderno") == 34


def _uso(prompt, completion):
    def call(llm, messages, **kwargs):
        llm._token_usage["prompt_tokens"] += prompt
        llm._token_usage["completion_tokens"] += completion
        return "ok"
    return call


def test_tope_de_tokens_por_mensaje(monkeypatch):
    monkeypatch.setattr(agentes, "PRESUPUESTO_TOKENS", 2500)
    monkeypatch.setattr(agentes.LLMGroq, "call", _uso(900, 100))
    llm = agentes.modelo()

    for _ in range(3):
        llm.call([{"role": "user", "content": "x"}])
    with pytest.raises(agentes.PresupuestoAgotado, match="tope de 2500"):
        llm.call([{"role": "user", "content": "x"}])

    agentes.nueva_peticion()
    assert llm.call([{"role": "user", "content": "x"}]) == "ok"


def test_tope_de_rechazos_por_limite(monkeypatch):
    import litellm

    def siempre_limite(llm, messages, **kwargs):
        raise litellm.RateLimitError("try again in 0.01s", llm_provider="groq", model="m")

    monkeypatch.setattr(agentes, "MAX_LIMITES", 4)
    monkeypatch.setattr(agentes.LLMGroq, "call", siempre_limite)
    monkeypatch.setattr(agentes.time, "sleep", lambda s: None)

    with pytest.raises(agentes.PresupuestoAgotado, match="rechazo 4 llamadas"):
        agentes.modelo().call([{"role": "user", "content": "x"}])
