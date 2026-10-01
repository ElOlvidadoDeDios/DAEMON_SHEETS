import pandas as pd
import socket
import requests
from gspread.exceptions import APIError
import schedule
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import hashlib
import sys
import warnings
import pyodbc
import config
from sql_queries import QUERY_PRODUCTIVIDAD, QUERY_INCLUSIVOS
import sync_metas_diario
import sync_metas_mensual
import sync_mora_gestion
import sync_plazo_fijo
import sync_preventivo_ia
import sync_administradores

warnings.filterwarnings("ignore")


def get_data_hash(df):
    return hashlib.md5(df.to_csv(index=False).encode()).hexdigest()


def push_to_google_sheets(df, df_anterior, df_inclusivos, sheet):
    try:
        # creds = ServiceAccountCredentials.from_json_keyfile_name(
        #    config.CREDS_FILE, config.SCOPE
        # )
        # client = gspread.authorize(creds)
        # sheet = client.open(config.SPREADSHEET_NAME).worksheet(config.PROD_PESTANA)

        actualizaciones = []
        filas_df = len(df)
        fila_fin = config.PROD_FILA_INICIO + filas_df - 1

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

    # ⏱️ Temporizador para la Mora
    ultima_mora_sync = 0
    # NUEVO TEMPORIZADOR PLAZO FIJO
    ultima_plazo_fijo_sync = 0
    # 🧠 TEMPORIZADOR PARA LA IA (Para que corra 1 sola vez al día)
    fecha_ultima_ia = None

    # 43200 segundos = 12 horas. Para correr cada 8 horas usa 28800.
    FRECUENCIA_PLAZO_FIJO = 43200

    # 1. ✅ AUTENTICAR SOLO UNA VEZ FUERA DEL BUCLE
    # gspread se encarga automáticamente de renovar el token cuando expire en segundo plano.
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        config.CREDS_FILE, config.SCOPE
    )
    client = gspread.authorize(creds)
    hoja_principal = client.open(config.SPREADSHEET_NAME).worksheet(config.PROD_PESTANA)

    while True:
        hora_actual = datetime.now().hour

        # 2. ✅ LECTURA OPTIMIZADA DEL PANEL DE CONTROL (1 sola petición en lugar de 5)
        try:
            celdas_a_leer = [
                config.CELDA_AUTOELIMINAR_DIARIO.split("!")[1],
                config.CELDA_AUTOINSERTAR_DIARIO.split("!")[1],
                config.CELDA_MANUAL_DIARIO.split("!")[1],
                config.CELDA_MODO_AUTO.split("!")[1],
                config.CELDA_BOTON_MANUAL.split("!")[1],
                config.CELDA_AUTO_ADMIN.split("!")[1],  # <-- NUEVO
                config.CELDA_MANUAL_ADMIN.split("!")[1],
            ]

            valores = hoja_principal.batch_get(celdas_a_leer)

            # Helper para parsear la respuesta de batch_get
            def get_bool(val_list):
                if val_list and len(val_list[0]) > 0:
                    return str(val_list[0][0]).upper() == "TRUE"
                return False

            btn_eliminar_diario = get_bool(valores[0])
            btn_insertar_diario = get_bool(valores[1])
            btn_manual_diario = get_bool(valores[2])
            modo_auto_mens = get_bool(valores[3])
            modo_manual_mens = get_bool(valores[4])
            modo_auto_admin = get_bool(valores[5])
            btn_manual_admin = get_bool(valores[6])

            # Apagar botones manuales en un solo batch si fueron activados (1 sola petición)
            actualizaciones_botones = []

            if btn_manual_diario:
                actualizaciones_botones.append(
                    {"range": celdas_a_leer[2], "values": [[False]]}
                )
                print(
                    f"[{time.strftime('%H:%M:%S')}] 🎯 Botón MANUAL DIARIO presionado. Forzando ejecución..."
                )

            ejecutar_mensual = False
            if modo_auto_mens:
                ejecutar_mensual = True
            elif modo_manual_mens:
                ejecutar_mensual = True
                actualizaciones_botones.append(
                    {"range": celdas_a_leer[4], "values": [[False]]}
                )
                print(
                    f"[{time.strftime('%H:%M:%S')}] 🎯 Botón MANUAL MENSUAL presionado."
                )

            if actualizaciones_botones:
                hoja_principal.batch_update(actualizaciones_botones)

            if btn_manual_admin:
                actualizaciones_botones.append(
                    {"range": celdas_a_leer[6], "values": [[False]]}
                )
                print(
                    f"[{time.strftime('%H:%M:%S')}] 🎯 Botón MANUAL ADMIN presionado."
                )

        # 3. ✅ MANEJO DE CAÍDAS DE RED Y LIMITES DE GOOGLE
        except APIError as e:
            if e.response.status_code in [403, 429]:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚠️ Límite de Google API excedido. Pausando Daemon por 5 minutos..."
                )
                time.sleep(300)  # Respiro largo para que Google libere el bloqueo
            continue
        except (requests.exceptions.ConnectionError, socket.gaierror) as e:
            print(
                f"[{time.strftime('%H:%M:%S')}] ⚠️ Microcorte de Internet/DNS. Ignorando panel este ciclo..."
            )
            time.sleep(60)
            continue
        except Exception as e:
            print(
                f"[{time.strftime('%H:%M:%S')}] ⚠️ Error inesperado leyendo Panel de Control: {e}"
            )
            time.sleep(120)
            continue
        # =========================================================
        # ESTADO 1: SUEÑO PROFUNDO
        # =========================================================
        if (
            (hora_actual >= 22 or hora_actual < 6)
            and not btn_manual_diario
            and not modo_manual_mens
        ):
            time.sleep(120)
            continue

        # =========================================================
        # ESTADO 1.5: CEREBRO IA PREVENTIVA (1 vez al día, al despertar)
        # =========================================================
        hoy_str_ia = datetime.now().strftime("%Y-%m-%d")
        if hora_actual >= 6 and fecha_ultima_ia != hoy_str_ia:
            print(
                f"[{time.strftime('%H:%M:%S')}] 🤖 Despertando al Cerebro IA Preventiva..."
            )
            try:
                sync_preventivo_ia.ejecutar_ia_preventiva()
                fecha_ultima_ia = hoy_str_ia  # Marcamos que ya corrió hoy
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Cerebro IA: {e}")

        # =========================================================
        # ESTADO 2: MODO MANTENIMIENTO (6:00 AM a 7:59 AM)
        # =========================================================
        if 6 <= hora_actual < 8 and not btn_manual_diario and not modo_manual_mens:
            try:
                sync_metas_diario.run_sync_metas(
                    btn_eliminar_diario, btn_insertar_diario, False
                )
            except Exception as e:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Limpieza Matutina Diaria: {e}"
                )

            time.sleep(120)
            continue

        # =========================================================
        # ESTADO 2.5: SINCRONIZACIÓN DE MORA (Frecuencia: Cada 2 horas)
        # =========================================================
        tiempo_actual = time.time()
        # 7200 segundos = 2 horas. Cambia este número si quieres más (ej: 10800 para 3 horas)
        if tiempo_actual - ultima_mora_sync >= 7200:
            print(
                f"[{time.strftime('%H:%M:%S')}] 🔍 Iniciando ciclo de Mora (Actualización periódica)..."
            )
            try:
                sync_mora_gestion.ejecutar_sincronizacion_mora()
                ultima_mora_sync = tiempo_actual  # Reiniciamos el cronómetro
            except Exception as e:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Sincronización de Mora: {e}"
                )

        # =========================================================
        # ESTADO 2.6: SINCRONIZACIÓN DE PLAZO FIJO (HACIA DWH)
        # =========================================================
        # Aprovechamos la variable tiempo_actual que ya declaraste arriba
        if tiempo_actual - ultima_plazo_fijo_sync >= FRECUENCIA_PLAZO_FIJO:
            print(
                f"[{time.strftime('%H:%M:%S')}] 🔍 Iniciando ETL de Plazo Fijo (Frecuencia: Cada {FRECUENCIA_PLAZO_FIJO/3600}h)..."
            )
            try:
                sync_plazo_fijo.ejecutar_sincronizacion_plazo_fijo()
                ultima_plazo_fijo_sync = tiempo_actual  # Reiniciamos el cronómetro
            except Exception as e:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Sincronización de Plazo Fijo: {e}"
                )

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
                # 4. ✅ Pasamos la hoja ya autenticada como cuarto argumento
                push_to_google_sheets(
                    df_actual, df_anterior, df_inclusivos, hoja_principal
                )
                df_anterior = df_actual.copy()
                ultimo_hash = hash_actual
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Error general Productividad: {e}")

        # ==========================================
        # VERIFICACIÓN INTELIGENTE DE CAMBIO DE MES
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

        if ejecutar_mensual:
            try:
                sync_metas_mensual.run_sync_metas_mensual()
            except Exception as e:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Tarea Metas Mensuales: {e}"
                )

        if modo_auto_admin or btn_manual_admin:
            try:
                sync_administradores.run_sync_administradores()
            except Exception as e:
                print(
                    f"[{time.strftime('%H:%M:%S')}] ⚠️ Error en Tarea Administradores: {e}"
                )

        time.sleep(120)


if __name__ == "__main__":
    try:
        run_daemon()
    except KeyboardInterrupt:
        print("\nDaemon detenido manualmente.")
        sys.exit(0)
