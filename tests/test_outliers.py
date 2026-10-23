import pandas as pd
import pytest

from etl import outliers


# --- calc_iqr_bounds ---

def test_calc_iqr_bounds():
    serie = pd.Series([10, 20, 30, 40])
    lower, upper = outliers.calc_iqr_bounds(serie, k=1.5)
    assert lower == pytest.approx(-5.0)
    assert upper == pytest.approx(55.0)


# --- calcular_anio_invalido ---

@pytest.mark.parametrize(
    "anio,esperado",
    [
        (None, True),    # sin dato
        (1909, True),    # por debajo de ANIO_MIN
        (1910, False),   # justo en el limite
        (2015, False),
        (2016, False),   # ultimo anio valido con anio_max=2016
        (2017, True),    # un anio despues del maximo derivado de los datos
        (2027, True),
    ],
)
def test_calcular_anio_invalido_usa_anio_max_explicito(anio, esperado):
    """El umbral entra por parametro, no sale de datetime.now()."""
    df = pd.DataFrame({"anio": pd.array([anio], dtype="Int64")})
    assert bool(outliers.calcular_anio_invalido(df, anio_max=2016).iloc[0]) is esperado


def test_calcular_anio_invalido_no_depende_del_reloj():
    """Mismo input y distinto anio_max dan distinto resultado, y solo por eso."""
    df = pd.DataFrame({"anio": pd.array([2020], dtype="Int64")})
    assert bool(outliers.calcular_anio_invalido(df, anio_max=2016).iloc[0]) is True
    assert bool(outliers.calcular_anio_invalido(df, anio_max=2030).iloc[0]) is False


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

def _aviso(id_pub, id_modelo, anio, price_ars, km=50_000):
    return {
        "id_publicacion": id_pub, "id_modelo": id_modelo, "anio": anio,
        "price_ars": price_ars, "kilometros": km, "precio_invalido": False,
    }


def _poblacion_con_dispersion(n=40, id_modelo="M1", anio=2010):
    """Grupo que pasa el gate, con precios dispersos pero sin outliers.

    Hace falta dispersion real para que el fence global tenga ancho: con todos
    los precios iguales el IQR da 0 y cualquier valor distinto cae afuera.
    """
    return [_aviso("G{}".format(i), id_modelo, anio, 150_000 + i * 5_000) for i in range(n)]


def test_gate_de_muestra_minima_cuenta_avisos_distintos_no_filas():
    """El tier 1 necesita IQR_MIN_AVISOS avisos distintos, no filas.

    15 filas de 3 avisos no alcanzan: las capturas repetidas del mismo auto no
    son observaciones independientes.
    """
    grupo_chico = []
    for ad in ("X0", "X1", "X2"):
        for _ in range(5):  # muchas capturas, pocos avisos distintos
            grupo_chico.append(_aviso(ad, "M2", 2010, 200_000))

    df = pd.DataFrame(_poblacion_con_dispersion() + grupo_chico)
    _, diag = outliers.aplicar_outliers(df, anio_max=2016)

    assert diag["precio_outlier"]["grupos_total"] == 2
    assert diag["precio_outlier"]["grupos_sin_muestra_minima"] == 1
    assert diag["precio_outlier"]["tier_global_por_muestra_chica"] == 15


def test_tier_1_marca_el_outlier_dentro_de_un_grupo_con_muestra():
    df = pd.DataFrame(_poblacion_con_dispersion() + [_aviso("RARO", "M1", 2010, 9_000_000)])
    df, diag = outliers.aplicar_outliers(df, anio_max=2016)

    assert df.loc[df["id_publicacion"] == "RARO", "precio_outlier"].all()
    assert diag["precio_outlier"]["tier_modelo_anio_filas"] == 41


def test_grupo_sin_muestra_minima_no_se_marca_por_defecto():
    """El gate dejo de significar "sin juzgar", pero no puede volverse
    "marcado por defecto": un precio normal en un grupo chico sigue limpio."""
    grupo_chico = [_aviso(ad, "M2", 2010, 200_000) for ad in ("X0", "X1", "X2")]

    df = pd.DataFrame(_poblacion_con_dispersion() + grupo_chico)
    df, diag = outliers.aplicar_outliers(df, anio_max=2016)

    chicos = df[df["id_modelo"] == "M2"]
    assert not chicos["precio_outlier"].any()
    assert chicos["price_ars_limpio"].notna().all()
    # Igual fueron juzgados: cayeron al tier global y quedaron adentro del fence.
    assert diag["precio_outlier"]["tier_global_filas"] == 3


def test_grupo_sin_muestra_minima_si_se_marca_si_el_precio_es_extremo():
    """Antes el grupo chico quedaba sin juzgar y el precio absurdo sobrevivia."""
    grupo_chico = [_aviso(ad, "M2", 2010, 50_000_000) for ad in ("X0", "X1", "X2")]

    df = pd.DataFrame(_poblacion_con_dispersion() + grupo_chico)
    df, _ = outliers.aplicar_outliers(df, anio_max=2016)

    chicos = df[df["id_modelo"] == "M2"]
    assert chicos["precio_outlier"].all()
    assert chicos["price_ars_limpio"].isna().all()


def test_aviso_sin_atributos_puede_ser_marcado_como_outlier():
    """El bug central: sin id_modelo/anio no habia forma de marcarlo nunca.

    Resultado en el dataset completo: los 3 precios mas extremos entraban
    limpios a price_ars_limpio, que es la columna pensada para graficar directo.
    """
    sin_attrs = [
        _aviso("SA_NORMAL", None, None, 200_000, km=None),
        _aviso("SA_EXTREMO", None, None, 50_000_000, km=None),
    ]

    df = pd.DataFrame(_poblacion_con_dispersion() + sin_attrs)
    df, diag = outliers.aplicar_outliers(df, anio_max=2016)

    extremo = df[df["id_publicacion"] == "SA_EXTREMO"]
    assert extremo["precio_outlier"].all()
    assert extremo["price_ars_limpio"].isna().all()

    # El sin_atributos con precio razonable no se toca.
    normal = df[df["id_publicacion"] == "SA_NORMAL"]
    assert not normal["precio_outlier"].any()
    assert normal["price_ars_limpio"].notna().all()

    assert diag["precio_outlier"]["tier_global_por_sin_grupo"] == 2
    assert diag["precio_outlier"]["fence_global_upper"] is not None


def test_km_no_usa_fallback_global():
    """Un fence de km sobre toda la poblacion mezclaria model-anios.

    Un auto de 2005 legitimamente tiene 150.000 km y uno de 2015 no, asi que la
    referencia global no significa nada para km. Las filas sin grupo quedan sin
    juzgar y km_invalido ya se encarga de las que no tienen el dato.
    """
    sin_grupo = [_aviso("SG", None, None, 200_000, km=700_000)]

    df = pd.DataFrame(_poblacion_con_dispersion() + sin_grupo)
    df, diag = outliers.aplicar_outliers(df, anio_max=2016)

    assert not df.loc[df["id_publicacion"] == "SG", "km_outlier"].any()
    assert diag["km_outlier"]["tier_global_filas"] == 0
    assert diag["km_outlier"]["fence_global_upper"] is None


def test_anio_fuera_de_rango_cae_al_tier_global_no_al_grupo():
    """Agrupar por un anio 1800 no tiene sentido; el precio igual se juzga."""
    df = pd.DataFrame(
        _poblacion_con_dispersion()
        + [_aviso("VIEJO", "M1", 1800, 50_000_000)]
    )
    df, diag = outliers.aplicar_outliers(df, anio_max=2016)

    viejo = df[df["id_publicacion"] == "VIEJO"]
    assert viejo["anio_invalido"].all()
    assert viejo["precio_outlier"].all()          # juzgado por el fence global
    assert viejo["anio_limpio"].isna().all()
    # No contamino el grupo M1/2010 con un anio basura.
    assert diag["precio_outlier"]["grupos_total"] == 1
