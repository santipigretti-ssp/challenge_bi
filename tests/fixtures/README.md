# Fixture de test

Muestra chica, determinista y anonimizada del scrape real. Es con esto que corren
`pytest` y CI, para que la suite funcione en un clon limpio sin los ~100 MB de CSVs
crudos (que viven fuera del repo) y sin tocar la red.

| Archivo | Filas | Tamaño |
|---|---|---|
| `results_sample.csv` | 3.306 capturas de 161 avisos | 557 KB |
| `attributes_sample.csv` | 17.398 | 954 KB |

Se regenera con `python scripts/generar_fixture.py`, que necesita los CSVs crudos y una
corrida previa del ETL completo (de ahí saca los flags para estratificar). `random_state=42`
en cada estrato, así la salida es reproducible.

## Por qué estratificado y no aleatorio

Una muestra random de ~100 avisos **no ejercita la capa 2 en absoluto**: el gate de muestra
mínima pide 8 avisos distintos en un mismo grupo `(id_modelo, anio)`, y una muestra random
los dispersa entre ~40 grupos sin llenar ninguno. El test de integración original tomaba 80
avisos al azar y por eso no probaba nada del IQR.

El generador **falla fuerte** si algún estrato queda vacío, en vez de producir un fixture que
aparenta una cobertura que no tiene.

## Estratos

| Estrato | Avisos | Qué ejercita |
|---|---|---|
| `sin_atributos`, incluidos los 3 precios más extremos del dataset | 15 | tier global de capa 2; los 790k/790k/850k ARS |
| `precio_invalido` por piso (`price <= 1000` ARS) | 8 | piso de capa 1 |
| `precio_invalido` por techo dinámico | 5 | `Q3 + 5*IQR` global |
| `obs_validas == 1` | 10 | etiqueta `Observación única` |
| precio sube >2% / baja >2% / plano | 10 / 10 / 10 | split de tendencia de 3 vías |
| `obs_validas == 0` | 5 | `Sin precio` |
| duplicado intra-día | 5 | tiebreak determinístico del dedup |
| `km == 0` / `0 < km < 1000` / `km > 800.000` | 5 / 5 / 5 | `rango_km`, capa 1 de km |
| `currency_id == "USD"` | 5 | `calcular_price_ars` con el blue |
| grupo `(id_modelo, anio)` que pasa el gate | 10 | capa 2 activa |
| grupo que no lo pasa | 3 | capa 2 saltea el grupo |
| grupo con outliers de precio reales: 20 normales + 5 marcados | 25 | `precio_outlier` |
| grupo con outliers de km reales: 20 normales + 5 marcados | 25 | `km_outlier` |

En los dos últimos estratos la mayoría son avisos **normales** a propósito: son los que fijan
los cuartiles, y sin ellos los outliers dejarían de ser outliers sobre la muestra chica.

Se conservan **todas** las capturas de cada aviso elegido (mediana 14, máximo 70). Es lo que
hace significativas las rutas de `fact_precios_historicos` y de tendencias.

## Cobertura resultante

Corriendo el ETL sobre el fixture: 161 avisos, `precio_invalido` 18, `km_invalido` 35,
`anio_invalido` 18, `sin_atributos` 18, `precio_outlier` 6 avisos (167 filas de captura),
`km_outlier` 13 avisos (324 filas), 6 avisos en USD, 2 grupos pasan el gate del IQR y 22 no.

**No cubierto:** la categoría `"Más de 500.000 KM"` de `rango_km`. No existe ningún aviso en
el dataset completo con km entre 500.000 y `KM_MAX_REAL` (el máximo válido es 490.000), así
que esa categoría es inalcanzable con estos datos. La rama queda cubierta por el test
unitario de `categoria_km`.

## Anonimización

- `id_u9` → `MLA9000000001…`, mapeo determinístico por orden alfabético.
- `title` → sintetizado como `"{Marca} {Modelo} {Versión}"` a partir de los atributos reales.
  El título original lo escribe el vendedor y suele traer teléfonos.
- `permalink` → `https://example.invalid/MLA9…` (el original embebe el id del aviso).
- `__KEY_results` queda **tal cual**: contiene la categoría (`MLA29483`), no el id del aviso,
  y es la clave de join con `attributes.csv`.
- **No se perturban** precio, kilómetros, año, fechas ni moneda: los tests dependen de la
  forma estadística real.
