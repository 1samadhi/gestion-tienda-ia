"""Clave del dueño y permiso de escritura en las herramientas. Sin red."""

import pytest

import acceso
import agentes
import db
import pendientes
import stock


def test_hash_con_sal_y_verificacion():
    a, b = acceso.hash_clave("clave-larga-1"), acceso.hash_clave("clave-larga-1")
    assert a != b and "clave-larga-1" not in a
    assert acceso.verificar_clave("clave-larga-1", a)
    assert not acceso.verificar_clave("otra-clave", a)
    assert not acceso.verificar_clave("", a)
    assert not acceso.verificar_clave("clave-larga-1", "basura")


def test_guardar_en_env_reemplaza_sin_tocar_lo_demas(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=x\nDUENO_CLAVE_HASH=viejo\n")
    acceso.guardar_en_env("nuevo", env)
    assert env.read_text() == "GROQ_API_KEY=x\nDUENO_CLAVE_HASH=nuevo\n"


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", tmp_path / "t.db")
    db.crear_esquema()
    db.sembrar_datos_demo()


def _tool(t):
    return getattr(t, "func", t)


def test_sin_sesion_las_herramientas_que_escriben_se_niegan(base):
    agentes.nueva_peticion()
    for tool, args in [
        (agentes.tool_registrar_venta, ("Cuaderno universitario", 5)),
        (agentes.tool_registrar_reposicion, ("Cuaderno universitario", 5)),
        (agentes.tool_enviar_correo, ("proveedor1@example.com", "Orden", "x")),
    ]:
        assert _tool(tool)(*args).startswith("Rechazado: solo el dueño")
    assert stock.consultar_stock("Cuaderno")[0].stock_actual == 40
    assert pendientes.listar() == []


def test_sin_sesion_se_puede_consultar(base):
    agentes.nueva_peticion()
    assert "40" in _tool(agentes.tool_consultar_stock)("Cuaderno")


def test_con_sesion_vende(base):
    agentes.nueva_peticion(dueno=True)
    _tool(agentes.tool_registrar_venta)("Cuaderno universitario", 5)
    assert stock.consultar_stock("Cuaderno")[0].stock_actual == 35
