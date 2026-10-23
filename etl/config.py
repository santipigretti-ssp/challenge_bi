from pathlib import Path

ETL_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ETL_DIR.parent
CHALLENGE_DIR = PROJECT_DIR.parent

RAW_DATA_DIR = CHALLENGE_DIR / "CSVs"
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"

RESULTS_CSV = RAW_DATA_DIR / "results.csv"
ATTRIBUTES_CSV = RAW_DATA_DIR / "attributes.csv"

RAW_ENCODING = "utf-8-sig"
RAW_DELIMITER = ";"
OUTPUT_ENCODING = "utf-8"
OUTPUT_DELIMITER = ","

STOP_TIME_FORMAT = "%m/%d/%Y %H:%M:%S"
EXCEL_EPOCH = "1899-12-30"

# Capa 1 - reglas de dominio (piso de precio)
PRECIO_INVALIDO_ARS_MIN = 1000
PRECIO_INVALIDO_USD_MIN = 100

# Capa 1 - techo dinamico (global, no por grupo), ver seccion 2.3 del plan
TECHO_GLOBAL_K = 5

# Capa 1 - kilometros / anio
KM_TYPO_MAX = 1000  # 0 < km < 1000 se considera typo
KM_MAX_REAL = 800_000
ANIO_MIN = 1910

# Capa 2 - IQR por grupo (id_modelo, anio)
IQR_GROUP_K = 1.5
IQR_MIN_AVISOS = 8

# Tendencias
TENDENCIA_UMBRAL = 0.02

# FX
FX_API_URL = "https://api.argentinadatos.com/v1/cotizaciones/dolares/{casa}"
FX_CASAS = ("oficial", "blue")
FX_TIMEOUT_SECONDS = 10
FX_RETRIES = 2
# Fallback si la API falla (ultimo valor conocido al cierre de este proyecto, nov-2015)
FX_FALLBACK = {"oficial": 10.0, "blue": 15.0}

LOG_FILE = PROJECT_DIR / "etl.log"
