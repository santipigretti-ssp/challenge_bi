import os
from datetime import datetime
from pathlib import Path

ETL_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ETL_DIR.parent
CHALLENGE_DIR = PROJECT_DIR.parent

# Que dataset leer. "completo" apunta a los CSVs crudos, que viven FUERA del
# repo (son ~100 MB); "fixture" apunta a la muestra estratificada versionada en
# tests/fixtures/, que es con la que corren los tests y CI.
DATASET = os.getenv("ETL_DATASET", "completo").strip().lower()
if DATASET not in ("completo", "fixture"):
    raise ValueError(
        "ETL_DATASET invalido: " + repr(DATASET) + ". Valores validos: completo, fixture"
    )

if DATASET == "fixture":
    RAW_DATA_DIR = PROJECT_DIR / "tests" / "fixtures"
    RESULTS_CSV = RAW_DATA_DIR / "results_sample.csv"
    ATTRIBUTES_CSV = RAW_DATA_DIR / "attributes_sample.csv"
    PROCESSED_DIR = PROJECT_DIR / "data" / "processed_fixture"
else:
    RAW_DATA_DIR = CHALLENGE_DIR / "CSVs"
    RESULTS_CSV = RAW_DATA_DIR / "results.csv"
    ATTRIBUTES_CSV = RAW_DATA_DIR / "attributes.csv"
    PROCESSED_DIR = PROJECT_DIR / "data" / "processed"

RAW_ENCODING = "utf-8-sig"
RAW_DELIMITER = ";"
OUTPUT_ENCODING = "utf-8"
OUTPUT_DELIMITER = ","

STOP_TIME_FORMAT = "%m/%d/%Y %H:%M:%S"
# La fecha de captura sale del serial de Excel que lleva __KEY_results.
# Era un string sin usar aca y un datetime redefinido en
# transform_results; ahora hay una sola definicion, en el lugar donde
# viven los demas parametros.
EXCEL_EPOCH = datetime(1899, 12, 30)

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
# Capa 2 - fence global, para las filas que no caen en ningun grupo con
# muestra suficiente (sin modelo/anio, o grupo chico). Mismo k que el de
# grupo a proposito: no es una constante nueva que haya que justificar, es
# el mismo fence de Tukey sobre otra poblacion de referencia. Sobre el
# dataset completo da un techo de ~550.000 ARS, que marca los 3 precios
# extremos de los avisos sin atributos (790k, 790k, 850k) y deja pasar los
# de 415k/440k/490k, que son plausibles. Con k=3 el techo se iria a ~870k y
# se escaparian 2 de los 3.
IQR_GLOBAL_K = 1.5
# Cuartiles sobre un valor por aviso en vez de sobre todas las capturas.
# El gate de muestra minima ya cuenta avisos distintos para evitar
# pseudo-replicacion; sin esto el estimador la reintroducia y un aviso con
# 70 capturas pesaba 70 veces en Q1/Q3. Queda como flag para poder
# publicar la fila de sensibilidad del README.
IQR_COLAPSAR_POR_AVISO = True

# Tendencias
TENDENCIA_UMBRAL = 0.02

# FX
FX_API_URL = "https://api.argentinadatos.com/v1/cotizaciones/dolares/{casa}"
FX_CASAS = ("oficial", "blue")
FX_TIMEOUT_SECONDS = 10
FX_RETRIES = 2
# Fallback si la API falla (ultimo valor conocido al cierre de este proyecto,
# nov-2015). Deshabilitado por defecto: estos valores coinciden con los que
# devuelve la API real, asi que usarlos en silencio volvia invisible
# cualquier falla. Se habilita con ETL_FX_FALLBACK=1.
FX_FALLBACK = {"oficial": 10.0, "blue": 15.0}
FX_FALLBACK_HABILITADO = os.getenv("ETL_FX_FALLBACK", "").strip() in ("1", "true", "True")

LOG_FILE = PROJECT_DIR / "etl.log"
