# sync_metas_diario.py

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


def run_sync_metas(permitir_borrado, permitir_insercion, manual_forzado=False):
    now = datetime.now()
    fecha_hoy = now.strftime("%Y-%m-%d")

    if now.weekday() == 6 and not manual_forzado:
        return

    # =========================================================
    # 1. BLOQUE DE LIMPIEZA AUTOMÁTICA
    # =========================================================
    if 6 <= now.hour < 10 and not manual_forzado:
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
                hoja_proyeccion = doc_proyeccion.worksheet(config.PROY_PESTANA)

                if permitir_borrado:
                    col_agencias = hoja_proyeccion.get(f"C{config.PROY_FILA_INICIO}:C")
                    num_agencias = 0
                    for fila in col_agencias:
                        if fila and "TOTAL" not in str(fila[0]).upper():
                            num_agencias += 1
                        else:
                            break

                    fila_fin_borrado = config.PROY_FILA_INICIO + num_agencias - 1
                    rango_borrado = f"{config.PROY_COL_LIMPIAR_INI}{config.PROY_FILA_INICIO}:{config.PROY_COL_LIMPIAR_FIN}{fila_fin_borrado}"

                    hoja_proyeccion.batch_clear([rango_borrado])

                    # LOG DE LIMPIEZA DIRECTO
                    hoja_proyeccion.update_acell(
                        config.PROY_MSJ_ESTADO_1,
                        f"🧹 Datos eliminados automáticamente a las: {now.strftime('%H:%M:%S')}",
                    )
                    hoja_proyeccion.update_acell(
                        config.PROY_MSJ_ESTADO_2, "⏳ Esperando metas..."
                    )

                    print(
                        f"[{now.strftime('%H:%M:%S')}] 🧹 Rango {rango_borrado} limpiado."
                    )
                else:
                    # LOG DE OMISIÓN DIRECTO
                    hoja_proyeccion.update_acell(
                        config.PROY_MSJ_ESTADO_1,
                        f"⏸️ Borrado cancelado por botón maestro ({now.strftime('%H:%M:%S')}).",
                    )
                    print(
                        f"[{now.strftime('%H:%M:%S')}] ⏸️ Borrado cancelado por botón maestro."
                    )

                with open(config.LOG_LIMPIEZA, "w") as f:
                    f.write(fecha_hoy)
            except Exception as e:
                print(f"[{now.strftime('%H:%M:%S')}] ❌ Error en limpieza: {e}")

    # =========================================================
    # 2. INSERCIÓN A SQL SERVER Y LOGS (Evolutiva)
    # =========================================================

    # Si no es manual, y aún no son las 10 AM (o el botón general está apagado), abortamos.
    if not manual_forzado:
        if now.hour < 10 or not permitir_insercion:
            return

    # 1. Leemos GSheets
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            config.CREDS_FILE, config.SCOPE
        )
        client = gspread.authorize(creds)
        hoja_metas = client.open(config.SPREADSHEET_NAME).worksheet(
            config.RANGO_LEER_METAS_DIAR.split("!")[0]
        )
        rango_exacto = config.RANGO_LEER_METAS_DIAR.split("!")[1]
        data = hoja_metas.get(rango_exacto)
    except Exception as e:
        print(
            f"[{now.strftime('%H:%M:%S')}] ❌ Error leyendo GSheets (Metas Diarias): {e}"
        )
        return

    # 2. Validamos los datos leídos
    datos_validos = []
    for row in data:
        if not row or str(row[0]).strip() == "" or "TOTAL" in str(row[0]).upper():
            continue
        if len(row) >= 6 and not any(str(cell).strip() == "" for cell in row[:6]):
            datos_validos.append(row[:6])

    if len(datos_validos) == 0:
        return

    # 3. VERIFICACIÓN DE HASH: ¿Alguien añadió o cambió un dato desde la última vez?
    cambios_detectados = existen_cambios_en_sheets(datos_validos, "diario")

    # Si es automático y no hay cambios nuevos, el robot se cruza de brazos y no gasta SQL
    if not manual_forzado and not cambios_detectados:
        return

    # 4. INSERCIÓN: Si hay cambios (ej. una agencia rezagada llenó sus datos), actualizamos SQL
    try:
        tipo_ejecucion = (
            "FORZADA (Manual)" if manual_forzado else "Evolutiva (Cambio detectado)"
        )
        print(
            f"[{now.strftime('%H:%M:%S')}] ⚡ {len(datos_validos)} Metas diarias. Ejecución {tipo_ejecucion}. Sincronizando..."
        )

        conn = pyodbc.connect(config.DB_DWH)
        cursor = conn.cursor()

        # Borra lo que había hoy para no duplicar, y vuelve a insertar la lista actualizada
        cursor.execute(
            "DELETE FROM [dm_productividad].[dbo].[FctDiario_MetaProy] WHERE Fecha = ?",
            fecha_hoy,
        )

        insert_sql = "INSERT INTO [dm_productividad].[dbo].[FctDiario_MetaProy] ([Fecha], [IdSAgencia], [ColocacionNumMeta], [ColocacionNumProy], [ColocacionMontoMeta], [ColocacionMontoProy]) VALUES (?, ?, ?, ?, ?, ?)"
        for row in datos_validos:
            cursor.execute(insert_sql, row)

        conn.commit()
        conn.close()

        # Opcional: Escribimos log visual en Google Sheets
        try:
            doc_proyeccion = client.open_by_key(config.SHEET_PROYECCION_ID)
            hoja_proyeccion = doc_proyeccion.worksheet(config.PROY_PESTANA)
            mensaje = f"✅ Metas guardadas ({len(datos_validos)} agencias): {now.strftime('%d/%m/%Y %H:%M:%S')}"
            hoja_proyeccion.update_acell(config.PROY_MSJ_ESTADO_1, mensaje)
        except Exception:
            pass  # Si falla el log visual, no detenemos el proceso

    except Exception as e:
        print(f"[{now.strftime('%H:%M:%S')}] ❌ Error en SQL (Metas): {e}")

        # ==========================================
        # ESCRITURA DEL LOG VISUAL EN GOOGLE SHEETS
        # ==========================================
        try:
            doc_proyeccion = client.open_by_key(config.SHEET_PROYECCION_ID)
            hoja_proyeccion = doc_proyeccion.worksheet(config.PROY_PESTANA)

            mensaje = f"✅ Metas guardadas en SQL: {now.strftime('%d/%m/%Y %H:%M:%S')} - {tipo_ejecucion}"

            # Usando .update_acell que es más directo y menos propenso a fallar por formatos
            hoja_proyeccion.update_acell(config.PROY_MSJ_ESTADO_1, mensaje)
            hoja_proyeccion.update_acell(config.PROY_MSJ_ESTADO_2, "")

            print(
                f"[{now.strftime('%H:%M:%S')}] 📝 Log visual actualizado en Google Sheets."
            )
        except Exception as error_sheet:
            print(
                f"[{now.strftime('%H:%M:%S')}] ⚠️ Error escribiendo log en Sheets: {error_sheet}"
            )

    except Exception as e:
        print(f"[{now.strftime('%H:%M:%S')}] ❌ Error en SQL: {e}")
