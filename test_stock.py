"""Tests de la capa determinista (stock.py). Sin LLM, sin red: cada uno
corre contra una base SQLite temporal propia, no contra tienda.db."""

import pytest

import db
import stock


@pytest.fixture(autouse=True)
def base_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", tmp_path / "test.db")
    db.crear_esquema()
    db.sembrar_datos_demo()


def _id_de(nombre: str) -> int:
    return stock.consultar_stock(nombre)[0].id


def test_consultar_stock_filtra_por_nombre():
    resultado = stock.consultar_stock("Taladro")
    assert len(resultado) == 1
    assert resultado[0].nombre == "Taladro percutor"


def test_consultar_stock_vacio_devuelve_todo():
    assert len(stock.consultar_stock("")) == 4


def test_productos_bajo_minimo_detecta_el_sembrado_bajo_minimo():
    nombres = {p.nombre for p in stock.productos_bajo_minimo()}
    # Taladro percutor (3/5) y Pan de molde (12/15) ya vienen bajo minimo
    # en los datos de demo.
    assert nombres == {"Taladro percutor", "Pan de molde"}


def test_registrar_venta_descuenta_stock():
    pid = _id_de("Cuaderno universitario")
    p = stock.registrar_venta(pid, 5)
    assert p.stock_actual == 35


def test_registrar_venta_falla_si_no_alcanza():
    pid = _id_de("Taladro percutor")
    with pytest.raises(ValueError):
        stock.registrar_venta(pid, 999)


def test_registrar_venta_producto_inexistente():
    with pytest.raises(ValueError):
        stock.registrar_venta(9999, 1)


def test_registrar_reposicion_suma_stock():
    pid = _id_de("Taladro percutor")
    p = stock.registrar_reposicion(pid, 10)
    assert p.stock_actual == 13


def test_venta_y_reposicion_quedan_en_el_historial():
    pid = _id_de("Pan de molde")
    stock.registrar_venta(pid, 2)
    stock.registrar_reposicion(pid, 7)
    movs = stock.historial_producto(pid)
    tipos = [m["tipo"] for m in movs]
    assert tipos == ["ingreso", "venta"]  # mas reciente primero


def test_historial_vacio_para_producto_sin_movimientos():
    pid = _id_de("Cuaderno universitario")
    assert stock.historial_producto(pid) == []


def test_producto_bajo_minimo_property():
    pid = _id_de("Taladro percutor")
    p = stock.consultar_stock("Taladro")[0]
    assert p.bajo_minimo is True
    stock.registrar_reposicion(pid, 20)
    p = stock.consultar_stock("Taladro")[0]
    assert p.bajo_minimo is False
