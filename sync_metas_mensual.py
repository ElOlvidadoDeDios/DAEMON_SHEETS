# sync_metas_mensuales.py

import pyodbc
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import config
from sync_metas_diario import existen_cambios_en_sheets
from datetime import datetime
import os


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

        hoja_nombre = config.RANGO_LEER_METAS_MENS.split("!")[0]
        rango_exacto = config.RANGO_LEER_METAS_MENS.split("!")[1]

        sheet = client.open(config.SPREADSHEET_NAME).worksheet(hoja_nombre)
        data = sheet.get(rango_exacto)

        datos_validos = []
        for row in data:
            if not row or len(row) < 2:
                continue

            # EL FRENO DE EMERGENCIA (Ignora a los administradores)
            if "TOTAL" in str(row[2]).upper():
                break

            if str(row[1]).strip() == "":
                continue

            while len(row) < 11:
                row.append("")
            datos_validos.append(row[:11])

        if len(datos_validos) == 0 or not existen_cambios_en_sheets(
            datos_validos, "mensual"
        ):
            return

        print(
            f"[{time.strftime('%H:%M:%S')}] ⚡ Cambio detectado en Google Sheets ({len(datos_validos)} Agencias). Sincronizando..."
        )

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
        df_metas = pd.DataFrame(datos_validos, columns=columnas)

        fecha_legible = time.strftime("%d/%m/%Y %H:%M:%S")
        with open(config.LOG_HISTORIAL_MENSUAL, "a", encoding="utf-8") as f:
            f.write(
                f"\n{'='*80}\nCAMBIO DE METAS DETECTADO EL: {fecha_legible}\n{'='*80}\n"
            )
            f.write(df_metas.to_string(index=False))
            f.write("\n\n")

        periodo_actual = str(df_metas.iloc[0]["Periodo"]).strip()
        conn = pyodbc.connect(config.DB_DWH)
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM [dm_productividad].[dbo].[FctMensual] WHERE [Periodo] = ?",
            periodo_actual,
        )

        insert_sql = "INSERT INTO [dm_productividad].[dbo].[FctMensual] ([Periodo], [IdSAgencia], [ColocacionNumMeta], [ColocacionNumMetaAjus], [ColocacionMontoMeta], [ColocacionMontoMetaAjus], [NumeroAsesores], [NumeroAsesoresAjus], [CrecimientoMetaAjus]) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"

        for index, row in df_metas.iterrows():
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
            f"[{time.strftime('%H:%M:%S')}] ✅ BD SQL actualizada con las nuevas metas ({periodo_actual})."
        )

    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Error crítico en mensual: {e}")


def verificar_y_limpiar_cambio_mes():
    now = datetime.now()
    mes_actual_real = now.strftime("%Y%m")  # Ej: "202608"

    # 1. Leemos cuál fue el último mes que el robot limpió
    mes_limpiado = ""
    if os.path.exists(config.LOG_LIMPIEZA_MENSUAL):
        with open(config.LOG_LIMPIEZA_MENSUAL, "r") as f:
            mes_limpiado = f.read().strip()

    # 2. Si ya estamos al día, abortamos en silencio
    if mes_actual_real == mes_limpiado:
        return

    # 3. Si parece un cambio de mes (o es la primera vez que se ejecuta el código):
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            config.CREDS_FILE, config.SCOPE
        )
        client = gspread.authorize(creds)

        pestana = config.RANGO_LEER_METAS_MENS.split("!")[0]
        sheet = client.open(config.SPREADSHEET_NAME).worksheet(pestana)

        # ==========================================
        # 🛡️ PROTECCIÓN DE PRIMER ARRANQUE
        # ==========================================
        if mes_limpiado == "":
            periodo_excel = str(
                sheet.acell(f"{config.MENS_COL_PERIODO}{config.MENS_FILA_INICIO}").value
            ).strip()

            if periodo_excel == mes_actual_real:
                # El Excel YA ESTÁ en el mes correcto. Solo creamos el sello y evitamos el borrado.
                with open(config.LOG_LIMPIEZA_MENSUAL, "w") as f:
                    f.write(mes_actual_real)
                print(
                    f"[{now.strftime('%H:%M:%S')}] 🛡️ Primer arranque detectado. Sello {mes_actual_real} creado sin borrar datos."
                )
                return

        # ==========================================
        # LECTURA DINÁMICA (Protege a los administradores)
        # ==========================================
        col_id_agencia = sheet.get(f"N{config.MENS_FILA_INICIO}:N")
        num_agencias = 0
        for fila in col_id_agencia:
            if fila and "TOTAL" not in str(fila[0]).upper():
                num_agencias += 1
            else:
                break

        if num_agencias == 0:
            return

        fila_fin = config.MENS_FILA_INICIO + num_agencias - 1

        # BORRAR METAS (Columnas P a W)
        rango_borrar = f"{config.MENS_COL_LIMPIAR_INI}{config.MENS_FILA_INICIO}:{config.MENS_COL_LIMPIAR_FIN}{fila_fin}"
        sheet.batch_clear([rango_borrar])

        # ACTUALIZAR PERIODO (Columna M)
        valores_periodo = [[mes_actual_real] for _ in range(num_agencias)]
        rango_periodo = f"{config.MENS_COL_PERIODO}{config.MENS_FILA_INICIO}:{config.MENS_COL_PERIODO}{fila_fin}"
        sheet.batch_update([{"range": rango_periodo, "values": valores_periodo}])

        # GUARDAR EL SELLO
        with open(config.LOG_LIMPIEZA_MENSUAL, "w") as f:
            f.write(mes_actual_real)

        print(
            f"[{now.strftime('%H:%M:%S')}] 🗓️ ¡CAMBIO DE MES DETECTADO! Tabla limpiada y periodo actualizado a {mes_actual_real}."
        )

    except Exception as e:
        print(
            f"[{now.strftime('%H:%M:%S')}] ❌ Error en limpieza de cambio de mes: {e}"
        )
