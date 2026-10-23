# Challenge BI MercadoLibre Autos — Documento de Diseño del ETL en Python

> ## ⚠️ Nota de versión — auditoría de 2026-10-23
>
> Este documento es el **diseño original** del ETL y se conserva como anexo histórico. Después
> de escribirlo se hizo una auditoría del pipeline que corrigió varias cosas, así que algunas
> partes de abajo describen el comportamiento *anterior*. Lo que cambió:
>
> | Sección | Qué cambió |
> |---|---|
> | 3.2 | `fact_publicaciones` tiene **36** columnas, no 35 (la lista enumerada siempre tuvo 36; el encabezado estaba mal). `tabla_tendencias` pasó de 6 a 8 columnas (`tendencia_medible`, `orden_tendencia`). `dim_FX` pasó de 3 a 4 (`fuente_fx`). |
> | 3.3 | Relación nueva (la 8ª): `fact_publicaciones[fecha_stop] → dim_fecha[fecha]`, N:1, **inactiva** (se activa con `USERELATIONSHIP` para "publicaciones que vencen por mes"). `fecha_pub` sigue siendo la activa. |
> | 3.2 / 6 | `dim_fecha` pasa de 73 a 133 filas y de 8 a 9 columnas (`es_periodo_captura`): el calendario ahora llega hasta el último `stop_time` (2016-02-19) y no solo hasta el fin del scrapeo. Antes el 44% de los `stop_time` no tenía fila en la dimensión. `fact_publicaciones` suma `fecha_stop` y queda en 37 columnas. |
> | 5.1 | `anio_invalido` ya no usa `datetime.now()`: el umbral se deriva de `max(fecha_captura).year + 1`. |
> | 5.2 | Capa 2 tiene ahora **dos niveles de referencia**. Los avisos sin modelo/año (y los grupos sin muestra mínima) se juzgan contra un fence global, porque antes no podían marcarse nunca. Los cuartiles se calculan sobre **un valor por aviso**, no por captura. |
> | 5.5 | `tendencia_precio` tiene 5 categorías: se agregó `Observación única` para los 543 avisos con una sola observación válida, que antes caían en `Estable`. |
> | 5.6 | El orden de deduplicación usa las tres claves numéricas de `__KEY_results`, no el string. |
> | 6 | La salida son 8 CSVs **más** `_manifest.json` (filas, columnas, bytes y sha256 por tabla). |
> | 7.1 | Las validaciones son excepciones explícitas, no `assert` (con `python -O` se salteaba todo el gate). |
>
> La referencia column-by-column al día está en [DATA_DICTIONARY.md](DATA_DICTIONARY.md), que se
> genera desde `etl/schemas.py`. El antes/después medido de cada corrección está en el
> [README](../README.md#data-quality-audit).


> Documento técnico para llevar a una sesión de VS Code. Contiene contexto, decisiones de diseño, reglas de negocio, especificación del pipeline y validaciones. Todo lo que aparece acá debería traducirse directamente a código.

> **ETL implementado y corriendo.** Este documento fue auditado contra los CSVs reales y corregido para reflejar lo que efectivamente se construyó (varios supuestos del diseño original no se sostenían — ver notas "🔧 Corregido" en cada sección). Código en `challenge_bi/` (correr con `python3 main.py` desde ahí, venv + `requirements.txt`). Auditoría de calidad de datos con el antes/después medido de cada corrección: ver el [README](../README.md#data-quality-audit). **Lo único que falta es la parte de Power BI** (sección 8): cargar los 8 CSVs de `challenge_bi/data/processed/` y armar el `.pbix`.

---

## 1. Contexto del challenge

**Objetivo del ejercicio:** construir un dashboard de Power BI sobre publicaciones de autos usados scrapeadas de MercadoLibre Argentina. El consigna explícita incluye:

> 🔧 **Corregido tras auditar los datos:** el dataset NO tiene "~113k avisos". `results.csv` tiene 124,511 *capturas* (snapshots de scraping) entre 2015-10-10 y 2015-12-21, pero sólo **6,586 avisos únicos** (`id_u9`), capturados en promedio ~19 veces cada uno (mediana 14, máximo 70). El "113k" venía de confundir capturas con avisos — y de hecho corresponde casi exactamente a las 113,299 capturas que tienen al menos un atributo en `attributes.csv`. Además, `category_id` resultó ser 1:1 con modelo: las 3 categorías presentes (`MLA29483`, `MLA29500`, `MLA29561`) son exactamente VW Vento, Citroën Xsara Picasso y Suzuki Fun — el dataset es un scrape dirigido a esos 3 modelos puntuales, no una muestra general del mercado. El "buscador por Marca/Modelo" del punto 1 de abajo va a tener sólo 3x3 combinaciones posibles.

1. Búsqueda por Marca, Modelo, Año, Kilometraje, Transmisión, Versión, etc.
2. Categorizar autos por rango de kilometraje (0 KM / <25k / 25-50k / 50-100k / 100-500k / >500k)
3. Identificar avisos que subieron / bajaron / se mantuvieron / no tuvieron precio
4. Dolarizar al tipo de cambio del último día del último mes cerrado
5. Diseño visual basado en el look & feel de MercadoLibre

**Entregables esperados:**
- Documentación técnica de los QVDs (Word)
- Documentación del ETL (este tipo de documento + código)
- Dashboard Power BI (.pbix)
- Documento de metodología

**Capacidades que se evaluan:**
- Análisis del origen de datos (qué sirve y qué no)
- Limpieza de outliers
- Clasificación en rangos
- Comparaciones entre registros
- Integración con fuente externa para conversión de moneda

---

## 2. Inventario de datos crudos

Los CSVs están en Google Drive (carpeta `Challenge BI/Challenge for Claude/ETL Python/CSVs/`). Delimitador `;`, encoding UTF-8 con BOM (`utf-8-sig`) 🔧.

### 2.1 `results.csv` — publicaciones (124,511 filas, 40 MB)

Es la tabla de hechos principal. Una fila por **captura de scraping** (no por aviso) — confirmado: 124,511 filas, pero sólo 6,586 `id_u9` (avisos) distintos.

> 🔧 Encoding real: el archivo tiene BOM (`utf-8-sig`), no UTF-8 simple — hay que leerlo con esa codificación o el primer header (`__KEY_results`) sale con basura adelante.

| Columna | Tipo | Descripción |
|---|---|---|
| `__KEY_results` | string | ID de la captura. Formato `{serial_fecha}-{página}-MLA29483-{posición}`. El primer bloque es un serial de fecha (días desde 1899-12-30 estilo Excel). |
| `id_u9` | string | ID del aviso en MercadoLibre. **Es el identificador real del aviso, no de la captura.** Se mantiene entre capturas del mismo aviso. Lo renombraremos a `id_publicacion`. |
| `title` | string | Título del aviso |
| `price` | number | Precio en la moneda nativa |
| `currency_id` | string | "ARS" o "USD" (~400 avisos están en USD) |
| `condition` | string | 🔧 3 valores reales: `used` (99,634), `not_specified` (23,431, ~19%), `new` (1,446) — no sólo "new"/"used" |
| `stop_time` | datetime | Fecha de fin de publicación. Formato `MM/dd/yyyy HH:mm:ss` (en-US) |
| `accepts_mercadopago` | bool | Acepta MercadoPago |
| `listing_type_id` | string | Tipo de aviso |
| `category_id` | string | Categoría |
| `permalink` | string | URL al aviso real (útil para tooltip/acción en dashboard) |
| `thumbnail` | string | URL de imagen (probablemente 404, fechas de 2015) |
| `original_price`, `subtitle`, `installments`, `official_store_id` | string | Vienen con "-" como placeholder. Se descartan o se normalizan a null. |
| `available_quantity`, `sold_quantity`, `buying_mode`, `site_id`, `__KEY_root` | varios | No aportan al análisis. Se descartan. |

**Observación clave:** el mismo `id_u9` aparece en múltiples filas con `__KEY_results` distintos (capturas en distintas fechas). Esto es la base para la serie temporal de precios.

### 2.2 `attributes.csv` — atributos del auto (662k filas, 59 MB)

Tabla en formato largo (atributo-valor). Una fila por `(captura, atributo)`.

| Columna | Tipo | Descripción |
|---|---|---|
| `__KEY_results` | string | Identifica la captura |
| `attribute_group_id` | string | Siempre "FIND" |
| `attribute_group_name` | string | Siempre "Ficha técnica" |
| `id_u8` | string | ID del tipo de atributo (ej. `MLA1744-MARC`) |
| `name_u6` | string | Nombre del atributo: "Marca", "Modelo", "Año", "Kilómetros", "Transmisión", "Versión" |
| `value_id` | string | ID del valor en el catálogo de MercadoLibre. 🔧 Sólo Kilómetros viene 100% vacío. Marca/Modelo lo tienen siempre; Transmisión en 73% de sus filas; y, a diferencia de lo que se pensaba, **Año (99.5%) y Versión (77%) también lo tienen casi siempre** — no es exclusivo de los atributos categóricos. No se usa hoy en el ETL (Año/Versión se toman de `value_name`), pero deja abierta la puerta a normalizar Versión por catálogo en el futuro. |
| `value_name` | string | Valor en texto: "Volkswagen", "Vento", "2011", etc. |

**Distribución real (662,469 filas en total):**
- De las 124,511 capturas de `results.csv`, sólo 113,299 (91%) tienen *alguna* fila en `attributes.csv` — **11,212 capturas (9%) no tienen ningún atributo**, algo que no estaba documentado.
- De esas 113,299 capturas con atributos: 92.2% tienen los 6 atributos completos, 7.5% tienen 4 (sin Versión y Transmisión), 0.2% tienen 5.
- 🔧 A nivel de **aviso** (no captura), esto se traduce en **514 avisos (7.8% de los 6,586) que no tienen Marca/Modelo/Año/Km en NINGUNA de sus capturas** — no es un problema de qué captura se elige al deduplicar, el dato simplemente no existe para esos avisos. Verificado: los 514 sí tienen `title` (100% de cobertura en todo el dataset), así que quedan visibles en el dashboard con precio y tendencia, sólo sin filtros de marca/modelo/año/km (`fact_publicaciones.sin_atributos = True`).

**Observación clave:** una vez pivotada (de largo a ancho), cada `__KEY_results` debería tener 1 fila con 6 columnas. Hay grafías inconsistentes ("VENTO": 107 filas vs "Vento": 81,177 filas, el único caso en todo el dataset) que se resuelven tomando la grafía **más frecuente** por `value_id` — más robusto que "la primera que aparece", que depende del orden del CSV.

### 2.3 Tablas geográficas — DESCARTADAS

`location.csv`, `state.csv`, `city.csv`, `neighborhood.csv`, `country.csv` parecían ser para enriquecer con info geográfica. Pero al investigar:

- `__KEY_location` resultó ser un identificador de **página de scraping**, no de ubicación geográfica
- Los campos esperables (lat, long, address, neighborhood_name) están vacíos
- No hay forma confiable de relacionarlas con `results.csv` a nivel de aviso

**Decisión documentada:** se descartan. Este es un hallazgo de calidad de datos que se reporta como tal. El dashboard no incluirá filtros geográficos.

> 🔧 **Confirmado con datos:** `__KEY_location` tiene sólo 200 valores distintos para 124,511 filas (cada uno compartido por ~700 filas), y cada valor mapea a ~80 ciudades *distintas* en `city.csv`. Es matemáticamente imposible que sea un ID de ubicación real — es un ID de página/lote de scraping, como se sospechaba. El descarte queda confirmado, no es necesario revisar esta decisión.

### 2.4 `seller_contact.csv` — datos de contacto del vendedor

Granularidad por captura (`__KEY_results`). Útil si se quisiera enriquecer con info del vendedor, pero opcional para el dashboard. Por ahora no se carga al modelo.

---

## 3. Modelo destino

```
                    dim_marca       dim_modelo      dim_transmision
                       ↘               ↓               ↙
                              fact_publicaciones ◄── dim_fecha
                 (1 fila/aviso, atributos integrados)         ↑
                              ↓                               │
                       fact_precios_historicos ◄──────────────┘
                          (1 fila/captura)
                              ↓
                        tabla_tendencias
                          (1 fila/aviso)

                    dim_FX (escalar)
                    Selector_Moneda (desconectada)
                    _Medidas (tabla virtual con DAX)
```

### 3.1 Tablas que carga Power BI

| Tabla | Grano | Filas reales | Origen |
|---|---|---|---|
| `fact_publicaciones` | 1 fila por aviso (`id_publicacion`) | **6,586** 🔧 (no ~113k) | Captura más reciente de cada aviso + atributos del auto |
| `fact_precios_historicos` | 1 fila por captura | **124,511** | Todas las capturas, columnas para serie temporal |
| `dim_marca` | catálogo | 3 (Volkswagen, Suzuki, Citroën) | Groupby directo sobre attributes.csv (sin pivot) |
| `dim_modelo` | catálogo | 3 (Vento, Fun, Xsara Picasso) | Idem |
| `dim_transmision` | catálogo | 3 (Manual, Automática, Secuencial) | Idem |
| `dim_fecha` | calendario | 73 (2015-10-10 a 2015-12-21) | Generado |
| `dim_FX` | 1 fila escalar | 1 | API ArgentinaDatos |
| `tabla_tendencias` | 1 fila por aviso | **6,586** 🔧 (no ~113k) | Calculado a partir de `fact_precios_historicos` |
| `Selector_Moneda` | desconectada | 3 | DATATABLE en DAX — pendiente, parte de Power BI |

### 3.2 Columnas detalladas

> 🔧 Columnas reales tal como salen en `data/processed/*.csv` (verificado contra la cabecera de cada archivo).

**`fact_publicaciones`** (37 columnas) 🔧 *el encabezado decía 35 cuando la lista tenía 36; la auditoría sumó además `fecha_stop`*:
- `id_publicacion` (PK) ← renombre de `id_u9`
- `title`, `permalink` 🔧 (se agregó, el doc original lo recomendaba como útil pero no lo listaba acá), `condition`, `currency_id`, `category_id`, `listing_type_id`, `accepts_mercadopago`
- `stop_time` (datetime), `fecha_pub` (date = fecha_captura más reciente)
- `price` (precio en moneda original)
- `price_ars` (precio normalizado a ARS), `price_ars_limpio` 🔧
- `price_usd_oficial`, `price_usd_oficial_limpio` 🔧, `price_usd_blue`, `price_usd_blue_limpio` 🔧 (dolarizado)
- `precio_invalido` (bool, capa 1 — piso + techo dinámico, ver 5.1)
- `precio_outlier` (bool, capa 2 — IQR sobre toda la serie histórica, ver 5.2)
- `id_marca`, `marca` (ID + texto normalizado desde dim)
- `id_modelo`, `modelo`
- `id_transmision`, `transmision`
- `anio`, `anio_limpio` 🔧, `kilometros`, `kilometros_limpio` 🔧, `version`
- `km_invalido`, `anio_invalido` (capa 1)
- `km_outlier` (capa 2 - IQR)
- `rango_km`, `orden_rango_km` (categoría según consigna + columna de orden)
- `sin_atributos` 🔧 (bool, nueva — True para los 514 avisos sin Marca/Modelo/Año/Km en ninguna captura)

> 🔧 **Columnas `_limpio` (agregado 2026-06-28):** `kilometros_limpio`, `anio_limpio`, `price_ars_limpio`, `price_usd_oficial_limpio`, `price_usd_blue_limpio` son copias de su columna cruda con `null` en las filas que la capa 1 (inválido) **o** la capa 2 (outlier) marcaron — pensadas para graficar directo en Power BI sin tener que combinar el valor crudo con 1-2 flags en cada medida DAX. Los valores crudos y los flags se mantienen intactos, esto es 100% adición. Ver `outliers.agregar_columnas_limpias` y `transform_results.dolarizar`. Cobertura real: `price_ars_limpio` 427 nulls (6.5%), `kilometros_limpio` 940 (14.3%), `anio_limpio` 514 (7.8%) — exactamente la suma de inválido + outlier de cada capa, porque ambas capas nunca se superponen en la misma fila (`precio_outlier`/`km_outlier` sólo se calculan sobre filas ya válidas en capa 1).

**`fact_precios_historicos`** (9 columnas):
- `id_publicacion`
- `fecha_captura`
- `__KEY_results` (para trazabilidad y deduplicación dentro de fecha)
- `price`, `currency_id`, `price_ars`, `price_ars_limpio` 🔧 (null si `precio_invalido` o `precio_outlier` — útil para el gráfico de evolución de precio sin que un outlier rompa la escala)
- `precio_invalido` (capa 1)
- `precio_outlier` 🔧 (bool, columna NUEVA respecto al diseño original — capa 2 calculada sobre toda la serie histórica, no sólo el snapshot; ver 5.2)

**`dim_marca`**: `id_marca`, `marca`
**`dim_modelo`**: `id_modelo`, `modelo`
**`dim_transmision`**: `id_transmision`, `transmision`

**`dim_fecha`**: `fecha`, `anio`, `mes_num`, `mes_nombre`, `anio_mes`, `dia`, `dia_semana_num`, `dia_semana_nombre`

**`dim_FX`**: `fecha_fx`, `usd_oficial`, `usd_blue`

**`tabla_tendencias`**: `id_publicacion`, `obs_validas`, `precio_ini`, `precio_fin`, `variacion_pct`, `tendencia_precio`

### 3.3 Relaciones

| Desde | Hasta | Tipo | Activa |
|---|---|---|---|
| `fact_publicaciones[id_marca]` | `dim_marca[id_marca]` | N:1 | Sí |
| `fact_publicaciones[id_modelo]` | `dim_modelo[id_modelo]` | N:1 | Sí |
| `fact_publicaciones[id_transmision]` | `dim_transmision[id_transmision]` | N:1 | Sí |
| `tabla_tendencias[id_publicacion]` | `fact_publicaciones[id_publicacion]` | 1:1 | Sí |
| `fact_precios_historicos[id_publicacion]` | `fact_publicaciones[id_publicacion]` | N:1 | Sí |
| `fact_publicaciones[fecha_pub]` | `dim_fecha[fecha]` | N:1 | Sí |
| `fact_precios_historicos[fecha_captura]` | `dim_fecha[fecha]` | N:1 | **No** (inactiva — evita ambigüedad) |

La última se activa en DAX con `USERELATIONSHIP` cuando se necesita para análisis temporal de la serie histórica.

---

## 4. Pipeline ETL paso a paso

### 4.1 Estructura del proyecto

```
challenge_bi/
├── etl/
│   ├── __init__.py
│   ├── config.py              # rutas, parámetros
│   ├── extract.py             # lectura de CSVs
│   ├── transform_results.py   # transformaciones de results
│   ├── transform_attrs.py     # pivot de attributes
│   ├── fx.py                  # llamada a ArgentinaDatos
│   ├── outliers.py            # capas 1 y 2 de outliers
│   ├── tendencias.py          # cálculo de tendencias
│   ├── dimensions.py          # generación de dims
│   ├── load.py                # escritura de CSVs finales
│   └── validate.py            # asserts y métricas
├── data/
│   ├── raw/                   # CSVs originales (referenciados, no copiados)
│   └── processed/             # CSVs de salida
├── notebooks/                 # 🔧 vacía — el diagnóstico del duplicado quedó
│                               #    cubierto por transform_results.diagnostico_duplicados()
│                               #    y el reporte de consola, no se hizo el notebook
├── tests/
│   └── test_etl.py            # 22 tests (unitarios + 1 integración con muestra real)
├── main.py                    # punto de entrada — python3 main.py
├── requirements.txt           # pandas, numpy, requests, pytest
├── .venv/                     # 🔧 creado, no estaba en el original
├── .gitignore                 # 🔧 creado
└── README.md                  # 🔧 resumen de la corrida + decisiones, para retomar
```

### 4.2 Flujo del pipeline (en orden)

> 🔧 **Reescrito completo** — el orden original (pivotear todo `attributes.csv`, calcular outliers sólo en `fact_publicaciones`) se cambió tras la auditoría. Esto es lo que efectivamente corre en `challenge_bi/main.py`:

```
1. EXTRACT
   ├─ Leer results.csv (utf-8-sig, columnas minimas)
   ├─ Leer attributes.csv (utf-8-sig, columnas minimas)
   └─ parse_basico(results) → id_publicacion, stop_time, fecha_captura
        (esto va ANTES de llamar a la API: hace falta max(fecha_captura)
        para saber que mes cerrado pedirle al FX)

2. TRANSFORM
   ├─ fx.get_fx(fecha_max) → oficial + blue del ultimo dia de noviembre 2015
   │
   ├─ results_base = TODAS las 124,511 capturas, sin deduplicar (nunca se
   │    sobreescribe con una version deduplicada en todo el pipeline)
   │    ├─ price_ars (USD × FX_blue; ARS sin cambios)
   │    └─ precio_invalido = piso (<=1000 ARS / <=100 USD) OR
   │                          techo dinamico global (Q3+5*IQR de price_ars
   │                          de esta misma corrida, ver 5.1)
   │
   ├─ dim_marca, dim_modelo, dim_transmision
   │    └─ groupby DIRECTO sobre attributes.csv en formato largo (SIN pivot),
   │         grafia = value_name MAS FRECUENTE por value_id (no "la primera")
   │
   ├─ atributos_pivot (optimizado — sólo ~36k filas, no 662k)
   │    ├─ Sobre results_base, elegir la captura ganadora por aviso
   │    │    (mismo criterio determinístico de 5.6) — esto da las claves
   │    │    __KEY_results candidatas ANTES de tocar attributes.csv
   │    ├─ Filtrar attributes.csv a esas ~6,586 claves (semi-join)
   │    ├─ Pivotear SÓLO ese subconjunto filtrado (dual: value_name + value_id)
   │    └─ Join con dim_marca/modelo/transmision para texto normalizado
   │
   ├─ Broadcast de atributos sobre results_base
   │    └─ Join id_marca/id_modelo/id_transmision/anio/kilometros/version desde
   │         atributos_pivot a TODAS las capturas del mismo aviso (por
   │         id_publicacion) — se repite en cada captura, es correcto porque
   │         son atributos del auto, no de la captura
   │
   ├─ outliers — UNA sola vez sobre results_base completo (124,511 filas),
   │    ANTES de ramificar a fact_publicaciones/fact_precios_historicos
   │    ├─ km_invalido, anio_invalido (capa 1, por fila)
   │    └─ IQR por (id_modelo, anio), capa 2 — gate = avisos DISTINTOS >= 8
   │         (no filas, para no inflar la muestra con capturas repetidas)
   │         ├─ price_ars → precio_outlier (toda la serie historica)
   │         └─ kilometros → km_outlier
   │
   ├─ fact_publicaciones (dedup de results_base, 6,586 filas)
   │    ├─ Deduplicar results_base por id_publicacion (mismo criterio de 5.6)
   │    ├─ sin_atributos = True para avisos sin match en atributos_pivot
   │    ├─ Calcular rango_km + orden_rango_km
   │    ├─ Dolarizar (price_usd_oficial, price_usd_blue)
   │    └─ VALIDAR: id_publicacion único
   │
   ├─ fact_precios_historicos (subset de results_base, SIN deduplicar, 124,511 filas)
   │    └─ id_publicacion, fecha_captura, __KEY_results, price, currency_id,
   │         price_ars, precio_invalido, precio_outlier
   │
   ├─ tabla_tendencias
   │    ├─ Agrupar fact_precios_historicos por id_publicacion, filtrando
   │    │    precio_invalido=False Y precio_outlier=False 🔧 (filtro nuevo)
   │    ├─ Primer y último precio en orden temporal
   │    ├─ Calcular variacion_pct
   │    └─ Etiquetar tendencia (Subió/Bajó/Estable/Sin precio)
   │
   └─ dim_fecha
        └─ Calendario sobre el rango de fecha_captura (2015-10-10 a 2015-12-21)

3. VALIDATE
   ├─ id_publicacion único en fact_publicaciones
   ├─ id_marca/modelo/transmision en fact siempre tienen match en dim
   ├─ Conteo de filas: 6,586 en fact_publicaciones (🔧 no ~113k)
   ├─ Tasa de outliers/inválidos por categoría
   ├─ Diagnóstico de duplicados (avisos con >1 captura, intra-día, etc.)
   └─ Reporte de cobertura de FX

4. LOAD
   └─ Escribir 8 CSVs en data/processed/ (utf-8 sin BOM, delimitador ,)
```

---

## 5. Reglas de negocio explícitas

### 5.1 Capa 1 de outliers — Reglas de dominio (flags, no se borran filas)

**`precio_invalido`** (en results_base y fact_publicaciones):
```python
piso_invalido = (
    price is None
    or (currency_id == "ARS" and price <= 1000)
    or (currency_id == "USD" and price <= 100)
)
```

> 🔧 **Agregado: techo dinámico.** El piso solo no alcanza — encontramos avisos con `price` = `1111111111`, `123456789`, `99999999`, `87654321`, etc. (placeholders/jokes de vendedores, casi siempre con título "Vendido" o "A consultar"). Un techo fijo en ARS se vuelve obsoleto con la inflación, así que se calcula dinámicamente sobre la propia distribución de `price_ars` de cada corrida (sólo filas que ya pasaron el piso):
> ```python
> q1_g, q3_g = price_ars_validas.quantile([0.25, 0.75])
> techo_global = q3_g + 5 * (q3_g - q1_g)   # k=5, deliberadamente generoso
> precio_invalido = piso_invalido or ((not piso_invalido) and price_ars > techo_global)
> ```
> En la corrida real esto dio un techo de ~1.144.000 ARS, marcando 633 filas (56 avisos) — verificado uno por uno, todos placeholders, sin falsos positivos. Como se recalcula cada vez, si el dataset se reprocesa con precios nominales mucho más altos el techo sube solo.

**`km_invalido`** (en fact_publicaciones):
```python
km_invalido = (
    kilometros is None
    or kilometros < 0
    or (kilometros > 0 and kilometros < 1000)  # típico typo de digitar mal el km
    or kilometros > 800000  # casi ningún auto pasa de 800k km reales
)
```

**`anio_invalido`** (en fact_publicaciones):
```python
anio_invalido = (
    anio is None
    or anio < 1910
    or anio > datetime.now().year + 1
)
```

### 5.2 Capa 2 de outliers — IQR por grupo

Se calcula sobre filas con `precio_invalido = False` y `km_invalido = False`. Grupo: `(id_modelo, anio)`. Método: Tukey con `k=1.5`.

```python
def calc_iqr_bounds(serie, k=1.5):
    q1 = serie.quantile(0.25)
    q3 = serie.quantile(0.75)
    iqr = q3 - q1
    return q1 - k*iqr, q3 + k*iqr
```

Aplicar a:
- `price_ars` → `precio_outlier`
- `kilometros` → `km_outlier`

Si el grupo tiene < 8 **avisos distintos** (no filas — ver nota abajo), no se calcula IQR (el flag queda en `False` por defecto — no hay base para juzgar outlier).

**Importante:** el flag se marca pero la fila no se elimina. Las medidas DAX deciden si excluyen o no según contexto.

> 🔧 **Cambio de fondo: se calcula sobre `results_base` completo (toda la serie histórica de precios), no sólo sobre el snapshot de `fact_publicaciones`, y el resultado se persiste en AMBAS tablas** (`precio_outlier` ahora también vive en `fact_precios_historicos`, ver 3.2). Esto resuelve un problema real: calculando sólo sobre el snapshot (~6,586 avisos repartidos en 45 grupos modelo+año), el 26.7% de los grupos quedaban sin muestra mínima. Usando toda la historia de precios para estimar Q1/Q3 (sin cambiar el gate, que sigue contando avisos distintos para no caer en pseudo-replicación — un auto visto 20 veces sigue siendo 1 sola observación independiente, no 20), las estimaciones de Q1/Q3 son más precisas para los grupos que sí califican. En la corrida real: 42 grupos modelo+año, 9 sin muestra mínima, 5,793 capturas marcadas `precio_outlier` en total.
>
> Por la misma razón, `tabla_tendencias` (ver 5.5) ahora también filtra `precio_outlier = False`, no sólo `precio_invalido = False` — si no, un valor que pasó la capa 1 pero es un outlier estadístico podría generar una "tendencia" artificial.

### 5.3 Dolarización

**API:** `https://api.argentinadatos.com/v1/cotizaciones/dolares/{casa}` donde casa ∈ {`oficial`, `blue`}.

**Fecha de referencia:** último día del último mes COMPLETO antes de `max(fact.fecha_captura)`. El dataset real llega hasta 2015-12-21 (no hasta fin de mes), así que el último mes completo es noviembre 2015. 🔧 Confirmado contra la API real: noviembre 2015 tiene cobertura diaria completa (30/30 días) tanto en oficial como en blue, con la misma fecha final (2015-11-30) en ambas — no hace falta el fallback de tomar el `min` entre las dos. Resultado real de esta corrida: **oficial $10.00, blue $15.00 al 2015-11-30**.

**Valor:** se toma `venta` (no compra). Es lo defendible para una conversión de precios de mercado.

**Aplicación:**
- `price_ars`: si `currency_id == "USD"`, multiplicar por `FX_blue`. Si es ARS, queda igual.
- `price_usd_oficial`: `price_ars / FX_oficial` (excepto si inválido)
- `price_usd_blue`: `price_ars / FX_blue` (excepto si inválido)

### 5.4 Categorización por kilometraje

```python
def categoria_km(km, km_invalido):
    if km_invalido:
        return "Sin dato"
    if km == 0:
        return "0 KM"
    if km < 25_000:
        return "Menos de 25.000 KM"
    if km < 50_000:
        return "De 25.000 a 50.000 KM"
    if km < 100_000:
        return "De 50.000 a 100.000 KM"
    if km < 500_000:
        return "De 100.000 a 500.000 KM"
    return "Más de 500.000 KM"
```

Hay que crear también una columna `orden_rango_km` (1-7) para que Power BI ordene la categoría correctamente (no alfabéticamente).

> 🔧 **Corregido (2026-06-29):** `categoria_km` se llama con `kilometros_limpio` (no el km crudo), así que `km_invalido` arriba en realidad combina capa 1 (inválido) **y** capa 2 (`km_outlier`) — un km que es outlier estadístico para su grupo modelo+año también cae en "Sin dato", no sólo los inválidos por regla de dominio. Antes de este fix, los 154 avisos con `km_outlier=True` quedaban clasificados en un rango real. Resultado real: "Sin dato" pasó de 786 a 940 avisos (7.8% → 14.3%).

### 5.5 Tendencias de precio

Calculadas sobre `fact_precios_historicos` filtrando `precio_invalido = False` 🔧 **Y `precio_outlier = False`** (ver nota en 5.2 — evita que un outlier estadístico genere una "tendencia" artificial).

```python
def clasificar_tendencia(precio_ini, precio_fin, obs_validas, umbral=0.02):
    if obs_validas == 0 or precio_ini is None or precio_ini == 0:
        return "Sin precio"
    variacion = (precio_fin - precio_ini) / precio_ini
    if abs(variacion) <= umbral:
        return "Estable"
    return "Subió" if variacion > 0 else "Bajó"
```

`precio_ini` y `precio_fin` se obtienen ordenando por `fecha_captura` ASC. Si hay varias capturas en la misma fecha, tomar la primera/última por `__KEY_results` para que sea determinístico.

> 🔧 **El ejemplo `MLA581616315` citado en el doc original NO es un duplicado intra-día real** — se verificó: tiene 45 capturas, todas en fechas distintas. El ejemplo correcto (uno de los 10 avisos reales con duplicado intra-día) es `MLA583896358`: dos capturas el 2015-11-08 (`__KEY_results` = `42316-0-MLA29483-200` y `42316-200-MLA29483-1`, mismo precio 170.000). Resultado real de tendencias: Subió 1,070 (16.2%), Bajó 283 (4.3%), Estable 4,881 (74.1%), Sin precio 352 (5.3%).

### 5.6 Deduplicación por captura más reciente

**Criterio determinístico para `fact_publicaciones` y para `atributos_pivot`:**

```python
df_sorted = df.sort_values(
    ['fecha_captura', '__KEY_results'],
    ascending=[False, False]
)
df_dedup = df_sorted.drop_duplicates(subset=['id_publicacion'], keep='first')
```

Esto garantiza:
- Si hay capturas en fechas distintas: se elige la más reciente
- Si hay capturas en la misma fecha: se elige la del `__KEY_results` "mayor" (segmento de scraping posterior)
- Resultado reproducible: corriendo el ETL dos veces, sale lo mismo

**Antes de deduplicar, registrar:**
- Cantidad total de filas en `results_base`
- Cantidad de `id_publicacion` únicos
- Cantidad de avisos con > 1 captura
- Cantidad de avisos con > 1 captura en la misma fecha (los "duplicados intra-día")
- Tope de capturas por aviso (máximo, mediana)

Eso permite documentar el comportamiento del scraper y justificar la elección.

> 🔧 **Números reales de esta corrida:** 124,511 filas totales, 6,586 `id_publicacion` únicos, 6,019 avisos con >1 captura, **10 avisos con duplicado intra-día** (ejemplos: `MLA580575432`, `MLA582386054`, `MLA583896358`, `MLA586355367`, `MLA586724363`), máximo 70 capturas por aviso, mediana 14, promedio 18.9.

### 5.7 Normalización de atributos

**Pivot dual, sólo sobre las capturas ganadoras:**
- 🔧 Antes de pivotear, se determina la captura ganadora por aviso sobre `results_base` (mismo criterio de 5.6) y se filtra `attributes.csv` a esas ~6,586 claves — de 662,469 a ~36,000 filas. Pivotear todo y deduplicar después (como decía el diseño original) es ~18x más trabajo para el mismo resultado.
- `pivot_nombres`: pivot del `value_name` (texto legible), sobre el subconjunto filtrado
- `pivot_ids`: pivot del `value_id` solo para Marca, Modelo, Transmisión (los que tienen catálogo), sobre el mismo subconjunto

**Join entre los dos** por `__KEY_results`. Quedan en una sola tabla con columnas:
`__KEY_results`, `marca` (texto), `modelo` (texto), `transmision` (texto), `anio`, `kilometros`, `version`, `id_marca`, `id_modelo`, `id_transmision`.

**dim_marca, dim_modelo, dim_transmision:**
- 🔧 Se construyen aparte, con un `groupby` directo sobre `attributes.csv` completo en formato largo (sin pivotear nada, ni siquiera el subconjunto filtrado) — más simple y no depende del orden de filas del CSV.
- Por cada `value_id`, se toma el `value_name` **más frecuente** (no "el primero que aparece"). Único caso real en el dataset: `MLA1744-MODL-VENTO` tiene "Vento" (81,177 filas) y "VENTO" (107 filas) — gana "Vento" automáticamente, sin necesitar diccionario de overrides manual (ver Q3 en sección 9, resuelta).

**fact_publicaciones lee el texto normalizado de las dims:** después del join con `atributos_pivot`, se hace otro join con `dim_marca/modelo/transmision` por ID, y se reemplazan las columnas de texto con la versión de la dim. Single source of truth.

### 5.8 Nomenclatura

- Todo en **snake_case ASCII** desde el inicio
- Sin tildes ni ñ en nombres de columnas (`anio` no `año`, `transmision` no `transmisión`)
- IDs y columnas con prefijos consistentes:
  - `id_*` para claves
  - `fecha_*` para fechas
  - `price_*` para precios numéricos
  - `precio_*` para flags de precio
  - `km_*` para kilometraje

---

## 6. Outputs esperados

Los CSVs se escriben en `data/processed/` con encoding UTF-8 y delimitador `,`. Power BI los carga sin transformación adicional.

🔧 Tabla con las filas reales de la corrida (no las estimadas originalmente):

| Archivo | Filas reales |
|---|---|
| `fact_publicaciones.csv` | 6,586 |
| `fact_precios_historicos.csv` | 124,511 |
| `dim_marca.csv` | 3 |
| `dim_modelo.csv` | 3 |
| `dim_transmision.csv` | 3 |
| `dim_fecha.csv` | 73 |
| `dim_FX.csv` | 1 |
| `tabla_tendencias.csv` | 6,586 |

---

## 7. Validaciones del ETL (asserts y métricas)

Estas son las verificaciones que el script ejecuta antes de escribir los CSVs. Si alguna falla, el ETL aborta con un mensaje claro.

### 7.1 Asserts duros (rompen si fallan)

```python
# Unicidad
assert fact_publicaciones['id_publicacion'].is_unique, "id_publicacion duplicado en fact"
assert dim_marca['id_marca'].is_unique
assert dim_modelo['id_modelo'].is_unique
assert dim_transmision['id_transmision'].is_unique

# Integridad referencial
assert fact_publicaciones['id_marca'].dropna().isin(dim_marca['id_marca']).all()
assert fact_publicaciones['id_modelo'].dropna().isin(dim_modelo['id_modelo']).all()
assert fact_publicaciones['id_transmision'].dropna().isin(dim_transmision['id_transmision']).all()

# fact_precios apunta a avisos que existen
assert fact_precios_historicos['id_publicacion'].isin(fact_publicaciones['id_publicacion']).all()
assert tabla_tendencias['id_publicacion'].isin(fact_publicaciones['id_publicacion']).all()

# FX cargado
assert dim_FX.shape[0] == 1, "dim_FX debería tener exactamente 1 fila"
assert dim_FX['usd_oficial'].notna().iloc[0]
assert dim_FX['usd_blue'].notna().iloc[0]
```

### 7.2 Métricas a reportar (info, no rompen)

🔧 Esto es lo que imprime de verdad `main.py` al final de la corrida (corrida real sobre el dataset completo, 2026-06-27):

```
=== ETL completado ===

Origen:
  results.csv:        124,511 filas leidas
  attributes.csv:     662,469 filas leidas

Diagnostico de duplicados (results_base, antes de deduplicar):
  Filas totales:                124,511
  id_publicacion unicos:        6,586
  Promedio capturas/aviso:      18.9
  Mediana capturas/aviso:       14
  Maximo capturas/aviso:        70
  Avisos con > 1 captura misma fecha: 10
  Ejemplos: ['MLA580575432', 'MLA582386054', 'MLA583896358', 'MLA586355367', 'MLA586724363']

Capa 1 - precio (piso + techo dinamico global):
  Invalidos por piso:           946
  Techo dinamico esta corrida:  1,144,000 ARS
  Invalidos por techo:          633
  Total precio_invalido:        1,579

Capa 2 - outliers IQR por grupo (id_modelo, anio):
  precio_outlier: 5,793 filas marcadas (9 de 42 grupos sin muestra minima)
  km_outlier:     3,465 filas marcadas (9 de 42 grupos sin muestra minima)

fact_publicaciones: 6,586 filas
  - con precio valido:     6,487 (98.5%)
  - con km valido:         5,800 (88.1%)
  - con anio valido:       6,072 (92.2%)
  - outliers precio (IQR): 328 (5.0%)
  - outliers km (IQR):     154 (2.3%)
  - sin atributos:         514 (7.8%)
fact_precios_historicos:   124,511 filas

Columnas limpias (nulls = invalido capa 1 OR outlier capa 2):
  price_ars_limpio: 427 (6.5%)
  kilometros_limpio: 940 (14.3%)
  anio_limpio: 514 (7.8%)

Tendencias:
  Subió: 1,070 (16.2%)
  Bajó: 283 (4.3%)
  Estable: 4,881 (74.1%)
  Sin precio: 352 (5.3%)

Marcas unicas:      3
Modelos unicos:     3
Transmisiones:      3
Rango fechas:       2015-10-10 a 2015-12-21

FX al 2015-11-30:
  Oficial: $10.00
  Blue:    $15.00

Duracion: 4.3 segundos
```

### 7.3 Diagnóstico del duplicado

Antes de aplicar el `drop_duplicates`, el script imprime (`transform_results.diagnostico_duplicados`, integrado en el reporte de 7.2 arriba):

```
Filas totales:                124,511
id_publicacion unicos:        6,586
Promedio capturas/aviso:      18.9
Mediana capturas/aviso:       14
Maximo capturas/aviso:        70
Avisos con > 1 captura misma fecha: 10
Ejemplos: ['MLA580575432', 'MLA582386054', 'MLA583896358', 'MLA586355367', 'MLA586724363']
```

Esto valida que la deduplicación tiene sentido. 🔧 El aviso `MLA581616315` mencionado en versiones anteriores de este documento como "el caso problemático" **no es un duplicado intra-día real** (tiene 45 capturas, todas en fechas distintas) — el ejemplo correcto es `MLA583896358` (dos capturas el 2015-11-08, ver 5.5/5.6).

---

## 8. Plan de Power BI

Una vez generados los CSVs, Power BI hace lo mínimo:

### 8.1 Cargar

`Inicio → Obtener datos → Texto/CSV` y conectar uno por uno los 8 archivos de `data/processed/`. Power BI detecta los tipos automáticamente. **Sin transformaciones en Power Query** — los CSVs ya vienen limpios.

### 8.2 Configurar el modelo

- Marcar `dim_fecha` como tabla de fechas (columna `fecha`)
- Definir las 7 relaciones de la sección 3.3
- Configurar las columnas que necesitan `sort_by`:
  - `rango_km` ordena por `orden_rango_km`
  - `Selector_Moneda[Moneda]` ordena por `Selector_Moneda[Orden]`

### 8.3 Crear tabla virtual de medidas

Una tabla calculada vacía llamada `_Medidas` (en DAX: `_Medidas = DATATABLE("_", STRING, {{""}})`), oculta la columna, y se vuelcan todas las medidas DAX ahí. Es el patrón estándar.

### 8.4 Crear Selector_Moneda

En DAX:
```dax
Selector_Moneda = DATATABLE(
    "Moneda", STRING,
    "Orden", INTEGER,
    {
        {"ARS", 1},
        {"USD Oficial", 2},
        {"USD Blue", 3}
    }
)
```

### 8.5 Medidas DAX

(Las que ya tenemos definidas en el documento de medidas. Se copian tal cual al `_Medidas`.)

---

## 9. Open questions — 🔧 todas resueltas, dejo la decisión final tomada

**Q1: ¿Usar `pandas` puro o `polars`?**
- ✅ **Resuelto: pandas.** 124,511 filas × 662,469 filas de atributos corren en ~4.3 segundos end-to-end (con la optimización de filtrar antes de pivotear, ver 5.7). No hizo falta evaluar polars.

**Q2: ¿Qué hacer con avisos donde la marca/modelo/transmisión es null?**
- ✅ **Resuelto, y es más grande de lo que parecía:** no es sólo el 7,5% sin Versión — son **514 avisos (7.8%) sin NINGÚN atributo** (ni Marca, ni Modelo, ni Año, ni Km) en ninguna de sus capturas. Quedan en `fact_publicaciones` con esos campos en null, `rango_km = "Sin dato"` y la columna nueva `sin_atributos = True`. Todos tienen `title` válido (100% de cobertura confirmada), así que siguen visibles en el dashboard con precio y tendencia.

**Q3: ¿Override manual de grafías?**
- ✅ **Resuelto sin necesitar diccionario.** Se cambió la regla de "primera grafía que aparece" a "grafía más frecuente por `value_id`". Único caso real: Vento (81,177) vs VENTO (107) — gana Vento automáticamente. No hizo falta el `OVERRIDES = {...}` manual.

**Q4: ¿`fecha_pub` en fact_publicaciones es la fecha de captura más reciente o la fecha de publicación original?**
- ✅ **Resuelto como se proponía:** `fecha_pub` = fecha de captura más reciente. Validado además que `stop_time` cambia en 25.7% de los avisos (el vendedor puede renovar), lo que confirma que tomar la captura más reciente es la elección correcta.

**Q5: ¿Cómo manejar la API de FX si falla (sin internet, timeout)?**
- ✅ **Resuelto como se proponía** (`etl/fx.py`): timeout 10s, retry 2 veces, fallback a oficial=10.0/blue=15.0 (último valor real conocido del dataset) con warning en el log si falla. En esta corrida la API respondió bien, no se usó el fallback.

**Q6: ¿Logueo a archivo o solo a consola?**
- ✅ **Resuelto: ambos.** Consola + `etl.log` siempre (no quedó como "opcional", se deja siempre activo — es gratis y ayuda a debuggear corridas pasadas).

**Q7: ¿Encoding de salida UTF-8 con BOM o sin BOM?**
- ✅ **Resuelto: sin BOM**, como se proponía. Nota aparte: los CSVs de *entrada* (`results.csv`, `attributes.csv`) sí tienen BOM (`utf-8-sig`), hay que leerlos con esa codificación.

**Q8: ¿Tests unitarios?**
- ✅ **Resuelto, 22 tests en `tests/test_etl.py`:** unitarios para `categoria_km`, `clasificar_tendencia`, `calc_iqr_bounds`, `calcular_precio_invalido` (piso+techo), `deduplicar_por_aviso`, y el gate de muestra mínima de IQR (avisos distintos vs filas). Más 1 test de integración que corre el pipeline completo sobre una muestra real de 80 avisos (no sintética) y valida los asserts y los CSVs de salida.

---

## 10. Cronograma de implementación sugerido

🔧 Pasos 1-13 (todo el ETL en Python) están **hechos** y corriendo en `challenge_bi/`. Lo único pendiente es Power BI (14-15).

| Paso | Estado |
|---|---|
| 1. Setup proyecto (`config.py`, estructura, requirements) | ✅ Hecho |
| 2. `extract.py` con lectura de CSVs | ✅ Hecho |
| 3. `fx.py` con llamada a API | ✅ Hecho |
| 4. `transform_attrs.py` (dims por groupby + pivot optimizado) | ✅ Hecho |
| 5. `transform_results.py` con base + flags | ✅ Hecho |
| 6. `outliers.py` con IQR por grupo sobre toda la serie histórica | ✅ Hecho |
| 7. Diagnóstico del duplicado | ✅ Hecho (vía reporte de consola, no notebook) |
| 8. Ensamblaje `fact_publicaciones` + dedup | ✅ Hecho |
| 9. `fact_precios_historicos` + `tendencias.py` | ✅ Hecho |
| 10. `dimensions.py` (dims + dim_fecha) | ✅ Hecho |
| 11. `validate.py` con asserts y métricas | ✅ Hecho |
| 12. `main.py` orquestador | ✅ Hecho |
| 13. README, requirements y tests (22 tests) | ✅ Hecho |
| **14. Cargar en Power BI nuevo (.pbix limpio)** | ⏳ **Pendiente — próxima sesión** |
| **15. Medidas DAX y dashboard** | ⏳ **Pendiente — próxima sesión** |

Para retomar: los 8 CSVs ya están generados en `challenge_bi/data/processed/`. Si se vuelven a tocar los CSVs crudos o el código, correr `python3 main.py` desde `challenge_bi/` (con el venv activado) para regenerarlos antes de recargar en Power BI.

---

## 11. Resumen ejecutivo

✅ Lo que se hizo en Python (`challenge_bi/`, correr con `python3 main.py`):
- Leer 2 CSVs grandes (results: 124,511 filas + attributes: 662,469 filas)
- Llamar 2 endpoints de API (FX oficial + blue) → $10.00 / $15.00 al 2015-11-30
- Construir dims por `groupby` directo (sin pivot) + pivotear atributos sólo de las capturas ganadoras (~36k filas, no 662k)
- Deduplicar por `id_publicacion` con criterio determinístico (fecha + key descendente) → 124,511 capturas en **6,586 avisos únicos**
- Flagear outliers en dos capas (dominio + techo dinámico, e IQR por grupo sobre toda la serie histórica de precios)
- Calcular tendencias temporales (filtrando inválidos Y outliers)
- Generar 8 CSVs limpios en `data/processed/`
- Validar todo con asserts antes de escribir + 22 tests automatizados

⏳ Lo que falta hacer en Power BI (próxima sesión):
- Cargar los 8 CSVs de `challenge_bi/data/processed/` sin transformación
- Definir las 7 relaciones de la sección 3.3
- Crear `Selector_Moneda` y `_Medidas` (sección 8.3/8.4)
- Cargar las medidas DAX
- Construir el dashboard (3 páginas: Buscador, Análisis, Evolución) — recordar que el "Buscador" sólo tiene 3 marcas x 3 modelos (ver corrección en sección 1)
