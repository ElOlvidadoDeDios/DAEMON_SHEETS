import hashlib
import json
import time
import os
from datetime import datetime
import pyodbc
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIGURACIÓN ---
LOG_FILE = "sync_metas_log.txt"  # Aquí se guardan los Hashes
DATE_LOG_FILE = "sync_diario_fecha.txt"  # Aquí se guarda la fecha de ejecución
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
CREDS_FILE = "credenciales.json"
SPREADSHEET_NAME = "Reporte_Productividad_En_Vivo"
# ---------------------


def existen_cambios_en_sheets(datos_sheets, tipo_meta):
    """
    Compara el hash de los datos actuales de Sheets con el guardado en sync_metas_log.txt
    """
    archivo_log = LOG_FILE

    # 1. Convertir los datos a un string y generar la huella digital (Hash)
    datos_string = json.dumps(datos_sheets, sort_keys=True).encode("utf-8")
    hash_actual = hashlib.md5(datos_string).hexdigest()

    # 2. Leer el hash anterior guardado en el log
    hash_guardado = ""
    if os.path.exists(archivo_log):
        with open(archivo_log, "r") as f:
            lineas = f.readlines()
            for linea in lineas:
                if linea.startswith(tipo_meta):
                    hash_guardado = linea.split(":")[1].strip()

    # 3. Comparar huellas
    if hash_actual == hash_guardado:
        return False  # No hay cambios

    # 4. Si hay cambios, actualizar el archivo log con el nuevo hash
    lineas_nuevas = []
    actualizado = False
    if os.path.exists(archivo_log):
        with open(archivo_log, "r") as f:
            lineas_nuevas = f.readlines()

    with open(archivo_log, "w") as f:
        for i, linea in enumerate(lineas_nuevas):
            if linea.startswith(tipo_meta):
                lineas_nuevas[i] = f"{tipo_meta}:{hash_actual}\n"
                actualizado = True
        if not actualizado:
            lineas_nuevas.append(f"{tipo_meta}:{hash_actual}\n")

        f.writelines(lineas_nuevas)

    return True  # Sí hay cambios, se debe hacer el INSERT/UPDATE en SQL


def run_sync_metas(db_config):
    """
    Sincroniza metas diarias.
    Condiciones: A partir de las 10:00 AM, una vez al día, celdas 100% llenas.
    """
    now = datetime.now()

    # CANDADO 1: A partir de las 10 AM
    if now.hour < 10:
        return

    # CANDADO 2: ¿Ya se ejecutó exitosamente hoy?
    fecha_hoy = now.strftime("%Y-%m-%d")
    if os.path.exists(DATE_LOG_FILE):
        with open(DATE_LOG_FILE, "r") as f:
            if f.read().strip() == fecha_hoy:
                return  # Ya se corrió hoy de forma exitosa

    # 3. Autenticarse y Leer Hoja 2
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
        client = gspread.authorize(creds)
        hoja_metas = client.open(SPREADSHEET_NAME).worksheet("Hoja 2")
        data = hoja_metas.get("H3:M15")
    except Exception as e:
        print(
            f"[{now.strftime('%H:%M:%S')}] ❌ Error leyendo GSheets (Metas Diarias): {e}"
        )
        return

    # CANDADO 3: Validar que no haya celdas vacías (Rango H3:M15)
    for row in data:
        if len(row) < 6 or any(str(cell).strip() == "" for cell in row):
            # No imprimimos error para no saturar la consola cada 2 minutos.
            # Simplemente se aborta y espera al siguiente ciclo del daemon.
            return

    # 4. CONTROL DE CAMBIOS (HASH)
    if not existen_cambios_en_sheets(data, "diario"):
        return

    # 5. Insertar en SQL Server
    try:
        print(
            f"[{now.strftime('%H:%M:%S')}] ⚡ Tabla llena detectada. Sincronizando metas diarias hacia SQL..."
        )

        conn = pyodbc.connect(db_config)
        cursor = conn.cursor()

        # Limpiar datos del día para evitar duplicados en caso de error
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

        # SELLADO DEL DÍA: Solo se marca la fecha SI la tabla estaba llena y se insertó
        with open(DATE_LOG_FILE, "w") as f:
            f.write(fecha_hoy)

        print(
            f"[{now.strftime('%H:%M:%S')}] ✅ Metas diarias sincronizadas exitosamente en SQL Server."
        )

    except Exception as e:
        print(f"[{now.strftime('%H:%M:%S')}] ❌ Error en SQL (Metas Diarias): {e}")
