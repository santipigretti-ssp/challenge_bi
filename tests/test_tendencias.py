import pandas as pd
import pytest

from etl import tendencias


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
    ],
)
def test_clasificar_tendencia(precio_ini, precio_fin, obs_validas, esperado):
    assert tendencias.clasificar_tendencia(precio_ini, precio_fin, obs_validas) == esperado


# --- build_tabla_tendencias ---

def _historico(filas):
    return pd.DataFrame(
        filas,
        columns=["id_publicacion", "fecha_captura", "__KEY_results",
                 "price_ars", "precio_invalido", "precio_outlier"],
    )


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
