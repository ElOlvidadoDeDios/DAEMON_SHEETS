import os
import pyodbc
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import hashlib
import sys
import warnings
from dotenv import load_dotenv
import sync_metas

warnings.filterwarnings("ignore")

# Cargar variables de entorno desde el archivo .env
load_dotenv()

# ==========================================
# CONFIGURACIÓN
# ==========================================
# 1. Google Sheets
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
CREDS_FILE = "credenciales.json"
SPREADSHEET_NAME = "Reporte_Productividad_En_Vivo"
SHEET_TAB_NAME = "Hoja 1"

# 2. Base de Datos (Credenciales seguras desde .env)
DB_CONFIG = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={os.getenv('DB_TRANSACMIF_SERVER')};"
    f"DATABASE={os.getenv('DB_TRANSACMIF_NAME')};"
    f"UID={os.getenv('DB_TRANSACMIF_USER')};"
    f"PWD={os.getenv('DB_TRANSACMIF_PASS')};"
)

DB_CONFIG_DWH = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={os.getenv('DB_DWH_SERVER')};"
    f"DATABASE={os.getenv('DB_DWH_NAME')};"
    f"Trusted_Connection=yes;"
)

# ==========================================
# CONSULTA SQL
# ==========================================
QUERY = """
WITH AgenciasMaestro AS (
    SELECT * FROM (VALUES 
        ('01', 'Wanchaq'), ('02', 'San Jerónimo'), ('03', 'Quillabamba'),
        ('04', 'Sicuani'), ('05', 'Molino'), ('06', 'Juliaca'),
        ('07', 'Lima Los Olivos'), ('08', 'Tica Tica'), ('09', 'Magisterio'),
        ('10', 'Lima SJL'), ('11', 'Chiclayo'), ('12', 'Arequipa'),
        ('13', 'Pucallpa')
    ) AS t(IdSAgencia, NombreAgencia)
),
TransaccionesHoy AS (
    SELECT 
        CASE
            WHEN T_ANA.ID_AGE = '98' THEN
                CASE
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%10' THEN '10'
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%11' THEN '11'
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%12' THEN '12'
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%13' THEN '13'
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%6'  THEN '06'
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%7'  THEN '07'
                    ELSE '98'
                END
            WHEN T_ANA.ID_AGE = '01' THEN
                CASE
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%9' THEN '09'
                    ELSE '01'
                END
            ELSE T_ANA.ID_AGE
        END AS IdSAgencia,
        T_PTM.PAGARE,
        T_PTM.MONTO_PRESTAMO
    FROM dbo.PRESTAMO T_PTM
    INNER JOIN dbo.PREEC T_PRE ON T_PRE.CUENTA = T_PTM.CUENTA AND T_PRE.OTORGA = T_PTM.OTORGA AND T_PRE.PAGARE = T_PTM.PAGARE AND T_PRE.PERIODO = CONVERT(VARCHAR(6), GETDATE(), 112)
    INNER JOIN SEGURIDAD.DBO.ANAREC T_ANA ON T_ANA.ID_ANAREC = T_PRE.ID_ANA AND T_ANA.FLAG_ANAREC = 'A'
    INNER JOIN SEGURIDAD.dbo.USUARIOS T_USU ON T_USU.ID_USER = T_ANA.ID_USER
    INNER JOIN SEGURIDAD.dbo.GRUPOUSER T_GRU ON T_GRU.ID_GRUPO = T_USU.ID_GRUPO AND T_GRU.NOM_GRUPO = 'CREDITOS'
    WHERE CAST(T_PTM.OTORGA AS DATE) = CAST(GETDATE() AS DATE)
      AND T_PTM.TIPO_PROD <> '52'
      AND T_USU.ID_USER NOT IN (
          'PRECASTIGO', 'RJULI6', 'RJULIACA', 'RLIMA7', 'RQUILLA3', 'RSICUA4',
          'LHR5', 'HTEJ5', 'TKPN5', 'GHVJ5', 'OTA5', 'SDHF5', 'CMN5', 'HQND5'
      )
)
SELECT 
    CAST(GETDATE() AS DATE) AS Fecha,
    CONVERT(VARCHAR(6), GETDATE(), 112) AS Periodo,
    CASE WHEN GROUPING(M.IdSAgencia) = 1 THEN 'TOTAL GENERAL' ELSE MAX(M.NombreAgencia) END AS NombreAgencia,
    ISNULL(COUNT(T.PAGARE), 0) AS ColocacionNumReal,
    ISNULL(SUM(T.MONTO_PRESTAMO), 0) AS ColocacionMontoReal
FROM AgenciasMaestro M
LEFT JOIN TransaccionesHoy T ON M.IdSAgencia = T.IdSAgencia
GROUP BY ROLLUP(M.IdSAgencia)
ORDER BY CASE WHEN M.IdSAgencia IS NULL THEN 1 ELSE 0 END, M.IdSAgencia;
"""

QUERY_INCLUSIVOS = """
WITH AgenciasMaestro AS (
    SELECT * FROM (VALUES 
        ('01', 'Wanchaq', 1), ('02', 'San Jerónimo', 2), ('03', 'Quillabamba', 3),
        ('04', 'Sicuani', 4), ('05', 'Molino', 5), ('06', 'Juliaca', 6),
        ('07', 'Lima Los Olivos', 7), ('08', 'Tica Tica', 8), ('09', 'Magisterio', 9),
        ('10', 'Lima SJL', 10), ('11', 'Chiclayo', 11), ('12', 'Arequipa', 12),
        ('13', 'Pucallpa', 13)
    ) AS t(IdSAgencia, NombreAgencia, Orden)
),
CreditosInclusivosMes AS (
    SELECT 
        CASE
            WHEN T_ANA.ID_AGE = '98' THEN
                CASE
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%10' THEN '10'
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%11' THEN '11'
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%12' THEN '12'
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%13' THEN '13'
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%6'  THEN '06'
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%7'  THEN '07'
                    ELSE '98'
                END
            WHEN T_ANA.ID_AGE = '01' THEN
                CASE
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%9' THEN '09'
                    ELSE '01'
                END
            ELSE T_ANA.ID_AGE
        END AS IdSAgencia,
        COUNT(T_PTM.PAGARE) AS CreditosInclusivos
    FROM dbo.PRESTAMO T_PTM
    INNER JOIN dbo.PREEC T_PRE ON T_PRE.CUENTA = T_PTM.CUENTA AND T_PRE.OTORGA = T_PTM.OTORGA AND T_PRE.PAGARE = T_PTM.PAGARE 
        AND T_PRE.PERIODO = CONVERT(VARCHAR(6), GETDATE(), 112)
    INNER JOIN SEGURIDAD.DBO.ANAREC T_ANA ON T_ANA.ID_ANAREC = T_PRE.ID_ANA AND T_ANA.FLAG_ANAREC = 'A'
    WHERE CAST(T_PTM.OTORGA AS DATE) >= DATEADD(month, DATEDIFF(month, 0, GETDATE()), 0)
      AND CAST(T_PTM.OTORGA AS DATE) <= CAST(GETDATE() AS DATE)
      AND T_PTM.TIPO_PROD IN ('42', '44') 
    GROUP BY T_ANA.ID_AGE, T_ANA.ID_USER
)
SELECT 
    AM.NombreAgencia AS AGENCIA,
    ISNULL(SUM(CI.CreditosInclusivos), 0) AS [CRÉDITOS PRODUCTO INCLUSIVOS]
FROM AgenciasMaestro AM
LEFT JOIN CreditosInclusivosMes CI ON AM.IdSAgencia = CI.IdSAgencia
GROUP BY AM.NombreAgencia, AM.Orden
ORDER BY AM.Orden;
"""


# ==========================================
# FUNCIONES NÚCLEO
# ==========================================
def get_data_hash(df):
    return hashlib.md5(df.to_csv(index=False).encode()).hexdigest()


def push_to_google_sheets(df, df_anterior, df_inclusivos):
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open(SPREADSHEET_NAME).worksheet(SHEET_TAB_NAME)

        # ========================================================
        # 1. MAPEO DE COLUMNAS (TOTALMENTE CONFIGURABLE)
        # ========================================================
        # Define exactamente a qué letra de columna va cada dato
        # Si no mapeas una columna (ej. D o F), el script la ignorará,
        # permitiendo que tus fórmulas de Excel vivan ahí intactas.
        MAPEO_PRINCIPAL = {
            "Fecha": "A",
            "Periodo": "B",
            "NombreAgencia": "C",
            "ColocacionNumReal": "E",  # Apunta a E
            "ColocacionMontoReal": "G",  # Apunta a G
        }

        # Rangos fijos para otros elementos
        RANGO_MARCA_TIEMPO = "H1:I1"
        COLUMNAS_DELTAS = "H:I"  # Apunta a H e I (desde la fila 2 hacia abajo)
        RANGO_INCLUSIVOS = "A20"

        # Lista para agrupar todas las peticiones (batch_update es mucho más rápido)
        actualizaciones = []

        # --------------------------------------------------------
        # Empaquetar columnas de la tabla principal
        # --------------------------------------------------------
        filas_totales = len(df) + 1  # +1 para incluir el encabezado

        for col_df, letra_sheet in MAPEO_PRINCIPAL.items():
            if col_df in df.columns:
                # Construye la estructura vertical: [[Encabezado], [Valor1], [Valor2], ...]
                valores_columna = [[col_df]] + df[[col_df]].values.tolist()
                rango_destino = f"{letra_sheet}1:{letra_sheet}{filas_totales}"

                actualizaciones.append(
                    {"range": rango_destino, "values": valores_columna}
                )

        # --------------------------------------------------------
        # Empaquetar Marca de Tiempo
        # --------------------------------------------------------
        hora_actual = time.strftime("%d/%m/%Y %H:%M:%S")
        actualizaciones.append(
            {
                "range": RANGO_MARCA_TIEMPO,
                "values": [["Última actualización:", hora_actual]],
            }
        )

        # --------------------------------------------------------
        # Empaquetar Deltas (Últimas actualizaciones)
        # --------------------------------------------------------
        deltas = []
        for i in range(len(df)):
            if df_anterior is not None:
                diff_num = (
                    df.iloc[i]["ColocacionNumReal"]
                    - df_anterior.iloc[i]["ColocacionNumReal"]
                )
                diff_monto = (
                    df.iloc[i]["ColocacionMontoReal"]
                    - df_anterior.iloc[i]["ColocacionMontoReal"]
                )
            else:
                diff_num = 0
                diff_monto = 0

            str_num = f"+ {int(diff_num)}" if diff_num > 0 else ""
            str_monto = (
                f"+ {diff_monto:.2f}".replace(".", ",") if diff_monto > 0 else ""
            )
            deltas.append([str_num, str_monto])

        letra_inicio_delta, letra_fin_delta = COLUMNAS_DELTAS.split(":")
        rango_deltas_dinamico = (
            f"{letra_inicio_delta}2:{letra_fin_delta}{filas_totales}"
        )

        actualizaciones.append({"range": rango_deltas_dinamico, "values": deltas})

        # --------------------------------------------------------
        # Empaquetar Tabla Inclusivos
        # --------------------------------------------------------
        datos_inc = [
            df_inclusivos.columns.values.tolist()
        ] + df_inclusivos.values.tolist()
        actualizaciones.append({"range": RANGO_INCLUSIVOS, "values": datos_inc})

        # ========================================================
        # 2. EJECUTAR ACTUALIZACIÓN MASIVA EN SHEETS
        # ========================================================
        sheet.batch_update(actualizaciones)

        print(
            f"[{time.strftime('%H:%M:%S')}] ✅ GSheets sincronizado (Mapeo avanzado por columnas)."
        )

    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Error en API Google: {e}")


# ==========================================
# BUCLE PRINCIPAL
# ==========================================
def run_daemon():
    print(f"Iniciando Daemon de sincronización para '{SPREADSHEET_NAME}'...")
    ultimo_hash = None
    df_anterior = None

    while True:
        try:
            # 1. Extracción de datos
            conn = pyodbc.connect(DB_CONFIG)
            df_actual = pd.read_sql(QUERY, conn)

            # Extraemos los datos inclusivos en la misma conexión
            df_inclusivos = pd.read_sql(QUERY_INCLUSIVOS, conn)
            df_inclusivos.fillna(0, inplace=True)

            conn.close()

            df_actual.fillna(0, inplace=True)

            if "ColocacionNumReal" in df_actual.columns:
                df_actual["ColocacionNumReal"] = pd.to_numeric(
                    df_actual["ColocacionNumReal"]
                ).astype(int)
            if "ColocacionMontoReal" in df_actual.columns:
                df_actual["ColocacionMontoReal"] = pd.to_numeric(
                    df_actual["ColocacionMontoReal"]
                ).astype(float)
            if "Fecha" in df_actual.columns:
                df_actual["Fecha"] = df_actual["Fecha"].astype(str)
            if "Periodo" in df_actual.columns:
                df_actual["Periodo"] = df_actual["Periodo"].astype(str)
            if "NombreAgencia" in df_actual.columns:
                df_actual["NombreAgencia"] = df_actual["NombreAgencia"].astype(str)

            # 2. Análisis de varianza
            hash_actual = get_data_hash(df_actual)

            # 3. Disparador Push
            if hash_actual != ultimo_hash:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚡ Nuevo crédito/cambio detectado en TRANSACMIF."
                )

                # Enviamos ambos DataFrames
                push_to_google_sheets(df_actual, df_anterior, df_inclusivos)

                df_anterior = df_actual.copy()
                ultimo_hash = hash_actual

        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error general: {e}")

        # 4. Tarea extra: Sincronización de Metas
        try:
            sync_metas.run_sync_metas(DB_CONFIG_DWH)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Tarea Metas: {e}")

        # Este sleep ahora está protegido y fuera de los bloques try/except
        time.sleep(120)


if __name__ == "__main__":
    try:
        run_daemon()
    except KeyboardInterrupt:
        print("\nDaemon detenido manualmente.")
        sys.exit(0)
