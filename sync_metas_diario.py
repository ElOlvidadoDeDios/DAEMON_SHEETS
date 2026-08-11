import hashlib
import json
import time
import os
from datetime import datetime
import pyodbc
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import config


def existen_cambios_en_sheets(datos_sheets, tipo_meta):
    archivo_log = config.LOG_METAS
    datos_string = json.dumps(datos_sheets, sort_keys=True).encode("utf-8")
    hash_actual = hashlib.md5(datos_string).hexdigest()

    hash_guardado = ""
    if os.path.exists(archivo_log):
        with open(archivo_log, "r") as f:
            for linea in f.readlines():
                if linea.startswith(tipo_meta):
                    hash_guardado = linea.split(":")[1].strip()

    if hash_actual == hash_guardado:
        return False

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


def run_sync_metas():
    now = datetime.now()
    fecha_hoy = now.strftime("%Y-%m-%d")

    # =========================================================
    # 0. FILTRO DE DOMINGOS
    # =========================================================
    # Si es Domingo (weekday() == 6) el robot descansa...
    if now.weekday() == 6:
        return  # Se aborta toda la sincronización del día en silencio

    # =========================================================
    # 1. BLOQUE DE LAS 6 AM a 9:59 AM: LIMPIEZA AUTOMÁTICA
    # =========================================================
    # Solo se permite limpiar en la ventana de 6:00 AM a 9:59 AM
    if 6 <= now.hour < 10:
        # Verificamos si ya se hizo la limpieza de hoy (El estado de borrado)
        ya_limpiado = False
        if os.path.exists(config.LOG_LIMPIEZA):
            with open(config.LOG_LIMPIEZA, "r") as f:
                if f.read().strip() == fecha_hoy:
                    ya_limpiado = True

        if not ya_limpiado:
            try:
                creds = ServiceAccountCredentials.from_json_keyfile_name(
                    config.CREDS_FILE, config.SCOPE
                )
                client = gspread.authorize(creds)
                doc_proyeccion = client.open_by_key(config.SHEET_PROYECCION_ID)

                hoja_proyeccion = doc_proyeccion.worksheet("Metas_Proyecciones")

                # 1. Borramos el rango indicado
                hoja_proyeccion.batch_clear(["D3:E15"])

                # 2. Escribimos los mensajes de estado
                actualizaciones_estado = [
                    {
                        "range": "A36",
                        "values": [
                            [
                                f"🧹 Datos eliminados automáticamente a las: {now.strftime('%H:%M:%S')}"
                            ]
                        ],
                    },
                    {"range": "A37", "values": [["⏳ Esperando metas..."]]},
                ]
                hoja_proyeccion.batch_update(actualizaciones_estado)

                # 3. Guardamos el sello de tiempo para no volver a borrar hoy
                with open(config.LOG_LIMPIEZA, "w") as f:
                    f.write(fecha_hoy)

                print(
                    f"[{now.strftime('%H:%M:%S')}] 🧹 Rango D3:E15 limpiado en Google Sheets. Modo 'Esperando metas' activado."
                )
            except Exception as e:
                print(
                    f"[{now.strftime('%H:%M:%S')}] ❌ Error en limpieza de la mañana: {e}"
                )

    # =========================================================
    # 2. BLOQUE DE LAS 10 AM: INSERCIÓN A SQL SERVER
    # =========================================================
    # Si aún no son las 10 AM, el robot no hace nada más.
    if now.hour < 10:
        return

    # Si ya se subieron las metas hoy, no hacemos nada más.
    if os.path.exists(config.LOG_FECHA_DIARIA):
        with open(config.LOG_FECHA_DIARIA, "r") as f:
            if f.read().strip() == fecha_hoy:
                return

    # Intentamos leer la hoja (Si a las 6PM se borró, esto fallará los filtros de abajo y no hará nada)
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            config.CREDS_FILE, config.SCOPE
        )
        client = gspread.authorize(creds)
        hoja_metas = client.open(config.SPREADSHEET_NAME).worksheet("Hoja 2")
        data = hoja_metas.get("H3:M15")
    except Exception as e:
        print(
            f"[{now.strftime('%H:%M:%S')}] ❌ Error leyendo GSheets (Metas Diarias): {e}"
        )
        return

    # Validamos que no haya celdas vacías (si se borró a las 6PM, el script morirá aquí silenciosamente)
    for row in data:
        if len(row) < 6 or any(str(cell).strip() == "" for cell in row):
            return

    # Control de cambios por hash
    if not existen_cambios_en_sheets(data, "diario"):
        return

    try:
        print(
            f"[{now.strftime('%H:%M:%S')}] ⚡ Tabla llena detectada. Sincronizando metas diarias hacia SQL..."
        )
        conn = pyodbc.connect(config.DB_DWH)
        cursor = conn.cursor()

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

        # Sello de inserción en SQL exitosa
        with open(config.LOG_FECHA_DIARIA, "w") as f:
            f.write(fecha_hoy)

        print(
            f"[{now.strftime('%H:%M:%S')}] ✅ Metas diarias sincronizadas exitosamente en SQL Server."
        )

        # =========================================================
        # 3. CONFIRMACIÓN EN SHEETS (Y BORRADO DEL "ESPERANDO METAS")
        # =========================================================
        try:
            doc_proyeccion = client.open_by_key(config.SHEET_PROYECCION_ID)

            # ¡OJO AQUÍ! Cambia "Nombre De Tu Pestaña" por el real
            hoja_proyeccion = doc_proyeccion.worksheet("Metas_Proyecciones")

            mensaje_exito = f"✅ Metas diarias guardadas en SQL: {now.strftime('%d/%m/%Y %H:%M:%S')}"

            # Escribimos el éxito en A1 y le mandamos un texto vacío ("") a A2 para borrar el "Esperando metas..."
            actualizaciones = [
                {"range": "A36", "values": [[mensaje_exito]]},
                {"range": "A37", "values": [[""]]},
            ]
            hoja_proyeccion.batch_update(actualizaciones)

        except Exception as error_sheet:
            print(
                f"[{now.strftime('%H:%M:%S')}] ⚠️ SQL actualizado, pero falló el mensaje en Sheets: {error_sheet}"
            )

    except Exception as e:
        print(f"[{now.strftime('%H:%M:%S')}] ❌ Error en SQL (Metas Diarias): {e}")
