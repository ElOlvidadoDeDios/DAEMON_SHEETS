# daemon.py

import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import hashlib
import sys
import warnings
import pyodbc
import threading
import re
import config
from sql_queries import QUERY_PRODUCTIVIDAD, QUERY_INCLUSIVOS
import sync_metas_diario
import sync_metas_mensual
import ejecutor_mora

warnings.filterwarnings("ignore")


# ==========================================
# FUNCIONES NÚCLEO PRODUCTIVIDAD
# ==========================================
def get_data_hash(df):
    return hashlib.md5(df.to_csv(index=False).encode()).hexdigest()


# Reemplaza SOLO la función push_to_google_sheets en tu daemon.py actual
def push_to_google_sheets(df, df_anterior, df_inclusivos):
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            config.CREDS_FILE, config.SCOPE
        )
        client = gspread.authorize(creds)
        sheet = client.open(config.SPREADSHEET_NAME).worksheet(config.PROD_PESTANA)

        actualizaciones = []
        filas_df = len(df)
        fila_fin = config.PROD_FILA_INICIO + filas_df - 1

        # 1. Columnas A, B, C (Fechas, Periodo, Agencia)
        datos_abc = df[["Fecha", "Periodo", "NombreAgencia"]].values.tolist()
        rango_abc = f"{config.PROD_COL_FECHA}{config.PROD_FILA_INICIO}:{config.PROD_COL_AGENCIA}{fila_fin}"
        actualizaciones.append({"range": rango_abc, "values": datos_abc})

        # 2. Columna E y G (Reales)
        datos_e = [[val] for val in df["ColocacionNumReal"].tolist()]
        actualizaciones.append(
            {
                "range": f"{config.PROD_COL_NUM_REAL}{config.PROD_FILA_INICIO}:{config.PROD_COL_NUM_REAL}{fila_fin}",
                "values": datos_e,
            }
        )

        datos_g = [[val] for val in df["ColocacionMontoReal"].tolist()]
        actualizaciones.append(
            {
                "range": f"{config.PROD_COL_MONTO_REAL}{config.PROD_FILA_INICIO}:{config.PROD_COL_MONTO_REAL}{fila_fin}",
                "values": datos_g,
            }
        )

        # 3. H1 (Hora) y H2 en adelante (Deltas)
        hora_actual = time.strftime("%d/%m/%Y\n%H:%M:%S")
        actualizaciones.append(
            {
                "range": config.PROD_CELDA_HORA_ACT,
                "values": [[f"Última act:\n{hora_actual}"]],
            }
        )

        datos_deltas = []
        for i in range(filas_df):
            diff_num = (
                df.iloc[i]["ColocacionNumReal"]
                - df_anterior.iloc[i]["ColocacionNumReal"]
                if df_anterior is not None
                else 0
            )
            diff_monto = (
                df.iloc[i]["ColocacionMontoReal"]
                - df_anterior.iloc[i]["ColocacionMontoReal"]
                if df_anterior is not None
                else 0
            )

            str_delta = (
                f"+{int(diff_num)} -> {diff_monto:.2f}".replace(".", ",")
                if (diff_num > 0 or diff_monto > 0)
                else ""
            )
            datos_deltas.append([str_delta])

        actualizaciones.append(
            {
                "range": f"{config.PROD_COL_DELTAS}{config.PROD_FILA_INICIO}:{config.PROD_COL_DELTAS}{fila_fin}",
                "values": datos_deltas,
            }
        )

        # 4. Tabla Inclusivos (Posicionamiento Dinámico)
        # Calcula dónde poner la tabla sumando las filas de la primera tabla + un espacio
        fila_inicio_inc = fila_fin + config.PROD_ESPACIO_INCLUSIVOS
        datos_inc = [
            df_inclusivos.columns.values.tolist()
        ] + df_inclusivos.values.tolist()
        fila_fin_inc = fila_inicio_inc + len(datos_inc) - 1

        # AHORA USA LAS VARIABLES DEL CONFIG EN LUGAR DE "A" Y "B"
        rango_inclusivos = f"{config.PROD_COL_INC_INI}{fila_inicio_inc}:{config.PROD_COL_INC_FIN}{fila_fin_inc}"
        actualizaciones.append({"range": rango_inclusivos, "values": datos_inc})

        sheet.batch_update(actualizaciones)
        print(
            f"[{time.strftime('%H:%M:%S')}] ✅ GSheets sincronizado. (Inclusivos en {rango_inclusivos})"
        )
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Error en API Google: {e}")


def a1_a_coordenadas(rango_a1):
    """Convierte notación A1 (ej. 'Hoja 1!J4') a índices de cuadrícula de Google (base 0)"""
    celda = rango_a1.split("!")[1] if "!" in rango_a1 else rango_a1
    match = re.match(r"([a-zA-Z]+)([0-9]+)", celda)

    col_str, row_str = match.groups()

    # Convertir columna letra a índice numérico (J = 9, K = 10)
    col_idx = 0
    for char in col_str.upper():
        col_idx = col_idx * 26 + (ord(char) - ord("A") + 1)
    col_idx -= 1

    # Convertir fila a índice numérico (Fila 4 = 3)
    row_idx = int(row_str) - 1

    return row_idx, row_idx + 1, col_idx, col_idx + 1


def gestionar_interfaz_botones(sheet, modo_auto):
    """Crea o destruye el botón manual leyendo las coordenadas desde config.py"""
    sheet_id = sheet.id

    rt_inicio, rt_fin, ct_inicio, ct_fin = a1_a_coordenadas(config.CELDA_TEXTO_MANUAL)
    rb_inicio, rb_fin, cb_inicio, cb_fin = a1_a_coordenadas(config.CELDA_BOTON_MANUAL)

    if modo_auto:
        # DESTRUIR: Limpiamos ambas celdas
        requests = [
            {
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": rt_inicio,
                        "endRowIndex": rb_fin,
                        "startColumnIndex": ct_inicio,
                        "endColumnIndex": cb_fin,
                    },
                    "fields": "userEnteredValue,dataValidation",
                }
            }
        ]
    else:
        # CREAR: Texto y Checkbox FORZANDO un valor False para que sea visible
        requests = [
            {
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": rt_inicio,
                        "endRowIndex": rt_fin,
                        "startColumnIndex": ct_inicio,
                        "endColumnIndex": ct_fin,
                    },
                    "rows": [
                        {
                            "values": [
                                {
                                    "userEnteredValue": {
                                        "stringValue": "Actualizar datos"
                                    }
                                }
                            ]
                        }
                    ],
                    "fields": "userEnteredValue",
                }
            },
            {
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": rb_inicio,
                        "endRowIndex": rb_fin,
                        "startColumnIndex": cb_inicio,
                        "endColumnIndex": cb_fin,
                    },
                    "rows": [
                        {
                            "values": [
                                {
                                    "userEnteredValue": {"boolValue": False},
                                    "dataValidation": {
                                        "condition": {"type": "BOOLEAN"},
                                        "showCustomUi": True,
                                    },
                                }
                            ]
                        }
                    ],
                    "fields": "userEnteredValue,dataValidation",
                }
            },
        ]

    sheet.spreadsheet.batch_update({"requests": requests})


# ==========================================
# BUCLE PRINCIPAL
# ==========================================
def run_daemon():
    print(f"Iniciando Daemon maestro para '{config.SPREADSHEET_NAME}'...")
    ultimo_hash = None
    df_anterior = None
    estado_auto_anterior = None

    while True:
        hora_actual = datetime.now().hour

        # =========================================================
        # ESTADO 1: SUEÑO PROFUNDO (10:00 PM a 5:59 AM)
        # =========================================================
        if hora_actual >= 22 or hora_actual < 6:
            # El sistema duerme totalmente. Despierta en 2 min solo para ver la hora(120).
            time.sleep(3600)
            continue

        # =========================================================
        # ESTADO 2: MODO MANTENIMIENTO (6:00 AM a 7:59 AM)
        # =========================================================
        if 6 <= hora_actual < 8:
            # Solo ejecuta la función de metas diarias para que dispare el borrado
            try:
                sync_metas_diario.run_sync_metas()
            except Exception as e:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Limpieza Matutina: {e}"
                )

            time.sleep(120)
            continue  # "continue" evita que pase al bloque de abajo (no carga SQL pesado)

        # =========================================================
        # ESTADO 3: JORNADA LABORAL COMPLETA (8:00 AM a 9:59 PM)
        # =========================================================
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                config.CREDS_FILE, config.SCOPE
            )
            client = gspread.authorize(creds)
            hoja_principal = client.open(config.SPREADSHEET_NAME).worksheet("Hoja 1")

            # 1. LECTURA DEL PANEL DE CONTROL
            celda_auto = config.CELDA_MODO_AUTO.split("!")[1]
            celda_manual = config.CELDA_BOTON_MANUAL.split("!")[1]

            val_auto = hoja_principal.acell(celda_auto).value
            modo_auto = True if str(val_auto).upper() == "TRUE" else False

            if modo_auto != estado_auto_anterior:
                gestionar_interfaz_botones(hoja_principal, modo_auto)
                estado_auto_anterior = modo_auto
                print(
                    f"[{time.strftime('%H:%M:%S')}] 🎨 Interfaz redibujada. Modo Auto de Metas: {'ON' if modo_auto else 'OFF'}"
                )

            # 2. EXTRACCIÓN DE PRODUCTIVIDAD (¡Esto corre SIEMPRE!)
            conn = pyodbc.connect(config.DB_TRANSACMIF)
            df_actual = pd.read_sql(QUERY_PRODUCTIVIDAD, conn)
            df_inclusivos = pd.read_sql(QUERY_INCLUSIVOS, conn)
            conn.close()

            df_actual.fillna(0, inplace=True)
            df_inclusivos.fillna(0, inplace=True)

            if "ColocacionNumReal" in df_actual.columns:
                df_actual["ColocacionNumReal"] = pd.to_numeric(
                    df_actual["ColocacionNumReal"]
                ).astype(int)
            if "ColocacionMontoReal" in df_actual.columns:
                df_actual["ColocacionMontoReal"] = pd.to_numeric(
                    df_actual["ColocacionMontoReal"]
                ).astype(float)
            if "Fecha" in df_actual.columns:
                df_actual["Fecha"] = df_actual["Fecha"].astype(str)
            if "Periodo" in df_actual.columns:
                df_actual["Periodo"] = df_actual["Periodo"].astype(str)
            if "NombreAgencia" in df_actual.columns:
                df_actual["NombreAgencia"] = df_actual["NombreAgencia"].astype(str)

            hash_actual = get_data_hash(df_actual)

            if hash_actual != ultimo_hash:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚡ Nuevo crédito/cambio detectado en TRANSACMIF."
                )
                push_to_google_sheets(df_actual, df_anterior, df_inclusivos)
                df_anterior = df_actual.copy()
                ultimo_hash = hash_actual

        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error general Productividad: {e}")

        # =========================================================
        # 3. CONTROL Y SINCRONIZACIÓN DE METAS (Regidas por el botón)
        # =========================================================
        ejecutar_metas = False

        if modo_auto:
            ejecutar_metas = True
        else:
            try:
                # Si estamos en manual, revisamos si el botón fue presionado
                val_manual = hoja_principal.acell(celda_manual).value
                if str(val_manual).upper() == "TRUE":
                    ejecutar_metas = True
                    print(
                        f"[{time.strftime('%H:%M:%S')}] 🎯 Botón manual presionado. Sincronizando metas..."
                    )
                    hoja_principal.update_acell(
                        celda_manual, False
                    )  # Apagamos el botón
            except Exception as e:
                pass  # Evita que un fallo leyendo el botón tire todo el script

        # Si el semáforo de metas está en verde, ejecutamos
        if ejecutar_metas:
            try:
                sync_metas_diario.run_sync_metas()
            except Exception as e:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Tarea Metas Diarias: {e}"
                )

            try:
                sync_metas_mensual.run_sync_metas_mensual()
            except Exception as e:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Tarea Metas Mensuales: {e}"
                )

        # Pausa del bucle principal
        time.sleep(120)


if __name__ == "__main__":
    try:
        # Iniciamos el vigilante del botón en paralelo (Hilo secundario)
        hilo_mora = threading.Thread(target=ejecutor_mora.escuchar_hoja, daemon=True)
        hilo_mora.start()

        # Iniciamos el bucle principal de productividad (Hilo principal)
        run_daemon()
    except KeyboardInterrupt:
        print("\nDaemon detenido manualmente.")
        sys.exit(0)
