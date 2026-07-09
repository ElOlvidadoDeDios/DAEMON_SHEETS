import pyodbc
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import hashlib
import sys
import warnings
import sync_metas

warnings.filterwarnings("ignore")

# ==========================================
# CONFIGURACIÓN
# ==========================================
# 1. Google Sheets
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
CREDS_FILE = "credenciales.json"
SPREADSHEET_NAME = (
    "Reporte_Productividad_En_Vivo"  # Reemplaza con el nombre exacto de tu archivo
)
SHEET_TAB_NAME = "Hoja 1"  # Reemplaza con el nombre exacto de la pestaña

# 2. Base de Datos (Asegura apuntar al servidor DESKTOP-K6HIFFS)
DB_CONFIG = (
    r"DRIVER={ODBC Driver 17 for SQL Server};"
    r"SERVER=192.168.10.150;"  # La IP de tu servidor Core
    r"DATABASE=TRANSACMIF;"  # Tu base de datos Upstream
    r"UID=UsuarioDTI;"  # Tu usuario definido en el .env
    r"PWD=DTI.12345;"  # Tu contraseña
)

# ==========================================
# CONSULTA SQL (Tu lógica de negocio pura)
# ==========================================
QUERY = """
WITH AgenciasMaestro AS (
    -- 1. Creamos un esqueleto rígido con las 13 agencias
    SELECT * FROM (VALUES 
        ('01', 'Wanchaq'), ('02', 'San Jerónimo'), ('03', 'Quillabamba'),
        ('04', 'Sicuani'), ('05', 'Molino'), ('06', 'Juliaca'),
        ('07', 'Lima Los Olivos'), ('08', 'Tica Tica'), ('09', 'Magisterio'),
        ('10', 'Lima SJL'), ('11', 'Chiclayo'), ('12', 'Arequipa'),
        ('13', 'Pucallpa')
    ) AS t(IdSAgencia, NombreAgencia)
),
TransaccionesHoy AS (
    -- 2. Filtramos la data operativa real del día
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
-- 3. Unimos el esqueleto con la data para forzar las 13 filas + el Total
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


# ==========================================
# FUNCIONES NÚCLEO
# ==========================================
def get_data_hash(df):
    """Genera una huella digital (hash) rápida de los datos."""
    return hashlib.md5(df.to_csv(index=False).encode()).hexdigest()


def push_to_google_sheets(df, df_anterior):
    """Sincroniza los datos con Google, incluye la marca de tiempo y calcula deltas."""
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open(SPREADSHEET_NAME).worksheet(SHEET_TAB_NAME)

        # 1. Limpiamos toda la hoja
        sheet.clear()

        # 2. Escribimos la tabla principal
        datos = [df.columns.values.tolist()] + df.values.tolist()
        sheet.update(values=datos, range_name="A1")

        # 3. Escribimos la marca de tiempo a la derecha (G1 y H1)
        hora_actual = time.strftime("%d/%m/%Y %H:%M:%S")
        marca_tiempo = [["Última actualización:", hora_actual]]
        sheet.update(values=marca_tiempo, range_name="G1:H1")

        # 4. Cálculo y escritura de variaciones en G2:H...
        deltas = []
        for i in range(len(df)):
            if df_anterior is not None:
                # Comparamos matemáticamente la fila actual con la anterior
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

            # Formateamos con el "+ " si hay crecimiento, o lo dejamos vacío
            str_num = f"+ {int(diff_num)}" if diff_num > 0 else ""
            str_monto = (
                f"+ {diff_monto:.2f}".replace(".", ",") if diff_monto > 0 else ""
            )

            deltas.append([str_num, str_monto])

        # Insertamos el bloque de deltas debajo de la marca de tiempo
        rango_deltas = f"G2:H{len(df) + 1}"
        sheet.update(values=deltas, range_name=rango_deltas)

        print(
            f"[{time.strftime('%H:%M:%S')}] ✅ GSheets sincronizado con deltas en columnas G y H."
        )
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Error en API Google: {e}")


# ==========================================
# BUCLE PRINCIPAL
# ==========================================
def run_daemon():
    print(f"Iniciando Daemon de sincronización para '{SPREADSHEET_NAME}'...")
    ultimo_hash = None
    df_anterior = None  # NUEVO: Memoria del estado previo

    while True:
        try:
            # 1. Extracción rápida (tu código actual)
            conn = pyodbc.connect(DB_CONFIG)
            df_actual = pd.read_sql(QUERY, conn)
            conn.close()

            df_actual.fillna(0, inplace=True)

            # (Tu código actual donde fuerzas int y float)
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

            # 2. Análisis de varianza (tu código actual)
            hash_actual = get_data_hash(df_actual)

            # 3. Disparador Push
            if hash_actual != ultimo_hash:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚡ Nuevo crédito/cambio detectado en TRANSACMIF."
                )

                # NUEVO: Pasamos df_anterior a la función
                push_to_google_sheets(df_actual, df_anterior)

                # NUEVO: Guardamos el dataframe actual como "anterior" para la próxima vuelta
                df_anterior = df_actual.copy()
                ultimo_hash = hash_actual

        except pyodbc.Error as db_err:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error de DB: {db_err}")
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error general: {e}")
        # 4. Tarea extra: Sincronización de Metas
        try:
            sync_metas.run_sync_metas(DB_CONFIG)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Tarea Metas: {e}")


if __name__ == "__main__":
    try:
        run_daemon()
    except KeyboardInterrupt:
        print("\nDaemon detenido manualmente.")
        sys.exit(0)
