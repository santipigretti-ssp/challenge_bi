import numpy as np
import pandas as pd

from etl import config

SIN_PRECIO = "Sin precio"
OBSERVACION_UNICA = "Observación única"
ESTABLE = "Estable"
SUBIO = "Subió"
BAJO = "Bajó"

# Las tres etiquetas donde la variacion de precio es realmente medible: hay al
# menos dos observaciones validas y por lo tanto algo que comparar. Es sobre
# esta particion que tiene que filtrar el dashboard para el split de 3 vias.
TENDENCIAS_MEDIBLES = frozenset({SUBIO, BAJO, ESTABLE})

# Power BI ordena alfabeticamente si no se le da una columna de orden
# (mismo criterio que orden_rango_km en transform_results).
ORDEN_TENDENCIA = {
    SUBIO: 1,
    BAJO: 2,
    ESTABLE: 3,
    OBSERVACION_UNICA: 4,
    SIN_PRECIO: 5,
}


def clasificar_tendencia(precio_ini, precio_fin, obs_validas, umbral: float = config.TENDENCIA_UMBRAL) -> str:
    """Clasifica la evolucion de precio de un aviso.

    "Observación única" existe porque con una sola observacion valida
    precio_ini == precio_fin por construccion, asi que la variacion da 0 y el
    aviso caia en "Estable". Eso mezclaba dos cosas distintas: un precio que se
    midio dos veces y no se movio, y un precio que solo se vio una vez y del
    que no se sabe nada. En el dataset completo eran 543 avisos (8,2%)
    reportados como estables sin que hubiera con que compararlos.

    No se pliega a "Sin precio" a proposito: estos avisos SI tienen precio
    valido. "Sin precio" responde cuantos avisos no tienen ningun precio
    usable, que es una pregunta de cobertura de dato; mezclarlas corromperia
    esa otra metrica.
    """
    if obs_validas == 0 or precio_ini is None or pd.isna(precio_ini) or precio_ini == 0:
        return SIN_PRECIO
    if obs_validas == 1:
        return OBSERVACION_UNICA
    variacion = (precio_fin - precio_ini) / precio_ini
    if abs(variacion) <= umbral:
        return ESTABLE
    return SUBIO if variacion > 0 else BAJO


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
    tabla["tendencia_medible"] = tabla["tendencia_precio"].isin(TENDENCIAS_MEDIBLES)
    tabla["orden_tendencia"] = tabla["tendencia_precio"].map(ORDEN_TENDENCIA)
    return tabla
