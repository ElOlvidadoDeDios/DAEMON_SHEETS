import pandas as pd
import sqlite3
import pyodbc
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import config
from sql_queries import QUERY_MORA_POTENCIAL_V2

DB_LOCAL = "mora_gestion.db"
# Dejamos la fila 1 intacta para que no borre tus encabezados bonitos
RANGO_DATOS = "A2:P2000"


def init_db():
    conn = sqlite3.connect(DB_LOCAL)
    c = conn.cursor()
    # Tabla local para guardar la memoria de lo que escriben los asesores
    c.execute("""
        CREATE TABLE IF NOT EXISTS compromisos (
            pagare TEXT PRIMARY KEY,
            compromiso TEXT,
            fecha_promesa TEXT,
            fecha_actualizacion DATETIME
        )
    """)
    conn.commit()
    conn.close()


def guardar_compromisos_en_local(df_compromisos):
    if df_compromisos.empty:
        return
    conn = sqlite3.connect(DB_LOCAL)
    cursor = conn.cursor()

    for index, row in df_compromisos.iterrows():
        pagare = str(row["PAGARE"]).strip()
        if not pagare or pagare == "None":
            continue

        compromiso = str(row.get("COMPROMISO", "")).strip()
        fecha = str(row.get("FECHA_PROMESA", "")).strip()

        # Si no hay nada escrito, no sobreescribimos
        if compromiso == "" and fecha == "":
            continue

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # UPSERT: Inserta si es nuevo, actualiza si ya existe
        cursor.execute(
            """
            INSERT INTO compromisos (pagare, compromiso, fecha_promesa, fecha_actualizacion)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(pagare) DO UPDATE SET
                compromiso=excluded.compromiso,
                fecha_promesa=excluded.fecha_promesa,
                fecha_actualizacion=excluded.fecha_actualizacion
        """,
            (pagare, compromiso, fecha, now),
        )

    conn.commit()
    conn.close()


def leer_compromisos_de_local():
    conn = sqlite3.connect(DB_LOCAL)
    df = pd.read_sql_query(
        "SELECT pagare AS PAGARE, compromiso AS COMPROMISO, fecha_promesa AS FECHA_PROMESA FROM compromisos",
        conn,
    )
    conn.close()
    return df


def ejecutar_sincronizacion_mora():
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Iniciando Sincronización de Mora y Compromisos..."
    )
    init_db()

    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            config.CREDS_FILE, config.SCOPE
        )
        client = gspread.authorize(creds)
        doc_mora = client.open_by_key(config.SHEET_MORA_ID)
    except Exception as e:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error conectando a Google Sheets: {e}"
        )
        return

    # 1. RESCATAR COMPROMISOS ACTUALES DE SHEETS
    agencias = [
        "Wanchaq",
        "San Jerónimo",
        "Quillabamba",
        "Sicuani",
        "Molino",
        "Juliaca",
        "Lima Los Olivos",
        "Tica Tica",
        "Magisterio",
        "Lima SJL",
        "Chiclayo",
        "Arequipa",
        "Pucallpa",
    ]
    compromisos_rescatados = []

    for agencia in agencias:
        try:
            ws = doc_mora.worksheet(agencia)
            data = ws.get(RANGO_DATOS)
            for row in data:
                if len(row) > 1:
                    pagare = str(row[1]).strip()
                    # Columna O es 14, Columna P es 15
                    compromiso = row[14] if len(row) > 14 else ""
                    fecha = row[15] if len(row) > 15 else ""

                    if compromiso or fecha:
                        compromisos_rescatados.append(
                            {
                                "PAGARE": pagare,
                                "COMPROMISO": compromiso,
                                "FECHA_PROMESA": fecha,
                            }
                        )
        except gspread.exceptions.WorksheetNotFound:
            pass
        except Exception as e:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Error leyendo pestaña '{agencia}': {e}"
            )

    df_rescate = pd.DataFrame(compromisos_rescatados)
    guardar_compromisos_en_local(df_rescate)

    # 2. TRAER LA FOTO FRESCA DE SQL SERVER
    try:
        conn_sql = pyodbc.connect(config.DB_TRANSACMIF)
        df_mora_fresca = pd.read_sql(QUERY_MORA_POTENCIAL_V2, conn_sql)
        conn_sql.close()
    except Exception as e:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error conectando a TRANSACMIF: {e}"
        )
        return

    if df_mora_fresca.empty:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ No hay mora que procesar.")
        return

    # 🚀 MAGIA PURIFICADORA (Cero espacios fantasma)
    if "PAGARE" in df_mora_fresca.columns:
        df_mora_fresca["PAGARE"] = df_mora_fresca["PAGARE"].astype(str).str.strip()
    if "CUENTA" in df_mora_fresca.columns:
        df_mora_fresca["CUENTA"] = df_mora_fresca["CUENTA"].astype(str).str.strip()

    df_local = leer_compromisos_de_local()
    if "PAGARE" in df_local.columns:
        df_local["PAGARE"] = df_local["PAGARE"].astype(str).str.strip()

    # =========================================================================
    # 🕵️‍♂️ DETECTAR QUIÉNES PAGARON (Cruzando con la foto anterior)
    # =========================================================================
    conn_sqlite = sqlite3.connect(DB_LOCAL)
    try:
        df_ayer = pd.read_sql("SELECT * FROM memoria_ayer", conn_sqlite)
        df_ayer["PAGARE"] = df_ayer["PAGARE"].astype(str).str.strip()
        # Filtramos los que estaban en la memoria anterior pero YA NO están en la mora fresca
        df_pagaron = df_ayer[~df_ayer["PAGARE"].isin(df_mora_fresca["PAGARE"])]
    except Exception:
        # Si es la primera vez que corre y no existe la tabla, creamos un DF vacío
        df_pagaron = pd.DataFrame()
    conn_sqlite.close()

    # 3. CRUZAR FOTO FRESCA CON LA BASE LOCAL (Compromisos)
    df_final = pd.merge(df_mora_fresca, df_local, on="PAGARE", how="left")
    df_final.fillna("", inplace=True)

    # 4. REPARTIR A GOOGLE SHEETS (Mora + Columna S de Pagos)
    for agencia in agencias:
        df_agencia = df_final[df_final["AGENCIA"] == agencia]

        # Filtramos los que pagaron específicamente de esta agencia
        if not df_pagaron.empty and "AGENCIA" in df_pagaron.columns:
            pagaron_agencia = df_pagaron[df_pagaron["AGENCIA"] == agencia]
        else:
            pagaron_agencia = pd.DataFrame()

        try:
            ws = doc_mora.worksheet(agencia)

            # Limpiamos los datos principales Y la columna S (desde S1 hasta S2000)
            ws.batch_clear([RANGO_DATOS, "S1:S2000"])

            # ---> Escribir la Mora (Columnas A - P)
            if not df_agencia.empty:
                valores_mora = df_agencia.values.tolist()
                ws.update("A2", valores_mora, value_input_option="USER_ENTERED")

            # ---> Escribir el "Muro de la Victoria" (Columna S)
            # El robot pone el título automáticamente en la celda S1
            datos_col_s = [["🏆 CLIENTES QUE PAGARON"]]

            for _, row in pagaron_agencia.iterrows():
                nombre = row.get("SOCIO", "Cliente")
                comp = str(row.get("COMPROMISO", "")).strip()
                texto_comp = "Con compromiso" if comp else "Sin compromiso"
                datos_col_s.append([f"✅ {nombre} ({texto_comp})"])

            # Si nadie ha pagado aún, ponemos un mensaje de aliento
            if len(datos_col_s) == 1:
                datos_col_s.append(["Nadie por ahora... ¡A gestionar!"])

            # Mandamos la lista a la columna S
            ws.update("S1", datos_col_s, value_input_option="USER_ENTERED")

        except gspread.exceptions.WorksheetNotFound:
            pass
        except Exception as e:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error escribiendo pestaña '{agencia}': {e}"
            )

    # =========================================================================
    # 📸 GUARDAR LA FOTO DE HOY PARA COMPARARLA MAÑANA
    # =========================================================================
    conn_sqlite = sqlite3.connect(DB_LOCAL)
    # Solo guardamos columnas clave para no hacer pesada la base local
    columnas_clave = [
        c for c in ["PAGARE", "AGENCIA", "SOCIO", "COMPROMISO"] if c in df_final.columns
    ]
    if columnas_clave:
        df_final[columnas_clave].to_sql(
            "memoria_ayer", conn_sqlite, if_exists="replace", index=False
        )
    conn_sqlite.close()

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Gestión de Mora actualizada. (Se detectaron {len(df_pagaron)} pagos)."
    )
