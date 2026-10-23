"""Tests de FX.

Lo que se prueba acá es que el modulo FALLE cuando no puede conseguir un dato
confiable. El bug original era el contrario: un `except Exception` que caia a
un fallback hardcodeado cuyos valores (10.0 / 15.0) son exactamente los que
devuelve la API para nov-2015, asi que una API caida producia salida
byte-identica y la unica evidencia quedaba en un log que se truncaba.
"""
from datetime import date

import pytest
import requests

from etl import config, fx

MAX_FECHA = date(2015, 12, 21)   # el ultimo mes cerrado es noviembre 2015


def _serie(fecha="2015-11-30", venta=10.0):
    return [
        {"fecha": "2015-10-30", "compra": 9.0, "venta": 9.5},
        {"fecha": fecha, "compra": venta - 0.5, "venta": venta},
    ]


def _responder(payload, status=200):
    """requests.get que devuelve el payload dado."""
    class Resp:
        def raise_for_status(self):
            if status >= 400:
                raise requests.HTTPError("HTTP {}".format(status))

        def json(self):
            return payload

    return lambda url, timeout=None: Resp()


def _api_ok(monkeypatch):
    def get(url, timeout=None):
        venta = 15.0 if "blue" in url else 10.0
        return _responder(_serie(venta=venta))(url, timeout)

    monkeypatch.setattr(requests, "get", get)


# --- Camino feliz ---

def test_api_ok_devuelve_fuente_api(monkeypatch):
    _api_ok(monkeypatch)
    resultado = fx.get_fx(MAX_FECHA)

    assert resultado["fuente"] == "api"
    assert resultado["usd_oficial"] == 10.0
    assert resultado["usd_blue"] == 15.0
    assert resultado["fecha_fx"] == "2015-11-30"


def test_toma_el_ultimo_mes_cerrado_no_el_de_la_captura(monkeypatch):
    """Con capturas hasta el 21-dic, la cotizacion es la de cierre de noviembre."""
    _api_ok(monkeypatch)
    assert fx.get_fx(MAX_FECHA)["fecha_fx"].startswith("2015-11")


# --- Fallas: tienen que levantar, no caer al fallback ---

def test_http_500_levanta_fx_error(monkeypatch):
    monkeypatch.setattr(requests, "get", _responder(None, status=500))
    with pytest.raises(fx.FxError, match="reintentos"):
        fx.get_fx(MAX_FECHA)


def test_timeout_levanta_fx_error(monkeypatch):
    def get(url, timeout=None):
        raise requests.Timeout("se agoto el tiempo")

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(fx.FxError, match="reintentos"):
        fx.get_fx(MAX_FECHA)


def test_campo_venta_renombrado_levanta_nombrando_el_campo(monkeypatch):
    """El caso que el except Exception se comia: un cambio de esquema de la API."""
    payload = [{"fecha": "2015-11-30", "compra": 9.5, "sale": 10.0}]
    monkeypatch.setattr(requests, "get", _responder(payload))

    with pytest.raises(fx.FxError, match="venta"):
        fx.get_fx(MAX_FECHA)


def test_el_mensaje_de_esquema_menciona_los_campos_que_si_vinieron(monkeypatch):
    payload = [{"fecha": "2015-11-30", "compra": 9.5, "sale": 10.0}]
    monkeypatch.setattr(requests, "get", _responder(payload))

    with pytest.raises(fx.FxError) as exc:
        fx.get_fx(MAX_FECHA)
    assert "sale" in str(exc.value)


def test_sin_cotizacion_del_mes_levanta(monkeypatch):
    payload = [{"fecha": "2014-05-30", "venta": 8.0}]
    monkeypatch.setattr(requests, "get", _responder(payload))

    with pytest.raises(fx.FxError, match="sin cotizacion para 2015-11"):
        fx.get_fx(MAX_FECHA)


def test_venta_no_numerica_levanta(monkeypatch):
    payload = [{"fecha": "2015-11-30", "venta": "n/d"}]
    monkeypatch.setattr(requests, "get", _responder(payload))

    with pytest.raises(fx.FxError, match="no es numerico"):
        fx.get_fx(MAX_FECHA)


def test_venta_no_positiva_levanta(monkeypatch):
    payload = [{"fecha": "2015-11-30", "venta": 0}]
    monkeypatch.setattr(requests, "get", _responder(payload))

    with pytest.raises(fx.FxError, match="no es positivo"):
        fx.get_fx(MAX_FECHA)


def test_fecha_con_otro_formato_levanta(monkeypatch):
    payload = [{"fecha": "30/11/2015", "venta": 10.0}]
    monkeypatch.setattr(requests, "get", _responder(payload))

    with pytest.raises(fx.FxError, match="YYYY-MM-DD"):
        fx.get_fx(MAX_FECHA)


def test_payload_que_no_es_lista_levanta(monkeypatch):
    monkeypatch.setattr(requests, "get", _responder({"error": "rate limited"}))

    with pytest.raises(fx.FxError, match="no es una lista"):
        fx.get_fx(MAX_FECHA)


def test_el_error_explica_como_habilitar_el_fallback(monkeypatch):
    monkeypatch.setattr(requests, "get", _responder(None, status=500))

    with pytest.raises(fx.FxError) as exc:
        fx.get_fx(MAX_FECHA)
    mensaje = str(exc.value)
    assert "ETL_FX_FALLBACK=1" in mensaje
    assert "ETL_FX_OFICIAL" in mensaje


# --- Fallback: solo si se pide explicitamente ---

def test_fallback_habilitado_devuelve_los_valores_hardcodeados(monkeypatch):
    monkeypatch.setattr(requests, "get", _responder(None, status=500))
    monkeypatch.setattr(config, "FX_FALLBACK_HABILITADO", True)

    resultado = fx.get_fx(MAX_FECHA)

    assert resultado["fuente"] == "fallback"
    assert resultado["usd_oficial"] == 10.0
    assert resultado["usd_blue"] == 15.0
    # Fin del ultimo mes cerrado.
    assert resultado["fecha_fx"] == "2015-11-30"


def test_el_fallback_queda_registrado_en_el_log(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(requests, "get", _responder(None, status=500))
    monkeypatch.setattr(config, "FX_FALLBACK_HABILITADO", True)

    with caplog.at_level(logging.ERROR, logger="etl.fx"):
        fx.get_fx(MAX_FECHA)

    assert "fallback" in caplog.text


# --- Override de entorno ---

def test_override_no_llama_a_la_red(monkeypatch):
    """Con el override puesto, get_fx no debe tocar requests en absoluto."""
    def explotar(*args, **kwargs):
        raise AssertionError("no deberia haber llamado a la red")

    monkeypatch.setattr(requests, "get", explotar)
    monkeypatch.setenv("ETL_FX_OFICIAL", "10")
    monkeypatch.setenv("ETL_FX_BLUE", "15")

    resultado = fx.get_fx(MAX_FECHA)

    assert resultado["fuente"] == "override"
    assert resultado["usd_oficial"] == 10.0
    assert resultado["usd_blue"] == 15.0
    assert resultado["fecha_fx"] == "2015-11-30"


def test_override_acepta_fecha_propia(monkeypatch):
    monkeypatch.setenv("ETL_FX_OFICIAL", "9.8")
    monkeypatch.setenv("ETL_FX_BLUE", "14.2")
    monkeypatch.setenv("ETL_FX_FECHA", "2015-11-27")

    assert fx.get_fx(MAX_FECHA)["fecha_fx"] == "2015-11-27"


def test_override_incompleto_se_ignora(monkeypatch):
    """Con solo una de las dos variables, se usa la API."""
    _api_ok(monkeypatch)
    monkeypatch.setenv("ETL_FX_OFICIAL", "10")
    monkeypatch.delenv("ETL_FX_BLUE", raising=False)

    assert fx.get_fx(MAX_FECHA)["fuente"] == "api"


def test_override_no_numerico_levanta(monkeypatch):
    monkeypatch.setenv("ETL_FX_OFICIAL", "diez")
    monkeypatch.setenv("ETL_FX_BLUE", "15")

    with pytest.raises(fx.FxError, match="no son numericos"):
        fx.get_fx(MAX_FECHA)


# --- Reintentos ---

def test_reintenta_antes_de_rendirse(monkeypatch):
    intentos = []

    def get(url, timeout=None):
        intentos.append(url)
        raise requests.ConnectionError("sin red")

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(fx.FxError):
        fx.get_fx(MAX_FECHA)

    # FX_RETRIES + 1 intentos sobre la primera casa, y ahi corta.
    assert len(intentos) == config.FX_RETRIES + 1
