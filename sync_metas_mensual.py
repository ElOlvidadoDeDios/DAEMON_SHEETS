import os
import pyodbc
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import hashlib

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
CREDS_FILE = "credenciales.json"
SPREADSHEET_NAME = "Reporte_Productividad_En_Vivo"
SHEET_TAB_NAME = "Hoja 1"

ULTIMO_HASH_METAS = None


def get_data_hash(df):
    return hashlib.md5(df.to_csv(index=False).encode()).hexdigest()


def clean_number(val):
    try:
        if str(val).strip() == "":
            return 0
        return float(str(val).replace(",", "").replace(" ", "").replace("S/", ""))
    except:
        return 0


def run_sync_metas_mensual(db_config_dwh):
    global ULTIMO_HASH_METAS

    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
        client = gspread.authorize(creds)
        sheet = client.open(SPREADSHEET_NAME).worksheet(SHEET_TAB_NAME)

        # Leemos el bloque exacto K2:U14
        data = sheet.get("K2:U14")

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
        hash_actual = get_data_hash(df_metas)

        if hash_actual == ULTIMO_HASH_METAS:
            return

        print(
            f"[{time.strftime('%H:%M:%S')}] ⚡ Cambio detectado en Google Sheets (Metas Mensuales). Sincronizando hacia SQL..."
        )

        if ULTIMO_HASH_METAS is not None:
            fecha_log = time.strftime("%Y%m%d_%H%M%S")
            nombre_archivo = f"historial_metas/cambio_metas_mensual_{fecha_log}.csv"
            if not os.path.exists("historial_metas"):
                os.makedirs("historial_metas")
            df_metas.to_csv(nombre_archivo, index=False)
            print(
                f"[{time.strftime('%H:%M:%S')}] 📁 Registro de cambio guardado en: {nombre_archivo}"
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

        ULTIMO_HASH_METAS = hash_actual
        print(
            f"[{time.strftime('%H:%M:%S')}] ✅ Base de datos SQL actualizada con las nuevas metas del periodo {periodo_actual}."
        )

    except Exception as e:
        print(
            f"[{time.strftime('%H:%M:%S')}] ❌ Error crítico en sync_metas_mensual: {e}"
        )
