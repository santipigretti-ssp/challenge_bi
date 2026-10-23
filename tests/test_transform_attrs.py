import logging

import pandas as pd
import pytest

from etl import transform_attrs

CLAVE = "42316-0-MLA29483-1"


def _attrs(filas):
    """Formato largo de attributes.csv: (__KEY_results, name_u6, value_id, value_name)."""
    return pd.DataFrame(filas, columns=["__KEY_results", "name_u6", "value_id", "value_name"])


def _completo(clave=CLAVE):
    return [
        (clave, "Marca", "MLA1744-BRND-VOLKSWAGEN", "Volkswagen"),
        (clave, "Modelo", "MLA1744-MODL-VENTO", "Vento"),
        (clave, "Transmisión", "MLA1744-TRNS-MANUAL", "Manual"),
        (clave, "Año", "", "2015"),
        (clave, "Kilómetros", "", "38000"),
        (clave, "Versión", "", "2.5 Luxury"),
    ]


# --- build_dim ---

def test_build_dim_elige_la_grafia_mas_frecuente():
    """VENTO/Vento se resuelve por frecuencia, sin diccionario de overrides."""
    df = _attrs([
        ("k1", "Modelo", "MLA1744-MODL-VENTO", "VENTO"),
        ("k2", "Modelo", "MLA1744-MODL-VENTO", "Vento"),
        ("k3", "Modelo", "MLA1744-MODL-VENTO", "Vento"),
    ])
    dim = transform_attrs.build_dim(df, "Modelo")

    assert len(dim) == 1
    assert dim.iloc[0]["modelo"] == "Vento"
    assert dim.iloc[0]["id_modelo"] == "MLA1744-MODL-VENTO"


def test_build_dim_ignora_value_id_vacio():
    """Año/Kilómetros/Versión vienen sin value_id y no forman dimension."""
    df = _attrs([
        ("k1", "Modelo", "", "Vento"),
        ("k2", "Modelo", None, "Fun"),
        ("k3", "Modelo", "MLA1744-MODL-FUN", "Fun"),
    ])
    dim = transform_attrs.build_dim(df, "Modelo")

    assert len(dim) == 1
    assert dim.iloc[0]["id_modelo"] == "MLA1744-MODL-FUN"


# --- pivotear_attrs: esquema fijo ---

def test_pivotear_attrs_caso_completo():
    pivot = transform_attrs.pivotear_attrs(_attrs(_completo()), pd.Series([CLAVE]))

    assert len(pivot) == 1
    fila = pivot.iloc[0]
    assert fila["marca"] == "Volkswagen"
    assert fila["anio"] == 2015
    assert fila["kilometros"] == 38000
    assert fila["version"] == "2.5 Luxury"
    assert pivot["anio"].dtype == "Int64"
    assert pivot["kilometros"].dtype == "Int64"


@pytest.mark.parametrize("ausente", ["Año", "Kilómetros", "Versión", "Marca", "Modelo", "Transmisión"])
def test_pivotear_attrs_tolera_cualquier_atributo_ausente(ausente):
    """Antes, faltar "Año" o "Kilómetros" reventaba con
    TypeError: data type 'Int64' not understood.

    Pasaba porque atributos_pivot.get("anio") devuelve None cuando la columna no
    existe, pd.to_numeric(None) da un np.float64(nan) y un escalar de numpy no
    acepta .astype("Int64"). Alcanzable con cualquier subconjunto que no traiga
    ese atributo: una muestra chica o un re-scrape.
    """
    filas = [f for f in _completo() if f[1] != ausente]
    pivot = transform_attrs.pivotear_attrs(_attrs(filas), pd.Series([CLAVE]))

    # El esquema es fijo: las 6 columnas de texto y las 3 de id existen siempre.
    esperadas = {"marca", "modelo", "transmision", "anio", "kilometros", "version",
                 "id_marca", "id_modelo", "id_transmision", "__KEY_results"}
    assert set(pivot.columns) == esperadas
    assert pivot["anio"].dtype == "Int64"
    assert pivot["kilometros"].dtype == "Int64"


def test_pivotear_attrs_sin_ningun_atributo_devuelve_el_esquema_vacio():
    pivot = transform_attrs.pivotear_attrs(_attrs(_completo()), pd.Series(["clave-que-no-existe"]))

    assert len(pivot) == 0
    assert "anio" in pivot.columns
    assert "id_marca" in pivot.columns


# --- pivotear_attrs: duplicados ---

def test_pivotear_attrs_no_revienta_con_duplicados(caplog):
    """.pivot() levanta ValueError ante un par (clave, atributo) duplicado.

    Hoy el archivo no tiene ninguno, pero el invariante estaba indefenso.
    """
    filas = _completo() + [(CLAVE, "Marca", "MLA1744-BRND-VOLKSWAGEN", "VOLKSWAGEN")]

    with caplog.at_level(logging.WARNING, logger="etl.transform_attrs"):
        pivot = transform_attrs.pivotear_attrs(_attrs(filas), pd.Series([CLAVE]))

    assert len(pivot) == 1
    assert "duplicado" in caplog.text
    # Determinístico: gana el ultimo por orden de value_id/value_name.
    assert pivot.iloc[0]["marca"] == "Volkswagen"


def test_pivotear_attrs_sin_duplicados_no_loguea_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="etl.transform_attrs"):
        transform_attrs.pivotear_attrs(_attrs(_completo()), pd.Series([CLAVE]))

    assert "duplicado" not in caplog.text


# --- normalizar_con_dims ---

def test_normalizar_con_dims_funciona_con_atributos_ausentes():
    """Antes hacia KeyError si la columna de id no estaba en el pivot."""
    filas = [f for f in _completo() if f[1] != "Transmisión"]
    pivot = transform_attrs.pivotear_attrs(_attrs(filas), pd.Series([CLAVE]))

    dims = transform_attrs.build_dims(_attrs(_completo()))
    out = transform_attrs.normalizar_con_dims(
        pivot, dims["dim_marca"], dims["dim_modelo"], dims["dim_transmision"]
    )

    assert len(out) == 1
    assert out.iloc[0]["marca"] == "Volkswagen"
    assert pd.isna(out.iloc[0]["transmision"])


def test_normalizar_con_dims_usa_el_texto_de_la_dim_no_el_del_pivot():
    """La dim es la unica fuente de verdad para el texto."""
    pivot = transform_attrs.pivotear_attrs(_attrs(_completo()), pd.Series([CLAVE]))
    # La dim resuelve la grafia por frecuencia: "Vento" gana sobre "VENTO".
    dims = transform_attrs.build_dims(_attrs([
        ("k1", "Modelo", "MLA1744-MODL-VENTO", "Vento"),
        ("k2", "Modelo", "MLA1744-MODL-VENTO", "Vento"),
        ("k3", "Modelo", "MLA1744-MODL-VENTO", "VENTO"),
        ("k1", "Marca", "MLA1744-BRND-VOLKSWAGEN", "Volkswagen"),
        ("k1", "Transmisión", "MLA1744-TRNS-MANUAL", "Manual"),
    ]))
    out = transform_attrs.normalizar_con_dims(
        pivot, dims["dim_marca"], dims["dim_modelo"], dims["dim_transmision"]
    )

    assert out.iloc[0]["modelo"] == "Vento"
    assert "modelo_x" not in out.columns  # no quedaron columnas colisionadas
