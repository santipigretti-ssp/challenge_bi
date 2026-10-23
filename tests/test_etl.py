import pandas as pd
import pytest

import main
from etl import config, extract, fx, outliers, tendencias, transform_results


# --- transform_results.categoria_km ---

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
        (500_000, False, "Más de 500.000 KM"),
    ],
)
def test_categoria_km(km, invalido, esperado):
    assert transform_results.categoria_km(km, invalido) == esperado


# --- tendencias.clasificar_tendencia ---

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


# --- outliers.calc_iqr_bounds ---

def test_calc_iqr_bounds():
    serie = pd.Series([10, 20, 30, 40])
    lower, upper = outliers.calc_iqr_bounds(serie, k=1.5)
    assert lower == pytest.approx(-5.0)
    assert upper == pytest.approx(55.0)


# --- transform_results.calcular_precio_invalido (piso + techo dinamico) ---

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


# --- transform_results.deduplicar_por_aviso ---

def test_deduplicar_por_aviso_criterio_deterministico():
    df = pd.DataFrame({
        "id_publicacion": ["A", "A", "A", "B"],
        "fecha_captura": [pd.Timestamp("2015-12-01").date(), pd.Timestamp("2015-12-05").date(),
                           pd.Timestamp("2015-12-05").date(), pd.Timestamp("2015-11-01").date()],
        "__KEY_results": ["42000-0-MLA-1", "42004-0-MLA-1", "42004-200-MLA-1", "41970-0-MLA-1"],
        "valor": [1, 2, 3, 4],
    })
    resultado = transform_results.deduplicar_por_aviso(df)
    fila_a = resultado.loc[resultado["id_publicacion"] == "A"].iloc[0]
    # misma fecha (2015-12-05): gana el __KEY_results "mayor" en orden de string descendente
    assert fila_a["__KEY_results"] == "42004-200-MLA-1"
    assert len(resultado) == 2


# --- outliers.aplicar_outliers: gate de muestra minima por avisos distintos, no por filas ---

def test_agregar_columnas_limpias():
    df = pd.DataFrame({
        "price_ars": [200_000, 500, 900_000, 1_000_000_000],
        "precio_invalido": [False, True, False, True],
        "precio_outlier": [False, False, True, False],
        "kilometros": [50_000, 50, 999_999, 30_000],
        "km_invalido": [False, True, False, False],
        "km_outlier": [False, False, True, False],
        "anio": [2010, 2011, 1800, 2012],
        "anio_invalido": [False, False, True, False],
    })
    out = outliers.agregar_columnas_limpias(df)

    assert out["price_ars_limpio"].tolist()[0] == 200_000
    assert out["price_ars_limpio"].isna().tolist() == [False, True, True, True]
    assert out["kilometros_limpio"].isna().tolist() == [False, True, True, False]
    assert out["anio_limpio"].isna().tolist() == [False, False, True, False]


def test_aplicar_outliers_gate_por_avisos_distintos():
    grupo_grande = []
    for i in range(9):
        precio = 1_000_000 if i == 8 else 200_000
        grupo_grande.append({
            "id_publicacion": f"G{i}", "id_modelo": "M1", "anio": 2010,
            "price_ars": precio, "kilometros": 50_000, "precio_invalido": False,
        })

    grupo_chico = []
    for i, ad in enumerate(["X0", "X1", "X2"]):
        precio = 1_000_000 if ad == "X2" else 200_000
        for captura in range(5):  # muchas capturas, pocos avisos distintos
            grupo_chico.append({
                "id_publicacion": ad, "id_modelo": "M2", "anio": 2010,
                "price_ars": precio, "kilometros": 50_000, "precio_invalido": False,
            })

    df = pd.DataFrame(grupo_grande + grupo_chico)
    df, diag = outliers.aplicar_outliers(df)

    assert df.loc[(df["id_publicacion"] == "G8"), "precio_outlier"].all()
    assert not df.loc[(df["id_publicacion"] == "X2"), "precio_outlier"].any()
    assert diag["precio_outlier"]["grupos_sin_muestra_minima"] == 1


# --- Integracion: pipeline completo sobre una muestra real chica ---

def test_pipeline_integracion_muestra_chica(monkeypatch, tmp_path):
    df_results_full = extract.read_results()
    sample_ids = df_results_full["id_u9"].drop_duplicates().sample(n=80, random_state=42)
    df_results_sample = df_results_full[df_results_full["id_u9"].isin(sample_ids)].reset_index(drop=True)

    df_attrs_full = extract.read_attributes()
    df_attrs_sample = df_attrs_full[
        df_attrs_full["__KEY_results"].isin(df_results_sample["__KEY_results"])
    ].reset_index(drop=True)

    monkeypatch.setattr(extract, "read_results", lambda: df_results_sample)
    monkeypatch.setattr(extract, "read_attributes", lambda: df_attrs_sample)
    monkeypatch.setattr(
        fx, "get_fx",
        lambda fecha_max: {"fecha_fx": "2015-11-30", "usd_oficial": 10.0, "usd_blue": 15.0},
    )
    monkeypatch.setattr(config, "PROCESSED_DIR", tmp_path)

    metricas = main.run()

    fact_publicaciones = metricas["fact_publicaciones"]
    assert len(fact_publicaciones) == sample_ids.nunique()
    assert fact_publicaciones["id_publicacion"].is_unique
    assert (tmp_path / "fact_publicaciones.csv").exists()
    assert (tmp_path / "fact_precios_historicos.csv").exists()
