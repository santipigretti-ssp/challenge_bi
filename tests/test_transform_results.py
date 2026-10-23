import pandas as pd
import pytest

from etl import transform_results


# --- categoria_km ---

@pytest.mark.parametrize(
    "km,invalido,esperado",
    [
        (None, True, "Sin dato"),
        (0, False, "0 KM"),
        (24_999, False, "Menos de 25.000 KM"),
        (25_000, False, "De 25.000 a 50.000 KM"),
        (49_999, False, "De 25.000 a 50.000 KM"),
        (50_000, False, "De 50.000 a 100.000 KM"),
        (99_999, False, "De 50.000 a 100.000 KM"),
        (100_000, False, "De 100.000 a 500.000 KM"),
        (499_999, False, "De 100.000 a 500.000 KM"),
        # Inalcanzable con el dataset real (no hay km entre 500k y KM_MAX_REAL),
        # pero la rama existe y se testea igual.
        (500_000, False, "Más de 500.000 KM"),
    ],
)
def test_categoria_km(km, invalido, esperado):
    assert transform_results.categoria_km(km, invalido) == esperado


# --- calcular_precio_invalido (piso + techo dinamico) ---

def test_calcular_precio_invalido_piso_y_techo():
    df = pd.DataFrame({
        "price": [200_000, 250_000, 300_000, 220_000, 500, 1_111_111_111],
        "currency_id": ["ARS"] * 6,
        "price_ars": [200_000, 250_000, 300_000, 220_000, 500, 1_111_111_111],
    })
    out, diag = transform_results.calcular_precio_invalido(df)

    assert out.loc[4, "precio_invalido"]  # piso: 500 <= 1000 ARS
    assert out.loc[5, "precio_invalido"]  # techo dinamico: placeholder absurdo
    assert not out.loc[0, "precio_invalido"]
    assert not out.loc[1, "precio_invalido"]
    assert diag["piso_invalido"] == 1
    assert diag["techo_invalido"] == 1


def test_calcular_precio_invalido_piso_por_moneda():
    """El piso es distinto segun la moneda: 1000 ARS vs 100 USD."""
    df = pd.DataFrame({
        "price": [900, 900, 50, 50],
        "currency_id": ["ARS", "USD", "ARS", "USD"],
        "price_ars": [900, 13_500, 50, 750],
    })
    out, _ = transform_results.calcular_precio_invalido(df)

    assert out.loc[0, "precio_invalido"]       # 900 ARS <= 1000
    assert not out.loc[1, "precio_invalido"]   # 900 USD > 100
    assert out.loc[2, "precio_invalido"]       # 50 ARS <= 1000
    assert out.loc[3, "precio_invalido"]       # 50 USD <= 100


# --- deduplicar_por_aviso ---

def test_deduplicar_por_aviso_gana_la_fecha_mas_reciente():
    df = pd.DataFrame({
        "id_publicacion": ["A", "A", "A", "B"],
        "fecha_captura": [pd.Timestamp("2015-12-01").date(), pd.Timestamp("2015-12-05").date(),
                          pd.Timestamp("2015-12-05").date(), pd.Timestamp("2015-11-01").date()],
        "__KEY_results": ["42000-0-MLA-1", "42004-0-MLA-1", "42004-200-MLA-1", "41970-0-MLA-1"],
        "valor": [1, 2, 3, 4],
    })
    resultado = transform_results.deduplicar_por_aviso(df)

    fila_a = resultado.loc[resultado["id_publicacion"] == "A"].iloc[0]
    assert fila_a["fecha_captura"] == pd.Timestamp("2015-12-05").date()
    # Dentro de la misma fecha gana la captura mas tardia del dia (offset 200 > 0).
    assert fila_a["__KEY_results"] == "42004-200-MLA-1"
    assert len(resultado) == 2


# --- dolarizar ---

def test_dolarizar_usa_price_ars_limpio_para_las_columnas_limpias():
    df = pd.DataFrame({
        "price_ars": [150_000.0, 200_000.0],
        "price_ars_limpio": [150_000.0, None],
        "precio_invalido": [False, False],
    })
    out = transform_results.dolarizar(df, fx_oficial=10.0, fx_blue=15.0)

    assert out.loc[0, "price_usd_oficial"] == pytest.approx(15_000.0)
    assert out.loc[0, "price_usd_blue"] == pytest.approx(10_000.0)
    # La fila 1 es outlier (price_ars_limpio nulo): la columna cruda sigue, la limpia no.
    assert out.loc[1, "price_usd_oficial"] == pytest.approx(20_000.0)
    assert pd.isna(out.loc[1, "price_usd_oficial_limpio"])


# --- diagnostico_duplicados ---

def test_diagnostico_duplicados_cuenta_intra_dia():
    df = pd.DataFrame({
        "id_publicacion": ["A", "A", "B"],
        "fecha_captura": [pd.Timestamp("2015-12-05").date()] * 2 + [pd.Timestamp("2015-12-05").date()],
    })
    diag = transform_results.diagnostico_duplicados(df)

    assert diag["filas_totales"] == 3
    assert diag["avisos_unicos"] == 2
    assert diag["max_capturas_por_aviso"] == 2
    assert diag["avisos_con_duplicado_intra_dia"] == 1
    assert diag["ejemplos_duplicado_intra_dia"] == ["A"]
