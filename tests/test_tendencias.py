import pandas as pd
import pytest

from etl import tendencias, transform_results


# --- clasificar_tendencia ---

@pytest.mark.parametrize(
    "precio_ini,precio_fin,obs_validas,esperado",
    [
        (None, None, 0, "Sin precio"),
        (100, 110, 0, "Sin precio"),
        (0, 110, 5, "Sin precio"),
        (100, 101, 5, "Estable"),
        (100, 102, 5, "Estable"),  # exactamente en el umbral de 2%
        (100, 103, 5, "Subió"),
        (100, 97, 5, "Bajó"),
        (100, 100, 1, "Observación única"),
        (100, 100, 2, "Estable"),   # dos observaciones iguales SI es estable
    ],
)
def test_clasificar_tendencia(precio_ini, precio_fin, obs_validas, esperado):
    assert tendencias.clasificar_tendencia(precio_ini, precio_fin, obs_validas) == esperado


def test_una_sola_observacion_no_es_estable():
    """Con obs_validas == 1, precio_ini == precio_fin por construccion.

    Antes caia en "Estable" y reportaba como estable un precio que solo se
    midio una vez: 543 avisos (8,2%) del dataset completo.
    """
    assert tendencias.clasificar_tendencia(150_000, 150_000, 1) == "Observación única"


def test_obs_validas_1_gana_sobre_la_variacion():
    """Aunque los precios difieran, una sola observacion no es medible.

    Caso defensivo: si precio_ini y precio_fin llegaran distintos con
    obs_validas == 1 (inconsistencia aguas arriba), la etiqueta tiene que
    seguir siendo la no medible, no "Subió".
    """
    assert tendencias.clasificar_tendencia(100, 130, 1) == "Observación única"


def test_observacion_unica_no_se_mezcla_con_sin_precio():
    """Son dos preguntas distintas y tienen que quedar separadas."""
    assert tendencias.clasificar_tendencia(150_000, 150_000, 1) == "Observación única"
    assert tendencias.clasificar_tendencia(None, None, 0) == "Sin precio"


def test_tendencias_medibles_son_solo_las_tres_con_variacion():
    assert tendencias.TENDENCIAS_MEDIBLES == {"Subió", "Bajó", "Estable"}
    assert "Observación única" not in tendencias.TENDENCIAS_MEDIBLES
    assert "Sin precio" not in tendencias.TENDENCIAS_MEDIBLES


def test_orden_tendencia_cubre_todas_las_etiquetas():
    """Si se agrega una etiqueta sin orden, Power BI la ordena alfabeticamente."""
    etiquetas = {"Subió", "Bajó", "Estable", "Observación única", "Sin precio"}
    assert set(tendencias.ORDEN_TENDENCIA) == etiquetas
    assert sorted(tendencias.ORDEN_TENDENCIA.values()) == [1, 2, 3, 4, 5]


# --- build_tabla_tendencias ---

def _historico(filas):
    """Historico de precios con las claves numericas de orden ya parseadas.

    Pasa por agregar_claves_orden a proposito, para que el test ejercite el
    mismo orden que usa el pipeline en vez de uno propio.
    """
    df = pd.DataFrame(
        filas,
        columns=["id_publicacion", "fecha_captura", "__KEY_results",
                 "price_ars", "precio_invalido", "precio_outlier"],
    )
    return transform_results.agregar_claves_orden(df)


def test_build_tabla_tendencias_toma_primero_y_ultimo_por_fecha():
    h = _historico([
        ("A", pd.Timestamp("2015-11-01").date(), "42309-0-MLA-1", 100_000.0, False, False),
        ("A", pd.Timestamp("2015-11-10").date(), "42318-0-MLA-1", 120_000.0, False, False),
        ("A", pd.Timestamp("2015-11-05").date(), "42313-0-MLA-1", 110_000.0, False, False),
    ])
    tabla = tendencias.build_tabla_tendencias(h, pd.Series(["A"]))

    fila = tabla.iloc[0]
    assert fila["obs_validas"] == 3
    assert fila["precio_ini"] == 100_000.0
    assert fila["precio_fin"] == 120_000.0
    assert fila["tendencia_precio"] == "Subió"


def test_build_tabla_tendencias_excluye_invalidos_y_outliers():
    h = _historico([
        ("A", pd.Timestamp("2015-11-01").date(), "42309-0-MLA-1", 100_000.0, False, False),
        ("A", pd.Timestamp("2015-11-05").date(), "42313-0-MLA-1", 9_000_000.0, False, True),
        ("A", pd.Timestamp("2015-11-10").date(), "42318-0-MLA-1", 500.0, True, False),
    ])
    tabla = tendencias.build_tabla_tendencias(h, pd.Series(["A"]))

    # Solo sobrevive la primera captura.
    assert tabla.iloc[0]["obs_validas"] == 1
    assert tabla.iloc[0]["precio_fin"] == 100_000.0


def test_build_tabla_tendencias_cubre_todos_los_avisos():
    """Un aviso sin ninguna captura valida igual tiene fila, con obs_validas 0."""
    h = _historico([
        ("A", pd.Timestamp("2015-11-01").date(), "42309-0-MLA-1", 100_000.0, False, False),
    ])
    tabla = tendencias.build_tabla_tendencias(h, pd.Series(["A", "B"]))

    assert len(tabla) == 2
    fila_b = tabla.loc[tabla["id_publicacion"] == "B"].iloc[0]
    assert fila_b["obs_validas"] == 0
    assert fila_b["tendencia_precio"] == "Sin precio"
    assert pd.isna(fila_b["variacion_pct"])


def test_build_tabla_tendencias_marca_observacion_unica_y_medible():
    h = _historico([
        ("A", pd.Timestamp("2015-11-01").date(), "42309-0-MLA-1", 100_000.0, False, False),
        ("A", pd.Timestamp("2015-11-10").date(), "42318-0-MLA-1", 120_000.0, False, False),
        ("B", pd.Timestamp("2015-11-01").date(), "42309-0-MLA-2", 100_000.0, False, False),
    ])
    tabla = tendencias.build_tabla_tendencias(h, pd.Series(["A", "B", "C"])).set_index("id_publicacion")

    assert tabla.loc["A", "tendencia_precio"] == "Subió"
    assert bool(tabla.loc["A", "tendencia_medible"]) is True
    assert tabla.loc["A", "orden_tendencia"] == 1

    assert tabla.loc["B", "tendencia_precio"] == "Observación única"
    assert bool(tabla.loc["B", "tendencia_medible"]) is False
    assert tabla.loc["B", "obs_validas"] == 1
    # La variacion sigue siendo 0 y precio_ini/fin se conservan: no se pierde
    # informacion, lo unico que cambia es la etiqueta.
    assert tabla.loc["B", "variacion_pct"] == 0.0
    assert tabla.loc["B", "precio_ini"] == tabla.loc["B", "precio_fin"]

    assert tabla.loc["C", "tendencia_precio"] == "Sin precio"
    assert bool(tabla.loc["C", "tendencia_medible"]) is False


def test_build_tabla_tendencias_tiene_ocho_columnas():
    h = _historico([("A", pd.Timestamp("2015-11-01").date(), "42309-0-MLA-1", 100_000.0, False, False)])
    tabla = tendencias.build_tabla_tendencias(h, pd.Series(["A"]))

    assert list(tabla.columns) == [
        "id_publicacion", "obs_validas", "precio_ini", "precio_fin",
        "variacion_pct", "tendencia_precio", "tendencia_medible", "orden_tendencia",
    ]
