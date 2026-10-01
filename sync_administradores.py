import pyodbc
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import config
import hashlib
import json
import os


def existen_cambios_admin(datos):
    archivo_log = os.path.join(config.CARPETA_LOGS, "sync_admin_hash.txt")
    datos_string = json.dumps(datos, sort_keys=True).encode("utf-8")
    hash_actual = hashlib.md5(datos_string).hexdigest()

    hash_guardado = ""
    if os.path.exists(archivo_log):
        with open(archivo_log, "r") as f:
            hash_guardado = f.read().strip()

    if hash_actual == hash_guardado:
        return False

    with open(archivo_log, "w") as f:
        f.write(hash_actual)
    return True


def run_sync_administradores():
    try:
        data = None
        for intento in range(3):
            try:
                creds = ServiceAccountCredentials.from_json_keyfile_name(
                    config.CREDS_FILE, config.SCOPE
                )
                client = gspread.authorize(creds)

                hoja_nombre = config.RANGO_LEER_ADMIN.split("!")[0]
                rango_exacto = config.RANGO_LEER_ADMIN.split("!")[1]
                sheet = client.open(config.SPREADSHEET_NAME).worksheet(hoja_nombre)

                data = sheet.get(rango_exacto)
                break
            except Exception as e:
                if intento < 2:
                    time.sleep(10)
                else:
                    raise e

        if not data:
            return

        datos_validos = []
        for row in data:
            # Ignoramos si la fila está vacía o si en el periodo no hay nada (evita la fila del Jefe comercial)
            if not row or str(row[0]).strip() == "" or "JEFE" in str(row[0]).upper():
                continue

            # De la J a la X hay 15 columnas. Rellenamos con vacíos si Google Sheets las corta.
            while len(row) < 15:
                row.append("")

            # Guardamos la fila completa estandarizada a 15 espacios
            datos_validos.append(row[:15])

        if len(datos_validos) == 0 or not existen_cambios_admin(datos_validos):
            return

        print(
            f"[{time.strftime('%H:%M:%S')}] ⚡ Cambio detectado en Tabla Administradores. Sincronizando..."
        )

        conn = pyodbc.connect(config.DB_DWH)
        cursor = conn.cursor()

        periodo_actual = str(datos_validos[0][0]).strip()
        cursor.execute(
            "DELETE FROM [DWH_Gestion_Cartera].[dbo].[dim_administrador] WHERE [Periodo] = ?",
            periodo_actual,
        )

        insert_sql = """
            INSERT INTO [DWH_Gestion_Cartera].[dbo].[dim_administrador] 
            ([Periodo], [IdSAgencia], [Nombre], [Celular], [CorreoPersonal], [CorreoCorporativo]) 
            VALUES (?, ?, ?, ?, ?, ?)
        """

        for row in datos_validos:
            # MAPEO EXACTO DE COLUMNAS SEGÚN TUS COORDENADAS
            periodo = str(row[0]).strip()  # Columna J (0)
            id_agencia = str(row[1]).strip()  # Columna K (1)
            # row[2] es Agencia (L), no lo insertamos
            nombre = str(row[3]).strip()  # Columna M (3) - Inicio de combinada
            celular = str(row[8]).strip()  # Columna R (8)
            correo_pers = str(row[9]).strip()  # Columna S (9) - Inicio de combinada
            correo_corp = str(row[12]).strip()  # Columna V (12) - Inicio de combinada

            cursor.execute(
                insert_sql,
                (periodo, id_agencia, nombre, celular, correo_pers, correo_corp),
            )

        conn.commit()
        conn.close()
        print(
            f"[{time.strftime('%H:%M:%S')}] ✅ Tabla de Administradores actualizada en SQL."
        )

    except Exception as e:
        print(
            f"[{time.strftime('%H:%M:%S')}] ❌ Error sincronizando Administradores: {e}"
        )
