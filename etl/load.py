"""Escritura de los CSVs de salida.

Dos propiedades que antes no tenia: verifica el esquema ANTES de tocar el
filesystem, y escribe de forma atomica. La version anterior hacia to_csv tabla
por tabla, asi que un crash a mitad dejaba CSVs parciales y Power BI los
consumia igual, sin ninguna senal de que faltaban filas.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import pandas as pd

from etl import config, schemas
from etl.errors import ValidationError

logger = logging.getLogger(__name__)

MANIFEST = "_manifest.json"


def verificar_esquemas(tablas: dict) -> None:
    """Nombre y orden exacto de columnas de cada tabla contra schemas.ESQUEMAS.

    Acumula todos los desvios y levanta una sola vez, antes de escribir nada.
    """
    fallas = []

    esperadas = set(schemas.ESQUEMAS)
    recibidas = set(tablas)
    if faltantes := esperadas - recibidas:
        fallas.append("faltan tablas: {}".format(sorted(faltantes)))
    if sobrantes := recibidas - esperadas:
        fallas.append("tablas no declaradas en schemas.ESQUEMAS: {}".format(sorted(sobrantes)))

    for nombre in sorted(esperadas & recibidas):
        real = list(tablas[nombre].columns)
        contrato = schemas.ESQUEMAS[nombre]
        if real != contrato:
            if set(real) == set(contrato):
                fallas.append("{}: las columnas estan en otro orden".format(nombre))
            else:
                fallas.append(
                    "{}: faltan {} / sobran {}".format(
                        nombre,
                        [c for c in contrato if c not in real],
                        [c for c in real if c not in contrato],
                    )
                )

    if fallas:
        raise ValidationError(
            "el esquema de salida no coincide con el contrato:\n  - {}".format("\n  - ".join(fallas))
        )


def _ordenar(nombre: str, df: pd.DataFrame) -> pd.DataFrame:
    claves = schemas.ORDEN_SALIDA.get(nombre, [])
    if not claves:
        return df
    return df.sort_values(claves, kind="stable").reset_index(drop=True)


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def escribir_csvs(tablas: dict, extra_manifest: dict | None = None) -> dict:
    """Verifica, escribe a temporales, y recien ahi mueve todo a su lugar.

    os.replace es atomico dentro del mismo volumen, tambien en Windows. Si algo
    falla a mitad, los CSVs de la corrida anterior quedan intactos.

    Devuelve el manifest, que ademas se escribe a disco: filas, columnas, bytes
    y sha256 por tabla. Es el artefacto que hace verificable la afirmacion de
    "dos corridas dan lo mismo".
    """
    verificar_esquemas(tablas)
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    temporales = {}
    try:
        for nombre, df in tablas.items():
            destino = config.PROCESSED_DIR / "{}.csv".format(nombre)
            temporal = destino.with_suffix(".csv.tmp")
            _ordenar(nombre, df).to_csv(
                temporal,
                sep=config.OUTPUT_DELIMITER,
                encoding=config.OUTPUT_ENCODING,
                index=False,
            )
            temporales[nombre] = (temporal, destino)

        manifest = {
            "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dataset": config.DATASET,
            "tablas": {},
        }
        for nombre, (temporal, destino) in temporales.items():
            os.replace(temporal, destino)
            manifest["tablas"][nombre] = {
                "filas": int(len(tablas[nombre])),
                "columnas": len(schemas.ESQUEMAS[nombre]),
                "bytes": destino.stat().st_size,
                "sha256": _sha256(destino),
            }
            logger.info("Escrito %s (%s filas)", destino, len(tablas[nombre]))
    finally:
        # Lo que quedo sin mover (porque algo fallo) no se deja tirado.
        for temporal, _ in temporales.values():
            if temporal.exists():
                temporal.unlink()

    if extra_manifest:
        manifest.update(extra_manifest)

    destino_manifest = config.PROCESSED_DIR / MANIFEST
    destino_manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Escrito %s", destino_manifest)
    return manifest
