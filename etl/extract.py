import logging

import pandas as pd

from etl import config

logger = logging.getLogger(__name__)

RESULTS_COLUMNS = [
    "__KEY_results",
    "id_u9",
    "title",
    "price",
    "currency_id",
    "condition",
    "stop_time",
    "accepts_mercadopago",
    "listing_type_id",
    "category_id",
    "permalink",
]

ATTRIBUTES_COLUMNS = [
    "__KEY_results",
    "name_u6",
    "value_id",
    "value_name",
]


def read_results() -> pd.DataFrame:
    df = pd.read_csv(
        config.RESULTS_CSV,
        sep=config.RAW_DELIMITER,
        encoding=config.RAW_ENCODING,
        usecols=RESULTS_COLUMNS,
        dtype={
            "__KEY_results": str,
            "id_u9": str,
            "title": str,
            "currency_id": str,
            "condition": str,
            "stop_time": str,
            "listing_type_id": str,
            "category_id": str,
            "permalink": str,
        },
    )
    df["accepts_mercadopago"] = df["accepts_mercadopago"].astype(str).str.strip().eq("True")
    logger.info("results.csv: %s filas leidas", len(df))
    return df


def read_attributes() -> pd.DataFrame:
    df = pd.read_csv(
        config.ATTRIBUTES_CSV,
        sep=config.RAW_DELIMITER,
        encoding=config.RAW_ENCODING,
        usecols=ATTRIBUTES_COLUMNS,
        dtype={
            "__KEY_results": str,
            "name_u6": str,
            "value_id": str,
            "value_name": str,
        },
    )
    logger.info("attributes.csv: %s filas leidas", len(df))
    return df
