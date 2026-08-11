import os
import pyodbc
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import config

# Reutilizamos la función del diario o la traemos
from sync_metas_diario import existen_cambios_en_sheets


def clean_number(val):
    try:
        if str(val).strip() == "":
            return 0
        return float(str(val).replace(",", "").replace(" ", "").replace("S/", ""))
    except:
        return 0


def run_sync_metas_mensual():
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            config.CREDS_FILE, config.SCOPE
        )
        client = gspread.authorize(creds)
        sheet = client.open(config.SPREADSHEET_NAME).worksheet("Hoja 1")
        data = sheet.get("K2:U14")

        if not existen_cambios_en_sheets(data, "mensual"):
            return

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

        fecha_legible = time.strftime("%d/%m/%Y %H:%M:%S")
        with open(config.LOG_HISTORIAL_MENSUAL, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"CAMBIO DE METAS DETECTADO EL: {fecha_legible}\n")
            f.write(f"{'='*80}\n")
            f.write(df_metas.to_string(index=False))
            f.write("\n\n")

        print(
            f"[{time.strftime('%H:%M:%S')}] 📁 Registro de cambio agregado en historial."
        )

        periodo_actual = str(df_metas.iloc[0]["Periodo"]).strip()
        conn = pyodbc.connect(config.DB_DWH)
        cursor = conn.cursor()

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
