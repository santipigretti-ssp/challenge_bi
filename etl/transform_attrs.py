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


def pivotear_attrs(df_attrs: pd.DataFrame, claves: pd.Series) -> pd.DataFrame:
    """Pivot dual (value_name + value_id) sobre solo las capturas ganadoras.

    Filtrar antes de pivotear reduce el volumen de ~662k filas a ~6k*6, en vez
    de pivotear todo y deduplicar después (ver sección 2.6 del plan).
    """
    df_filtrado = df_attrs[df_attrs["__KEY_results"].isin(set(claves))]
    logger.info(
        "atributos_pivot: filtrado de %s a %s filas antes de pivotear",
        len(df_attrs),
        len(df_filtrado),
    )

    pivot_nombres = df_filtrado.pivot(index="__KEY_results", columns="name_u6", values="value_name")
    pivot_nombres = pivot_nombres.rename(columns=NOMBRE_A_COLUMNA)

    con_id = df_filtrado[df_filtrado["name_u6"].isin(ATRIBUTOS_CON_ID)]
    pivot_ids = con_id.pivot(index="__KEY_results", columns="name_u6", values="value_id")
    pivot_ids = pivot_ids.rename(columns=NOMBRE_A_COLUMNA_ID)

    atributos_pivot = pivot_nombres.join(pivot_ids, how="left").reset_index()

    # Int64 nullable (no float) para que Power BI/Excel no muestre "2015.0" en vez de "2015"
    atributos_pivot["anio"] = pd.to_numeric(atributos_pivot.get("anio"), errors="coerce").astype("Int64")
    atributos_pivot["kilometros"] = pd.to_numeric(atributos_pivot.get("kilometros"), errors="coerce").astype("Int64")

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
