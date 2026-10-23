import logging

from etl import tendencias
from etl.errors import ValidationError

logger = logging.getLogger(__name__)


def _avisar_columnas_sin_varianza(fact_publicaciones) -> list:
    """Loguea las columnas que tienen un solo valor distinto en toda la tabla.

    Nace de accepts_mercadopago, que es el string 'False' en las 124.511 filas
    crudas: no lleva informacion y se publicaba sin documentar. La columna se
    conserva por fidelidad al origen, pero ahora el hecho sale a la superficie
    en cada corrida, y la proxima columna asi se detecta gratis.
    """
    avisos = []
    for columna in fact_publicaciones.columns:
        if fact_publicaciones[columna].nunique(dropna=False) == 1:
            valor = fact_publicaciones[columna].iloc[0] if len(fact_publicaciones) else None
            avisos.append((columna, valor))
            logger.warning(
                "columna sin varianza en fact_publicaciones: %s = %r en las %s filas",
                columna, valor, len(fact_publicaciones),
            )
    return avisos


def resumir_fact_publicaciones(fact_publicaciones) -> dict:
    """Conteos y porcentajes de fact_publicaciones, como escalares.

    print_metricas los derivaba del DataFrame completo, que por eso tenia que
    viajar dentro del dict de metricas. Separarlo deja las metricas
    serializables.
    """
    n = len(fact_publicaciones)
    fp = fact_publicaciones

    def _pct(cantidad):
        return 100 * cantidad / n if n else 0.0

    resumen = {"filas": n}
    for columna, clave in [
        ("precio_invalido", "precio_valido"),
        ("km_invalido", "km_valido"),
        ("anio_invalido", "anio_valido"),
    ]:
        cantidad = int((~fp[columna]).sum())
        resumen[clave] = cantidad
        resumen[clave + "_pct"] = _pct(cantidad)

    for columna in ("precio_outlier", "km_outlier", "sin_atributos"):
        cantidad = int(fp[columna].sum())
        resumen[columna] = cantidad
        resumen[columna + "_pct"] = _pct(cantidad)

    resumen["nulls"] = {
        columna: {"n": int(fp[columna].isna().sum()), "pct": _pct(int(fp[columna].isna().sum()))}
        for columna in ("price_ars_limpio", "kilometros_limpio", "anio_limpio")
    }
    return resumen


def run_asserts(tablas: dict) -> None:
    """Gate de integridad previo a escribir. Levanta ValidationError si algo falla.

    Antes eran 11 `assert` desnudos, asi que correr con `python -O` saltaba
    TODA la validacion y escribia igual. Ahora son excepciones explicitas.

    Las fallas se acumulan y se reportan juntas en vez de cortar en la primera:
    si un cambio de esquema rompe tres invariantes, conviene verlas las tres.
    """
    fact_publicaciones = tablas["fact_publicaciones"]
    fact_precios_historicos = tablas["fact_precios_historicos"]
    tabla_tendencias = tablas["tabla_tendencias"]
    dim_marca = tablas["dim_marca"]
    dim_modelo = tablas["dim_modelo"]
    dim_transmision = tablas["dim_transmision"]
    dim_fx = tablas["dim_FX"]

    fallas: list = []

    def _check(condicion, mensaje: str) -> None:
        if not bool(condicion):
            fallas.append(mensaje)

    # Unicidad de claves primarias.
    _check(fact_publicaciones["id_publicacion"].is_unique, "id_publicacion duplicado en fact_publicaciones")
    _check(dim_marca["id_marca"].is_unique, "id_marca duplicado en dim_marca")
    _check(dim_modelo["id_modelo"].is_unique, "id_modelo duplicado en dim_modelo")
    _check(dim_transmision["id_transmision"].is_unique, "id_transmision duplicado en dim_transmision")
    _check(tabla_tendencias["id_publicacion"].is_unique, "id_publicacion duplicado en tabla_tendencias")

    # Integridad referencial hacia las dimensiones.
    _check(fact_publicaciones["id_marca"].dropna().isin(dim_marca["id_marca"]).all(),
           "id_marca en fact sin match en dim_marca")
    _check(fact_publicaciones["id_modelo"].dropna().isin(dim_modelo["id_modelo"]).all(),
           "id_modelo en fact sin match en dim_modelo")
    _check(fact_publicaciones["id_transmision"].dropna().isin(dim_transmision["id_transmision"]).all(),
           "id_transmision en fact sin match en dim_transmision")

    # Integridad referencial hacia la tabla de hechos principal.
    _check(fact_precios_historicos["id_publicacion"].isin(fact_publicaciones["id_publicacion"]).all(),
           "fact_precios_historicos tiene id_publicacion que no existe en fact_publicaciones")
    _check(tabla_tendencias["id_publicacion"].isin(fact_publicaciones["id_publicacion"]).all(),
           "tabla_tendencias tiene id_publicacion que no existe en fact_publicaciones")

    # Cobertura: tabla_tendencias tiene que tener una fila por aviso. Se cumple
    # por construccion, pero no estaba chequeado.
    _check(len(tabla_tendencias) == len(fact_publicaciones),
           "tabla_tendencias tiene {} filas y fact_publicaciones {}".format(
               len(tabla_tendencias), len(fact_publicaciones)))

    # dim_FX.
    _check(dim_fx.shape[0] == 1, "dim_FX deberia tener exactamente 1 fila, tiene {}".format(dim_fx.shape[0]))
    if dim_fx.shape[0] == 1:
        _check(dim_fx["usd_oficial"].notna().iloc[0], "dim_FX.usd_oficial es null")
        _check(dim_fx["usd_blue"].notna().iloc[0], "dim_FX.usd_blue es null")

    if fallas:
        raise ValidationError(
            "{} validacion(es) fallaron antes de escribir:\n  - {}".format(
                len(fallas), "\n  - ".join(fallas)
            )
        )

    _avisar_columnas_sin_varianza(fact_publicaciones)
    logger.info("Todas las validaciones duras pasaron OK")


def print_metricas(m: dict) -> None:
    print()
    print("=== ETL completado ===")
    print()
    print("Origen:")
    print(f"  results.csv:        {m['results_filas']:,} filas leidas")
    print(f"  attributes.csv:     {m['attributes_filas']:,} filas leidas")
    print()
    print("Diagnostico de duplicados (results_base, antes de deduplicar):")
    dd = m["dup_diag"]
    print(f"  Filas totales:                {dd['filas_totales']:,}")
    print(f"  id_publicacion unicos:        {dd['avisos_unicos']:,}")
    print(f"  Promedio capturas/aviso:      {dd['promedio_capturas_por_aviso']:.1f}")
    print(f"  Mediana capturas/aviso:       {dd['mediana_capturas_por_aviso']:.0f}")
    print(f"  Maximo capturas/aviso:        {dd['max_capturas_por_aviso']}")
    print(f"  Avisos con > 1 captura:       {dd['avisos_con_mas_de_1_captura']:,}")
    print(f"  Avisos con > 1 captura misma fecha: {dd['avisos_con_duplicado_intra_dia']}")
    print(f"  Ejemplos: {dd['ejemplos_duplicado_intra_dia']}")
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
    p2 = o["precio_outlier"]
    print(f"  filas por tier (precio): modelo_anio {p2['tier_modelo_anio_filas']:,} / "
          f"global {p2['tier_global_filas']:,} "
          f"(sin grupo {p2['tier_global_por_sin_grupo']:,} + "
          f"muestra chica {p2['tier_global_por_muestra_chica']:,})")
    if p2["fence_global_upper"] is not None:
        print(f"  fence global (precio):   [{p2['fence_global_lower']:,.0f} .. "
              f"{p2['fence_global_upper']:,.0f}] ARS")
    print()
    d = m["fact_diag"]
    print(f"fact_publicaciones: {d['filas']:,} filas")
    print(f"  - con precio valido:     {d['precio_valido']:,} ({d['precio_valido_pct']:.1f}%)")
    print(f"  - con km valido:         {d['km_valido']:,} ({d['km_valido_pct']:.1f}%)")
    print(f"  - con anio valido:       {d['anio_valido']:,} ({d['anio_valido_pct']:.1f}%)")
    print(f"  - outliers precio (IQR): {d['precio_outlier']:,} ({d['precio_outlier_pct']:.1f}%)")
    print(f"  - outliers km (IQR):     {d['km_outlier']:,} ({d['km_outlier_pct']:.1f}%)")
    print(f"  - sin atributos:         {d['sin_atributos']:,} ({d['sin_atributos_pct']:.1f}%)")
    print(f"fact_precios_historicos:   {m['fact_precios_historicos_filas']:,} filas")
    print()
    print("Columnas limpias (nulls = invalido capa 1 OR outlier capa 2):")
    for col, v in d["nulls"].items():
        print(f"  {col}: {v['n']:,} ({v['pct']:.1f}%)")
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
    print(f"  Fuente:  {m['fx']['fuente']}")
    print()
    print(f"Duracion: {m['duracion_segundos']:.1f} segundos")
