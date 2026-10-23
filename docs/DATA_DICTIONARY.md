# Diccionario de datos

> Generado por `scripts/generar_diccionario.py` desde `etl/schemas.py`. No editar a mano:
> la lista de columnas sale del codigo, asi no puede divergir de lo que el ETL escribe.

Las 8 tablas que el pipeline escribe en `data/processed/`, mas `_manifest.json` con el sha256 de cada una.

**Convenciones:**

- Las columnas `_limpio` son copias del valor crudo con **null si la fila es invalida (capa 1) O outlier (capa 2)**. Estan para graficar directo: ninguna medida DAX necesita combinar el valor crudo con uno o dos flags.
- Los valores crudos y los flags se conservan intactos, asi que nada se pierde.
- Capa 1 son reglas de dominio (un precio de $500 no es un auto). Capa 2 es estadistica (un precio que se sale de la distribucion de su modelo-anio).
- Las columnas `orden_*` existen para la propiedad **"Sort by column"** de Power BI.

---

## `fact_publicaciones`

**Grano:** 1 fila por aviso (snapshot de la captura mas reciente)  
**PK:** `id_publicacion`  
**Filas:** 6.586 · **Columnas:** 36

| Columna | Tipo | Nulos | Origen | Definicion |
|---|---|---|---|---|
| `id_publicacion` | texto | no | crudo | PK del aviso. Renombre de `id_u9` del CSV crudo. |
| `title` | texto | no | crudo | Titulo que escribio el vendedor. |
| `permalink` | texto | no | crudo | URL del aviso en MercadoLibre. |
| `condition` | texto | no | crudo | Condicion declarada (`used` en todo el dataset). |
| `currency_id` | texto | no | crudo | Moneda del precio publicado: `ARS` (124.148 filas) o `USD` (363). |
| `category_id` | texto | no | crudo | Categoria de MercadoLibre (`MLA29483`, autos usados). |
| `listing_type_id` | texto | no | crudo | Tipo de publicacion (`gold_premium`, etc.). |
| `accepts_mercadopago` | booleano | no | crudo | **Sin varianza en este snapshot**: es `False` en las 124.511 filas crudas, asi que no lleva informacion. Se conserva por fidelidad al origen, y el detector de varianza cero de `validate` la reporta en cada corrida. |
| `stop_time` | datetime | no | crudo | Fin de la publicacion. Llega hasta 2016-02-19, fuera del rango de `dim_fecha`. Cambia en el 25,7% de los avisos: el vendedor puede renovar. |
| `fecha_pub` | fecha | no | derivada | Fecha de la captura mas reciente del aviso. Renombre de `fecha_captura` al armar el snapshot. Es la clave de la relacion activa con `dim_fecha`. |
| `price` | decimal | no | crudo | Precio en la moneda original (`currency_id`). |
| `price_ars` | decimal | no | derivada | Precio normalizado a ARS. Si `currency_id = USD`, se multiplica por el dolar blue de `dim_FX`. |
| `price_ars_limpio` | decimal | si | derivada _limpio | `price_ars` con **null si `precio_invalido` O `precio_outlier`**. Pensada para graficar directo: ninguna medida DAX necesita cruzarla con los flags. 489 nulls (7,4%). |
| `price_usd_oficial` | decimal | si | derivada | `price_ars / usd_oficial`, null si `precio_invalido`. Ojo: a diferencia de la version `_limpio`, esta NO excluye outliers de capa 2. |
| `price_usd_oficial_limpio` | decimal | si | derivada _limpio | `price_ars_limpio / usd_oficial`. |
| `price_usd_blue` | decimal | si | derivada | `price_ars / usd_blue`, null si `precio_invalido`. |
| `price_usd_blue_limpio` | decimal | si | derivada _limpio | `price_ars_limpio / usd_blue`. |
| `precio_invalido` | booleano | no | flag capa 1 | Reglas de dominio sobre el precio. True si: `price` es nulo; o `currency_id = ARS` y `price <= 1000`; o `currency_id = USD` y `price <= 100`; o `price_ars` supera el techo dinamico `Q3_global + 5*IQR_global` (1.144.000 ARS en esta corrida). El techo se recalcula en cada corrida para no quedar obsoleto por la inflacion. Total: 1.579 filas (946 por piso, 633 por techo). |
| `precio_outlier` | booleano | no | flag capa 2 | Fence de Tukey (k=1,5) sobre `price_ars`, en dos niveles de referencia. **Tier 1**: grupo `(id_modelo, anio)` con al menos 8 avisos DISTINTOS. **Tier 2 (global)**: el resto de las filas validas en capa 1 — sin modelo/anio, o grupo sin muestra suficiente — contra la distribucion de toda la poblacion elegible (techo 589.961 ARS en esta corrida). Los cuartiles se calculan sobre un valor por aviso, no por captura. 390 avisos marcados. |
| `id_marca` | texto | si | crudo | FK a `dim_marca`. Null en los 514 avisos sin atributos. |
| `marca` | texto | si | normalizada desde dim | Texto normalizado desde `dim_marca` (unica fuente de verdad). |
| `id_modelo` | texto | si | crudo | FK a `dim_modelo`. |
| `modelo` | texto | si | normalizada desde dim | Texto normalizado desde `dim_modelo`. |
| `id_transmision` | texto | si | crudo | FK a `dim_transmision`. |
| `transmision` | texto | si | normalizada desde dim | Texto normalizado desde `dim_transmision`. |
| `anio` | entero | si | crudo | Anio del modelo segun los atributos. Rango real: 1980-2016. |
| `anio_limpio` | entero | si | derivada _limpio | `anio` con null si `anio_invalido`. 514 nulls (7,8%). |
| `kilometros` | entero | si | crudo | Kilometraje declarado. |
| `kilometros_limpio` | entero | si | derivada _limpio | `kilometros` con null si `km_invalido` O `km_outlier`. 940 nulls (14,3%). |
| `version` | texto | si | crudo | Version del modelo segun los atributos del aviso. |
| `km_invalido` | booleano | no | flag capa 1 | True si `kilometros` es nulo, negativo, esta entre 1 y 999 (typo: nadie vende un auto con 500 km reales a precio de usado) o supera 800.000. |
| `anio_invalido` | booleano | no | flag capa 1 | True si `anio` es nulo, menor a 1910, o mayor a `max(fecha_captura).year + 1` (2016). El limite sale de los datos, no del reloj del sistema. |
| `km_outlier` | booleano | no | flag capa 2 | Fence de Tukey (k=1,5) sobre `kilometros` por grupo `(id_modelo, anio)`. **Sin tier global**: un fence de km sobre toda la poblacion mezclaria model-anios, y un auto de 2005 legitimamente tiene mas km que uno de 2015. 154 avisos marcados. |
| `rango_km` | texto | no | derivada | Categoria de kilometraje, calculada sobre `kilometros_limpio` (no el crudo), asi que un `km_outlier` cae en "Sin dato" igual que un `km_invalido`. **"Más de 500.000 KM" es inalcanzable con este dataset**: no hay ningun aviso con km entre 500.000 y 800.000 (el maximo valido es 490.000). |
| `orden_rango_km` | entero | no | columna de orden | 1-7 para ordenar `rango_km` en Power BI. **Usar como "Sort by column" de `rango_km`**, si no se ordena alfabeticamente. |
| `sin_atributos` | booleano | no | derivada | True en los 514 avisos (7,8%) que no tienen Marca/Modelo/Anio/Km en **ninguna** captura. No es un problema de orden de deduplicacion: el dato no existe. Se conservan en la tabla con esos campos en null, manteniendo precio y tendencia. |

---

## `fact_precios_historicos`

**Grano:** 1 fila por captura de precio  
**PK:** `id_publicacion + __KEY_results`  
**Filas:** 124.511 · **Columnas:** 9

**Nunca se deriva de la tabla deduplicada.** Las dos tablas de hechos se ramifican de `results_base` sin deduplicar; el dedup se aplica solo al armar el snapshot de `fact_publicaciones`. Las 124.511 filas son capturas, no avisos: mediana de 14 capturas por aviso, maximo 70.

| Columna | Tipo | Nulos | Origen | Definicion |
|---|---|---|---|---|
| `id_publicacion` | texto | no | crudo | PK del aviso. Renombre de `id_u9` del CSV crudo. |
| `fecha_captura` | fecha | no | derivada | Dia de la captura, derivado del serial de Excel que lleva el primer campo de `__KEY_results`. |
| `__KEY_results` | texto | no | crudo | Clave de la captura, con forma `{serial}-{offset}-{categoria}-{indice}` (p.ej. `42316-0-MLA29483-200`). Se conserva para trazabilidad. **No ordenar como string**: el offset toma valores de 1 a 4 digitos, asi que `'800' > '1400'` lexicograficamente. |
| `price` | decimal | no | crudo | Precio en la moneda original (`currency_id`). |
| `currency_id` | texto | no | crudo | Moneda del precio publicado: `ARS` (124.148 filas) o `USD` (363). |
| `price_ars` | decimal | no | derivada | Precio normalizado a ARS. Si `currency_id = USD`, se multiplica por el dolar blue de `dim_FX`. |
| `price_ars_limpio` | decimal | si | derivada _limpio | `price_ars` con **null si `precio_invalido` O `precio_outlier`**. Pensada para graficar directo: ninguna medida DAX necesita cruzarla con los flags. 489 nulls (7,4%). |
| `precio_invalido` | booleano | no | flag capa 1 | Reglas de dominio sobre el precio. True si: `price` es nulo; o `currency_id = ARS` y `price <= 1000`; o `currency_id = USD` y `price <= 100`; o `price_ars` supera el techo dinamico `Q3_global + 5*IQR_global` (1.144.000 ARS en esta corrida). El techo se recalcula en cada corrida para no quedar obsoleto por la inflacion. Total: 1.579 filas (946 por piso, 633 por techo). |
| `precio_outlier` | booleano | no | flag capa 2 | Fence de Tukey (k=1,5) sobre `price_ars`, en dos niveles de referencia. **Tier 1**: grupo `(id_modelo, anio)` con al menos 8 avisos DISTINTOS. **Tier 2 (global)**: el resto de las filas validas en capa 1 — sin modelo/anio, o grupo sin muestra suficiente — contra la distribucion de toda la poblacion elegible (techo 589.961 ARS en esta corrida). Los cuartiles se calculan sobre un valor por aviso, no por captura. 390 avisos marcados. |

---

## `tabla_tendencias`

**Grano:** 1 fila por aviso  
**PK:** `id_publicacion`  
**Filas:** 6.586 · **Columnas:** 8

Filtrar por `tendencia_medible` para el split de 3 vias del dashboard: da un denominador honesto de 5.629 avisos. Los 957 no medibles (543 `Observación única` + 414 `Sin precio`) se reportan aparte.

| Columna | Tipo | Nulos | Origen | Definicion |
|---|---|---|---|---|
| `id_publicacion` | texto | no | crudo | PK del aviso. Renombre de `id_u9` del CSV crudo. |
| `obs_validas` | entero | no | derivada | Cantidad de capturas con precio usable del aviso (excluye `precio_invalido` y `precio_outlier`). 0 si ninguna. |
| `precio_ini` | decimal | si | derivada | `price_ars` de la primera captura valida, por fecha y clave de orden. |
| `precio_fin` | decimal | si | derivada | `price_ars` de la ultima captura valida. |
| `variacion_pct` | decimal | si | derivada | `(precio_fin - precio_ini) / precio_ini`. Null si no hay precio inicial usable. |
| `tendencia_precio` | texto | no | derivada | Cinco categorias. `Subió` / `Bajó` si la variacion supera ±2% con al menos 2 observaciones; `Estable` si esta dentro de ±2% con al menos 2; **`Observación única`** si hay exactamente 1 observacion valida (el precio es valido pero no hay con que compararlo: 543 avisos, 8,2%); `Sin precio` si no hay ninguna. |
| `tendencia_medible` | booleano | no | derivada | True para `Subió`/`Bajó`/`Estable`, o sea donde la variacion se pudo medir de verdad. **Es la columna sobre la que debe filtrar el dashboard** para el split de 3 vias: 5.629 avisos (85,5%). |
| `orden_tendencia` | entero | no | columna de orden | 1-5 para ordenar `tendencia_precio`. **"Sort by column" de `tendencia_precio`**. |

---

## `dim_marca`

**Grano:** 1 fila por marca  
**PK:** `id_marca`  
**Filas:** 3 · **Columnas:** 2

| Columna | Tipo | Nulos | Origen | Definicion |
|---|---|---|---|---|
| `id_marca` | texto | no | crudo | PK de la dimension, el `value_id` de MercadoLibre. |
| `marca` | texto | no | crudo | Grafia normalizada: la **mas frecuente** por `value_id`, asi VENTO/Vento se resuelve sin diccionario de overrides. |

---

## `dim_modelo`

**Grano:** 1 fila por modelo  
**PK:** `id_modelo`  
**Filas:** 3 · **Columnas:** 2

| Columna | Tipo | Nulos | Origen | Definicion |
|---|---|---|---|---|
| `id_modelo` | texto | no | crudo | PK de la dimension, el `value_id` de MercadoLibre. |
| `modelo` | texto | no | crudo | Grafia mas frecuente por `value_id`. |

---

## `dim_transmision`

**Grano:** 1 fila por tipo de transmision  
**PK:** `id_transmision`  
**Filas:** 3 · **Columnas:** 2

| Columna | Tipo | Nulos | Origen | Definicion |
|---|---|---|---|---|
| `id_transmision` | texto | no | crudo | PK de la dimension, el `value_id` de MercadoLibre. |
| `transmision` | texto | no | crudo | Grafia mas frecuente por `value_id`. |

---

## `dim_fecha`

**Grano:** 1 fila por dia del periodo de captura  
**PK:** `fecha`  
**Filas:** 73 · **Columnas:** 8

Cubre 2015-10-10 a 2015-12-21, el periodo de captura. **No cubre `stop_time`**, que llega hasta 2016-02-19: el 44% de los `stop_time` no tiene fila en esta dimension. Las relaciones del modelo usan `fecha_pub` (activa) y `fecha_captura` (inactiva), asi que no hay relacion rota, pero no se puede cortar "publicaciones que vencen por mes" por el calendario.

| Columna | Tipo | Nulos | Origen | Definicion |
|---|---|---|---|---|
| `fecha` | fecha | no | derivada | Dia del calendario. PK de `dim_fecha`. |
| `anio` | entero | no | derivada | Anio del calendario. |
| `mes_num` | entero | no | derivada | 1-12. |
| `mes_nombre` | texto | no | derivada | Nombre del mes en espanol. |
| `anio_mes` | texto | no | derivada | `YYYY-MM`, para agrupar por mes manteniendo el orden. |
| `dia` | entero | no | derivada | Dia del mes. |
| `dia_semana_num` | entero | no | derivada | 0 = lunes ... 6 = domingo. |
| `dia_semana_nombre` | texto | no | derivada | Nombre del dia en espanol. |

---

## `dim_FX`

**Grano:** 1 fila: la cotizacion usada en la corrida  
**PK:** `fecha_fx`  
**Filas:** 1 · **Columnas:** 4

Una sola cotizacion para todo el periodo, no una serie diaria. Es la de cierre del ultimo mes cerrado respecto de la ultima captura (noviembre 2015).

| Columna | Tipo | Nulos | Origen | Definicion |
|---|---|---|---|---|
| `fecha_fx` | fecha | no | derivada | Fecha de la cotizacion: cierre del ultimo mes cerrado respecto de la ultima captura. |
| `usd_oficial` | decimal | no | crudo | Dolar oficial (venta) de la API de ArgentinaDatos. |
| `usd_blue` | decimal | no | crudo | Dolar blue (venta). Es el que se usa para normalizar los precios en USD a ARS. |
| `fuente_fx` | texto | no | derivada | Origen del tipo de cambio: `api`, `override` (variables de entorno) o `fallback` (valores hardcodeados, solo con `ETL_FX_FALLBACK=1`). Deja el linaje visible en el modelo y no solo en el log. |

---

## Parametros del pipeline

Todos en `etl/config.py`.

| Parametro | Valor | Que controla |
|---|---|---|
| `PRECIO_INVALIDO_ARS_MIN` | 1000 | Piso de precio en ARS (capa 1) |
| `PRECIO_INVALIDO_USD_MIN` | 100 | Piso de precio en USD (capa 1) |
| `TECHO_GLOBAL_K` | 5 | Multiplicador del techo dinamico `Q3 + k*IQR` (capa 1) |
| `KM_TYPO_MAX` | 1000 | Por debajo de esto (y sobre 0) el km se considera typo |
| `KM_MAX_REAL` | 800,000 | Km maximo plausible |
| `ANIO_MIN` | 1910 | Anio minimo plausible |
| `IQR_GROUP_K` | 1.5 | Fence de Tukey por grupo `(id_modelo, anio)` (capa 2, tier 1) |
| `IQR_GLOBAL_K` | 1.5 | Fence de Tukey del tier global (capa 2, tier 2) |
| `IQR_MIN_AVISOS` | 8 | Avisos **distintos** minimos para que un grupo se juzgue en tier 1 |
| `IQR_COLAPSAR_POR_AVISO` | True | Cuartiles sobre un valor por aviso, no por captura |
| `TENDENCIA_UMBRAL` | 0.02 | Banda de "Estable" (±2%) |

