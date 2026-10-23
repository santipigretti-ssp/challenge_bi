"""Configuracion comun de la suite.

Lo importante que pasa aca: por defecto los tests corren contra el fixture
versionado en tests/fixtures/, no contra los CSVs crudos de ~100 MB que viven
fuera del repo. Asi `pytest` anda en un clon limpio, sin descargar nada y sin
tocar la red.

Para correr la suite contra el dataset completo:

    ETL_DATASET=completo pytest
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from etl import config  # noqa: E402

FIXTURE_DIR = RAIZ / "tests" / "fixtures"
RESULTS_FIXTURE = FIXTURE_DIR / "results_sample.csv"
ATTRS_FIXTURE = FIXTURE_DIR / "attributes_sample.csv"


def _pidio_dataset_completo() -> bool:
    return os.getenv("ETL_DATASET", "").strip().lower() == "completo"


@pytest.fixture(scope="session", autouse=True)
def dataset_de_test(tmp_path_factory):
    """Apunta el ETL al fixture, salvo que se pida el dataset completo.

    Se parchean los atributos del modulo config en vez de confiar en el orden
    en que se lee la variable de entorno al importarlo: config resuelve las
    rutas en tiempo de import, asi que setear la variable despues no alcanza.
    """
    if _pidio_dataset_completo():
        yield
        return

    faltan = [p.name for p in (RESULTS_FIXTURE, ATTRS_FIXTURE) if not p.exists()]
    if faltan:
        pytest.fail(
            "Falta el fixture ({}). Regeneralo con `python scripts/generar_fixture.py` "
            "(necesita los CSVs crudos).".format(", ".join(faltan))
        )

    salida = tmp_path_factory.mktemp("processed")
    mp = pytest.MonkeyPatch()
    mp.setattr(config, "DATASET", "fixture")
    mp.setattr(config, "RAW_DATA_DIR", FIXTURE_DIR)
    mp.setattr(config, "RESULTS_CSV", RESULTS_FIXTURE)
    mp.setattr(config, "ATTRIBUTES_CSV", ATTRS_FIXTURE)
    mp.setattr(config, "PROCESSED_DIR", salida)
    yield
    mp.undo()


@pytest.fixture
def fx_fijo(monkeypatch):
    """Tipo de cambio fijo, para que ningun test dependa de la API de FX.

    Son los valores reales de nov-2015, asi los numeros del fixture son
    comparables con los de una corrida de verdad.
    """
    from etl import fx

    valores = {"fecha_fx": "2015-11-30", "usd_oficial": 10.0, "usd_blue": 15.0}
    monkeypatch.setattr(fx, "get_fx", lambda max_fecha_captura: dict(valores))
    return valores
