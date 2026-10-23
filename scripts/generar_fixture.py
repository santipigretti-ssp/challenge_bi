"""Genera el fixture chico y determinista que usan los tests.

Se corre a mano una sola vez y la salida se commitea; CI nunca lo ejecuta.
Necesita los CSVs crudos en config.RAW_DATA_DIR y una corrida previa del ETL
completo en data/processed/ (de ahi saca los flags para estratificar).

    python scripts/generar_fixture.py

El muestreo es ESTRATIFICADO a proposito, no aleatorio: una muestra random no
toca capa 2 ni los casos de borde, que es justamente lo que hay que testear.
Cada estrato es un chequeo duro — si alguno queda vacio el script falla, en vez
de generar un fixture que aparenta cobertura que no tiene.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl import config, extract  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
SEED = 42

# Columnas que realmente lee etl.extract — el fixture solo necesita esas.
RESULTS_OUT = extract.RESULTS_COLUMNS
ATTRS_OUT = extract.ATTRIBUTES_COLUMNS


class EstratoVacio(RuntimeError):
    """Un estrato no encontro candidatos: el fixture seria enganoso."""


def _cargar_salidas_etl() -> pd.DataFrame:
    """fact_publicaciones + tabla_tendencias de la corrida sobre el dataset completo."""
    fp_path = config.PROCESSED_DIR / "fact_publicaciones.csv"
    tt_path = config.PROCESSED_DIR / "tabla_tendencias.csv"
    faltan = [p for p in (fp_path, tt_path) if not p.exists()]
    if faltan:
        raise SystemExit(
            "Falta la salida del ETL completo: "
            + ", ".join(str(p) for p in faltan)
            + "\nCorre 'python main.py' sobre el dataset completo antes de generar el fixture."
        )
    fp = pd.read_csv(fp_path)
    tt = pd.read_csv(tt_path, usecols=["id_publicacion", "obs_validas", "variacion_pct"])
    return fp.merge(tt, on="id_publicacion", how="left")


def _tomar(candidatos: pd.Series, n: int, nombre: str, elegidos: set) -> list:
    """n ids del estrato que no esten ya elegidos. Falla si el estrato esta vacio."""
    disponibles = [i for i in candidatos.tolist() if i not in elegidos]
    if not disponibles:
        raise EstratoVacio("estrato sin candidatos disponibles: " + nombre)
    serie = pd.Series(sorted(disponibles))
    tomados = serie.sample(n=min(n, len(serie)), random_state=SEED).tolist()
    elegidos.update(tomados)
    print("  {:<44} pedidos={:<4} disponibles={:<6} tomados={}".format(
        nombre, n, len(disponibles), len(tomados)))
    return tomados


def seleccionar_avisos(base: pd.DataFrame, df_results: pd.DataFrame) -> list:
    elegidos = set()
    print("Estratos:")

    # Capa 2 / tier global: sin atributos, incluyendo los precios mas extremos.
    sin_attrs = base[base["sin_atributos"]]
    extremos = sin_attrs.nlargest(3, "price_ars")["id_publicacion"]
    elegidos.update(extremos.tolist())
    print("  {:<44} tomados={}".format("sin_atributos (3 extremos, forzados)", len(extremos)))
    _tomar(sin_attrs["id_publicacion"], 12, "sin_atributos (resto)", elegidos)

    # Capa 1 de precio: piso por moneda y techo dinamico.
    piso = base[base["precio_invalido"] & (base["price"] <= config.PRECIO_INVALIDO_ARS_MIN)]
    _tomar(piso["id_publicacion"], 8, "precio_invalido por piso", elegidos)
    techo = base[base["precio_invalido"] & (base["price"] > 1_000_000)]
    _tomar(techo["id_publicacion"], 5, "precio_invalido por techo dinamico", elegidos)

    # Tendencias: una sola observacion y los tres movimientos.
    _tomar(base.loc[base["obs_validas"] == 1, "id_publicacion"], 10, "obs_validas == 1", elegidos)
    medibles = base[base["obs_validas"] >= 2]
    _tomar(medibles.loc[medibles["variacion_pct"] > 0.02, "id_publicacion"], 10, "precio sube > 2%", elegidos)
    _tomar(medibles.loc[medibles["variacion_pct"] < -0.02, "id_publicacion"], 10, "precio baja > 2%", elegidos)
    _tomar(medibles.loc[medibles["variacion_pct"].abs() <= 0.02, "id_publicacion"], 10, "precio plano", elegidos)
    _tomar(base.loc[base["obs_validas"] == 0, "id_publicacion"], 5, "obs_validas == 0 (sin precio)", elegidos)

    # Dedup: avisos con mas de una captura el mismo dia.
    por_dia = df_results.groupby(["id_u9", "fecha_captura"]).size()
    intra_dia = pd.Series(por_dia[por_dia > 1].index.get_level_values("id_u9").unique())
    _tomar(intra_dia, 5, "duplicado intra-dia", elegidos)

    # Capa 1 de km.
    _tomar(base.loc[base["kilometros"] == 0, "id_publicacion"], 5, "km == 0", elegidos)
    _tomar(base.loc[base["kilometros"].between(1, config.KM_TYPO_MAX - 1), "id_publicacion"],
           5, "0 < km < 1000 (typo)", elegidos)
    _tomar(base.loc[base["kilometros"] > config.KM_MAX_REAL, "id_publicacion"], 5, "km > 800.000", elegidos)
    # Nota: no hay estrato para "Mas de 500.000 KM". En este dataset no existe
    # ningun aviso con km entre 500.000 y KM_MAX_REAL (el maximo valido es
    # 490.000), asi que esa categoria de rango_km es inalcanzable y el fixture
    # no puede cubrirla. La rama de categoria_km queda cubierta por el test
    # unitario, que si la ejercita con km=500_000.

    # Moneda.
    _tomar(base.loc[base["currency_id"] == "USD", "id_publicacion"], 5, "currency_id == USD", elegidos)

    # Gate del IQR: hace falta un grupo (id_modelo, anio) que lo pase y uno que no.
    con_grupo = base.dropna(subset=["id_modelo", "anio"])
    grupos = con_grupo.groupby(["id_modelo", "anio"])["id_publicacion"].count().sort_values(ascending=False)
    if grupos.empty:
        raise EstratoVacio("no hay ningun grupo (id_modelo, anio)")

    id_modelo_g, anio_g = grupos.index[0]
    grande = con_grupo[(con_grupo["id_modelo"] == id_modelo_g) & (con_grupo["anio"] == anio_g)]
    _tomar(grande["id_publicacion"], config.IQR_MIN_AVISOS + 2,
           "grupo IQR grande {}/{}".format(id_modelo_g, int(anio_g)), elegidos)

    chicos = grupos[grupos < config.IQR_MIN_AVISOS]
    if chicos.empty:
        raise EstratoVacio("no hay ningun grupo (id_modelo, anio) por debajo del minimo")
    id_modelo_c, anio_c = chicos.index[0]
    chico = con_grupo[(con_grupo["id_modelo"] == id_modelo_c) & (con_grupo["anio"] == anio_c)]
    _tomar(chico["id_publicacion"], config.IQR_MIN_AVISOS - 5,
           "grupo IQR chico {}/{}".format(id_modelo_c, int(anio_c)), elegidos)

    # Capa 2 tiene que marcar algo, o el fixture no prueba nada de lo que mas
    # importa. Para cada flag se toma el grupo que mas outliers concentra en el
    # dataset completo, mayoritariamente con avisos normales (son los que fijan
    # los cuartiles) y unos pocos marcados, para que el fence los vuelva a
    # marcar sobre la muestra chica.
    for col, etiqueta in (("precio_outlier", "precio"), ("km_outlier", "km")):
        conteo = base[base[col]].groupby(["id_modelo", "anio"]).size().sort_values(ascending=False)
        if conteo.empty:
            raise EstratoVacio("el dataset completo no tiene ningun " + col)
        id_mod, anio_o = conteo.index[0]
        grupo = con_grupo[(con_grupo["id_modelo"] == id_mod) & (con_grupo["anio"] == anio_o)]
        _tomar(grupo.loc[~grupo[col], "id_publicacion"], 20,
               "outliers {} {}/{} (normales)".format(etiqueta, id_mod, int(anio_o)), elegidos)
        _tomar(grupo.loc[grupo[col], "id_publicacion"], 5,
               "outliers {} {}/{} (marcados)".format(etiqueta, id_mod, int(anio_o)), elegidos)

    return sorted(elegidos)


def verificar_gate_iqr(base: pd.DataFrame, ids: list) -> None:
    """El fixture tiene que ejercitar el gate de muestra minima en los dos sentidos."""
    sel = base[base["id_publicacion"].isin(ids)].dropna(subset=["id_modelo", "anio"])
    conteos = sel.groupby(["id_modelo", "anio"])["id_publicacion"].nunique()
    pasan = int((conteos >= config.IQR_MIN_AVISOS).sum())
    no_pasan = int((conteos < config.IQR_MIN_AVISOS).sum())
    print("\nGate IQR en el fixture: {} grupo(s) con >= {} avisos, {} por debajo".format(
        pasan, config.IQR_MIN_AVISOS, no_pasan))
    print(conteos.sort_values(ascending=False).to_string())
    if pasan == 0:
        raise EstratoVacio(
            "ningun grupo alcanza IQR_MIN_AVISOS={}: capa 2 no se ejercita".format(config.IQR_MIN_AVISOS))
    if no_pasan == 0:
        raise EstratoVacio("ningun grupo queda por debajo del minimo: el gate no se ejercita")


def anonimizar(df_results: pd.DataFrame, attrs_sel: pd.DataFrame) -> pd.DataFrame:
    """Reescribe id_u9, title y permalink. No toca precio, km, anio, fechas ni moneda.

    __KEY_results lleva la categoria (MLA29483), no el id del aviso, asi que
    queda tal cual: es la clave de join con attributes.csv.
    """
    df = df_results.copy()
    ids = sorted(df["id_u9"].unique())
    mapa = {viejo: "MLA9{:09d}".format(i + 1) for i, viejo in enumerate(ids)}

    # title sintetico a partir de los atributos reales del auto, para no
    # arrastrar el titulo que escribio el vendedor (suele traer telefonos).
    texto = (
        attrs_sel[attrs_sel["name_u6"].isin(["Marca", "Modelo", "Versión"])]
        .pivot_table(index="__KEY_results", columns="name_u6", values="value_name", aggfunc="first")
    )
    for col in ("Marca", "Modelo", "Versión"):
        if col not in texto.columns:
            texto[col] = pd.NA
    titulos = (
        texto[["Marca", "Modelo", "Versión"]]
        .apply(lambda r: " ".join(str(v) for v in r if pd.notna(v) and str(v).strip() not in ("", "-")), axis=1)
        .replace("", pd.NA)
    )

    df["title"] = df["__KEY_results"].map(titulos).fillna("Auto usado")
    df["id_u9"] = df["id_u9"].map(mapa)
    df["permalink"] = "https://example.invalid/" + df["id_u9"]
    return df


def main() -> None:
    print("Leyendo salidas del ETL completo desde {}".format(config.PROCESSED_DIR))
    base = _cargar_salidas_etl()
    print("  fact_publicaciones: {:,} avisos\n".format(len(base)))

    df_results = extract.read_results()
    df_attrs = extract.read_attributes()
    serial = df_results["__KEY_results"].str.split("-", n=1).str[0].astype(int)
    df_results["fecha_captura"] = (
        pd.Timestamp("1899-12-30") + pd.to_timedelta(serial, unit="D")
    ).dt.date
    print()

    ids = seleccionar_avisos(base, df_results)
    print("\nAvisos seleccionados: {}".format(len(ids)))
    verificar_gate_iqr(base, ids)

    # Todas las capturas de cada aviso: es lo que hace significativa la ruta de
    # tendencias y el historico de precios.
    res_sel = df_results[df_results["id_u9"].isin(ids)].drop(columns="fecha_captura")
    attrs_sel = df_attrs[df_attrs["__KEY_results"].isin(set(res_sel["__KEY_results"]))]
    res_sel = anonimizar(res_sel, attrs_sel)

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    res_path = FIXTURE_DIR / "results_sample.csv"
    attrs_path = FIXTURE_DIR / "attributes_sample.csv"
    res_sel[RESULTS_OUT].to_csv(res_path, sep=config.RAW_DELIMITER,
                                encoding=config.RAW_ENCODING, index=False)
    attrs_sel[ATTRS_OUT].to_csv(attrs_path, sep=config.RAW_DELIMITER,
                                encoding=config.RAW_ENCODING, index=False)

    capturas = res_sel.groupby("id_u9").size()
    print("\nEscrito {}:   {:,} filas, {:.0f} KB".format(
        res_path.name, len(res_sel), res_path.stat().st_size / 1024))
    print("Escrito {}: {:,} filas, {:.0f} KB".format(
        attrs_path.name, len(attrs_sel), attrs_path.stat().st_size / 1024))
    print("Capturas por aviso: mediana {:.0f}, max {}".format(capturas.median(), capturas.max()))


if __name__ == "__main__":
    main()
