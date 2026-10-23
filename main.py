import logging
import time

from etl import config, dimensions, extract, fx, load, outliers, tendencias, transform_attrs, transform_results, validate

FACT_PUBLICACIONES_COLUMNAS = [
    "id_publicacion", "title", "permalink", "condition", "currency_id", "category_id",
    "listing_type_id", "accepts_mercadopago", "stop_time", "fecha_pub",
    "price", "price_ars", "price_ars_limpio",
    "price_usd_oficial", "price_usd_oficial_limpio", "price_usd_blue", "price_usd_blue_limpio",
    "precio_invalido", "precio_outlier",
    "id_marca", "marca", "id_modelo", "modelo", "id_transmision", "transmision",
    "anio", "anio_limpio", "kilometros", "kilometros_limpio", "version",
    "km_invalido", "anio_invalido", "km_outlier",
    "rango_km", "orden_rango_km", "sin_atributos",
]

FACT_PRECIOS_HISTORICOS_COLUMNAS = [
    "id_publicacion", "fecha_captura", "__KEY_results",
    "price", "currency_id", "price_ars", "price_ars_limpio", "precio_invalido", "precio_outlier",
]


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(config.LOG_FILE, mode="w")],
    )


def run() -> dict:
    t0 = time.time()

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

    df_base, outliers_diag = outliers.aplicar_outliers(df_base)

    fact_publicaciones = transform_results.deduplicar_por_aviso(df_base).copy()
    fact_publicaciones = transform_results.agregar_rango_km(fact_publicaciones)
    fact_publicaciones = transform_results.dolarizar(fact_publicaciones, fx_dict["usd_oficial"], fx_dict["usd_blue"])
    fact_publicaciones = fact_publicaciones.rename(columns={"fecha_captura": "fecha_pub"})
    fact_publicaciones = fact_publicaciones[FACT_PUBLICACIONES_COLUMNAS]

    fact_precios_historicos = df_base[FACT_PRECIOS_HISTORICOS_COLUMNAS].copy()

    tabla_tendencias = tendencias.build_tabla_tendencias(
        fact_precios_historicos, fact_publicaciones["id_publicacion"]
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
        "dim_fx": dim_fx,
        "tabla_tendencias": tabla_tendencias,
    }

    validate.run_asserts(tablas)

    duracion = time.time() - t0
    metricas = {
        "results_filas": len(df_results),
        "attributes_filas": len(df_attrs),
        "dup_diag": dup_diag,
        "precio_diag": diag_precio,
        "outliers_diag": outliers_diag,
        "fact_publicaciones": fact_publicaciones,
        "fact_precios_historicos_filas": len(fact_precios_historicos),
        "tendencias_counts": tabla_tendencias["tendencia_precio"].value_counts().to_dict(),
        "marcas_unicas": len(dims["dim_marca"]),
        "modelos_unicos": len(dims["dim_modelo"]),
        "transmisiones_unicas": len(dims["dim_transmision"]),
        "fecha_min": fecha_min,
        "fecha_max": fecha_max,
        "fx": fx_dict,
        "duracion_segundos": duracion,
    }
    validate.print_metricas(metricas)

    load.escribir_csvs({k: v for k, v in tablas.items() if k != "dim_fx"} | {"dim_FX": tablas["dim_fx"]})

    return metricas


if __name__ == "__main__":
    setup_logging()
    run()
