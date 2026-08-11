import gspread
import pyodbc
import time
from datetime import datetime
import config
from sql_queries import QUERY_MORA_POTENCIAL
from oauth2client.service_account import ServiceAccountCredentials

CELDA_GATILLO = "J1"  # Asegúrate de que esta sea la celda correcta de tu checkbox
SHEET_TAB_NAME = "Hoja 5"


def ejecutar_consulta_sql():
    print(f"[{datetime.now()}] Conectando a SQL Server (Mora Potencial)...")
    conn = pyodbc.connect(config.DB_TRANSACMIF)
    cursor = conn.cursor()
    cursor.execute(QUERY_MORA_POTENCIAL)
    columnas = [column[0] for column in cursor.description]
    datos = [list(row) for row in cursor.fetchall()]
    conn.close()
    return columnas, datos


def escuchar_hoja():
    """El daemon que corre infinitamente esperando el click del checkbox."""
    print(
        f"Hilo de Mora Iniciado. Escuchando checkbox en {SHEET_TAB_NAME} celda {CELDA_GATILLO}..."
    )
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            config.CREDS_FILE, config.SCOPE
        )
        client = gspread.authorize(creds)
        hoja_reporte = client.open(config.SPREADSHEET_NAME).worksheet(SHEET_TAB_NAME)
    except Exception as e:
        print(f"Error autenticando Google Sheets en Mora: {e}")
        return

    while True:
        # 1. Validamos la hora para que el botón no consuma API de noche
        hora_actual = datetime.now().hour
        if hora_actual >= 22 or hora_actual < 8:
            time.sleep(
                3600
            )  # Chequea cada minuto en lugar de 5 segundos, ahorrando recursos
            continue

        try:
            estado_boton = hoja_reporte.acell(CELDA_GATILLO).value
            if estado_boton == "TRUE" or estado_boton == True:
                print(
                    f"[{datetime.now()}] ¡Botón presionado! Iniciando extracción de Mora..."
                )

                # 1. Cambiamos estado a procesando
                hoja_reporte.update_acell(CELDA_GATILLO, "PROCESANDO...")

                # 2. Extraemos los datos y columnas
                columnas, datos = ejecutar_consulta_sql()

                # 3. TRUCO DE OPTIMIZACIÓN: Añadimos los títulos extra a la lista de SQL
                # Automáticamente caerán en la columna G y H de la fila 1
                columnas.append("Compromiso")
                columnas.append("Fecha")

                # 4. Limpiamos el rango exacto, protegiendo al botón en la columna K
                hoja_reporte.batch_clear(["A1:H20000"])

                # 5. Insertamos la matriz combinada a partir de A1
                hoja_reporte.update("A1", [columnas] + datos)

                # 6. CAMBIO AQUÍ: Escribimos la última actualización en J1
                hora_texto = datetime.now().strftime("%d/%m/%Y\n%H:%M:%S")
                hoja_reporte.update_acell("J1", f"Última act:\n{hora_texto}")

                # 7. Apagamos el botón
                hoja_reporte.update_acell(CELDA_GATILLO, "FALSE")
                print(f"[{datetime.now()}] Reporte de Mora actualizado con éxito.")

        except Exception as e:
            print(f"Error en el Hilo de Mora: {e}")
        # Escucha cada 5 segundos
        time.sleep(120)
