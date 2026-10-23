import numpy as np
import pandas as pd

from etl import config


def clasificar_tendencia(precio_ini, precio_fin, obs_validas, umbral: float = config.TENDENCIA_UMBRAL) -> str:
    if obs_validas == 0 or precio_ini is None or pd.isna(precio_ini) or precio_ini == 0:
        return "Sin precio"
    variacion = (precio_fin - precio_ini) / precio_ini
    if abs(variacion) <= umbral:
        return "Estable"
    return "Subió" if variacion > 0 else "Bajó"


def build_tabla_tendencias(fact_precios_historicos: pd.DataFrame, ids_publicacion: pd.Series) -> pd.DataFrame:
    """Tendencias calculadas sobre fact_precios_historicos, excluyendo tanto
    precio_invalido (capa 1) como precio_outlier (capa 2) — ver sección 2.2 del plan.
    """
    validos = fact_precios_historicos.loc[
        ~fact_precios_historicos["precio_invalido"] & ~fact_precios_historicos["precio_outlier"]
    ].sort_values(["id_publicacion", "fecha_captura", "__KEY_results"])

    grupos = validos.groupby("id_publicacion")
    obs_validas = grupos.size().rename("obs_validas")
    precio_ini = grupos["price_ars"].first().rename("precio_ini")
    precio_fin = grupos["price_ars"].last().rename("precio_fin")

    base = pd.DataFrame(index=pd.Index(ids_publicacion.unique(), name="id_publicacion"))
    tabla = base.join(obs_validas).join(precio_ini).join(precio_fin).reset_index()
    tabla["obs_validas"] = tabla["obs_validas"].fillna(0).astype(int)

    tabla["variacion_pct"] = np.where(
        (tabla["obs_validas"] > 0) & tabla["precio_ini"].notna() & (tabla["precio_ini"] != 0),
        (tabla["precio_fin"] - tabla["precio_ini"]) / tabla["precio_ini"],
        np.nan,
    )
    tabla["tendencia_precio"] = [
        clasificar_tendencia(ini, fin, obs)
        for ini, fin, obs in zip(tabla["precio_ini"], tabla["precio_fin"], tabla["obs_validas"])
    ]
    return tabla
