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

def _con_claves(id_pubs, fechas, claves, **extra):
    df = pd.DataFrame({
        "id_publicacion": id_pubs,
        "fecha_captura": [pd.Timestamp(f).date() for f in fechas],
        "__KEY_results": claves,
        **extra,
    })
    return transform_results.agregar_claves_orden(df)


def test_deduplicar_por_aviso_gana_la_fecha_mas_reciente():
    df = _con_claves(
        ["A", "A", "A", "B"],
        ["2015-12-01", "2015-12-05", "2015-12-05", "2015-11-01"],
        ["42000-0-MLA29483-1", "42004-0-MLA29483-1", "42004-200-MLA29483-1", "41970-0-MLA29483-1"],
        valor=[1, 2, 3, 4],
    )
    resultado = transform_results.deduplicar_por_aviso(df)

    fila_a = resultado.loc[resultado["id_publicacion"] == "A"].iloc[0]
    assert fila_a["fecha_captura"] == pd.Timestamp("2015-12-05").date()
    # Dentro de la misma fecha gana la captura mas tardia del dia (offset 200 > 0).
    assert fila_a["__KEY_results"] == "42004-200-MLA29483-1"
    assert len(resultado) == 2


def test_deduplicar_ordena_el_offset_como_numero_no_como_string():
    """El caso que el orden lexicografico erraba.

    El offset toma valores {0, 200, ..., 1400} con distinta cantidad de
    digitos, asi que como string '800' > '1400' y ganaba la captura de las 8
    sobre la de las 14 del mismo dia.
    """
    df = _con_claves(
        ["A", "A"],
        ["2015-12-05", "2015-12-05"],
        ["42004-800-MLA29483-1", "42004-1400-MLA29483-1"],
    )
    resultado = transform_results.deduplicar_por_aviso(df)

    assert len(resultado) == 1
    assert resultado.iloc[0]["__KEY_results"] == "42004-1400-MLA29483-1"


def test_deduplicar_desempata_por_indice_cuando_el_offset_empata():
    df = _con_claves(
        ["A", "A"],
        ["2015-12-05", "2015-12-05"],
        ["42004-200-MLA29483-9", "42004-200-MLA29483-113"],
    )
    resultado = transform_results.deduplicar_por_aviso(df)

    assert resultado.iloc[0]["__KEY_results"] == "42004-200-MLA29483-113"


# --- agregar_claves_orden ---

def test_agregar_claves_orden_parsea_los_tres_campos_numericos():
    df = pd.DataFrame({"__KEY_results": ["42316-1200-MLA29483-200"]})
    out = transform_results.agregar_claves_orden(df)

    assert out.iloc[0]["_k_serial"] == 42316
    assert out.iloc[0]["_k_offset"] == 1200
    assert out.iloc[0]["_k_indice"] == 200
    assert all(out[c].dtype == "int64" for c in transform_results.CLAVES_ORDEN)


@pytest.mark.parametrize("clave", ["42316-0-MLA29483", "42316-0", "42316-0-MLA29483-1-extra"])
def test_agregar_claves_orden_rechaza_claves_con_otra_forma(clave):
    """Una clave malformada no puede degradar en silencio a orden de string."""
    with pytest.raises(ValueError, match="4 campos"):
        transform_results.agregar_claves_orden(pd.DataFrame({"__KEY_results": [clave]}))


def test_agregar_claves_orden_rechaza_campos_no_numericos():
    with pytest.raises(ValueError, match="no es numerico"):
        transform_results.agregar_claves_orden(
            pd.DataFrame({"__KEY_results": ["42316-xx-MLA29483-1"]})
        )


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
