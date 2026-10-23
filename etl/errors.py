"""Errores y precondiciones del pipeline.

Modulo sin dependencias dentro de etl/, para que lo pueda importar cualquier
otro sin armar un ciclo.
"""
from __future__ import annotations

import pandas as pd


class ValidationError(Exception):
    """Una invariante del pipeline no se cumple."""


def requiere_columnas(df: pd.DataFrame, columnas, quien: str) -> None:
    """Falla nombrando la funcion y las columnas que faltan.

    Varias funciones tienen una dependencia de orden real: agregar_rango_km y
    dolarizar leen columnas que solo existen despues de
    outliers.agregar_columnas_limpias. Estaba documentada en un docstring (y en
    el caso de dolarizar, ni eso). Chequearlo en runtime convierte un resultado
    silenciosamente incorrecto en un error que dice que falta y donde.

    No se usa un framework de orquestacion a proposito: para diez modulos seria
    desproporcionado y taparia el flujo lineal de main.run, que hoy es lo que
    mejor se lee del repo.
    """
    faltan = [c for c in columnas if c not in df.columns]
    if faltan:
        raise ValidationError(
            "{}: faltan las columnas {}. Presentes: {}".format(
                quien, faltan, sorted(df.columns)
            )
        )
