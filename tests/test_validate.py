import logging

import pandas as pd
import pytest

from etl import validate
from etl.errors import ValidationError


def _tablas_validas():
    """Juego minimo de tablas que pasa todas las validaciones."""
    return {
        "fact_publicaciones": pd.DataFrame({
            "id_publicacion": ["A", "B"],
            "id_marca": ["M1", "M1"],
            "id_modelo": ["MO1", None],
            "id_transmision": ["T1", "T1"],
            "price_ars": [100_000.0, 200_000.0],
        }),
        "fact_precios_historicos": pd.DataFrame({"id_publicacion": ["A", "A", "B"]}),
        "tabla_tendencias": pd.DataFrame({"id_publicacion": ["A", "B"]}),
        "dim_marca": pd.DataFrame({"id_marca": ["M1"], "marca": ["Volkswagen"]}),
        "dim_modelo": pd.DataFrame({"id_modelo": ["MO1"], "modelo": ["Vento"]}),
        "dim_transmision": pd.DataFrame({"id_transmision": ["T1"], "transmision": ["Manual"]}),
        "dim_FX": pd.DataFrame([{"fecha_fx": "2015-11-30", "usd_oficial": 10.0, "usd_blue": 15.0}]),
    }


def test_tablas_validas_no_levantan():
    validate.run_asserts(_tablas_validas())


# --- Cada invariante por separado ---

def test_detecta_id_publicacion_duplicado():
    t = _tablas_validas()
    t["fact_publicaciones"] = pd.concat([t["fact_publicaciones"]] * 2, ignore_index=True)
    with pytest.raises(ValidationError, match="id_publicacion duplicado en fact_publicaciones"):
        validate.run_asserts(t)


def test_detecta_dim_duplicada():
    t = _tablas_validas()
    t["dim_marca"] = pd.DataFrame({"id_marca": ["M1", "M1"], "marca": ["Volkswagen", "VW"]})
    with pytest.raises(ValidationError, match="id_marca duplicado en dim_marca"):
        validate.run_asserts(t)


def test_detecta_id_huerfano_en_la_dimension():
    t = _tablas_validas()
    t["fact_publicaciones"]["id_marca"] = ["M1", "FANTASMA"]
    with pytest.raises(ValidationError, match="id_marca en fact sin match"):
        validate.run_asserts(t)


def test_detecta_aviso_huerfano_en_el_historico():
    t = _tablas_validas()
    t["fact_precios_historicos"] = pd.DataFrame({"id_publicacion": ["A", "FANTASMA"]})
    with pytest.raises(ValidationError, match="fact_precios_historicos tiene id_publicacion"):
        validate.run_asserts(t)


def test_detecta_cobertura_incompleta_en_tendencias():
    """tabla_tendencias tiene que tener una fila por aviso. Antes no se chequeaba."""
    t = _tablas_validas()
    t["tabla_tendencias"] = pd.DataFrame({"id_publicacion": ["A"]})
    with pytest.raises(ValidationError, match="tabla_tendencias tiene 1 filas"):
        validate.run_asserts(t)


@pytest.mark.parametrize("filas", [0, 2])
def test_detecta_dim_fx_con_cantidad_de_filas_incorrecta(filas):
    t = _tablas_validas()
    t["dim_FX"] = pd.concat([t["dim_FX"]] * filas) if filas else t["dim_FX"].iloc[:0]
    with pytest.raises(ValidationError, match="dim_FX deberia tener exactamente 1 fila"):
        validate.run_asserts(t)


def test_detecta_fx_nulo():
    t = _tablas_validas()
    t["dim_FX"] = pd.DataFrame([{"fecha_fx": "2015-11-30", "usd_oficial": None, "usd_blue": 15.0}])
    with pytest.raises(ValidationError, match="usd_oficial es null"):
        validate.run_asserts(t)


# --- Las fallas se acumulan ---

def test_reporta_todas_las_fallas_juntas():
    """Si un cambio de esquema rompe tres invariantes, conviene verlas las tres."""
    t = _tablas_validas()
    t["fact_publicaciones"] = pd.concat([t["fact_publicaciones"]] * 2, ignore_index=True)
    t["dim_marca"] = pd.DataFrame({"id_marca": ["M1", "M1"], "marca": ["Volkswagen", "VW"]})
    t["dim_FX"] = t["dim_FX"].iloc[:0]

    with pytest.raises(ValidationError) as exc:
        validate.run_asserts(t)

    mensaje = str(exc.value)
    assert "id_publicacion duplicado" in mensaje
    assert "id_marca duplicado" in mensaje
    assert "dim_FX deberia tener exactamente 1 fila" in mensaje
    assert "validacion(es) fallaron" in mensaje


# --- Detector de varianza cero ---

def test_avisa_de_columnas_sin_varianza(caplog):
    """accepts_mercadopago es el string 'False' en las 124.511 filas crudas."""
    t = _tablas_validas()
    t["fact_publicaciones"]["accepts_mercadopago"] = [False, False]

    with caplog.at_level(logging.WARNING, logger="etl.validate"):
        validate.run_asserts(t)

    assert "sin varianza" in caplog.text
    assert "accepts_mercadopago" in caplog.text


def test_no_avisa_si_todas_las_columnas_tienen_varianza(caplog):
    t = _tablas_validas()
    # Toda columna con al menos dos valores distintos.
    t["fact_publicaciones"] = pd.DataFrame({
        "id_publicacion": ["A", "B"],
        "id_marca": ["M1", "M2"],
        "id_modelo": ["MO1", None],
        "id_transmision": ["T1", "T2"],
        "price_ars": [100_000.0, 200_000.0],
    })
    t["dim_marca"] = pd.DataFrame({"id_marca": ["M1", "M2"], "marca": ["Volkswagen", "Suzuki"]})
    t["dim_transmision"] = pd.DataFrame({
        "id_transmision": ["T1", "T2"], "transmision": ["Manual", "Automática"],
    })

    with caplog.at_level(logging.WARNING, logger="etl.validate"):
        validate.run_asserts(t)

    assert "sin varianza" not in caplog.text


# --- print_metricas ---

def _metricas_minimas(tendencias_counts):
    return {
        "results_filas": 10, "attributes_filas": 20,
        "dup_diag": {
            "filas_totales": 10, "avisos_unicos": 2, "promedio_capturas_por_aviso": 5.0,
            "mediana_capturas_por_aviso": 5.0, "max_capturas_por_aviso": 5,
            "avisos_con_mas_de_1_captura": 2, "avisos_con_duplicado_intra_dia": 0,
            "ejemplos_duplicado_intra_dia": [],
        },
        "precio_diag": {
            "piso_invalido": 1, "techo_global": 1_000_000.0,
            "techo_invalido": 1, "precio_invalido_total": 2,
        },
        "outliers_diag": {
            flag: {
                "grupos_total": 2, "grupos_sin_muestra_minima": 1, "filas_marcadas": 1,
                "tier_modelo_anio_filas": 5, "tier_global_filas": 0,
                "tier_global_por_sin_grupo": 0, "tier_global_por_muestra_chica": 0,
                "fence_global_lower": None, "fence_global_upper": None,
            }
            for flag in ("precio_outlier", "km_outlier")
        },
        "fact_publicaciones": pd.DataFrame({
            "precio_invalido": [False, True], "km_invalido": [False, False],
            "anio_invalido": [False, False], "precio_outlier": [False, False],
            "km_outlier": [False, False], "sin_atributos": [False, True],
            "price_ars_limpio": [1.0, None], "kilometros_limpio": [1.0, None],
            "anio_limpio": [2015.0, None],
        }),
        "fact_precios_historicos_filas": 10,
        "tendencias_counts": tendencias_counts,
        "marcas_unicas": 1, "modelos_unicos": 1, "transmisiones_unicas": 1,
        "fecha_min": "2015-10-10", "fecha_max": "2015-12-21",
        "fx": {"fecha_fx": "2015-11-30", "usd_oficial": 10.0, "usd_blue": 15.0},
        "duracion_segundos": 1.0,
    }


def test_print_metricas_incluye_la_etiqueta_nueva(capsys):
    """Antes recorria una lista fija de 4 etiquetas y habria omitido la nueva."""
    validate.print_metricas(_metricas_minimas({
        "Subió": 1, "Bajó": 1, "Estable": 1, "Observación única": 5, "Sin precio": 1,
    }))
    salida = capsys.readouterr().out

    assert "Observación única" in salida
    assert "medibles" in salida


def test_print_metricas_no_revienta_con_tabla_vacia(capsys):
    """Antes: ZeroDivisionError al dividir por la suma de los conteos."""
    validate.print_metricas(_metricas_minimas({}))
    assert "sin avisos" in capsys.readouterr().out
