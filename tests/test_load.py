import json

import pandas as pd
import pytest

from etl import config, load, schemas
from etl.errors import ValidationError


def _tabla(nombre, filas=1):
    """DataFrame con el esquema declarado de la tabla."""
    cols = schemas.ESQUEMAS[nombre]
    return pd.DataFrame({c: list(range(filas)) for c in cols})


def _todas_las_tablas():
    return {nombre: _tabla(nombre) for nombre in schemas.ESQUEMAS}


@pytest.fixture
def salida(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROCESSED_DIR", tmp_path)
    return tmp_path


# --- Verificacion de esquema ---

def test_escribe_las_ocho_tablas_y_el_manifest(salida):
    manifest = load.escribir_csvs(_todas_las_tablas())

    for nombre in schemas.ESQUEMAS:
        assert (salida / "{}.csv".format(nombre)).exists()
    assert (salida / load.MANIFEST).exists()
    assert set(manifest["tablas"]) == set(schemas.ESQUEMAS)


def test_rechaza_columnas_en_otro_orden_sin_escribir_nada(salida):
    """El orden de columnas es parte del contrato: Power Query lo cachea."""
    tablas = _todas_las_tablas()
    cols = list(tablas["dim_marca"].columns)
    tablas["dim_marca"] = tablas["dim_marca"][cols[::-1]]

    with pytest.raises(ValidationError, match="en otro orden"):
        load.escribir_csvs(tablas)

    assert list(salida.iterdir()) == [], "no deberia haber escrito nada"


def test_rechaza_columna_faltante(salida):
    tablas = _todas_las_tablas()
    tablas["fact_publicaciones"] = tablas["fact_publicaciones"].drop(columns="rango_km")

    with pytest.raises(ValidationError, match="rango_km"):
        load.escribir_csvs(tablas)
    assert list(salida.iterdir()) == []


def test_rechaza_columna_sobrante(salida):
    tablas = _todas_las_tablas()
    tablas["dim_marca"] = tablas["dim_marca"].assign(sobrante=1)

    with pytest.raises(ValidationError, match="sobran"):
        load.escribir_csvs(tablas)


def test_rechaza_tabla_faltante(salida):
    tablas = _todas_las_tablas()
    del tablas["dim_fecha"]

    with pytest.raises(ValidationError, match="faltan tablas"):
        load.escribir_csvs(tablas)


def test_rechaza_tabla_no_declarada(salida):
    tablas = _todas_las_tablas()
    tablas["dim_inventada"] = pd.DataFrame({"a": [1]})

    with pytest.raises(ValidationError, match="no declaradas"):
        load.escribir_csvs(tablas)


def test_reporta_todos_los_desvios_juntos(salida):
    tablas = _todas_las_tablas()
    tablas["dim_marca"] = tablas["dim_marca"].drop(columns="marca")
    tablas["dim_modelo"] = tablas["dim_modelo"].assign(sobrante=1)

    with pytest.raises(ValidationError) as exc:
        load.escribir_csvs(tablas)

    mensaje = str(exc.value)
    assert "dim_marca" in mensaje
    assert "dim_modelo" in mensaje


# --- Atomicidad ---

def test_no_deja_temporales(salida):
    load.escribir_csvs(_todas_las_tablas())
    assert not list(salida.glob("*.tmp"))


def test_una_falla_a_mitad_no_deja_csvs_parciales(salida, monkeypatch):
    """Un crash escribiendo la tabla N no puede dejar las N-1 anteriores.

    Antes se hacia to_csv tabla por tabla, asi que un crash a mitad dejaba
    CSVs parciales que Power BI consumia igual, sin senal de que faltaban filas.
    """
    original = pd.DataFrame.to_csv
    llamadas = {"n": 0}

    def to_csv_que_falla(self, *args, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 3:
            raise OSError("disco lleno (simulado)")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_csv", to_csv_que_falla)

    with pytest.raises(OSError, match="disco lleno"):
        load.escribir_csvs(_todas_las_tablas())

    assert not list(salida.glob("*.csv")), "quedaron CSVs de una corrida fallida"
    assert not list(salida.glob("*.tmp")), "quedaron temporales"


def test_una_corrida_fallida_no_pisa_la_anterior(salida, monkeypatch):
    load.escribir_csvs(_todas_las_tablas())
    antes = {p.name: p.read_bytes() for p in salida.glob("*.csv")}

    original = pd.DataFrame.to_csv
    llamadas = {"n": 0}

    def to_csv_que_falla(self, *args, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 3:
            raise OSError("disco lleno (simulado)")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_csv", to_csv_que_falla)
    with pytest.raises(OSError):
        load.escribir_csvs(_todas_las_tablas())

    despues = {p.name: p.read_bytes() for p in salida.glob("*.csv")}
    assert despues == antes, "la corrida fallida modifico los CSVs buenos"


# --- Orden de salida determinístico ---

def test_ordena_las_filas_por_la_clave(salida):
    tablas = _todas_las_tablas()
    tablas["dim_marca"] = pd.DataFrame({
        "id_marca": ["M3", "M1", "M2"], "marca": ["C", "A", "B"],
    })
    load.escribir_csvs(tablas)

    escrito = pd.read_csv(salida / "dim_marca.csv")
    assert escrito["id_marca"].tolist() == ["M1", "M2", "M3"]


def test_el_orden_de_entrada_no_cambia_la_salida(salida):
    """Dos frames con las mismas filas en otro orden dan el mismo CSV."""
    base = pd.DataFrame({"id_marca": ["M1", "M2", "M3"], "marca": ["A", "B", "C"]})

    tablas = _todas_las_tablas()
    tablas["dim_marca"] = base
    load.escribir_csvs(tablas)
    primero = (salida / "dim_marca.csv").read_bytes()

    tablas["dim_marca"] = base.iloc[::-1]
    load.escribir_csvs(tablas)
    assert (salida / "dim_marca.csv").read_bytes() == primero


# --- Manifest ---

def test_el_manifest_registra_filas_columnas_y_sha256(salida):
    tablas = _todas_las_tablas()
    tablas["dim_marca"] = pd.DataFrame({"id_marca": ["M1", "M2"], "marca": ["A", "B"]})
    manifest = load.escribir_csvs(tablas)

    entrada = manifest["tablas"]["dim_marca"]
    assert entrada["filas"] == 2
    assert entrada["columnas"] == 2
    assert len(entrada["sha256"]) == 64
    assert entrada["bytes"] == (salida / "dim_marca.csv").stat().st_size


def test_el_sha256_del_manifest_coincide_con_el_archivo(salida):
    manifest = load.escribir_csvs(_todas_las_tablas())

    for nombre, entrada in manifest["tablas"].items():
        assert entrada["sha256"] == load._sha256(salida / "{}.csv".format(nombre))


def test_el_manifest_es_json_valido_en_disco(salida):
    load.escribir_csvs(_todas_las_tablas(), extra_manifest={"fx": {"fuente": "override"}})

    en_disco = json.loads((salida / load.MANIFEST).read_text(encoding="utf-8"))
    assert en_disco["dataset"] == config.DATASET
    assert en_disco["fx"]["fuente"] == "override"
    assert "generado" in en_disco


def test_dos_escrituras_iguales_dan_el_mismo_sha256(salida):
    tablas = _todas_las_tablas()
    primero = load.escribir_csvs(tablas)
    segundo = load.escribir_csvs(tablas)

    for nombre in primero["tablas"]:
        assert primero["tablas"][nombre]["sha256"] == segundo["tablas"][nombre]["sha256"]
