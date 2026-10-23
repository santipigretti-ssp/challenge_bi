import logging

import pandas as pd

from etl import config

logger = logging.getLogger(__name__)


def escribir_csvs(tablas: dict[str, pd.DataFrame]) -> None:
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for nombre, df in tablas.items():
        destino = config.PROCESSED_DIR / f"{nombre}.csv"
        df.to_csv(
            destino,
            sep=config.OUTPUT_DELIMITER,
            encoding=config.OUTPUT_ENCODING,
            index=False,
        )
        logger.info("Escrito %s (%s filas)", destino, len(df))
