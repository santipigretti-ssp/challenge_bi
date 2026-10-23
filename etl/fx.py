from __future__ import annotations

import logging
from datetime import date, timedelta

import requests

from etl import config

logger = logging.getLogger(__name__)


def _ultimo_mes_cerrado(max_fecha_captura: date) -> tuple[int, int]:
    primer_dia_mes_actual = max_fecha_captura.replace(day=1)
    ultimo_dia_mes_anterior = primer_dia_mes_actual - timedelta(days=1)
    return ultimo_dia_mes_anterior.year, ultimo_dia_mes_anterior.month


def _fetch_serie(casa: str) -> list[dict]:
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
    raise RuntimeError(f"No se pudo obtener cotizacion {casa} tras reintentos") from last_error


def _ultimo_valor_del_mes(serie: list[dict], anio: int, mes: int) -> dict | None:
    prefijo = f"{anio:04d}-{mes:02d}"
    del_mes = [d for d in serie if d["fecha"].startswith(prefijo)]
    if not del_mes:
        return None
    return max(del_mes, key=lambda d: d["fecha"])


def get_fx(max_fecha_captura: date) -> dict:
    anio, mes = _ultimo_mes_cerrado(max_fecha_captura)

    try:
        series = {casa: _fetch_serie(casa) for casa in config.FX_CASAS}
        ultimos = {
            casa: _ultimo_valor_del_mes(serie, anio, mes) for casa, serie in series.items()
        }
        if any(v is None for v in ultimos.values()):
            raise RuntimeError(f"Sin cotizacion para {anio}-{mes:02d} en alguna casa")

        fecha_fx = min(v["fecha"] for v in ultimos.values())
        return {
            "fecha_fx": fecha_fx,
            "usd_oficial": float(ultimos["oficial"]["venta"]),
            "usd_blue": float(ultimos["blue"]["venta"]),
        }
    except Exception as exc:
        logger.error("FX API fallo, usando fallback hardcodeado: %s", exc)
        ultimo_dia_mes = (date(anio, mes, 1).replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        return {
            "fecha_fx": ultimo_dia_mes.isoformat(),
            "usd_oficial": config.FX_FALLBACK["oficial"],
            "usd_blue": config.FX_FALLBACK["blue"],
        }
