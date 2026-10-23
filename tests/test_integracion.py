"""Pipeline completo sobre el fixture versionado.

El fixture esta estratificado para que estas aserciones sean significativas: si
alguien lo regenera y pierde cobertura de capa 2, de los casos de borde de capa 1
o de los avisos sin atributos, estos tests fallan en vez de pasar en verde sobre
una muestra que no prueba nada. Ver tests/fixtures/README.md.
"""
import pathlib

import pandas as pd

import main
from etl import config

RAIZ_REPO = pathlib.Path(__file__).resolve().parent.parent

AVISOS_FIXTURE = 161
CAPTURAS_FIXTURE = 3306

ARCHIVOS_ESPERADOS = [
    "fact_publicaciones.csv",
    "fact_precios_historicos.csv",
    "tabla_tendencias.csv",
    "dim_marca.csv",
    "dim_modelo.csv",
    "dim_transmision.csv",
    "dim_fecha.csv",
    "dim_FX.csv",
]


def test_pipeline_corre_y_escribe_las_ocho_tablas(fx_fijo):
    metricas = main.run()

    fp = metricas["fact_publicaciones"]
    assert len(fp) == AVISOS_FIXTURE
    assert fp["id_publicacion"].is_unique
    assert metricas["fact_precios_historicos_filas"] == CAPTURAS_FIXTURE

    for nombre in ARCHIVOS_ESPERADOS:
        destino = config.PROCESSED_DIR / nombre
        assert destino.exists(), "no se escribio {}".format(nombre)
        assert destino.stat().st_size > 0


def test_pipeline_ejercita_las_dos_capas_de_outliers(fx_fijo):
    metricas = main.run()
    fp = metricas["fact_publicaciones"]
    diag = metricas["outliers_diag"]

    # Capa 1
    assert metricas["precio_diag"]["piso_invalido"] > 0
    assert metricas["precio_diag"]["techo_invalido"] > 0
    assert int(fp["km_invalido"].sum()) > 0
    assert int(fp["anio_invalido"].sum()) > 0

    # Capa 2: el gate tiene que pasar en algun grupo y saltear en otros.
    for flag in ("precio_outlier", "km_outlier"):
        assert diag[flag]["filas_marcadas"] > 0, "{} no marco ninguna fila".format(flag)
        assert diag[flag]["grupos_sin_muestra_minima"] > 0
        assert diag[flag]["grupos_total"] > diag[flag]["grupos_sin_muestra_minima"]
        assert int(fp[flag].sum()) > 0


def test_pipeline_conserva_los_avisos_sin_atributos(fx_fijo):
    """Los avisos sin Marca/Modelo/Anio/Km quedan, con nulls y el flag prendido."""
    fp = main.run()["fact_publicaciones"]
    sin_attrs = fp[fp["sin_atributos"]]

    assert len(sin_attrs) > 0
    assert sin_attrs["id_marca"].isna().all()
    assert sin_attrs["anio_limpio"].isna().all()
    assert sin_attrs["kilometros_limpio"].isna().all()
    assert (sin_attrs["rango_km"] == "Sin dato").all()
    # Conservan precio: es la decision de diseno declarada en el README.
    assert sin_attrs["price_ars"].notna().any()


def test_los_avisos_sin_atributos_si_pueden_ser_outliers(fx_fijo):
    """Antes no podian serlo por construccion, y los precios extremos del
    dataset entraban limpios a price_ars_limpio. Ver etl.outliers._flag_outliers."""
    metricas = main.run()
    fp = metricas["fact_publicaciones"]
    diag = metricas["outliers_diag"]["precio_outlier"]

    sin_attrs = fp[fp["sin_atributos"]]
    assert int(sin_attrs["precio_outlier"].sum()) > 0, (
        "ningun sin_atributos marcado: el tier global no esta actuando"
    )

    # El fence global se calculo y las filas sin grupo pasaron por el.
    assert diag["fence_global_upper"] is not None
    assert diag["tier_global_por_sin_grupo"] > 0

    # Lo que importa: ningun aviso sin atributos conserva en price_ars_limpio
    # un precio por encima del fence global. Antes ahi quedaban los extremos.
    limpios_sin_attrs = sin_attrs["price_ars_limpio"].dropna()
    assert (limpios_sin_attrs <= diag["fence_global_upper"]).all()


def test_km_no_tiene_tier_global(fx_fijo):
    diag = main.run()["outliers_diag"]["km_outlier"]
    assert diag["fence_global_upper"] is None
    assert diag["tier_global_filas"] == 0


def test_pipeline_cubre_todos_los_avisos_en_tendencias(fx_fijo):
    metricas = main.run()
    fp = metricas["fact_publicaciones"]
    total = sum(metricas["tendencias_counts"].values())

    assert total == len(fp)
    assert metricas["tendencias_counts"].get("Sin precio", 0) > 0


def test_pipeline_usa_el_fixture_no_el_dataset_completo(fx_fijo):
    """Guarda contra un conftest mal configurado que apunte a los CSVs de 100 MB."""
    assert config.RESULTS_CSV.name == "results_sample.csv"
    assert config.RESULTS_CSV.exists()


def test_columnas_de_salida_coinciden_con_el_contrato(fx_fijo):
    main.run()

    fp = pd.read_csv(config.PROCESSED_DIR / "fact_publicaciones.csv")
    assert list(fp.columns) == main.FACT_PUBLICACIONES_COLUMNAS

    fph = pd.read_csv(config.PROCESSED_DIR / "fact_precios_historicos.csv")
    assert list(fph.columns) == main.FACT_PRECIOS_HISTORICOS_COLUMNAS


def test_pipeline_es_reproducible(fx_fijo):
    """Dos corridas con el mismo input dan CSVs byte-identicos.

    Esta afirmacion recien es honesta desde que anio_invalido dejo de leer
    datetime.now(): antes el umbral de anio cambiaba de ano en ano y arrastraba
    a los dos filtros de elegibilidad del IQR, las columnas _limpio, rango_km
    y tabla_tendencias.
    """
    main.run()
    primera = {n: (config.PROCESSED_DIR / n).read_bytes() for n in ARCHIVOS_ESPERADOS}

    main.run()
    segunda = {n: (config.PROCESSED_DIR / n).read_bytes() for n in ARCHIVOS_ESPERADOS}

    distintos = [n for n in ARCHIVOS_ESPERADOS if primera[n] != segunda[n]]
    assert not distintos, "no reproducible: {}".format(distintos)


def test_ningun_modulo_de_transformacion_lee_el_reloj():
    """Guard de reproducibilidad a nivel codigo fuente.

    Parchear datetime en un test no sirve de guard: si un modulo hace
    `from datetime import datetime`, el nombre ya quedo resuelto en su
    namespace y el parche no lo alcanza. Lo que si detecta la regresion es
    buscar la llamada en el fuente. main.py queda excluido porque usa
    time.time() solo para medir la duracion, que va a las metricas y no a
    ninguna tabla de salida.
    """
    prohibidos = ("datetime.now(", "date.today(", "datetime.utcnow(", "time.time(")
    culpables = []
    for modulo in sorted((RAIZ_REPO / "etl").glob("*.py")):
        for linea in modulo.read_text(encoding="utf-8").splitlines():
            # Se saltean comentarios y lineas de docstring: la mencion de
            # datetime.now() dentro de una explicacion no es una llamada.
            desnuda = linea.lstrip()
            if desnuda.startswith(("#", '"', "'")):
                continue
            codigo = linea.split("#")[0]
            for patron in prohibidos:
                if patron in codigo:
                    culpables.append("{}: {}".format(modulo.name, patron))
    assert not culpables, \
        "lecturas del reloj que vuelven la salida no reproducible: {}".format(culpables)
