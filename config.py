import os
from dotenv import load_dotenv

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
SHEET_PROYECCION_ID = "1i8uFkkRe9wjVF9LFmHTcPQ2xWBNwZWdMpe4df0gUIgQ"

# ==========================================
# PANEL DE CONTROL (BOTONES Y SWITCHES)
# ==========================================
CELDA_AUTOELIMINAR_DIARIO = "Hoja 1!B2"
CELDA_AUTOINSERTAR_DIARIO = "Hoja 1!B5"
CELDA_MODO_AUTO = "Hoja 1!L3"
CELDA_TEXTO_MANUAL = "Hoja 1!L4"
CELDA_BOTON_MANUAL = "Hoja 1!L5"

# ==========================================
# RANGOS DINÁMICOS (SOPORTAN CRECIMIENTO)
# ==========================================
# Hoja 1: Productividad (Escritura)
PROD_PESTANA = "Hoja 1"
PROD_FILA_INICIO = 2
PROD_COL_FECHA = "C"
PROD_COL_AGENCIA = "E"
PROD_COL_NUM_REAL = "G"
PROD_COL_MONTO_REAL = "I"
PROD_COL_DELTAS = "J"
PROD_CELDA_HORA_ACT = "J1"
PROD_ESPACIO_INCLUSIVOS = (
    5  # Filas de separación entre la tabla principal y la de Inclusivos
)

PROD_COL_DELTAS = "J"
PROD_CELDA_HORA_ACT = "J1"
PROD_ESPACIO_INCLUSIVOS = 5

# NUEVO: Columnas dinámicas para la tabla de Inclusivos
PROD_COL_INC_INI = "C"
PROD_COL_INC_FIN = "D"

# Hoja 1: Metas Mensuales (Lectura infinita)
RANGO_LEER_METAS_MENS = "Hoja 1!M2:U"

# Hoja 2: Metas Diarias (Lectura infinita)
RANGO_LEER_METAS_DIAR = "Hoja 2!H3:M"

# Proyecciones (Borrado Inteligente)
PROY_PESTANA = "Metas_Proyecciones"
PROY_FILA_INICIO = 3
PROY_COL_LIMPIAR_INI = "D"
PROY_COL_LIMPIAR_FIN = "E"


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
CARPETA_LOGS = "logs"
os.makedirs(CARPETA_LOGS, exist_ok=True)
LOG_METAS = os.path.join(CARPETA_LOGS, "sync_metas_log.txt")
LOG_FECHA_DIARIA = os.path.join(CARPETA_LOGS, "sync_diario_fecha.txt")
LOG_HISTORIAL_MENSUAL = os.path.join(CARPETA_LOGS, "historial_metas_mensual.txt")
LOG_LIMPIEZA = os.path.join(CARPETA_LOGS, "sync_diario_limpieza.txt")
