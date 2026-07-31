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

# Módulos de sincronización externa
import sync_metas_diario
import sync_metas_mensual

warnings.filterwarnings("ignore")
load_dotenv()

# ==========================================
# CONFIGURACIÓN
# ==========================================
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
CREDS_FILE = "credenciales.json"
SPREADSHEET_NAME = "Reporte_Productividad_En_Vivo"
SHEET_TAB_NAME = "Hoja 1"

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
# CONSULTAS SQL (Intactas)
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
    FROM dbo.PRESTAMO T_PTM WITH (NOLOCK)
    INNER JOIN dbo.PREEC T_PRE WITH (NOLOCK) ON T_PRE.CUENTA = T_PTM.CUENTA AND T_PRE.OTORGA = T_PTM.OTORGA AND T_PRE.PAGARE = T_PTM.PAGARE AND T_PRE.PERIODO = CONVERT(VARCHAR(6), GETDATE(), 112)
    INNER JOIN SEGURIDAD.DBO.ANAREC T_ANA WITH (NOLOCK) ON T_ANA.ID_ANAREC = T_PRE.ID_ANA AND T_ANA.FLAG_ANAREC = 'A'
    INNER JOIN SEGURIDAD.dbo.USUARIOS T_USU WITH (NOLOCK) ON T_USU.ID_USER = T_ANA.ID_USER
    INNER JOIN SEGURIDAD.dbo.GRUPOUSER T_GRU WITH (NOLOCK) ON T_GRU.ID_GRUPO = T_USU.ID_GRUPO AND T_GRU.NOM_GRUPO = 'CREDITOS'
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

        actualizaciones = []
        filas_df = len(df)

        # 1. Columnas A, B, C (Fechas, Periodo, Agencia)
        datos_abc = df[["Fecha", "Periodo", "NombreAgencia"]].values.tolist()
        actualizaciones.append({"range": f"A2:C{filas_df + 1}", "values": datos_abc})

        # 2. Columna E (ColocacionNumReal) - Saltando la D
        datos_e = [[val] for val in df["ColocacionNumReal"].tolist()]
        actualizaciones.append({"range": f"E2:E{filas_df + 1}", "values": datos_e})

        # 3. Columna G (ColocacionMontoReal) - Saltando la F
        datos_g = [[val] for val in df["ColocacionMontoReal"].tolist()]
        actualizaciones.append({"range": f"G2:G{filas_df + 1}", "values": datos_g})

        # 4. Columna H (Última actualización)
        hora_actual = time.strftime("%d/%m/%Y\n%H:%M:%S")
        actualizaciones.append(
            {"range": "H1", "values": [[f"Última act:\n{hora_actual}"]]}
        )

        # 5. Columna H (Deltas con el formato +Cantidad -> Monto)
        datos_deltas = []
        for i in range(filas_df):
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

            # Solo se escribe si hubo un aumento (evita que marque ceros al inicio del día)
            if diff_num > 0 or diff_monto > 0:
                # Formato: +1 -> 2500,00
                str_delta = f"+{int(diff_num)} -> {diff_monto:.2f}".replace(".", ",")
            else:
                str_delta = ""

            datos_deltas.append([str_delta])

        actualizaciones.append({"range": f"H2:H{filas_df + 1}", "values": datos_deltas})

        # 6. Inclusivos en A20
        datos_inc = [
            df_inclusivos.columns.values.tolist()
        ] + df_inclusivos.values.tolist()
        actualizaciones.append(
            {"range": f"A20:B{19+len(datos_inc)}", "values": datos_inc}
        )

        # Disparamos todas las celdas en un solo envío
        sheet.batch_update(actualizaciones)

        print(
            f"[{time.strftime('%H:%M:%S')}] ✅ GSheets sincronizado (E=NumReal, G=MontoReal, H=Deltas)."
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
            conn = pyodbc.connect(DB_CONFIG)
            df_actual = pd.read_sql(QUERY, conn)
            df_inclusivos = pd.read_sql(QUERY_INCLUSIVOS, conn)
            conn.close()

            df_actual.fillna(0, inplace=True)
            df_inclusivos.fillna(0, inplace=True)

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

            hash_actual = get_data_hash(df_actual)

            if hash_actual != ultimo_hash:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚡ Nuevo crédito/cambio detectado en TRANSACMIF."
                )
                push_to_google_sheets(df_actual, df_anterior, df_inclusivos)
                df_anterior = df_actual.copy()
                ultimo_hash = hash_actual

        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error general: {e}")

        # Metas Diarias
        try:
            sync_metas_diario.run_sync_metas(DB_CONFIG_DWH)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Tarea Metas Diarias: {e}")

        # Metas Mensuales
        try:
            sync_metas_mensual.run_sync_metas_mensual(DB_CONFIG_DWH)
        except Exception as e:
            print(
                f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Tarea Metas Mensuales: {e}"
            )

        time.sleep(120)


if __name__ == "__main__":
    try:
        run_daemon()
    except KeyboardInterrupt:
        print("\nDaemon detenido manualmente.")
        sys.exit(0)
