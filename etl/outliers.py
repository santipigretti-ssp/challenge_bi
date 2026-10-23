import logging

import pandas as pd

from etl import config

logger = logging.getLogger(__name__)


def calc_iqr_bounds(serie: pd.Series, k: float = 1.5) -> tuple[float, float]:
    q1 = serie.quantile(0.25)
    q3 = serie.quantile(0.75)
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


def calcular_km_invalido(df: pd.DataFrame) -> pd.Series:
    km = df["kilometros"]
    return (
        km.isna()
        | (km < 0)
        | ((km > 0) & (km < config.KM_TYPO_MAX))
        | (km > config.KM_MAX_REAL)
    )


def calcular_anio_invalido(df: pd.DataFrame, anio_max: int) -> pd.Series:
    """anio_max se deriva de los datos (ver main.run), no del reloj.

    Usar el reloj aca hacia que la salida del pipeline dependiera de la
    fecha de la corrida: anio_invalido alimenta los filtros de elegibilidad
    del IQR, y de ahi se propaga a precio_outlier, km_outlier, las columnas
    _limpio, rango_km y tabla_tendencias.
    """
    anio = df["anio"]
    return anio.isna() | (anio < config.ANIO_MIN) | (anio > anio_max)


def _booleana(serie: pd.Series) -> pd.Series:
    """Booleana de numpy sin NA. Los flags son dtype 'boolean' (nullable)
    porque derivan de columnas Int64, y pandas no indexa con NA."""
    return serie.fillna(False).astype(bool)


def _indices_fuera_del_fence(serie: pd.Series, lower: float, upper: float) -> pd.Index:
    """Indices de la serie que caen fuera del fence. Un NA nunca se marca."""
    return serie.index[_booleana((serie < lower) | (serie > upper))]


def _serie_de_referencia(frame: pd.DataFrame, value_col: str) -> pd.Series:
    """Serie sobre la que se calculan los cuartiles.

    Con IQR_COLAPSAR_POR_AVISO se toma un valor (la mediana) por
    id_publicacion, en vez de todas las capturas. El gate de muestra minima ya
    cuenta avisos distintos precisamente para no tratar capturas repetidas del
    mismo auto como observaciones independientes; calcular los cuartiles sobre
    las capturas reintroducia esa pseudo-replicacion, y un aviso visto 70 veces
    pesaba 70 veces en Q1/Q3. Para km es todavia mas degenerado, porque el km
    es un atributo del auto replicado en cada captura.

    Las filas se marcan igual todas: lo que cambia es de donde sale el fence.
    """
    if not config.IQR_COLAPSAR_POR_AVISO:
        return frame[value_col]
    return frame.groupby("id_publicacion")[value_col].median()


def _flag_outliers(
    df: pd.DataFrame,
    value_col: str,
    filtro_valido: pd.Series,
    k_grupo: float,
    min_avisos: int,
    k_global: float | None,
) -> tuple[pd.Series, dict]:
    """Marca outliers con una escalera de dos niveles de referencia.

    Tier 1 (modelo_anio): filas con id_modelo y anio valido cuyo grupo
    (id_modelo, anio) tiene al menos min_avisos avisos DISTINTOS. Fence de
    Tukey con k_grupo. Es el criterio original, sin cambios.

    Tier 2 (global): todo el resto de las filas validas en capa 1 — las que no
    tienen modelo o anio, y las que si lo tienen pero cuyo grupo no llego a la
    muestra minima. Fence con k_global calculado sobre la distribucion de TODA
    la poblacion elegible, no sobre las filas del tier 2: cuartiles
    autorreferenciales sobre un subconjunto chico y sesgado serian ruido.

    k_global=None desactiva el tier 2 y deja el comportamiento original. Es lo
    que se usa para km (ver aplicar_outliers).

    Por que hace falta el tier 2: la elegibilidad exigia tener modelo y anio,
    asi que los avisos sin atributos no podian ser marcados nunca. En el
    dataset completo eso dejaba pasar los 3 precios mas extremos (hasta 850.000
    ARS, contra un maximo de 550.000 entre los avisos que si tienen atributos)
    directo a price_ars_limpio, justamente la columna pensada para graficar sin
    cruzar flags. Con el tier global, toda fila valida en capa 1 se juzga
    contra alguna referencia: ninguna se escapa.
    """
    flag = pd.Series(False, index=df.index)
    elegibles = df[_booleana(filtro_valido)]

    # El tier 1 exige anio VALIDO, no solo presente: agrupar por un anio 1800
    # no tiene sentido. Esas filas caen al tier global, que no agrupa por anio.
    tiene_grupo = elegibles["id_modelo"].notna() & ~_booleana(elegibles["anio_invalido"])
    con_grupo = elegibles[tiene_grupo]

    idx_juzgados: list = []
    idx_muestra_chica: list = []
    grupos_total = 0
    grupos_sin_muestra = 0

    for _, grupo in con_grupo.groupby(["id_modelo", "anio"]):
        grupos_total += 1
        if grupo["id_publicacion"].nunique() < min_avisos:
            grupos_sin_muestra += 1
            idx_muestra_chica.extend(grupo.index)
            continue
        lower, upper = calc_iqr_bounds(_serie_de_referencia(grupo, value_col), k_grupo)
        flag.loc[_indices_fuera_del_fence(grupo[value_col], lower, upper)] = True
        idx_juzgados.extend(grupo.index)

    idx_tier2 = elegibles.index.difference(pd.Index(idx_juzgados))

    diag = {
        "grupos_total": grupos_total,
        "grupos_sin_muestra_minima": grupos_sin_muestra,
        "tier_modelo_anio_filas": len(idx_juzgados),
        "tier_global_filas": 0,
        "tier_global_por_sin_grupo": 0,
        "tier_global_por_muestra_chica": 0,
        "fence_global_lower": None,
        "fence_global_upper": None,
    }

    if k_global is None:
        # Sin fallback global: las filas del tier 2 quedan sin juzgar.
        return flag, diag

    diag["tier_global_filas"] = len(idx_tier2)
    diag["tier_global_por_muestra_chica"] = len(idx_muestra_chica)
    diag["tier_global_por_sin_grupo"] = len(idx_tier2) - len(idx_muestra_chica)

    if len(idx_tier2):
        lower_g, upper_g = calc_iqr_bounds(_serie_de_referencia(elegibles, value_col), k_global)
        flag.loc[_indices_fuera_del_fence(df.loc[idx_tier2, value_col], lower_g, upper_g)] = True
        diag["fence_global_lower"] = float(lower_g)
        diag["fence_global_upper"] = float(upper_g)

    return flag, diag


def agregar_columnas_limpias(df: pd.DataFrame) -> pd.DataFrame:
    """Columnas derivadas con null en las filas invalidas (capa 1) u outlier (capa 2).

    Pensadas para graficar directo en Power BI sin tener que combinar el valor
    crudo con los flags en cada medida. precio_outlier/km_outlier solo se
    calculan sobre filas ya validas en capa 1 (ver _flag_outliers),
    asi que invalido y outlier nunca se superponen para la misma fila.
    """
    df = df.copy()
    precio_malo = df["precio_invalido"] | df["precio_outlier"]
    km_malo = df["km_invalido"] | df["km_outlier"]

    df["price_ars_limpio"] = df["price_ars"].mask(precio_malo)
    df["kilometros_limpio"] = df["kilometros"].mask(km_malo)
    df["anio_limpio"] = df["anio"].mask(df["anio_invalido"])
    return df


def aplicar_outliers(df: pd.DataFrame, anio_max: int) -> tuple[pd.DataFrame, dict]:
    """Capa 1 (km/anio) y capa 2 (IQR por grupo) sobre results_base completo.

    Se corre una sola vez, antes de ramificar a fact_publicaciones y
    fact_precios_historicos (ver sección 2.2 del plan). El gate de muestra
    minima cuenta avisos distintos (id_publicacion.nunique()), no filas, para
    no inflar artificialmente la "muestra" con capturas repetidas del mismo
    auto.
    """
    df = df.copy()
    df["km_invalido"] = calcular_km_invalido(df)
    df["anio_invalido"] = calcular_anio_invalido(df, anio_max)

    # El filtro de elegibilidad ya no incluye ~anio_invalido: de la condicion
    # sobre el anio se encarga la asignacion de tier (el tier 1 lo exige, el
    # global no, porque no agrupa por el). Tenerlo aca excluia dos veces a los
    # avisos sin atributos, y era la causa de que no pudieran marcarse nunca.
    precio_outlier, diag_precio = _flag_outliers(
        df,
        value_col="price_ars",
        filtro_valido=~df["precio_invalido"],
        k_grupo=config.IQR_GROUP_K,
        min_avisos=config.IQR_MIN_AVISOS,
        k_global=config.IQR_GLOBAL_K,
    )
    df["precio_outlier"] = precio_outlier

    # Km no lleva fallback global, a proposito. Los avisos sin atributos ya
    # tienen kilometros nulo, asi que km_invalido los marca y kilometros_limpio
    # queda en null: no hay nada que rescatar ahi. Y un fence de km sobre la
    # poblacion entera seria activamente erroneo, porque mezcla model-anios: un
    # auto de 2005 legitimamente tiene 150.000 km y uno de 2015 no.
    km_outlier, diag_km = _flag_outliers(
        df,
        value_col="kilometros",
        filtro_valido=~df["km_invalido"],
        k_grupo=config.IQR_GROUP_K,
        min_avisos=config.IQR_MIN_AVISOS,
        k_global=None,
    )
    df["km_outlier"] = km_outlier

    df = agregar_columnas_limpias(df)

    diagnostico = {
        "precio_outlier": {**diag_precio, "filas_marcadas": int(precio_outlier.sum())},
        "km_outlier": {**diag_km, "filas_marcadas": int(km_outlier.sum())},
    }
    logger.info("Outliers capa 2: %s", diagnostico)
    return df, diagnostico
