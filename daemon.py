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


def get_data_hash(df):
    return hashlib.md5(df.to_csv(index=False).encode()).hexdigest()


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

        datos_abc = df[["Fecha", "Periodo", "NombreAgencia"]].values.tolist()
        actualizaciones.append(
            {
                "range": f"{config.PROD_COL_FECHA}{config.PROD_FILA_INICIO}:{config.PROD_COL_AGENCIA}{fila_fin}",
                "values": datos_abc,
            }
        )

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

        fila_inicio_inc = fila_fin + config.PROD_ESPACIO_INCLUSIVOS
        datos_inc = [
            df_inclusivos.columns.values.tolist()
        ] + df_inclusivos.values.tolist()
        fila_fin_inc = fila_inicio_inc + len(datos_inc) - 1

        rango_inclusivos = f"{config.PROD_COL_INC_INI}{fila_inicio_inc}:{config.PROD_COL_INC_FIN}{fila_fin_inc}"
        actualizaciones.append({"range": rango_inclusivos, "values": datos_inc})

        sheet.batch_update(actualizaciones)
        print(
            f"[{time.strftime('%H:%M:%S')}] ✅ GSheets sincronizado. (Inclusivos en {rango_inclusivos})"
        )
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Error en API Google: {e}")


# ==========================================
# BUCLE PRINCIPAL (EL ORQUESTADOR)
# ==========================================
def run_daemon():
    print(f"Iniciando Daemon maestro para '{config.SPREADSHEET_NAME}'...")
    ultimo_hash = None
    df_anterior = None

    while True:
        hora_actual = datetime.now().hour

        # 1. EL DIRECTOR LEE TODOS LOS BOTONES PRIMERO
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                config.CREDS_FILE, config.SCOPE
            )
            client = gspread.authorize(creds)
            hoja_principal = client.open(config.SPREADSHEET_NAME).worksheet(
                config.PROD_PESTANA
            )

            # Botones Diarios
            btn_eliminar_diario = (
                str(
                    hoja_principal.acell(
                        config.CELDA_AUTOELIMINAR_DIARIO.split("!")[1]
                    ).value
                ).upper()
                == "TRUE"
            )
            btn_insertar_diario = (
                str(
                    hoja_principal.acell(
                        config.CELDA_AUTOINSERTAR_DIARIO.split("!")[1]
                    ).value
                ).upper()
                == "TRUE"
            )

            celda_manual_diar = config.CELDA_MANUAL_DIARIO.split("!")[1]
            btn_manual_diario = (
                str(hoja_principal.acell(celda_manual_diar).value).upper() == "TRUE"
            )

            if btn_manual_diario:
                hoja_principal.update_acell(celda_manual_diar, False)
                print(
                    f"[{time.strftime('%H:%M:%S')}] 🎯 Botón MANUAL DIARIO presionado. Forzando ejecución..."
                )

            # Botones Mensuales
            celda_manual_mens = config.CELDA_BOTON_MANUAL.split("!")[1]
            modo_auto_mens = (
                str(
                    hoja_principal.acell(config.CELDA_MODO_AUTO.split("!")[1]).value
                ).upper()
                == "TRUE"
            )
            modo_manual_mens = (
                str(hoja_principal.acell(celda_manual_mens).value).upper() == "TRUE"
            )

            ejecutar_mensual = False
            if modo_auto_mens:
                ejecutar_mensual = True
            elif modo_manual_mens:
                ejecutar_mensual = True
                hoja_principal.update_acell(celda_manual_mens, False)
                print(
                    f"[{time.strftime('%H:%M:%S')}] 🎯 Botón MANUAL MENSUAL presionado."
                )

        except Exception as e:
            print(
                f"[{time.strftime('%H:%M:%S')}] ⚠️ Error leyendo Panel de Control: {e}"
            )
            time.sleep(120)
            continue

        # =========================================================
        # ESTADO 1: SUEÑO PROFUNDO
        # =========================================================
        # Si es de noche Y NO hay emergencias manuales, descansa 2 minutos
        if (
            (hora_actual >= 22 or hora_actual < 6)
            and not btn_manual_diario
            and not modo_manual_mens
        ):
            time.sleep(120)
            continue

        # =========================================================
        # ESTADO 2: MODO MANTENIMIENTO (6:00 AM a 7:59 AM)
        # =========================================================
        if 6 <= hora_actual < 8 and not btn_manual_diario and not modo_manual_mens:
            # Tarea 1: Limpieza del tablero diario
            try:
                sync_metas_diario.run_sync_metas(
                    btn_eliminar_diario, btn_insertar_diario, False
                )
            except Exception as e:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Limpieza Matutina Diaria: {e}"
                )

            # Tarea 2: Limpieza mensual (Solo se activará si es el día 1 del mes)
            try:
                sync_metas_mensual.limpieza_primer_dia_mes()
            except Exception as e:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Limpieza Matutina Mensual: {e}"
                )

            time.sleep(120)
            continue

        # =========================================================
        # ESTADO 3: EXTRACCIÓN Y TAREAS DELEGADAS
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

        # ==========================================
        # VERIFICACIÓN DE CAMBIO DE MES
        # ==========================================
        try:
            sync_metas_mensual.verificar_y_limpiar_cambio_mes()
        except Exception as e:
            print(
                f"[{time.strftime('%H:%M:%S')}] ⚠️ Error verificando cambio de mes: {e}"
            )

        # TAREAS DELEGADAS
        try:
            sync_metas_diario.run_sync_metas(
                btn_eliminar_diario, btn_insertar_diario, btn_manual_diario
            )
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Tarea Metas Diarias: {e}")

        # TAREAS DELEGADAS
        try:
            sync_metas_diario.run_sync_metas(
                btn_eliminar_diario, btn_insertar_diario, btn_manual_diario
            )
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Tarea Metas Diarias: {e}")

        if ejecutar_mensual:
            try:
                sync_metas_mensual.run_sync_metas_mensual()
            except Exception as e:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Tarea Metas Mensuales: {e}"
                )

        time.sleep(120)


if __name__ == "__main__":
    try:
        hilo_mora = threading.Thread(target=ejecutor_mora.escuchar_hoja, daemon=True)
        hilo_mora.start()
        run_daemon()
    except KeyboardInterrupt:
        print("\nDaemon detenido manualmente.")
        sys.exit(0)
