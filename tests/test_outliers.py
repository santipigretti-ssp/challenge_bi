import pandas as pd
import pytest

from etl import outliers


# --- calc_iqr_bounds ---

def test_calc_iqr_bounds():
    serie = pd.Series([10, 20, 30, 40])
    lower, upper = outliers.calc_iqr_bounds(serie, k=1.5)
    assert lower == pytest.approx(-5.0)
    assert upper == pytest.approx(55.0)


# --- calcular_km_invalido ---

@pytest.mark.parametrize(
    "km,esperado",
    [
        (None, True),       # sin dato
        (-1, True),         # negativo
        (0, False),         # 0 KM es valido (auto nuevo)
        (500, True),        # typo: 0 < km < 1000
        (999, True),
        (1_000, False),     # justo en el limite
        (450_000, False),
        (800_001, True),    # por encima de KM_MAX_REAL
    ],
)
def test_calcular_km_invalido(km, esperado):
    df = pd.DataFrame({"kilometros": pd.array([km], dtype="Int64")})
    assert bool(outliers.calcular_km_invalido(df).iloc[0]) is esperado


# --- agregar_columnas_limpias ---

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


# --- aplicar_outliers: el gate cuenta avisos distintos, no filas ---

def test_aplicar_outliers_gate_por_avisos_distintos():
    grupo_grande = []
    for i in range(9):
        precio = 1_000_000 if i == 8 else 200_000
        grupo_grande.append({
            "id_publicacion": "G{}".format(i), "id_modelo": "M1", "anio": 2010,
            "price_ars": precio, "kilometros": 50_000, "precio_invalido": False,
        })

    grupo_chico = []
    for ad in ("X0", "X1", "X2"):
        precio = 1_000_000 if ad == "X2" else 200_000
        for _ in range(5):  # muchas capturas, pocos avisos distintos
            grupo_chico.append({
                "id_publicacion": ad, "id_modelo": "M2", "anio": 2010,
                "price_ars": precio, "kilometros": 50_000, "precio_invalido": False,
            })

    df = pd.DataFrame(grupo_grande + grupo_chico)
    df, diag = outliers.aplicar_outliers(df)

    # 9 avisos distintos: el gate pasa y el precio raro se marca.
    assert df.loc[df["id_publicacion"] == "G8", "precio_outlier"].all()
    # 3 avisos con 5 capturas cada uno: 15 filas, pero solo 3 avisos -> no pasa.
    assert not df.loc[df["id_publicacion"] == "X2", "precio_outlier"].any()
    assert diag["precio_outlier"]["grupos_sin_muestra_minima"] == 1
