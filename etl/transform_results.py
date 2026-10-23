import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from etl import config
from etl.errors import requiere_columnas

logger = logging.getLogger(__name__)

EXCEL_EPOCH = datetime(1899, 12, 30)


def _serial_a_fecha(key_results: pd.Series) -> pd.Series:
    serial = key_results.str.split("-", n=1).str[0].astype(int)
    return EXCEL_EPOCH + pd.to_timedelta(serial, unit="D")


# __KEY_results tiene la forma {serial}-{offset}-{categoria}-{indice},
# p.ej. 42316-0-MLA29483-200. Los tres campos numericos ordenan las capturas.
CLAVES_ORDEN = ["_k_serial", "_k_offset", "_k_indice"]
_CAMPOS_NUMERICOS = {"_k_serial": 0, "_k_offset": 1, "_k_indice": 3}


def agregar_claves_orden(df: pd.DataFrame) -> pd.DataFrame:
    """Parsea __KEY_results a columnas numericas de orden.

    Ordenar __KEY_results como string es incorrecto: el offset toma los valores
    {0, 200, 400, 600, 800, 1000, 1200, 1400}, con distinta cantidad de
    digitos, asi que lexicograficamente '800' > '1400' y la captura de las 8
    ganaria sobre la de las 14 del mismo dia. En este dataset no muerde (de los
    10 duplicados intra-dia reales, los 10 resuelven igual con string que con
    numero, porque ningun par mezcla cantidades de digitos), pero un re-scrape
    elegiria la captura equivocada en silencio.

    Las columnas son privadas (prefijo _) y ninguna tabla de salida las lista,
    asi que no llegan a los CSVs.
    """
    df = df.copy()
    partes = df["__KEY_results"].str.split("-", expand=True)
    if partes.shape[1] != 4:
        raise ValueError(
            "__KEY_results deberia tener 4 campos separados por '-', "
            "se encontraron {}. Ejemplo: {!r}".format(partes.shape[1], df["__KEY_results"].iloc[0])
        )

    for columna, campo in _CAMPOS_NUMERICOS.items():
        valores = pd.to_numeric(partes[campo], errors="coerce")
        if valores.isna().any():
            malformadas = df.loc[valores.isna(), "__KEY_results"].head(3).tolist()
            raise ValueError(
                "campo {} de __KEY_results no es numerico en {} filas. Ejemplos: {}".format(
                    campo, int(valores.isna().sum()), malformadas
                )
            )
        df[columna] = valores.astype("int64")
    return df


def parse_basico(df_results: pd.DataFrame) -> pd.DataFrame:
    df = df_results.rename(columns={"id_u9": "id_publicacion"}).copy()
    df["stop_time"] = pd.to_datetime(df["stop_time"], format=config.STOP_TIME_FORMAT)
    df["fecha_captura"] = _serial_a_fecha(df["__KEY_results"]).dt.date
    return agregar_claves_orden(df)


def calcular_price_ars(df: pd.DataFrame, fx_blue: float) -> pd.DataFrame:
    df = df.copy()
    es_usd = df["currency_id"].eq("USD")
    df["price_ars"] = np.where(es_usd, df["price"] * fx_blue, df["price"])
    return df


def calcular_precio_invalido(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Capa 1 de outliers de precio: piso por moneda + techo dinamico global.

    El techo se recalcula en cada corrida a partir de los propios cuartiles de
    price_ars (sobre filas que ya pasaron el piso), para no depender de un
    numero fijo en ARS que la inflacion vuelve obsoleto.
    """
    df = df.copy()

    piso_invalido = (
        df["price"].isna()
        | ((df["currency_id"] == "ARS") & (df["price"] <= config.PRECIO_INVALIDO_ARS_MIN))
        | ((df["currency_id"] == "USD") & (df["price"] <= config.PRECIO_INVALIDO_USD_MIN))
    )

    precios_validos_piso = df.loc[~piso_invalido, "price_ars"]
    q1, q3 = precios_validos_piso.quantile([0.25, 0.75])
    iqr = q3 - q1
    techo_global = q3 + config.TECHO_GLOBAL_K * iqr

    techo_invalido = (~piso_invalido) & (df["price_ars"] > techo_global)
    precio_invalido = piso_invalido | techo_invalido

    df["precio_invalido"] = precio_invalido

    diagnostico = {
        "piso_invalido": int(piso_invalido.sum()),
        "techo_global": float(techo_global),
        "techo_invalido": int(techo_invalido.sum()),
        "precio_invalido_total": int(precio_invalido.sum()),
    }
    logger.info(
        "Capa 1 precio: piso=%s, techo_global=%.0f ARS, techo_invalido=%s, total_invalido=%s",
        diagnostico["piso_invalido"],
        diagnostico["techo_global"],
        diagnostico["techo_invalido"],
        diagnostico["precio_invalido_total"],
    )
    return df, diagnostico


def deduplicar_por_aviso(df: pd.DataFrame) -> pd.DataFrame:
    """Criterio determinístico de dedup (sección 5.6 del documento de diseño).

    Gana la captura mas reciente: fecha, y dentro del dia el offset y el indice
    mas altos. El orden sale de las claves numericas, no del string
    __KEY_results (ver agregar_claves_orden).

    Se usa tanto para elegir la captura ganadora de atributos (antes de
    pivotear) como para construir el snapshot final de fact_publicaciones.
    """
    df_sorted = df.sort_values(["fecha_captura"] + CLAVES_ORDEN, ascending=False)
    return df_sorted.drop_duplicates(subset=["id_publicacion"], keep="first")


def categoria_km(km, km_invalido) -> str:
    """Categoriza el kilometraje. Un km nulo es "Sin dato" venga como venga.

    El chequeo de nulo va primero y explicito: con km=pd.NA, la comparacion
    `km == 0` devuelve pd.NA y el `if` revienta con
    TypeError: boolean value of NA is ambiguous.
    Hoy es inalcanzable porque agregar_rango_km deriva km_malo de
    kilometros_limpio.isna(), pero era una precondicion indefensa que depende
    de que el llamador no se equivoque.
    """
    if pd.isna(km_invalido) or bool(km_invalido) or pd.isna(km):
        return "Sin dato"
    if km == 0:
        return "0 KM"
    if km < 25_000:
        return "Menos de 25.000 KM"
    if km < 50_000:
        return "De 25.000 a 50.000 KM"
    if km < 100_000:
        return "De 50.000 a 100.000 KM"
    if km < 500_000:
        return "De 100.000 a 500.000 KM"
    return "Más de 500.000 KM"


ORDEN_RANGO_KM = {
    "0 KM": 1,
    "Menos de 25.000 KM": 2,
    "De 25.000 a 50.000 KM": 3,
    "De 50.000 a 100.000 KM": 4,
    "De 100.000 a 500.000 KM": 5,
    "Más de 500.000 KM": 6,
    "Sin dato": 7,
}


def agregar_rango_km(df: pd.DataFrame) -> pd.DataFrame:
    """Categoriza por kilometros_limpio (no el crudo), asi un km_outlier (capa 2)
    cae en "Sin dato" igual que un km_invalido (capa 1) — requiere que
    kilometros_limpio ya exista (outliers.agregar_columnas_limpias corre antes).
    """
    df = df.copy()
    requiere_columnas(df, ["kilometros_limpio"], "agregar_rango_km")
    km_malo = df["kilometros_limpio"].isna()
    df["rango_km"] = [
        categoria_km(km, malo) for km, malo in zip(df["kilometros_limpio"], km_malo)
    ]
    df["orden_rango_km"] = df["rango_km"].map(ORDEN_RANGO_KM)
    return df


def dolarizar(df: pd.DataFrame, fx_oficial: float, fx_blue: float) -> pd.DataFrame:
    """Columnas en USD. Las _limpio salen de price_ars_limpio, asi que esta
    funcion tambien depende de que outliers.agregar_columnas_limpias haya
    corrido antes."""
    requiere_columnas(df, ["price_ars", "price_ars_limpio", "precio_invalido"], "dolarizar")
    df = df.copy()
    valido = ~df["precio_invalido"]
    df["price_usd_oficial"] = np.where(valido, df["price_ars"] / fx_oficial, np.nan)
    df["price_usd_blue"] = np.where(valido, df["price_ars"] / fx_blue, np.nan)
    df["price_usd_oficial_limpio"] = df["price_ars_limpio"] / fx_oficial
    df["price_usd_blue_limpio"] = df["price_ars_limpio"] / fx_blue
    return df


def diagnostico_duplicados(df: pd.DataFrame) -> dict:
    capturas_por_aviso = df.groupby("id_publicacion").size()
    intra_dia = df.groupby(["id_publicacion", "fecha_captura"]).size()
    intra_dia = intra_dia[intra_dia > 1]

    return {
        "filas_totales": len(df),
        "avisos_unicos": int(capturas_por_aviso.shape[0]),
        "promedio_capturas_por_aviso": float(capturas_por_aviso.mean()),
        "mediana_capturas_por_aviso": float(capturas_por_aviso.median()),
        "max_capturas_por_aviso": int(capturas_por_aviso.max()),
        "avisos_con_mas_de_1_captura": int((capturas_por_aviso > 1).sum()),
        "avisos_con_duplicado_intra_dia": int(intra_dia.index.get_level_values("id_publicacion").nunique()),
        "ejemplos_duplicado_intra_dia": list(
            intra_dia.index.get_level_values("id_publicacion").unique()[:5]
        ),
    }
