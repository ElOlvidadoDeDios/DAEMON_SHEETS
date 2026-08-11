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


def push_to_google_sheets(df, df_anterior, df_inclusivos):
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            config.CREDS_FILE, config.SCOPE
        )
        client = gspread.authorize(creds)
        sheet = client.open(config.SPREADSHEET_NAME).worksheet("Hoja 1")

        actualizaciones = []
        filas_df = len(df)

        # 1. Columnas A, B, C (Fechas, Periodo, Agencia)
        datos_abc = df[["Fecha", "Periodo", "NombreAgencia"]].values.tolist()
        actualizaciones.append({"range": f"A2:C{filas_df + 1}", "values": datos_abc})

        # 2. Columna E (ColocacionNumReal)
        datos_e = [[val] for val in df["ColocacionNumReal"].tolist()]
        actualizaciones.append({"range": f"E2:E{filas_df + 1}", "values": datos_e})

        # 3. Columna G (ColocacionMontoReal)
        datos_g = [[val] for val in df["ColocacionMontoReal"].tolist()]
        actualizaciones.append({"range": f"G2:G{filas_df + 1}", "values": datos_g})

        # 4. Columna H (Última actualización GENERAL)
        hora_actual = time.strftime("%d/%m/%Y\n%H:%M:%S")
        actualizaciones.append(
            {"range": "H1", "values": [[f"Última act:\n{hora_actual}"]]}
        )

        # 5. Columna H (Deltas con el formato +Cantidad -> Monto)
        datos_deltas = []
        for i in range(filas_df):
            if df_anterior is not None:
                diff_num = (
                    df.iloc[i]["ColocacionNumReal"]
                    - df_anterior.iloc[i]["ColocacionNumReal"]
                )
                diff_monto = (
                    df.iloc[i]["ColocacionMontoReal"]
                    - df_anterior.iloc[i]["ColocacionMontoReal"]
                )
            else:
                diff_num = 0
                diff_monto = 0

            if diff_num > 0 or diff_monto > 0:
                str_delta = f"+{int(diff_num)} -> {diff_monto:.2f}".replace(".", ",")
            else:
                str_delta = ""
            datos_deltas.append([str_delta])

        actualizaciones.append({"range": f"H2:H{filas_df + 1}", "values": datos_deltas})

        # 6. Tabla Inclusivos en A20
        datos_inc = [
            df_inclusivos.columns.values.tolist()
        ] + df_inclusivos.values.tolist()
        actualizaciones.append(
            {"range": f"A20:B{19+len(datos_inc)}", "values": datos_inc}
        )

        # Disparamos todas las celdas en un solo envío
        sheet.batch_update(actualizaciones)
        print(
            f"[{time.strftime('%H:%M:%S')}] ✅ GSheets sincronizado (E=NumReal, G=MontoReal, H=Deltas, Inclusivos)."
        )
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Error en API Google: {e}")


# ==========================================
# BUCLE PRINCIPAL
# ==========================================
def run_daemon():
    print(f"Iniciando Daemon maestro para '{config.SPREADSHEET_NAME}'...")
    ultimo_hash = None
    df_anterior = None

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

        # Sincronización de Metas (Inserción de las 10 AM en adelante)
        try:
            sync_metas_diario.run_sync_metas()
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Tarea Metas Diarias: {e}")

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
