import os
from datetime import datetime
import pyodbc
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIGURACIÓN ---
LOG_FILE = "sync_metas_log.txt"
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
CREDS_FILE = "credenciales.json"
SPREADSHEET_NAME = "Reporte_Productividad_En_Vivo"
# ---------------------


def run_sync_metas(db_config):
    """
    Sincroniza metas diarias.
    Condiciones: Hora 10am-10:59am, una vez al día, celdas llenas.
    """
    now = datetime.now()

    # 1. Validar ventana de tiempo (10:00 a 10:59)
    if not (now.hour == 10):
        return

    # 2. Validar si ya se ejecutó hoy
    fecha_hoy = now.strftime("%Y-%m-%d")
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            if f.read().strip() == fecha_hoy:
                return  # Ya se corrió hoy

    # 3. Autenticarse y Leer Hoja 2
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
        client = gspread.authorize(creds)
        hoja_metas = client.open(SPREADSHEET_NAME).worksheet("Hoja 2")
        data = hoja_metas.get("H3:M15")
    except Exception as e:
        print(f"[{now.strftime('%H:%M:%S')}] ❌ Error leyendo GSheets (Metas): {e}")
        return

    # 4. Validar que no haya celdas vacías (Rango H3:M15)
    for row in data:
        if len(row) < 6 or any(str(cell).strip() == "" for cell in row):
            print(
                f"[{now.strftime('%H:%M:%S')}] ⚠️ Sync Metas pausado: Celdas vacías detectadas."
            )
            return

    # 5. Insertar en SQL Server
    try:
        # AQUÍ USAMOS EL PARÁMETRO db_config (que viene del daemon)
        conn = pyodbc.connect(db_config)
        cursor = conn.cursor()

        # Limpiar datos del día para evitar duplicados
        cursor.execute(
            "DELETE FROM [dm_productividad].[dbo].[FctDiario_MetaProy] WHERE Fecha = ?",
            fecha_hoy,
        )

        insert_sql = """
        INSERT INTO [dm_productividad].[dbo].[FctDiario_MetaProy] 
        ([Fecha], [IdSAgencia], [ColocacionNumMeta], [ColocacionNumProy], [ColocacionMontoMeta], [ColocacionMontoProy])
        VALUES (?, ?, ?, ?, ?, ?)
        """

        for row in data:
            cursor.execute(insert_sql, row)

        conn.commit()
        conn.close()

        # Marcar como ejecutado
        with open(LOG_FILE, "w") as f:
            f.write(fecha_hoy)

        print(
            f"[{now.strftime('%H:%M:%S')}] ✅ Metas diarias sincronizadas exitosamente en SQL Server."
        )

    except Exception as e:
        print(f"[{now.strftime('%H:%M:%S')}] ❌ Error en SQL (Metas): {e}")
