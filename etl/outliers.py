import logging
from datetime import datetime

import pandas as pd

from etl import config

logger = logging.getLogger(__name__)


def calc_iqr_bounds(serie: pd.Series, k: float = 1.5) -> tuple[float, float]:
    q1 = serie.quantile(0.25)
    q3 = serie.quantile(0.75)
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


def calcular_km_invalido(df: pd.DataFrame) -> pd.Series:
    km = df["kilometros"]
    return (
        km.isna()
        | (km < 0)
        | ((km > 0) & (km < config.KM_TYPO_MAX))
        | (km > config.KM_MAX_REAL)
    )


def calcular_anio_invalido(df: pd.DataFrame) -> pd.Series:
    anio = df["anio"]
    anio_max = datetime.now().year + 1
    return anio.isna() | (anio < config.ANIO_MIN) | (anio > anio_max)


def _flag_outliers_por_grupo(
    df: pd.DataFrame,
    value_col: str,
    filtro_valido: pd.Series,
    k: float,
    min_avisos: int,
) -> tuple[pd.Series, dict]:
    flag = pd.Series(False, index=df.index)
    elegibles = df[filtro_valido & df["anio"].notna() & df["id_modelo"].notna()]

    grupos_total = 0
    grupos_sin_muestra = 0

    for _, grupo in elegibles.groupby(["id_modelo", "anio"]):
        grupos_total += 1
        n_avisos = grupo["id_publicacion"].nunique()
        if n_avisos < min_avisos:
            grupos_sin_muestra += 1
            continue
        lower, upper = calc_iqr_bounds(grupo[value_col], k)
        mask = (grupo[value_col] < lower) | (grupo[value_col] > upper)
        flag.loc[grupo.index[mask]] = True

    diag = {
        "grupos_total": grupos_total,
        "grupos_sin_muestra_minima": grupos_sin_muestra,
    }
    return flag, diag


def agregar_columnas_limpias(df: pd.DataFrame) -> pd.DataFrame:
    """Columnas derivadas con null en las filas invalidas (capa 1) u outlier (capa 2).

    Pensadas para graficar directo en Power BI sin tener que combinar el valor
    crudo con los flags en cada medida. precio_outlier/km_outlier solo se
    calculan sobre filas ya validas en capa 1 (ver _flag_outliers_por_grupo),
    asi que invalido y outlier nunca se superponen para la misma fila.
    """
    df = df.copy()
    precio_malo = df["precio_invalido"] | df["precio_outlier"]
    km_malo = df["km_invalido"] | df["km_outlier"]

    df["price_ars_limpio"] = df["price_ars"].mask(precio_malo)
    df["kilometros_limpio"] = df["kilometros"].mask(km_malo)
    df["anio_limpio"] = df["anio"].mask(df["anio_invalido"])
    return df


def aplicar_outliers(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Capa 1 (km/anio) y capa 2 (IQR por grupo) sobre results_base completo.

    Se corre una sola vez, antes de ramificar a fact_publicaciones y
    fact_precios_historicos (ver sección 2.2 del plan). El gate de muestra
    minima cuenta avisos distintos (id_publicacion.nunique()), no filas, para
    no inflar artificialmente la "muestra" con capturas repetidas del mismo
    auto.
    """
    df = df.copy()
    df["km_invalido"] = calcular_km_invalido(df)
    df["anio_invalido"] = calcular_anio_invalido(df)

    precio_outlier, diag_precio = _flag_outliers_por_grupo(
        df,
        value_col="price_ars",
        filtro_valido=~df["precio_invalido"] & ~df["anio_invalido"],
        k=config.IQR_GROUP_K,
        min_avisos=config.IQR_MIN_AVISOS,
    )
    df["precio_outlier"] = precio_outlier

    km_outlier, diag_km = _flag_outliers_por_grupo(
        df,
        value_col="kilometros",
        filtro_valido=~df["km_invalido"] & ~df["anio_invalido"],
        k=config.IQR_GROUP_K,
        min_avisos=config.IQR_MIN_AVISOS,
    )
    df["km_outlier"] = km_outlier

    df = agregar_columnas_limpias(df)

    diagnostico = {
        "precio_outlier": {**diag_precio, "filas_marcadas": int(precio_outlier.sum())},
        "km_outlier": {**diag_km, "filas_marcadas": int(km_outlier.sum())},
    }
    logger.info("Outliers capa 2: %s", diagnostico)
    return df, diagnostico
