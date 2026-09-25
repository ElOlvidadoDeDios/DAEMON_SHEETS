import pandas as pd
import pyodbc
import time
from datetime import datetime
import config
from sql_queries import QUERY_PLAZO_FIJO
import warnings

warnings.filterwarnings("ignore")


def ejecutar_sincronizacion_plazo_fijo():
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] 🏦 Iniciando ETL de Plazo Fijo hacia DWH..."
    )

    # 1. EXTRACCIÓN (Desde TRANSACMIF)
    try:
        conn_origen = pyodbc.connect(config.DB_TRANSACMIF)
        df_plazo = pd.read_sql(QUERY_PLAZO_FIJO, conn_origen)
        conn_origen.close()
    except Exception as e:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error extrayendo Plazo Fijo: {e}"
        )
        return

    if df_plazo.empty:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ No hay datos de Plazo Fijo vigentes."
        )
        return

    # 2. TRANSFORMACIÓN
    # Añadimos la hora exacta en que el daemon procesa la data
    df_plazo["fecha_actualizacion"] = datetime.now()
    # Pandas usa NaN para vacíos, SQL Server necesita None (NULL)
    df_plazo = df_plazo.where(pd.notnull(df_plazo), None)

    # 3. CARGA (Hacia el DWH)
    try:
        # Asegúrate de tener config.DB_DWH configurado en tu config.py
        conn_destino = pyodbc.connect(config.DB_DWH)
        cursor = conn_destino.cursor()

        # AQUÍ ESTÁ EL CAMBIO 1: Ruta absoluta para el TRUNCATE
        cursor.execute(
            "TRUNCATE TABLE [DWH_Gestion_Cartera].[dbo].[fact_plazo_fijo_vigente]"
        )
        conn_destino.commit()

        # Inserción masiva ultra-rápida (fast_executemany)
        cursor.fast_executemany = True

        # AQUÍ ESTÁ EL CAMBIO 2: Ruta absoluta para el INSERT
        insert_query = """
        INSERT INTO [DWH_Gestion_Cartera].[dbo].[fact_plazo_fijo_vigente] (
            IdSAgencia, cuenta, nombre_socio, contrato, capital, tea, interes, 
            fecha_apertura, plazo_dias, fecha_vencimiento, fecha_actualizacion
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        # Convertimos el DataFrame a una lista de tuplas para pyodbc
        records = df_plazo.values.tolist()
        cursor.executemany(insert_query, records)

        conn_destino.commit()
        conn_destino.close()

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Éxito: {len(df_plazo)} registros actualizados en el DWH."
        )

    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error cargando al DWH: {e}")
