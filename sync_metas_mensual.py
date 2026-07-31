import os
import pyodbc
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import hashlib
import json

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
CREDS_FILE = "credenciales.json"
SPREADSHEET_NAME = "Reporte_Productividad_En_Vivo"
SHEET_TAB_NAME = "Hoja 1"
LOG_FILE = "sync_metas_log.txt"


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

    return True


def clean_number(val):
    try:
        if str(val).strip() == "":
            return 0
        return float(str(val).replace(",", "").replace(" ", "").replace("S/", ""))
    except:
        return 0


def run_sync_metas_mensual(db_config_dwh):
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open(SPREADSHEET_NAME).worksheet(SHEET_TAB_NAME)

        # Leemos el bloque exacto K2:U14
        data = sheet.get("K2:U14")

        # === CONTROL DE CAMBIOS (HASH DELTA CHECK) ===
        # Validamos usando la etiqueta "mensual"
        if not existen_cambios_en_sheets(data, "mensual"):
            return  # Saliendo silenciosamente, no hay cambios desde hace 3 días

        print(
            f"[{time.strftime('%H:%M:%S')}] ⚡ Cambio detectado en Google Sheets (Metas Mensuales). Sincronizando hacia SQL..."
        )

        for row in data:
            while len(row) < 11:
                row.append("")

        columnas = [
            "Periodo",
            "IdSAgencia",
            "Agencia",
            "ColocacionNumMeta",
            "ColocacionNumMetaAjus",
            "ColocacionMontoMeta",
            "ColocacionMontoMetaAjus",
            "NumeroAsesores",
            "NumeroAsesoresAjus",
            "CrecimientoMeta",
            "CrecimientoMetaAjus",
        ]

        df_metas = pd.DataFrame(data, columns=columnas)

        # === GUARDAR BACKUP HISTÓRICO EN TXT ===
        fecha_legible = time.strftime("%d/%m/%Y %H:%M:%S")
        nombre_archivo = "historial_metas_mensual.txt"

        # Usamos "a" (append) para agregar el texto al final sin borrar lo anterior
        with open(nombre_archivo, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"CAMBIO DE METAS DETECTADO EL: {fecha_legible}\n")
            f.write(f"{'='*80}\n")
            # to_string(index=False) dibuja una tabla de texto alineada con espacios
            f.write(df_metas.to_string(index=False))
            f.write("\n\n")

        print(
            f"[{time.strftime('%H:%M:%S')}] 📁 Registro de cambio agregado en: {nombre_archivo}"
        )

        # === INSERCIÓN SEGURA EN SQL SERVER ===
        # Obtenemos el periodo de la hoja (K2) para acotar la consulta
        periodo_actual = str(df_metas.iloc[0]["Periodo"]).strip()

        conn = pyodbc.connect(db_config_dwh)
        cursor = conn.cursor()

        # Protegemos el histórico: Borramos UNICAMENTE el periodo_actual detectado en K2
        cursor.execute(
            "DELETE FROM [dm_productividad].[dbo].[FctMensual] WHERE [Periodo] = ?",
            periodo_actual,
        )

        insert_sql = """
        INSERT INTO [dm_productividad].[dbo].[FctMensual] 
        ([Periodo], [IdSAgencia], [ColocacionNumMeta], [ColocacionNumMetaAjus], 
         [ColocacionMontoMeta], [ColocacionMontoMetaAjus], [NumeroAsesores], 
         [NumeroAsesoresAjus], [CrecimientoMetaAjus])
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        for index, row in df_metas.iterrows():
            if str(row["IdSAgencia"]).strip() == "":
                continue

            valores_fila = (
                str(row["Periodo"]).strip(),
                str(row["IdSAgencia"]).strip(),
                clean_number(row["ColocacionNumMeta"]),
                clean_number(row["ColocacionNumMetaAjus"]),
                clean_number(row["ColocacionMontoMeta"]),
                clean_number(row["ColocacionMontoMetaAjus"]),
                clean_number(row["NumeroAsesores"]),
                clean_number(row["NumeroAsesoresAjus"]),
                clean_number(row["CrecimientoMetaAjus"]),
            )
            cursor.execute(insert_sql, valores_fila)

        conn.commit()
        conn.close()

        print(
            f"[{time.strftime('%H:%M:%S')}] ✅ Base de datos SQL actualizada con las nuevas metas del periodo {periodo_actual}."
        )

    except Exception as e:
        print(
            f"[{time.strftime('%H:%M:%S')}] ❌ Error crítico en sync_metas_mensual: {e}"
        )
