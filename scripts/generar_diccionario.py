"""Genera docs/DATA_DICTIONARY.md a partir de etl/schemas.py.

Se genera en vez de escribirse a mano por una razon concreta: el README y el
documento de diseno decian "fact_publicaciones (35 columnas)" cuando tiene 36,
y encima el documento afirmaba estar "verificado contra la cabecera de cada
archivo". Si la lista sale del codigo, no puede divergir.

    python scripts/generar_diccionario.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl import config, schemas  # noqa: E402

SALIDA = Path(__file__).resolve().parent.parent / "docs" / "DATA_DICTIONARY.md"

# Origen de cada columna, para la columna "Origen" de las tablas.
CRUDO = "crudo"
DERIVADA = "derivada"
DIM = "normalizada desde dim"
FLAG1 = "flag capa 1"
FLAG2 = "flag capa 2"
LIMPIA = "derivada _limpio"
ORDEN = "columna de orden"

GRANO = {
    "fact_publicaciones": ("1 fila por aviso (snapshot de la captura mas reciente)", "id_publicacion"),
    "fact_precios_historicos": ("1 fila por captura de precio", "id_publicacion + __KEY_results"),
    "tabla_tendencias": ("1 fila por aviso", "id_publicacion"),
    "dim_marca": ("1 fila por marca", "id_marca"),
    "dim_modelo": ("1 fila por modelo", "id_modelo"),
    "dim_transmision": ("1 fila por tipo de transmision", "id_transmision"),
    "dim_fecha": ("1 fila por dia del periodo de captura", "fecha"),
    "dim_FX": ("1 fila: la cotizacion usada en la corrida", "fecha_fx"),
}

FILAS_REALES = {
    "fact_publicaciones": "6.586",
    "fact_precios_historicos": "124.511",
    "tabla_tendencias": "6.586",
    "dim_marca": "3",
    "dim_modelo": "3",
    "dim_transmision": "3",
    "dim_fecha": "73",
    "dim_FX": "1",
}

NOTAS_TABLA = {
    "fact_precios_historicos": (
        "**Nunca se deriva de la tabla deduplicada.** Las dos tablas de hechos se "
        "ramifican de `results_base` sin deduplicar; el dedup se aplica solo al armar "
        "el snapshot de `fact_publicaciones`. Las 124.511 filas son capturas, no avisos: "
        "mediana de 14 capturas por aviso, maximo 70."
    ),
    "tabla_tendencias": (
        "Filtrar por `tendencia_medible` para el split de 3 vias del dashboard: da un "
        "denominador honesto de 5.629 avisos. Los 957 no medibles "
        "(543 `Observación única` + 414 `Sin precio`) se reportan aparte."
    ),
    "dim_fecha": (
        "Cubre 2015-10-10 a 2015-12-21, el periodo de captura. **No cubre `stop_time`**, "
        "que llega hasta 2016-02-19: el 44% de los `stop_time` no tiene fila en esta "
        "dimension. Las relaciones del modelo usan `fecha_pub` (activa) y "
        "`fecha_captura` (inactiva), asi que no hay relacion rota, pero no se puede "
        "cortar \"publicaciones que vencen por mes\" por el calendario."
    ),
    "dim_FX": (
        "Una sola cotizacion para todo el periodo, no una serie diaria. Es la de cierre "
        "del ultimo mes cerrado respecto de la ultima captura (noviembre 2015)."
    ),
}

# nombre -> (tipo, nullable, origen, definicion)
D = {}

def _reg(columna, tipo, nullable, origen, definicion):
    D[columna] = (tipo, nullable, origen, definicion)


# --- Identificadores y atributos crudos del aviso ---
_reg("id_publicacion", "texto", "no", CRUDO, "PK del aviso. Renombre de `id_u9` del CSV crudo.")
_reg("title", "texto", "no", CRUDO, "Titulo que escribio el vendedor.")
_reg("permalink", "texto", "no", CRUDO, "URL del aviso en MercadoLibre.")
_reg("condition", "texto", "no", CRUDO, "Condicion declarada (`used` en todo el dataset).")
_reg("currency_id", "texto", "no", CRUDO, "Moneda del precio publicado: `ARS` (124.148 filas) o `USD` (363).")
_reg("category_id", "texto", "no", CRUDO, "Categoria de MercadoLibre (`MLA29483`, autos usados).")
_reg("listing_type_id", "texto", "no", CRUDO, "Tipo de publicacion (`gold_premium`, etc.).")
_reg("accepts_mercadopago", "booleano", "no", CRUDO,
     "**Sin varianza en este snapshot**: es `False` en las 124.511 filas crudas, asi que no "
     "lleva informacion. Se conserva por fidelidad al origen, y el detector de varianza cero "
     "de `validate` la reporta en cada corrida.")
_reg("stop_time", "datetime", "no", CRUDO,
     "Fin de la publicacion. Llega hasta 2016-02-19, fuera del rango de `dim_fecha`. "
     "Cambia en el 25,7% de los avisos: el vendedor puede renovar.")
_reg("fecha_pub", "fecha", "no", DERIVADA,
     "Fecha de la captura mas reciente del aviso. Renombre de `fecha_captura` al armar el snapshot. "
     "Es la clave de la relacion activa con `dim_fecha`.")
_reg("fecha_captura", "fecha", "no", DERIVADA,
     "Dia de la captura, derivado del serial de Excel que lleva el primer campo de `__KEY_results`.")
_reg("__KEY_results", "texto", "no", CRUDO,
     "Clave de la captura, con forma `{serial}-{offset}-{categoria}-{indice}` "
     "(p.ej. `42316-0-MLA29483-200`). Se conserva para trazabilidad. **No ordenar como string**: "
     "el offset toma valores de 1 a 4 digitos, asi que `'800' > '1400'` lexicograficamente.")
_reg("version", "texto", "si", CRUDO, "Version del modelo segun los atributos del aviso.")

# --- Precio ---
_reg("price", "decimal", "no", CRUDO, "Precio en la moneda original (`currency_id`).")
_reg("price_ars", "decimal", "no", DERIVADA,
     "Precio normalizado a ARS. Si `currency_id = USD`, se multiplica por el dolar blue de `dim_FX`.")
_reg("price_ars_limpio", "decimal", "si", LIMPIA,
     "`price_ars` con **null si `precio_invalido` O `precio_outlier`**. Pensada para graficar "
     "directo: ninguna medida DAX necesita cruzarla con los flags. 489 nulls (7,4%).")
_reg("price_usd_oficial", "decimal", "si", DERIVADA,
     "`price_ars / usd_oficial`, null si `precio_invalido`. Ojo: a diferencia de la version "
     "`_limpio`, esta NO excluye outliers de capa 2.")
_reg("price_usd_oficial_limpio", "decimal", "si", LIMPIA, "`price_ars_limpio / usd_oficial`.")
_reg("price_usd_blue", "decimal", "si", DERIVADA, "`price_ars / usd_blue`, null si `precio_invalido`.")
_reg("price_usd_blue_limpio", "decimal", "si", LIMPIA, "`price_ars_limpio / usd_blue`.")

# --- Flags de capa 1 ---
_reg("precio_invalido", "booleano", "no", FLAG1,
     "Reglas de dominio sobre el precio. True si: `price` es nulo; o `currency_id = ARS` y "
     "`price <= 1000`; o `currency_id = USD` y `price <= 100`; o `price_ars` supera el techo "
     "dinamico `Q3_global + 5*IQR_global` (1.144.000 ARS en esta corrida). El techo se "
     "recalcula en cada corrida para no quedar obsoleto por la inflacion. "
     "Total: 1.579 filas (946 por piso, 633 por techo).")
_reg("km_invalido", "booleano", "no", FLAG1,
     "True si `kilometros` es nulo, negativo, esta entre 1 y 999 (typo: nadie vende un auto "
     "con 500 km reales a precio de usado) o supera 800.000.")
_reg("anio_invalido", "booleano", "no", FLAG1,
     "True si `anio` es nulo, menor a 1910, o mayor a `max(fecha_captura).year + 1` (2016). "
     "El limite sale de los datos, no del reloj del sistema.")

# --- Flags de capa 2 ---
_reg("precio_outlier", "booleano", "no", FLAG2,
     "Fence de Tukey (k=1,5) sobre `price_ars`, en dos niveles de referencia. "
     "**Tier 1**: grupo `(id_modelo, anio)` con al menos 8 avisos DISTINTOS. "
     "**Tier 2 (global)**: el resto de las filas validas en capa 1 — sin modelo/anio, o grupo "
     "sin muestra suficiente — contra la distribucion de toda la poblacion elegible "
     "(techo 589.961 ARS en esta corrida). Los cuartiles se calculan sobre un valor por aviso, "
     "no por captura. 390 avisos marcados.")
_reg("km_outlier", "booleano", "no", FLAG2,
     "Fence de Tukey (k=1,5) sobre `kilometros` por grupo `(id_modelo, anio)`. "
     "**Sin tier global**: un fence de km sobre toda la poblacion mezclaria model-anios, y un "
     "auto de 2005 legitimamente tiene mas km que uno de 2015. 154 avisos marcados.")

# --- Atributos normalizados ---
_reg("id_marca", "texto", "si", CRUDO, "FK a `dim_marca`. Null en los 514 avisos sin atributos.")
_reg("marca", "texto", "si", DIM, "Texto normalizado desde `dim_marca` (unica fuente de verdad).")
_reg("id_modelo", "texto", "si", CRUDO, "FK a `dim_modelo`.")
_reg("modelo", "texto", "si", DIM, "Texto normalizado desde `dim_modelo`.")
_reg("id_transmision", "texto", "si", CRUDO, "FK a `dim_transmision`.")
_reg("transmision", "texto", "si", DIM, "Texto normalizado desde `dim_transmision`.")
_reg("anio", "entero", "si", CRUDO, "Anio del modelo segun los atributos. Rango real: 1980-2016.")
_reg("anio_limpio", "entero", "si", LIMPIA, "`anio` con null si `anio_invalido`. 514 nulls (7,8%).")
_reg("kilometros", "entero", "si", CRUDO, "Kilometraje declarado.")
_reg("kilometros_limpio", "entero", "si", LIMPIA,
     "`kilometros` con null si `km_invalido` O `km_outlier`. 940 nulls (14,3%).")
_reg("sin_atributos", "booleano", "no", DERIVADA,
     "True en los 514 avisos (7,8%) que no tienen Marca/Modelo/Anio/Km en **ninguna** captura. "
     "No es un problema de orden de deduplicacion: el dato no existe. Se conservan en la tabla "
     "con esos campos en null, manteniendo precio y tendencia.")

# --- Rango de km ---
_reg("rango_km", "texto", "no", DERIVADA,
     "Categoria de kilometraje, calculada sobre `kilometros_limpio` (no el crudo), asi que un "
     "`km_outlier` cae en \"Sin dato\" igual que un `km_invalido`. "
     "**\"Más de 500.000 KM\" es inalcanzable con este dataset**: no hay ningun aviso con km "
     "entre 500.000 y 800.000 (el maximo valido es 490.000).")
_reg("orden_rango_km", "entero", "no", ORDEN,
     "1-7 para ordenar `rango_km` en Power BI. **Usar como \"Sort by column\" de `rango_km`**, "
     "si no se ordena alfabeticamente.")

# --- tabla_tendencias ---
_reg("obs_validas", "entero", "no", DERIVADA,
     "Cantidad de capturas con precio usable del aviso (excluye `precio_invalido` y "
     "`precio_outlier`). 0 si ninguna.")
_reg("precio_ini", "decimal", "si", DERIVADA, "`price_ars` de la primera captura valida, por fecha y clave de orden.")
_reg("precio_fin", "decimal", "si", DERIVADA, "`price_ars` de la ultima captura valida.")
_reg("variacion_pct", "decimal", "si", DERIVADA,
     "`(precio_fin - precio_ini) / precio_ini`. Null si no hay precio inicial usable.")
_reg("tendencia_precio", "texto", "no", DERIVADA,
     "Cinco categorias. `Subió` / `Bajó` si la variacion supera ±2% con al menos 2 "
     "observaciones; `Estable` si esta dentro de ±2% con al menos 2; "
     "**`Observación única`** si hay exactamente 1 observacion valida (el precio es valido pero "
     "no hay con que compararlo: 543 avisos, 8,2%); `Sin precio` si no hay ninguna.")
_reg("tendencia_medible", "booleano", "no", DERIVADA,
     "True para `Subió`/`Bajó`/`Estable`, o sea donde la variacion se pudo medir de verdad. "
     "**Es la columna sobre la que debe filtrar el dashboard** para el split de 3 vias: "
     "5.629 avisos (85,5%).")
_reg("orden_tendencia", "entero", "no", ORDEN,
     "1-5 para ordenar `tendencia_precio`. **\"Sort by column\" de `tendencia_precio`**.")

# --- Dimensiones ---
_reg("fecha", "fecha", "no", DERIVADA, "Dia del calendario. PK de `dim_fecha`.")
_reg("mes_num", "entero", "no", DERIVADA, "1-12.")
_reg("mes_nombre", "texto", "no", DERIVADA, "Nombre del mes en espanol.")
_reg("anio_mes", "texto", "no", DERIVADA, "`YYYY-MM`, para agrupar por mes manteniendo el orden.")
_reg("dia", "entero", "no", DERIVADA, "Dia del mes.")
_reg("dia_semana_num", "entero", "no", DERIVADA, "0 = lunes ... 6 = domingo.")
_reg("dia_semana_nombre", "texto", "no", DERIVADA, "Nombre del dia en espanol.")
_reg("fecha_fx", "fecha", "no", DERIVADA,
     "Fecha de la cotizacion: cierre del ultimo mes cerrado respecto de la ultima captura.")
_reg("usd_oficial", "decimal", "no", CRUDO, "Dolar oficial (venta) de la API de ArgentinaDatos.")
_reg("usd_blue", "decimal", "no", CRUDO,
     "Dolar blue (venta). Es el que se usa para normalizar los precios en USD a ARS.")
_reg("fuente_fx", "texto", "no", DERIVADA,
     "Origen del tipo de cambio: `api`, `override` (variables de entorno) o `fallback` "
     "(valores hardcodeados, solo con `ETL_FX_FALLBACK=1`). Deja el linaje visible en el "
     "modelo y no solo en el log.")


def _descripcion(tabla: str, columna: str):
    if columna == "anio" and tabla == "dim_fecha":
        return ("entero", "no", DERIVADA, "Anio del calendario.")
    if columna == "marca" and tabla == "dim_marca":
        return ("texto", "no", CRUDO, "Grafia normalizada: la **mas frecuente** por `value_id`, "
                                      "asi VENTO/Vento se resuelve sin diccionario de overrides.")
    if columna in ("modelo", "transmision") and tabla.startswith("dim_"):
        return ("texto", "no", CRUDO, "Grafia mas frecuente por `value_id`.")
    if columna in ("id_marca", "id_modelo", "id_transmision") and tabla.startswith("dim_"):
        return ("texto", "no", CRUDO, "PK de la dimension, el `value_id` de MercadoLibre.")
    return D.get(columna, ("", "", "", "_(sin descripcion)_"))


def generar() -> str:
    lineas = [
        "# Diccionario de datos",
        "",
        "> Generado por `scripts/generar_diccionario.py` desde `etl/schemas.py`. No editar a mano:",
        "> la lista de columnas sale del codigo, asi no puede divergir de lo que el ETL escribe.",
        "",
        "Las 8 tablas que el pipeline escribe en `data/processed/`, mas `_manifest.json` con el "
        "sha256 de cada una.",
        "",
        "**Convenciones:**",
        "",
        "- Las columnas `_limpio` son copias del valor crudo con **null si la fila es invalida "
        "(capa 1) O outlier (capa 2)**. Estan para graficar directo: ninguna medida DAX necesita "
        "combinar el valor crudo con uno o dos flags.",
        "- Los valores crudos y los flags se conservan intactos, asi que nada se pierde.",
        "- Capa 1 son reglas de dominio (un precio de $500 no es un auto). Capa 2 es estadistica "
        "(un precio que se sale de la distribucion de su modelo-anio).",
        "- Las columnas `orden_*` existen para la propiedad **\"Sort by column\"** de Power BI.",
        "",
    ]

    for tabla, columnas in schemas.ESQUEMAS.items():
        grano, pk = GRANO[tabla]
        lineas += [
            "---",
            "",
            "## `{}`".format(tabla),
            "",
            "**Grano:** {}  ".format(grano),
            "**PK:** `{}`  ".format(pk),
            "**Filas:** {} · **Columnas:** {}".format(FILAS_REALES[tabla], len(columnas)),
            "",
        ]
        if tabla in NOTAS_TABLA:
            lineas += [NOTAS_TABLA[tabla], ""]

        lineas += [
            "| Columna | Tipo | Nulos | Origen | Definicion |",
            "|---|---|---|---|---|",
        ]
        for columna in columnas:
            tipo, nullable, origen, definicion = _descripcion(tabla, columna)
            lineas.append("| `{}` | {} | {} | {} | {} |".format(columna, tipo, nullable, origen, definicion))
        lineas.append("")

    lineas += [
        "---",
        "",
        "## Parametros del pipeline",
        "",
        "Todos en `etl/config.py`.",
        "",
        "| Parametro | Valor | Que controla |",
        "|---|---|---|",
        "| `PRECIO_INVALIDO_ARS_MIN` | {} | Piso de precio en ARS (capa 1) |".format(config.PRECIO_INVALIDO_ARS_MIN),
        "| `PRECIO_INVALIDO_USD_MIN` | {} | Piso de precio en USD (capa 1) |".format(config.PRECIO_INVALIDO_USD_MIN),
        "| `TECHO_GLOBAL_K` | {} | Multiplicador del techo dinamico `Q3 + k*IQR` (capa 1) |".format(config.TECHO_GLOBAL_K),
        "| `KM_TYPO_MAX` | {} | Por debajo de esto (y sobre 0) el km se considera typo |".format(config.KM_TYPO_MAX),
        "| `KM_MAX_REAL` | {:,} | Km maximo plausible |".format(config.KM_MAX_REAL),
        "| `ANIO_MIN` | {} | Anio minimo plausible |".format(config.ANIO_MIN),
        "| `IQR_GROUP_K` | {} | Fence de Tukey por grupo `(id_modelo, anio)` (capa 2, tier 1) |".format(config.IQR_GROUP_K),
        "| `IQR_GLOBAL_K` | {} | Fence de Tukey del tier global (capa 2, tier 2) |".format(config.IQR_GLOBAL_K),
        "| `IQR_MIN_AVISOS` | {} | Avisos **distintos** minimos para que un grupo se juzgue en tier 1 |".format(config.IQR_MIN_AVISOS),
        "| `IQR_COLAPSAR_POR_AVISO` | {} | Cuartiles sobre un valor por aviso, no por captura |".format(config.IQR_COLAPSAR_POR_AVISO),
        "| `TENDENCIA_UMBRAL` | {} | Banda de \"Estable\" (±2%) |".format(config.TENDENCIA_UMBRAL),
        "",
    ]
    return "\n".join(lineas) + "\n"


def main() -> None:
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(generar(), encoding="utf-8", newline="\n")
    total = sum(len(c) for c in schemas.ESQUEMAS.values())
    print("Escrito {} ({} tablas, {} columnas)".format(SALIDA, len(schemas.ESQUEMAS), total))


if __name__ == "__main__":
    main()
