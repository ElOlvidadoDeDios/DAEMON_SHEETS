# sync_riesgo_integral.py

import pandas as pd
import sqlite3
import pyodbc
from datetime import datetime
import config
from sql_queries import QUERY_CARTERA_INTEGRAL
import warnings

warnings.filterwarnings("ignore")


def clasificar_estado(row, hoy_dia):
    if row["Cuotas_Atrasadas"] > 0 and row["Dias_Atraso"] >= hoy_dia:
        return "3. Mora Potencial"
    elif row["Cuotas_Atrasadas"] > 0 and row["Dias_Atraso"] > 0:
        return "2. Mora Temprana"
    else:
        return "1. Al Día"


def clasificar_riesgo(prob):
    if pd.isna(prob):
        return None
    if prob >= 75:
        return "ALTO"
    elif prob >= 50:
        return "MEDIO"
    else:
        return "BAJO"


def fusionar_telefonos(row):
    # Recolectamos los 4 campos crudos
    tels = [
        str(row["Celular1"]),
        str(row["Celular2"]),
        str(row["Telefono1"]),
        str(row["Telefono2"]),
    ]
    tels_limpios = []

    for t in tels:
        # Quitamos espacios en blanco y basurita de formato
        t_clean = t.replace(" ", "").replace(".0", "").strip()

        # Ignoramos si está vacío o si pandas le puso 'nan' o 'None'
        if t_clean and t_clean.lower() not in ["nan", "none", "null"]:
            # Evitamos duplicados (si el CEL1 es igual al CEL2, solo lo pone una vez)
            if t_clean not in tels_limpios:
                tels_limpios.append(t_clean)

    # Unimos la lista final con un guion y espacios
    return " - ".join(tels_limpios) if tels_limpios else None


def ejecutar_etl_riesgo_integral():
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] 🏗️ Iniciando ETL de Riesgo Integral (Cartera unificada)..."
    )

    # 1. Extraer el 100% de la cartera de TRANSACMIF
    try:
        conn_sql = pyodbc.connect(config.DB_TRANSACMIF)
        df_cartera = pd.read_sql(QUERY_CARTERA_INTEGRAL, conn_sql)
        conn_sql.close()
    except Exception as e:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error conectando a TRANSACMIF: {e}"
        )
        return

    # 2. Extraer memoria local (Predicciones IA y Compromisos)
    conn_sqlite = sqlite3.connect("mora_gestion.db")
    try:
        df_ia = pd.read_sql(
            "SELECT pagare, probabilidad FROM historial_ia", conn_sqlite
        )
        # 🚀 CORRECCIÓN: Borrar predicciones antiguas del mismo pagaré, conservar la más reciente
        df_ia = df_ia.drop_duplicates(subset=["pagare"], keep="last")
    except:
        df_ia = pd.DataFrame(columns=["pagare", "probabilidad"])

    try:
        df_compromisos = pd.read_sql(
            "SELECT pagare, compromiso, fecha_promesa FROM compromisos", conn_sqlite
        )
        # 🚀 CORRECCIÓN: Borrar compromisos antiguos, conservar solo la promesa más reciente
        df_compromisos = df_compromisos.drop_duplicates(subset=["pagare"], keep="last")
    except:
        df_compromisos = pd.DataFrame(columns=["pagare", "compromiso", "fecha_promesa"])
    conn_sqlite.close()

    # Normalizar espacios en las llaves (Pagarés) para el cruce perfecto
    df_cartera["Pagare"] = df_cartera["Pagare"].astype(str).str.strip()
    df_ia["pagare"] = df_ia["pagare"].astype(str).str.strip()
    df_compromisos["pagare"] = df_compromisos["pagare"].astype(str).str.strip()

    # 3. Cruzar datos (LEFT JOIN)
    df_final = pd.merge(
        df_cartera, df_ia, left_on="Pagare", right_on="pagare", how="left"
    )
    df_final = pd.merge(
        df_final, df_compromisos, left_on="Pagare", right_on="pagare", how="left"
    )

    # 4. Transformar y etiquetar
    hoy_dia = datetime.now().day
    fecha_foto = datetime.now().strftime("%Y-%m-%d")

    df_final["Estado_Mora"] = df_final.apply(
        lambda row: clasificar_estado(row, hoy_dia), axis=1
    )
    df_final["Nivel_Riesgo_IA"] = df_final["probabilidad"].apply(clasificar_riesgo)

    df_final["Telefonos"] = df_final.apply(fusionar_telefonos, axis=1)

    # Lógica de Negocio: Los que están "Al Día" NO deben tener compromiso (se borra lo residual)
    df_final.loc[
        df_final["Estado_Mora"] == "1. Al Día", ["compromiso", "fecha_promesa"]
    ] = None

    # Preparar DataFrame con la estructura exacta de SQL
    df_insert = pd.DataFrame()
    df_insert["Fecha_Foto"] = [fecha_foto] * len(df_final)
    df_insert["Periodo"] = df_final["Periodo"]
    df_insert["IdSAgencia"] = df_final["IdSAgencia"]
    df_insert["IdSAsesor"] = df_final["IdSAsesor"]
    df_insert["Pagare"] = df_final["Pagare"]
    df_insert["Socio"] = df_final["Socio"]
    df_insert["Producto"] = df_final["Producto"]
    df_insert["Monto_Desembolsado"] = pd.to_numeric(
        df_final["Monto_Desembolsado"], errors="coerce"
    )
    df_insert["Saldo_Capital"] = pd.to_numeric(
        df_final["Saldo_Capital"], errors="coerce"
    )
    df_insert["Tasa_TEA"] = pd.to_numeric(df_final["Tasa_TEA"], errors="coerce")
    df_insert["Cuota_Mensual"] = pd.to_numeric(
        df_final["Cuota_Mensual"], errors="coerce"
    )
    df_insert["Dias_Atraso"] = (
        pd.to_numeric(df_final["Dias_Atraso"], errors="coerce").fillna(0).astype(int)
    )
    df_insert["Estado_Mora"] = df_final["Estado_Mora"]
    df_insert["Nivel_Riesgo_IA"] = df_final["Nivel_Riesgo_IA"]
    df_insert["Probabilidad_IA"] = pd.to_numeric(
        df_final["probabilidad"], errors="coerce"
    )
    df_insert["Compromiso"] = df_final["compromiso"]
    df_insert["Telefonos"] = df_final["Telefonos"]

    # Limpieza estricta de la fecha promesa para que SQL Server no explote
    df_insert["Fecha_Promesa"] = pd.to_datetime(
        df_final["fecha_promesa"], errors="coerce", dayfirst=True
    ).dt.strftime("%Y-%m-%d")

    # Convertir NaN de pandas a None de Python (para que inserte NULL en la base de datos)
    df_insert = df_insert.astype(object).where(pd.notnull(df_insert), None)

    # 🚀 CORRECCIÓN 1: Forzar el orden exacto de las columnas para que cuadre con el INSERT
    columnas_ordenadas = [
        "Fecha_Foto",
        "Periodo",
        "IdSAgencia",
        "IdSAsesor",
        "Pagare",
        "Socio",
        "Producto",
        "Monto_Desembolsado",
        "Saldo_Capital",
        "Tasa_TEA",
        "Cuota_Mensual",
        "Dias_Atraso",
        "Estado_Mora",
        "Nivel_Riesgo_IA",
        "Probabilidad_IA",
        "Compromiso",
        "Fecha_Promesa",
        "Telefonos",
    ]
    df_insert = df_insert[columnas_ordenadas]

    # 5. Carga a SQL Server (DWH)
    try:
        conn_dwh = pyodbc.connect(config.DB_DWH)
        cursor = conn_dwh.cursor()

        # Eliminar la foto de hoy si el daemon pasa por segunda vez, para evitar duplicar
        cursor.execute(
            "DELETE FROM [DWH_Gestion_Cartera].[dbo].[fct_riesgo_integral] WHERE Fecha_Foto = ?",
            fecha_foto,
        )

        # 🚀 CORRECCIÓN 2: Mantenemos apagado 'fast_executemany' para evitar el bug de tipos con nulos
        # La inserción estándar tardará menos de 2 segundos de todos modos.

        sql_insert = """
            INSERT INTO [DWH_Gestion_Cartera].[dbo].[fct_riesgo_integral] (
                [Fecha_Foto], [Periodo], [IdSAgencia], [IdSAsesor], [Pagare], [Socio], 
                [Producto], [Monto_Desembolsado], [Saldo_Capital], [Tasa_TEA], [Cuota_Mensual], 
                [Dias_Atraso], [Estado_Mora], [Nivel_Riesgo_IA], [Probabilidad_IA], [Compromiso], [Fecha_Promesa], [Telefonos]
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor.executemany(sql_insert, df_insert.values.tolist())
        conn_dwh.commit()
        conn_dwh.close()

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Riesgo Integral actualizado. {len(df_insert)} créditos procesados hacia el DWH."
        )
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error cargando a DWH: {e}")
