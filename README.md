# Challenge BI — ETL MercadoLibre Autos

Pipeline en Python que transforma los CSVs crudos de `results.csv` / `attributes.csv` (scrape de MercadoLibre Argentina, autos usados) en los 8 CSVs que carga el dashboard de Power BI.

Diseño completo y hallazgos de la auditoría de datos: ver `/Users/Santi/.claude/plans/hola-calude-necesito-que-greedy-sparkle.md` y `Challenge_BI_Diseno_ETL_Python.md` (documento original).

## Setup

```bash
cd challenge_bi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Correr el ETL

```bash
source .venv/bin/activate
python3 main.py
```

Lee `../CSVs/results.csv` y `../CSVs/attributes.csv`, llama a la API de [ArgentinaDatos](https://argentinadatos.com/) para el tipo de cambio, y escribe 8 CSVs en `data/processed/`. Imprime un reporte de métricas y corre los asserts de integridad antes de escribir.

## Tests

```bash
source .venv/bin/activate
python3 -m pytest tests/ -v
```

Incluye tests unitarios de las funciones de negocio (`categoria_km`, `clasificar_tendencia`, `calc_iqr_bounds`, dedup determinístico, gate de muestra mínima de IQR) y un test de integración que corre el pipeline completo sobre una muestra real de 80 avisos.

## Resultado real (corrida sobre el dataset completo)

| Tabla | Filas |
|---|---|
| `fact_publicaciones` | 6,586 |
| `fact_precios_historicos` | 124,511 |
| `tabla_tendencias` | 6,586 |
| `dim_marca` / `dim_modelo` / `dim_transmision` | 3 / 3 / 3 |
| `dim_fecha` | 73 (2015-10-10 a 2015-12-21) |
| `dim_FX` | 1 (oficial $10.00 / blue $15.00 al 2015-11-30) |

## Decisiones de diseño no obvias

- **`fact_precios_historicos` nunca se deriva de la tabla deduplicada.** Ambas tablas (`fact_publicaciones` y `fact_precios_historicos`) se ramifican desde `results_base` sin deduplicar; el dedup sólo se aplica al construir el snapshot de `fact_publicaciones`.
- **La capa 2 de outliers (IQR) corre una sola vez, sobre toda la serie histórica de precios**, antes de ramificar — no por separado en cada tabla. El umbral mínimo de 8 observaciones cuenta avisos distintos, no filas, para no inflar la muestra con capturas repetidas del mismo auto.
- **El techo de precio inválido es dinámico** (`Q3_global + 5*IQR_global`, recalculado en cada corrida), no un número fijo en ARS — así no queda obsoleto por la inflación. Ver `transform_results.calcular_precio_invalido`.
- **`attributes.csv` (662k filas) nunca se pivotea completo.** Las dimensiones se construyen con `groupby` directo sobre el formato largo, y `atributos_pivot` filtra primero a las ~6k claves "ganadoras" por aviso antes de pivotear.
- **514 avisos (7.8%) no tienen Marca/Modelo/Año/Km en ninguna captura** (no es un problema de orden de deduplicación, el dato no existe). Quedan en `fact_publicaciones` con esos campos en null y `sin_atributos=True`, conservando precio y tendencia.
- **Columnas "limpias" para graficar sin tocar los flags.** Además de los valores crudos y los flags, `fact_publicaciones` tiene `kilometros_limpio`, `anio_limpio`, `price_ars_limpio`, `price_usd_oficial_limpio`, `price_usd_blue_limpio`; `fact_precios_historicos` tiene `price_ars_limpio`. Quedan en `null` si la fila es inválida (capa 1) **o** outlier (capa 2) — nunca hace falta cruzar con los flags en una medida DAX. Ver `outliers.agregar_columnas_limpias`. Cobertura real: `price_ars_limpio` 427 nulls (6.5%), `kilometros_limpio` 940 (14.3%), `anio_limpio` 514 (7.8%).
- **`rango_km` se calcula sobre `kilometros_limpio`, no sobre el km crudo.** Así un `km_outlier` (capa 2, 154 avisos) cae en "Sin dato" igual que un `km_invalido` (capa 1) — antes sólo se excluían los inválidos y los outliers quedaban clasificados en un rango real. Ver `transform_results.agregar_rango_km`.
- **Las columnas `_limpio` se agregaron intercaladas junto a su columna cruda, no al final.** Esto corrió de posición a `rango_km` y todo lo que venía después, y rompió el refresh de conexiones de Power BI ya creadas (el paso "Origen" de Power Query cachea la cantidad de columnas). Decisión consciente: por ahora se deja así y el fix es del lado de Power BI (editar `Columns=N` en el paso Origen, o borrar y reconectar la consulta) — no se reordenó el ETL para no tener que tocar más cosas a la vez.

## Pendiente / fuera de alcance de este ETL

- `notebooks/diagnostico.ipynb` (exploración del duplicado) — el diagnóstico ya está cubierto por `transform_results.diagnostico_duplicados()` y el reporte de consola; no se generó el notebook.
- Documentación Word de QVDs y documento de metodología (entregables de la sección 1 del documento original) — no forman parte de este repo de código.
- Construcción del `.pbix` y medidas DAX (sección 8 del documento original).
