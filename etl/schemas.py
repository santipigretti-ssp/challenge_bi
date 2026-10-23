"""Esquema de las 8 tablas de salida: unica fuente de verdad.

Lo usan el verificador de etl.load, etl.validate, los tests y el generador del
diccionario de datos. Tener la lista en un solo lugar es lo que evita que la
documentacion se desincronice del codigo: el README y el documento de diseno
decian "35 columnas" cuando fact_publicaciones tenia 36, y encima el documento
afirmaba estar "verificado contra la cabecera de cada archivo".
"""
from __future__ import annotations

FACT_PUBLICACIONES_COLUMNAS = [
    "id_publicacion", "title", "permalink", "condition", "currency_id", "category_id",
    "listing_type_id", "accepts_mercadopago", "stop_time", "fecha_stop", "fecha_pub",
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

TABLA_TENDENCIAS_COLUMNAS = [
    "id_publicacion", "obs_validas", "precio_ini", "precio_fin",
    "variacion_pct", "tendencia_precio", "tendencia_medible", "orden_tendencia",
]

DIM_MARCA_COLUMNAS = ["id_marca", "marca"]
DIM_MODELO_COLUMNAS = ["id_modelo", "modelo"]
DIM_TRANSMISION_COLUMNAS = ["id_transmision", "transmision"]

DIM_FECHA_COLUMNAS = [
    "fecha", "anio", "mes_num", "mes_nombre", "anio_mes",
    "dia", "dia_semana_num", "dia_semana_nombre", "es_periodo_captura",
]

DIM_FX_COLUMNAS = ["fecha_fx", "usd_oficial", "usd_blue", "fuente_fx"]

ESQUEMAS = {
    "fact_publicaciones": FACT_PUBLICACIONES_COLUMNAS,
    "fact_precios_historicos": FACT_PRECIOS_HISTORICOS_COLUMNAS,
    "tabla_tendencias": TABLA_TENDENCIAS_COLUMNAS,
    "dim_marca": DIM_MARCA_COLUMNAS,
    "dim_modelo": DIM_MODELO_COLUMNAS,
    "dim_transmision": DIM_TRANSMISION_COLUMNAS,
    "dim_fecha": DIM_FECHA_COLUMNAS,
    "dim_FX": DIM_FX_COLUMNAS,
}

# Orden de filas con el que se escribe cada tabla. Sin esto el orden sale del
# sort interno del dedup, que es estable entre corridas pero arbitrario: dos
# versiones del codigo con la misma salida logica daban CSVs distintos y no
# habia forma de diffearlos. Ordenar por la clave los vuelve comparables.
ORDEN_SALIDA = {
    "fact_publicaciones": ["id_publicacion"],
    "fact_precios_historicos": ["id_publicacion", "fecha_captura", "__KEY_results"],
    "tabla_tendencias": ["id_publicacion"],
    "dim_marca": ["id_marca"],
    "dim_modelo": ["id_modelo"],
    "dim_transmision": ["id_transmision"],
    "dim_fecha": ["fecha"],
    "dim_FX": [],  # una sola fila
}
