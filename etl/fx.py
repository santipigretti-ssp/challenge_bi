"""Tipo de cambio ARS/USD desde la API de ArgentinaDatos.

Decision central de este modulo: por defecto FALLA. Antes envolvia todo en un
`except Exception` y caia a un fallback hardcodeado de {oficial: 10.0,
blue: 15.0}, que son exactamente los valores que la API devuelve para nov-2015.
O sea que una API caida, un cambio de esquema o un campo "venta" renombrado
producian una salida byte-identica, con la unica evidencia en un log que ademas
se truncaba en la corrida siguiente. Un fallback que coincide con la realidad
es peor que no tener fallback: vuelve el error invisible.

Ahora el fallback es opt-in (ETL_FX_FALLBACK=1) y el origen del dato viaja en
el resultado y termina en dim_FX, asi que el linaje queda visible en el modelo
y no solo en un log.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta

import requests

from etl import config

logger = logging.getLogger(__name__)

FUENTE_API = "api"
FUENTE_FALLBACK = "fallback"
FUENTE_OVERRIDE = "override"

_FECHA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FxError(RuntimeError):
    """No se pudo obtener un tipo de cambio confiable."""


def _ultimo_mes_cerrado(max_fecha_captura: date) -> tuple[int, int]:
    primer_dia_mes_actual = max_fecha_captura.replace(day=1)
    ultimo_dia_mes_anterior = primer_dia_mes_actual - timedelta(days=1)
    return ultimo_dia_mes_anterior.year, ultimo_dia_mes_anterior.month


def _ultimo_dia_del_mes(anio: int, mes: int) -> date:
    return (date(anio, mes, 28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _fetch_serie(casa: str) -> list:
    url = config.FX_API_URL.format(casa=casa)
    last_error = None
    for attempt in range(1, config.FX_RETRIES + 2):
        try:
            resp = requests.get(url, timeout=config.FX_TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_error = exc
            logger.warning("FX API (%s) intento %s fallo: %s", casa, attempt, exc)
    raise FxError("no se pudo obtener la cotizacion {} tras reintentos".format(casa)) from last_error


def _validar_serie(serie, casa: str) -> list:
    """Valida la forma del payload en vez de confiar en un except Exception.

    Es justamente lo que faltaba: sin esto, un "venta" renombrado se comia la
    excepcion y salia por el fallback sin que se notara.
    """
    if not isinstance(serie, list) or not serie:
        raise FxError("la serie de {} no es una lista no vacia (es {})".format(casa, type(serie).__name__))

    validos = []
    for registro in serie:
        if not isinstance(registro, dict):
            raise FxError("la serie de {} trae un elemento que no es dict: {!r}".format(casa, registro))
        if "fecha" not in registro:
            raise FxError("falta el campo 'fecha' en un registro de {}: {!r}".format(casa, registro))
        if "venta" not in registro:
            raise FxError(
                "falta el campo 'venta' en un registro de {} (campos: {}). "
                "Puede ser un cambio de esquema de la API.".format(casa, sorted(registro))
            )
        if not isinstance(registro["fecha"], str) or not _FECHA_ISO.match(registro["fecha"]):
            raise FxError("'fecha' no tiene formato YYYY-MM-DD en {}: {!r}".format(casa, registro["fecha"]))
        validos.append(registro)
    return validos


def _ultimo_valor_del_mes(serie: list, anio: int, mes: int):
    prefijo = "{:04d}-{:02d}".format(anio, mes)
    del_mes = [d for d in serie if d["fecha"].startswith(prefijo)]
    if not del_mes:
        return None
    return max(del_mes, key=lambda d: d["fecha"])


def _cotizacion(registro, casa: str) -> float:
    try:
        valor = float(registro["venta"])
    except (TypeError, ValueError) as exc:
        raise FxError("'venta' no es numerico en {}: {!r}".format(casa, registro["venta"])) from exc
    if valor <= 0:
        raise FxError("'venta' no es positivo en {}: {}".format(casa, valor))
    return valor


def _override_del_entorno(anio: int, mes: int):
    """ETL_FX_OFICIAL / ETL_FX_BLUE cortocircuitan la llamada a la API.

    Es lo que usan CI y los tests. Mejor que monkeypatchear get_fx, porque el
    codigo real de get_fx sigue bajo test.
    """
    oficial = os.getenv("ETL_FX_OFICIAL")
    blue = os.getenv("ETL_FX_BLUE")
    if oficial is None or blue is None:
        return None
    try:
        valores = {"usd_oficial": float(oficial), "usd_blue": float(blue)}
    except ValueError as exc:
        raise FxError(
            "ETL_FX_OFICIAL/ETL_FX_BLUE no son numericos: {!r} / {!r}".format(oficial, blue)
        ) from exc

    fecha = os.getenv("ETL_FX_FECHA") or _ultimo_dia_del_mes(anio, mes).isoformat()
    if not _FECHA_ISO.match(fecha):
        raise FxError("ETL_FX_FECHA no tiene formato YYYY-MM-DD: {!r}".format(fecha))

    logger.info("FX por override de entorno: oficial=%s blue=%s al %s",
                valores["usd_oficial"], valores["usd_blue"], fecha)
    return {"fecha_fx": fecha, "fuente": FUENTE_OVERRIDE, **valores}


def get_fx(max_fecha_captura: date) -> dict:
    """Cotizacion de cierre del ultimo mes cerrado respecto de la ultima captura.

    Devuelve fecha_fx, usd_oficial, usd_blue y fuente (api | override |
    fallback). Levanta FxError si no puede conseguir un valor confiable, salvo
    que el fallback este habilitado explicitamente.
    """
    anio, mes = _ultimo_mes_cerrado(max_fecha_captura)

    override = _override_del_entorno(anio, mes)
    if override is not None:
        return override

    try:
        series = {casa: _validar_serie(_fetch_serie(casa), casa) for casa in config.FX_CASAS}
        ultimos = {casa: _ultimo_valor_del_mes(serie, anio, mes) for casa, serie in series.items()}

        sin_dato = [casa for casa, v in ultimos.items() if v is None]
        if sin_dato:
            raise FxError("sin cotizacion para {}-{:02d} en {}".format(anio, mes, ", ".join(sin_dato)))

        return {
            "fecha_fx": min(v["fecha"] for v in ultimos.values()),
            "usd_oficial": _cotizacion(ultimos["oficial"], "oficial"),
            "usd_blue": _cotizacion(ultimos["blue"], "blue"),
            "fuente": FUENTE_API,
        }
    except FxError as exc:
        if not config.FX_FALLBACK_HABILITADO:
            raise FxError(
                "{}. El fallback hardcodeado esta deshabilitado a proposito: sus valores "
                "coinciden con los reales de nov-2015, asi que usarlo en silencio haria "
                "invisible una falla de la API. Para habilitarlo: ETL_FX_FALLBACK=1. "
                "Para fijar el valor a mano: ETL_FX_OFICIAL y ETL_FX_BLUE.".format(exc)
            ) from exc

        logger.error("FX API fallo, se usa el fallback hardcodeado (ETL_FX_FALLBACK=1): %s", exc)
        return {
            "fecha_fx": _ultimo_dia_del_mes(anio, mes).isoformat(),
            "usd_oficial": config.FX_FALLBACK["oficial"],
            "usd_blue": config.FX_FALLBACK["blue"],
            "fuente": FUENTE_FALLBACK,
        }
