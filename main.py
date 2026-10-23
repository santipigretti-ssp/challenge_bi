import logging
import time
from dataclasses import dataclass, field

import pandas as pd

from etl import (
    config, dimensions, extract, fx, load, outliers, schemas,
    tendencias, transform_attrs, transform_results, validate,
)

logger = logging.getLogger(__name__)

# El contrato de columnas vive en etl/schemas.py, que es lo que leen tambien
# el verificador de load, validate y el generador del diccionario de datos.
# Se re-exportan por compatibilidad con quien importe desde main.
FACT_PUBLICACIONES_COLUMNAS = schemas.FACT_PUBLICACIONES_COLUMNAS
FACT_PRECIOS_HISTORICOS_COLUMNAS = schemas.FACT_PRECIOS_HISTORICOS_COLUMNAS


@dataclass
class ResultadoCorrida:
    """Salida de run(): las tablas por un lado, las metricas por el otro.

    Antes run() devolvia un unico dict de "metricas" que traia adentro el
    DataFrame completo de fact_publicaciones (~3 MB) solo para que
    print_metricas y el test de integracion pudieran alcanzarlo. Ahora
    metricas son escalares serializables y las tablas se piden por su nombre.
    """
    tablas: dict = field(default_factory=dict)
    metricas: dict = field(default_factory=dict)


def setup_logging() -> None:
    """Configura logging a stderr y a etl.log, una sola vez.

    mode="a", no "w": el log se truncaba en cada corrida, asi que la evidencia
    de una falla (por ejemplo de la API de FX) se perdia en la corrida
    siguiente. El banner separa las corridas.

    Es idempotente y se llama desde run(), asi la ruta de logging tambien se
    ejercita en los tests; antes solo corria bajo __main__ y todos los
    logger.warning del pipeline se descartaban durante la suite.
    """
    raiz = logging.getLogger()
    if not any(isinstance(h, logging.FileHandler) for h in raiz.handlers):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            handlers=[logging.StreamHandler(), logging.FileHandler(config.LOG_FILE, mode="a")],
        )


def run() -> ResultadoCorrida:
    setup_logging()
    t0 = time.time()
    logger.info("===== corrida: dataset=%s =====", config.DATASET)

    df_results = extract.read_results()
    df_attrs = extract.read_attributes()

    df_basico = transform_results.parse_basico(df_results)
    fecha_min = df_basico["fecha_captura"].min()
    fecha_max = df_basico["fecha_captura"].max()

    fx_dict = fx.get_fx(fecha_max)

    df_base = transform_results.calcular_price_ars(df_basico, fx_dict["usd_blue"])
    df_base, diag_precio = transform_results.calcular_precio_invalido(df_base)

    dup_diag = transform_results.diagnostico_duplicados(df_base)

    dims = transform_attrs.build_dims(df_attrs)
    results_dedup = transform_results.deduplicar_por_aviso(df_base)
    atributos_pivot = transform_attrs.build_atributos_pivot(df_attrs, results_dedup, dims)
    atributos_pivot["_tiene_atributos"] = True

    df_base = df_base.merge(atributos_pivot.drop(columns="__KEY_results"), on="id_publicacion", how="left")
    df_base["sin_atributos"] = df_base["_tiene_atributos"].isna()
    df_base = df_base.drop(columns="_tiene_atributos")

    # Umbral de anio derivado de los datos, no del reloj: un auto no puede
    # ser de un modelo mas de un anio posterior a la ultima captura.
    anio_max_valido = fecha_max.year + 1
    df_base, outliers_diag = outliers.aplicar_outliers(df_base, anio_max_valido)

    fact_publicaciones = transform_results.deduplicar_por_aviso(df_base).copy()
    fact_publicaciones = transform_results.agregar_rango_km(fact_publicaciones)
    fact_publicaciones = transform_results.dolarizar(fact_publicaciones, fx_dict["usd_oficial"], fx_dict["usd_blue"])
    fact_publicaciones = fact_publicaciones.rename(columns={"fecha_captura": "fecha_pub"})
    fact_publicaciones = fact_publicaciones[schemas.FACT_PUBLICACIONES_COLUMNAS]

    fact_precios_historicos = df_base[schemas.FACT_PRECIOS_HISTORICOS_COLUMNAS].copy()

    # Se le pasa df_base, no fact_precios_historicos: son las mismas filas,
    # pero df_base todavia tiene las claves numericas de orden que definen cual
    # captura es precio_ini y cual precio_fin.
    tabla_tendencias = tendencias.build_tabla_tendencias(
        df_base, fact_publicaciones["id_publicacion"]
    )

    dim_fecha = dimensions.build_dim_fecha(fecha_min, fecha_max)
    dim_fx = dimensions.build_dim_fx(fx_dict)

    tablas = {
        "fact_publicaciones": fact_publicaciones,
        "fact_precios_historicos": fact_precios_historicos,
        "dim_marca": dims["dim_marca"],
        "dim_modelo": dims["dim_modelo"],
        "dim_transmision": dims["dim_transmision"],
        "dim_fecha": dim_fecha,
        "dim_FX": dim_fx,
        "tabla_tendencias": tabla_tendencias,
    }

    validate.run_asserts(tablas)

    metricas = {
        "results_filas": len(df_results),
        "attributes_filas": len(df_attrs),
        "dup_diag": dup_diag,
        "precio_diag": diag_precio,
        "outliers_diag": outliers_diag,
        "fact_diag": validate.resumir_fact_publicaciones(fact_publicaciones),
        "fact_precios_historicos_filas": len(fact_precios_historicos),
        "tendencias_counts": tabla_tendencias["tendencia_precio"].value_counts().to_dict(),
        "marcas_unicas": len(dims["dim_marca"]),
        "modelos_unicos": len(dims["dim_modelo"]),
        "transmisiones_unicas": len(dims["dim_transmision"]),
        "fecha_min": str(fecha_min),
        "fecha_max": str(fecha_max),
        "fx": fx_dict,
        "duracion_segundos": round(time.time() - t0, 2),
    }
    validate.print_metricas(metricas)

    manifest = load.escribir_csvs(tablas, extra_manifest={"fx": fx_dict})
    metricas["manifest"] = manifest

    return ResultadoCorrida(tablas=tablas, metricas=metricas)


if __name__ == "__main__":
    run()
