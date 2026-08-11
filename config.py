import os
from dotenv import load_dotenv

# Cargar variables de entorno (.env)
load_dotenv()

# ==========================================
# CONFIGURACIÓN DE GOOGLE SHEETS
# ==========================================
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
CREDS_FILE = "credenciales.json"
SPREADSHEET_NAME = "Reporte_Productividad_En_Vivo"

# NUEVO: ID del documento "PROYECCIÓN DEL DÍA"
SHEET_PROYECCION_ID = "1i8uFkkRe9wjVF9LFmHTcPQ2xWBNwZWdMpe4df0gUIgQ"

# ==========================================
# CONFIGURACIÓN DE BASES DE DATOS (SQL SERVER)
# ==========================================
DB_TRANSACMIF = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={os.getenv('DB_TRANSACMIF_SERVER')};"
    f"DATABASE={os.getenv('DB_TRANSACMIF_NAME')};"
    f"UID={os.getenv('DB_TRANSACMIF_USER')};"
    f"PWD={os.getenv('DB_TRANSACMIF_PASS')};"
)

DB_DWH = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={os.getenv('DB_DWH_SERVER')};"
    f"DATABASE={os.getenv('DB_DWH_NAME')};"
    f"Trusted_Connection=yes;"
)

# ==========================================
# ARCHIVOS DE REGISTRO (LOGS)
# ==========================================
# Definimos el nombre de la carpeta
CARPETA_LOGS = "logs"

# Le decimos a Python que cree la carpeta mágicamente si no existe
os.makedirs(CARPETA_LOGS, exist_ok=True)

LOG_METAS = os.path.join(CARPETA_LOGS, "sync_metas_log.txt")
LOG_FECHA_DIARIA = os.path.join(CARPETA_LOGS, "sync_diario_fecha.txt")
LOG_HISTORIAL_MENSUAL = os.path.join(CARPETA_LOGS, "historial_metas_mensual.txt")
LOG_LIMPIEZA = os.path.join(CARPETA_LOGS, "sync_diario_limpieza.txt")
