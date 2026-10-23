import pandas as pd

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}
DIAS_ES = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}


def build_dim_fecha(fecha_min, fecha_max) -> pd.DataFrame:
    fechas = pd.date_range(start=fecha_min, end=fecha_max, freq="D")
    df = pd.DataFrame({"fecha": fechas})
    df["anio"] = df["fecha"].dt.year
    df["mes_num"] = df["fecha"].dt.month
    df["mes_nombre"] = df["mes_num"].map(MESES_ES)
    df["anio_mes"] = df["fecha"].dt.strftime("%Y-%m")
    df["dia"] = df["fecha"].dt.day
    df["dia_semana_num"] = df["fecha"].dt.weekday
    df["dia_semana_nombre"] = df["dia_semana_num"].map(DIAS_ES)
    df["fecha"] = df["fecha"].dt.date
    return df


def build_dim_fx(fx: dict) -> pd.DataFrame:
    """Una fila con la cotizacion usada en la corrida.

    fuente_fx deja el linaje visible EN EL MODELO, no solo en un log: quien
    abra el dashboard puede ver si el tipo de cambio salio de la API, de un
    override de entorno o del fallback hardcodeado.
    """
    return pd.DataFrame([{
        "fecha_fx": fx["fecha_fx"],
        "usd_oficial": fx["usd_oficial"],
        "usd_blue": fx["usd_blue"],
        "fuente_fx": fx["fuente"],
    }])
