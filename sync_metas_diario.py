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

    if now.weekday() == 6:
        return

    # =========================================================
    # 1. BLOQUE DE LAS 6 AM a 9:59 AM: LIMPIEZA AUTOMÁTICA
    # =========================================================
    if 6 <= now.hour < 10:
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

                # 1. LEER EL BOTÓN EN EL ARCHIVO MAESTRO
                doc_maestro = client.open(config.SPREADSHEET_NAME)
                pestana_borrar = config.CELDA_AUTOELIMINAR_DIARIO.split("!")[0]
                celda_borrar = config.CELDA_AUTOELIMINAR_DIARIO.split("!")[1]
                estado_boton_borrar = (
                    doc_maestro.worksheet(pestana_borrar).acell(celda_borrar).value
                )

                # 2. CONECTAR AL ARCHIVO DE PROYECCIONES PARA BORRAR
                doc_proyeccion = client.open_by_key(config.SHEET_PROYECCION_ID)
                hoja_proyeccion = doc_proyeccion.worksheet(config.PROY_PESTANA)

                if str(estado_boton_borrar).upper() == "TRUE":
                    # LECTURA DINÁMICA DE AGENCIAS
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
                    actualizaciones_estado = [
                        {
                            "range": config.PROY_MSJ_ESTADO_1,
                            "values": [
                                [
                                    f"🧹 Datos eliminados automáticamente a las: {now.strftime('%H:%M:%S')}"
                                ]
                            ],
                        },
                        {
                            "range": config.PROY_MSJ_ESTADO_2,
                            "values": [["⏳ Esperando metas..."]],
                        },
                    ]
                    hoja_proyeccion.batch_update(actualizaciones_estado)
                    print(
                        f"[{now.strftime('%H:%M:%S')}] 🧹 Rango {rango_borrado} limpiado. Control remoto desde archivo maestro."
                    )
                else:
                    actualizaciones_estado = [
                        {
                            "range": config.PROY_MSJ_ESTADO_1,
                            "values": [
                                [
                                    f"⏸️ Borrado omitido. El botón de seguridad en el archivo maestro está apagado ({now.strftime('%H:%M:%S')})"
                                ]
                            ],
                        }
                    ]
                    hoja_proyeccion.batch_update(actualizaciones_estado)
                    print(
                        f"[{now.strftime('%H:%M:%S')}] ⏸️ Borrado cancelado por botón de seguridad."
                    )

                with open(config.LOG_LIMPIEZA, "w") as f:
                    f.write(fecha_hoy)
            except Exception as e:
                print(f"[{now.strftime('%H:%M:%S')}] ❌ Error en limpieza remota: {e}")

    # =========================================================
    # 2. BLOQUE DE LAS 10 AM: INSERCIÓN A SQL SERVER
    # =========================================================
    if now.hour < 10:
        return

    if os.path.exists(config.LOG_FECHA_DIARIA):
        with open(config.LOG_FECHA_DIARIA, "r") as f:
            if f.read().strip() == fecha_hoy:
                return

    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            config.CREDS_FILE, config.SCOPE
        )
        client = gspread.authorize(creds)
        doc_maestro = client.open(config.SPREADSHEET_NAME)

        # ==========================================
        # NUEVO: LECTURA DEL BOTÓN DE AUTO-INSERCIÓN
        # ==========================================
        pestana_insertar = config.CELDA_AUTOINSERTAR_DIARIO.split("!")[0]
        celda_insertar = config.CELDA_AUTOINSERTAR_DIARIO.split("!")[1]
        estado_boton_insertar = (
            doc_maestro.worksheet(pestana_insertar).acell(celda_insertar).value
        )

        # Si el usuario apagó la inserción automática, el daemon se detiene aquí silenciosamente.
        if str(estado_boton_insertar).upper() != "TRUE":
            return

        # Si está encendido, procedemos a leer la hoja de metas (Hoja 2)
        hoja_nombre = config.RANGO_LEER_METAS_DIAR.split("!")[0]
        rango_exacto = config.RANGO_LEER_METAS_DIAR.split("!")[1]
        hoja_metas = doc_maestro.worksheet(hoja_nombre)
        data = hoja_metas.get(rango_exacto)
    except Exception as e:
        print(
            f"[{now.strftime('%H:%M:%S')}] ❌ Error leyendo GSheets (Permisos o Botón): {e}"
        )
        return

    # LECTURA INFINITA: Filtramos solo las filas válidas y obviamos los totales
    datos_validos = []
    for row in data:
        if not row or str(row[0]).strip() == "" or "TOTAL" in str(row[0]).upper():
            continue
        if len(row) >= 6 and not any(str(cell).strip() == "" for cell in row[:6]):
            datos_validos.append(row[:6])

    if len(datos_validos) == 0 or not existen_cambios_en_sheets(
        datos_validos, "diario"
    ):
        return

    try:
        print(
            f"[{now.strftime('%H:%M:%S')}] ⚡ {len(datos_validos)} Metas diarias detectadas. Botón Inserción ON. Sincronizando..."
        )
        conn = pyodbc.connect(config.DB_DWH)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM [dm_productividad].[dbo].[FctDiario_MetaProy] WHERE Fecha = ?",
            fecha_hoy,
        )

        insert_sql = "INSERT INTO [dm_productividad].[dbo].[FctDiario_MetaProy] ([Fecha], [IdSAgencia], [ColocacionNumMeta], [ColocacionNumProy], [ColocacionMontoMeta], [ColocacionMontoProy]) VALUES (?, ?, ?, ?, ?, ?)"
        for row in datos_validos:
            cursor.execute(insert_sql, row)

        conn.commit()
        conn.close()

        with open(config.LOG_FECHA_DIARIA, "w") as f:
            f.write(fecha_hoy)
        print(f"[{now.strftime('%H:%M:%S')}] ✅ Metas diarias guardadas en SQL.")

        # Escribir el mensaje de éxito en el archivo de proyecciones
        try:
            doc_proyeccion = client.open_by_key(config.SHEET_PROYECCION_ID)
            hoja_proyeccion = doc_proyeccion.worksheet(config.PROY_PESTANA)
            actualizaciones = [
                {
                    "range": config.PROY_MSJ_ESTADO_1,
                    "values": [
                        [
                            f"✅ Metas diarias guardadas en SQL: {now.strftime('%d/%m/%Y %H:%M:%S')}"
                        ]
                    ],
                },
                {"range": config.PROY_MSJ_ESTADO_2, "values": [[""]]},
            ]
            hoja_proyeccion.batch_update(actualizaciones)
        except Exception as error_sheet:
            pass
    except Exception as e:
        print(f"[{now.strftime('%H:%M:%S')}] ❌ Error en SQL: {e}")
