"""El contrato de columnas, fijado.

Estos tests existen por una razon concreta: el README y el documento de diseno
decian "fact_publicaciones (35 columnas)" cuando tiene 36, y el documento
afirmaba estar "verificado contra la cabecera de cada archivo". Fijar la lista
aca vuelve ese claim verificable por CI en vez de por buena voluntad.
"""
from etl import schemas


def test_fact_publicaciones_tiene_36_columnas_en_este_orden():
    assert schemas.FACT_PUBLICACIONES_COLUMNAS == [
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
    assert len(schemas.FACT_PUBLICACIONES_COLUMNAS) == 36


def test_fact_precios_historicos_tiene_9_columnas():
    assert len(schemas.FACT_PRECIOS_HISTORICOS_COLUMNAS) == 9


def test_tabla_tendencias_tiene_8_columnas():
    """6 originales + tendencia_medible + orden_tendencia."""
    assert len(schemas.TABLA_TENDENCIAS_COLUMNAS) == 8
    assert "tendencia_medible" in schemas.TABLA_TENDENCIAS_COLUMNAS
    assert "orden_tendencia" in schemas.TABLA_TENDENCIAS_COLUMNAS


def test_dim_fx_tiene_4_columnas():
    """3 originales + fuente_fx, el linaje del tipo de cambio."""
    assert schemas.DIM_FX_COLUMNAS == ["fecha_fx", "usd_oficial", "usd_blue", "fuente_fx"]


def test_son_ocho_tablas():
    assert len(schemas.ESQUEMAS) == 8


def test_toda_tabla_tiene_un_orden_de_salida_declarado():
    """Sin orden explicito el CSV sale en el orden interno del dedup: estable
    entre corridas pero arbitrario, y no diffeable entre versiones."""
    assert set(schemas.ORDEN_SALIDA) == set(schemas.ESQUEMAS)


def test_las_claves_de_orden_existen_en_su_tabla():
    for nombre, claves in schemas.ORDEN_SALIDA.items():
        faltantes = [c for c in claves if c not in schemas.ESQUEMAS[nombre]]
        assert not faltantes, "{}: {} no estan en el esquema".format(nombre, faltantes)


def test_ninguna_tabla_expone_las_claves_privadas_de_orden():
    """_k_serial/_k_offset/_k_indice son internas y no deben llegar a los CSVs."""
    for nombre, columnas in schemas.ESQUEMAS.items():
        privadas = [c for c in columnas if c.startswith("_k_")]
        assert not privadas, "{} expone {}".format(nombre, privadas)


def test_no_hay_columnas_repetidas_en_ninguna_tabla():
    for nombre, columnas in schemas.ESQUEMAS.items():
        assert len(columnas) == len(set(columnas)), "{} tiene columnas repetidas".format(nombre)
