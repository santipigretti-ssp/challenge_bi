import logging

import pandas as pd

logger = logging.getLogger(__name__)

NOMBRE_A_COLUMNA = {
    "Marca": "marca",
    "Modelo": "modelo",
    "Transmisión": "transmision",
    "Año": "anio",
    "Kilómetros": "kilometros",
    "Versión": "version",
}
ATRIBUTOS_CON_ID = ("Marca", "Modelo", "Transmisión")
NOMBRE_A_COLUMNA_ID = {n: f"id_{NOMBRE_A_COLUMNA[n]}" for n in ATRIBUTOS_CON_ID}


def build_dim(df_attrs: pd.DataFrame, nombre_atributo: str) -> pd.DataFrame:
    """Dimensión por groupby directo sobre el formato largo, sin pivotear.

    La grafía elegida es la más frecuente por id (no la primera que aparece),
    así VENTO/Vento se resuelve solo sin necesitar un diccionario de overrides.
    """
    col = NOMBRE_A_COLUMNA[nombre_atributo]
    id_col = f"id_{col}"

    subset = df_attrs.loc[
        df_attrs["name_u6"].eq(nombre_atributo) & df_attrs["value_id"].notna() & df_attrs["value_id"].ne(""),
        ["value_id", "value_name"],
    ]
    grafia_mas_frecuente = (
        subset.groupby(["value_id", "value_name"]).size().rename("n").reset_index()
        .sort_values("n", ascending=False)
        .drop_duplicates(subset="value_id", keep="first")
        [["value_id", "value_name"]]
        .rename(columns={"value_id": id_col, "value_name": col})
        .reset_index(drop=True)
    )
    return grafia_mas_frecuente


def build_dims(df_attrs: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "dim_marca": build_dim(df_attrs, "Marca"),
        "dim_modelo": build_dim(df_attrs, "Modelo"),
        "dim_transmision": build_dim(df_attrs, "Transmisión"),
    }


def claves_ganadoras(results_base_dedup: pd.DataFrame) -> pd.Series:
    """__KEY_results de la captura más reciente de cada aviso (ver transform_results.deduplicar_por_aviso)."""
    return results_base_dedup["__KEY_results"]


def _reindexar_como_texto(pivot: pd.DataFrame, columnas: list) -> pd.DataFrame:
    """Fija el esquema del pivot y deja todas las columnas en dtype object.

    El reindex por si solo no alcanza: una columna que no existia la crea
    all-NaN con dtype float64, y despues normalizar_con_dims no puede mergear
    un float64 contra el object del id de la dimension ("You are trying to
    merge on float64 and object columns"). Forzando object, el dtype es el
    mismo venga el atributo de los datos o del reindex.
    """
    return pivot.reindex(columns=columnas).astype(object)


def _deduplicar_atributos(df_filtrado: pd.DataFrame) -> pd.DataFrame:
    """Un solo valor por (__KEY_results, name_u6), que es lo que .pivot() exige.

    .pivot() levanta ValueError ante cualquier par duplicado. En el archivo
    actual no hay ninguno (verificado sobre las 662.469 filas), asi que esto no
    cambia nada hoy; lo que hace es volver explicito un invariante que estaba
    indefenso y dejar ruido en el log si un re-scrape lo rompe.

    Se prefiere esto a pivot_table(aggfunc="last"), que resolveria el duplicado
    en silencio. El orden fija cual gana, asi que el resultado es
    determinístico.
    """
    orden = ["__KEY_results", "name_u6", "value_id", "value_name"]
    df_ordenado = df_filtrado.sort_values(orden)
    sin_dups = df_ordenado.drop_duplicates(subset=["__KEY_results", "name_u6"], keep="last")

    removidas = len(df_filtrado) - len(sin_dups)
    if removidas:
        logger.warning(
            "atributos_pivot: %s filas con (__KEY_results, name_u6) duplicado; "
            "se conserva el ultimo por orden de value_id/value_name",
            removidas,
        )
    return sin_dups


def pivotear_attrs(df_attrs: pd.DataFrame, claves: pd.Series) -> pd.DataFrame:
    """Pivot dual (value_name + value_id) sobre solo las capturas ganadoras.

    Filtrar antes de pivotear reduce el volumen de ~662k filas a ~6k*6, en vez
    de pivotear todo y deduplicar después (ver sección 2.6 del plan).

    Las dos tablas pivoteadas se reindexan contra la lista completa de
    atributos, asi que el esquema de salida es fijo: las 6 columnas de texto y
    las 3 de id existen siempre, todo-NaN si el atributo no aparece. Eso vuelve
    el contrato explicito y de paso elimina dos fallas: el TypeError del
    .astype("Int64") cuando faltaba "Año" o "Kilómetros", y el KeyError de
    normalizar_con_dims cuando faltaba alguno de los tres ids.
    """
    df_filtrado = df_attrs[df_attrs["__KEY_results"].isin(set(claves))]
    logger.info(
        "atributos_pivot: filtrado de %s a %s filas antes de pivotear",
        len(df_attrs),
        len(df_filtrado),
    )
    df_filtrado = _deduplicar_atributos(df_filtrado)

    pivot_nombres = df_filtrado.pivot(index="__KEY_results", columns="name_u6", values="value_name")
    pivot_nombres = pivot_nombres.rename(columns=NOMBRE_A_COLUMNA)
    pivot_nombres = _reindexar_como_texto(pivot_nombres, list(NOMBRE_A_COLUMNA.values()))

    con_id = df_filtrado[df_filtrado["name_u6"].isin(ATRIBUTOS_CON_ID)]
    pivot_ids = con_id.pivot(index="__KEY_results", columns="name_u6", values="value_id")
    pivot_ids = pivot_ids.rename(columns=NOMBRE_A_COLUMNA_ID)
    pivot_ids = _reindexar_como_texto(pivot_ids, list(NOMBRE_A_COLUMNA_ID.values()))

    atributos_pivot = pivot_nombres.join(pivot_ids, how="left").reset_index()

    # Int64 nullable (no float) para que Power BI/Excel no muestre "2015.0" en vez de "2015".
    # Los reindex de arriba garantizan que las columnas existan: antes esto era
    # atributos_pivot.get("anio"), que devuelve None si el atributo no aparece
    # en el subconjunto, y pd.to_numeric(None) da un np.float64 sobre el que
    # .astype("Int64") revienta con TypeError.
    atributos_pivot["anio"] = pd.to_numeric(atributos_pivot["anio"], errors="coerce").astype("Int64")
    atributos_pivot["kilometros"] = pd.to_numeric(atributos_pivot["kilometros"], errors="coerce").astype("Int64")

    return atributos_pivot


def normalizar_con_dims(
    atributos_pivot: pd.DataFrame,
    dim_marca: pd.DataFrame,
    dim_modelo: pd.DataFrame,
    dim_transmision: pd.DataFrame,
) -> pd.DataFrame:
    """Reemplaza marca/modelo/transmision por el texto normalizado de las dims (single source of truth)."""
    df = atributos_pivot.drop(columns=["marca", "modelo", "transmision"], errors="ignore")
    df = df.merge(dim_marca, on="id_marca", how="left")
    df = df.merge(dim_modelo, on="id_modelo", how="left")
    df = df.merge(dim_transmision, on="id_transmision", how="left")
    return df


def build_atributos_pivot(
    df_attrs: pd.DataFrame,
    results_base_dedup: pd.DataFrame,
    dims: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    claves = claves_ganadoras(results_base_dedup)
    atributos_pivot = pivotear_attrs(df_attrs, claves)
    atributos_pivot = atributos_pivot.merge(
        results_base_dedup[["__KEY_results", "id_publicacion"]], on="__KEY_results", how="left"
    )
    atributos_pivot = normalizar_con_dims(
        atributos_pivot, dims["dim_marca"], dims["dim_modelo"], dims["dim_transmision"]
    )
    return atributos_pivot
