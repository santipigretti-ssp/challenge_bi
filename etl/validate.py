import logging

from etl import tendencias

logger = logging.getLogger(__name__)


def run_asserts(tablas: dict) -> None:
    fact_publicaciones = tablas["fact_publicaciones"]
    fact_precios_historicos = tablas["fact_precios_historicos"]
    tabla_tendencias = tablas["tabla_tendencias"]
    dim_marca = tablas["dim_marca"]
    dim_modelo = tablas["dim_modelo"]
    dim_transmision = tablas["dim_transmision"]
    dim_fx = tablas["dim_fx"]

    assert fact_publicaciones["id_publicacion"].is_unique, "id_publicacion duplicado en fact_publicaciones"
    assert dim_marca["id_marca"].is_unique, "id_marca duplicado en dim_marca"
    assert dim_modelo["id_modelo"].is_unique, "id_modelo duplicado en dim_modelo"
    assert dim_transmision["id_transmision"].is_unique, "id_transmision duplicado en dim_transmision"

    assert fact_publicaciones["id_marca"].dropna().isin(dim_marca["id_marca"]).all(), \
        "id_marca en fact sin match en dim_marca"
    assert fact_publicaciones["id_modelo"].dropna().isin(dim_modelo["id_modelo"]).all(), \
        "id_modelo en fact sin match en dim_modelo"
    assert fact_publicaciones["id_transmision"].dropna().isin(dim_transmision["id_transmision"]).all(), \
        "id_transmision en fact sin match en dim_transmision"

    assert fact_precios_historicos["id_publicacion"].isin(fact_publicaciones["id_publicacion"]).all(), \
        "fact_precios_historicos tiene id_publicacion que no existe en fact_publicaciones"
    assert tabla_tendencias["id_publicacion"].isin(fact_publicaciones["id_publicacion"]).all(), \
        "tabla_tendencias tiene id_publicacion que no existe en fact_publicaciones"

    assert dim_fx.shape[0] == 1, "dim_FX deberia tener exactamente 1 fila"
    assert dim_fx["usd_oficial"].notna().iloc[0], "dim_FX.usd_oficial es null"
    assert dim_fx["usd_blue"].notna().iloc[0], "dim_FX.usd_blue es null"

    logger.info("Todos los asserts duros pasaron OK")


def print_metricas(m: dict) -> None:
    print()
    print("=== ETL completado ===")
    print()
    print("Origen:")
    print(f"  results.csv:        {m['results_filas']:,} filas leidas")
    print(f"  attributes.csv:     {m['attributes_filas']:,} filas leidas")
    print()
    print("Diagnostico de duplicados (results_base, antes de deduplicar):")
    d = m["dup_diag"]
    print(f"  Filas totales:                {d['filas_totales']:,}")
    print(f"  id_publicacion unicos:        {d['avisos_unicos']:,}")
    print(f"  Promedio capturas/aviso:      {d['promedio_capturas_por_aviso']:.1f}")
    print(f"  Mediana capturas/aviso:       {d['mediana_capturas_por_aviso']:.0f}")
    print(f"  Maximo capturas/aviso:        {d['max_capturas_por_aviso']}")
    print(f"  Avisos con > 1 captura misma fecha: {d['avisos_con_duplicado_intra_dia']}")
    print(f"  Ejemplos: {d['ejemplos_duplicado_intra_dia']}")
    print()
    print("Capa 1 - precio (piso + techo dinamico global):")
    p = m["precio_diag"]
    print(f"  Invalidos por piso:           {p['piso_invalido']:,}")
    print(f"  Techo dinamico esta corrida:  {p['techo_global']:,.0f} ARS")
    print(f"  Invalidos por techo:          {p['techo_invalido']:,}")
    print(f"  Total precio_invalido:        {p['precio_invalido_total']:,}")
    print()
    print("Capa 2 - outliers IQR por grupo (id_modelo, anio):")
    o = m["outliers_diag"]
    print(f"  precio_outlier: {o['precio_outlier']['filas_marcadas']:,} filas marcadas "
          f"({o['precio_outlier']['grupos_sin_muestra_minima']} de {o['precio_outlier']['grupos_total']} "
          f"grupos sin muestra minima)")
    print(f"  km_outlier:     {o['km_outlier']['filas_marcadas']:,} filas marcadas "
          f"({o['km_outlier']['grupos_sin_muestra_minima']} de {o['km_outlier']['grupos_total']} "
          f"grupos sin muestra minima)")
    print()
    fp = m["fact_publicaciones"]
    n = len(fp)
    print(f"fact_publicaciones: {n:,} filas")
    print(f"  - con precio valido:     {(~fp['precio_invalido']).sum():,} ({100*(~fp['precio_invalido']).mean():.1f}%)")
    print(f"  - con km valido:         {(~fp['km_invalido']).sum():,} ({100*(~fp['km_invalido']).mean():.1f}%)")
    print(f"  - con anio valido:       {(~fp['anio_invalido']).sum():,} ({100*(~fp['anio_invalido']).mean():.1f}%)")
    print(f"  - outliers precio (IQR): {fp['precio_outlier'].sum():,} ({100*fp['precio_outlier'].mean():.1f}%)")
    print(f"  - outliers km (IQR):     {fp['km_outlier'].sum():,} ({100*fp['km_outlier'].mean():.1f}%)")
    print(f"  - sin atributos:         {fp['sin_atributos'].sum():,} ({100*fp['sin_atributos'].mean():.1f}%)")
    print(f"fact_precios_historicos:   {m['fact_precios_historicos_filas']:,} filas")
    print()
    print("Columnas limpias (nulls = invalido capa 1 OR outlier capa 2):")
    for col in ["price_ars_limpio", "kilometros_limpio", "anio_limpio"]:
        n_nulos = fp[col].isna().sum()
        print(f"  {col}: {n_nulos:,} ({100*n_nulos/n:.1f}%)")
    print()
    t = m["tendencias_counts"]
    total_t = sum(t.values())
    print("Tendencias:")
    if total_t == 0:
        print("  (sin avisos)")
    else:
        # Se recorren las etiquetas que realmente aparecieron, ordenadas por
        # ORDEN_TENDENCIA, en vez de una lista fija: con una lista hardcodeada
        # una etiqueta nueva no saldria en el reporte.
        etiquetas = sorted(t, key=lambda label: tendencias.ORDEN_TENDENCIA.get(label, 99))
        medibles = sum(c for label, c in t.items() if label in tendencias.TENDENCIAS_MEDIBLES)
        for label in etiquetas:
            c = t[label]
            print(f"  {label}: {c:,} ({100*c/total_t:.1f}%)")
        print(f"  --- medibles (base del split del dashboard): {medibles:,} "
              f"({100*medibles/total_t:.1f}%)")
    print()
    print(f"Marcas unicas:      {m['marcas_unicas']}")
    print(f"Modelos unicos:     {m['modelos_unicos']}")
    print(f"Transmisiones:      {m['transmisiones_unicas']}")
    print(f"Rango fechas:       {m['fecha_min']} a {m['fecha_max']}")
    print()
    print(f"FX al {m['fx']['fecha_fx']}:")
    print(f"  Oficial: ${m['fx']['usd_oficial']:.2f}")
    print(f"  Blue:    ${m['fx']['usd_blue']:.2f}")
    print()
    print(f"Duracion: {m['duracion_segundos']:.1f} segundos")
