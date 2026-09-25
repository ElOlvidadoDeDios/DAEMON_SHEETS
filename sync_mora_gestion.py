import pandas as pd
import sqlite3
import pyodbc
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime, timedelta
import config
from sql_queries import QUERY_MORA_POTENCIAL_V2

DB_LOCAL = "mora_gestion.db"
RANGO_DATOS = "A2:P2000"


def init_db():
    conn = sqlite3.connect(DB_LOCAL)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS compromisos (
            pagare TEXT PRIMARY KEY,
            compromiso TEXT,
            fecha_promesa TEXT,
            fecha_actualizacion DATETIME
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS pagos_diarios (
            pagare TEXT,
            agencia TEXT,
            socio TEXT,
            texto_mostrar TEXT,
            fecha_deteccion DATE
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

        if compromiso == "" and fecha == "":
            continue

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

    # 1. RESCATAR COMPROMISOS
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

    # 2. TRAER LA FOTO FRESCA DE SQL
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

    # 🚀 MAGIA PURIFICADORA
    if "PAGARE" in df_mora_fresca.columns:
        df_mora_fresca["PAGARE"] = df_mora_fresca["PAGARE"].astype(str).str.strip()
    if "CUENTA" in df_mora_fresca.columns:
        df_mora_fresca["CUENTA"] = df_mora_fresca["CUENTA"].astype(str).str.strip()

    df_local = leer_compromisos_de_local()
    if "PAGARE" in df_local.columns:
        df_local["PAGARE"] = df_local["PAGARE"].astype(str).str.strip()

    # =========================================================================
    # 🤖 MEMORIA DE LA IA: MARCAR A LOS SOCIOS QUE FUERON ADVERTIDOS PREVIAMENTE
    # =========================================================================
    try:
        conn_ia = sqlite3.connect(DB_LOCAL)
        # Solo leemos si la tabla ya fue creada por el otro script
        cursor = conn_ia.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='historial_ia';"
        )
        if cursor.fetchone():
            df_memoria_ia = pd.read_sql(
                "SELECT pagare AS PAGARE FROM historial_ia", conn_ia
            )
            if not df_memoria_ia.empty and "PAGARE" in df_mora_fresca.columns:
                df_memoria_ia["PAGARE"] = (
                    df_memoria_ia["PAGARE"].astype(str).str.strip()
                )
                # Cruzar pagarés morosos de hoy con pagarés advertidos por la IA
                es_predicho = df_mora_fresca["PAGARE"].isin(df_memoria_ia["PAGARE"])
                # Pegarle la medalla al nombre del socio
                df_mora_fresca.loc[es_predicho, "SOCIO"] = (
                    df_mora_fresca["SOCIO"] + " ⚠️ (IA Advirtió)"
                )
        conn_ia.close()
    except Exception as e:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Omitiendo validación IA: {e}"
        )

    # =========================================================================
    # 🕵️‍♂️ DETECTAR PAGOS TOTALES Y PARCIALES
    # =========================================================================
    conn_sqlite = sqlite3.connect(DB_LOCAL)
    try:
        df_ayer = pd.read_sql("SELECT * FROM memoria_ayer", conn_sqlite)
        df_ayer["PAGARE"] = df_ayer["PAGARE"].astype(str).str.strip()
    except Exception:
        df_ayer = pd.DataFrame()
    conn_sqlite.close()

    df_pagaron_total = pd.DataFrame()
    df_pagaron_parcial = pd.DataFrame()

    if not df_ayer.empty:
        if "SALDO_PRES" not in df_ayer.columns:
            df_ayer["SALDO_PRES"] = 0

        df_pagaron_total = df_ayer[
            ~df_ayer["PAGARE"].isin(df_mora_fresca["PAGARE"])
        ].copy()

        if "SALDO_PRES" in df_mora_fresca.columns:
            df_comunes = pd.merge(
                df_ayer[["PAGARE", "AGENCIA", "SOCIO", "COMPROMISO", "SALDO_PRES"]],
                df_mora_fresca[["PAGARE", "SALDO_PRES"]],
                on="PAGARE",
                suffixes=("_ayer", "_hoy"),
            )
            df_comunes["SALDO_PRES_ayer"] = pd.to_numeric(
                df_comunes["SALDO_PRES_ayer"], errors="coerce"
            ).fillna(0)
            df_comunes["SALDO_PRES_hoy"] = pd.to_numeric(
                df_comunes["SALDO_PRES_hoy"], errors="coerce"
            ).fillna(0)

            df_pagaron_parcial = df_comunes[
                df_comunes["SALDO_PRES_hoy"] < df_comunes["SALDO_PRES_ayer"]
            ].copy()
            if not df_pagaron_parcial.empty:
                df_pagaron_parcial["MONTO_PAGADO"] = (
                    df_pagaron_parcial["SALDO_PRES_ayer"]
                    - df_pagaron_parcial["SALDO_PRES_hoy"]
                )

    # 🌟 INYECCIÓN DE COMPROMISO FRESCO 🌟
    # Actualizamos el compromiso con lo ultimito que tipeó el asesor antes de que pagaran
    if not df_pagaron_total.empty:
        if "COMPROMISO" in df_pagaron_total.columns:
            df_pagaron_total = df_pagaron_total.drop(columns=["COMPROMISO"])
        df_pagaron_total = pd.merge(
            df_pagaron_total,
            df_local[["PAGARE", "COMPROMISO"]],
            on="PAGARE",
            how="left",
        )
        df_pagaron_total.fillna("", inplace=True)

    if not df_pagaron_parcial.empty:
        if "COMPROMISO" in df_pagaron_parcial.columns:
            df_pagaron_parcial = df_pagaron_parcial.drop(columns=["COMPROMISO"])
        df_pagaron_parcial = pd.merge(
            df_pagaron_parcial,
            df_local[["PAGARE", "COMPROMISO"]],
            on="PAGARE",
            how="left",
        )
        df_pagaron_parcial.fillna("", inplace=True)

    # =========================================================================
    # 🏆 REGISTRAR EN LA BITÁCORA DEL DÍA
    # =========================================================================
    fecha_hoy_obj = datetime.now()
    hoy_str = fecha_hoy_obj.strftime("%Y-%m-%d")
    ayer_str = (fecha_hoy_obj - timedelta(days=1)).strftime("%Y-%m-%d")

    conn_sqlite = sqlite3.connect(DB_LOCAL)
    cursor = conn_sqlite.cursor()

    for _, row in df_pagaron_total.iterrows():
        nombre = (
            str(row.get("SOCIO", "Cliente")).split()[0]
            + " "
            + str(row.get("SOCIO", "")).split()[-1]
            if len(str(row.get("SOCIO", "")).split()) > 1
            else str(row.get("SOCIO", ""))
        )
        comp = str(row.get("COMPROMISO", "")).strip()

        # Limpiamos si pandas metió algún 'nan'
        if comp.lower() in ["nan", "none"]:
            comp = ""

        texto_comp = f'Cumplió: "{comp}"' if comp else "Sin comp."
        texto = f"✅ {nombre}: Pago Exitoso ({texto_comp})"

        cursor.execute(
            "SELECT 1 FROM pagos_diarios WHERE pagare=? AND fecha_deteccion=?",
            (row["PAGARE"], hoy_str),
        )
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO pagos_diarios VALUES (?, ?, ?, ?, ?)",
                (row["PAGARE"], row["AGENCIA"], nombre, texto, hoy_str),
            )

    for _, row in df_pagaron_parcial.iterrows():
        nombre = (
            str(row.get("SOCIO", "Cliente")).split()[0]
            + " "
            + str(row.get("SOCIO", "")).split()[-1]
            if len(str(row.get("SOCIO", "")).split()) > 1
            else str(row.get("SOCIO", ""))
        )
        comp = str(row.get("COMPROMISO", "")).strip()

        if comp.lower() in ["nan", "none"]:
            comp = ""

        texto_comp = f" ({comp})" if comp else ""
        texto = f"⚠️ {nombre}{texto_comp}: Pagó S/ {row['MONTO_PAGADO']:,.2f} ➔ Resta S/ {row['SALDO_PRES_hoy']:,.2f}"

        cursor.execute(
            "SELECT 1 FROM pagos_diarios WHERE pagare=? AND fecha_deteccion=? AND texto_mostrar=?",
            (row["PAGARE"], hoy_str, texto),
        )
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO pagos_diarios VALUES (?, ?, ?, ?, ?)",
                (row["PAGARE"], row["AGENCIA"], nombre, texto, hoy_str),
            )

    conn_sqlite.commit()

    # 📖 LEER PAGOS DE HOY Y AYER
    df_pagos_recientes = pd.read_sql_query(
        f"SELECT * FROM pagos_diarios WHERE fecha_deteccion IN ('{hoy_str}', '{ayer_str}') ORDER BY fecha_deteccion DESC",
        conn_sqlite,
    )
    conn_sqlite.close()

    # 3. CRUZAR FOTO FRESCA CON LA BASE LOCAL
    df_final = pd.merge(df_mora_fresca, df_local, on="PAGARE", how="left")
    df_final.fillna("", inplace=True)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📊 RESULTADOS DE GESTIÓN:")
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}]    🏆 Nuevos pagos procesados en este ciclo: {len(df_pagaron_total) + len(df_pagaron_parcial)}"
    )
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}]    📈 Histórico cargado (Hoy y Ayer): {len(df_pagos_recientes)}"
    )

    # 4. REPARTIR A GOOGLE SHEETS
    for agencia in agencias:
        df_agencia = df_final[df_final["AGENCIA"] == agencia]

        pagos_agencia = (
            df_pagos_recientes[df_pagos_recientes["agencia"] == agencia]
            if not df_pagos_recientes.empty
            else pd.DataFrame()
        )

        pagos_hoy_agencia = (
            pagos_agencia[pagos_agencia["fecha_deteccion"] == hoy_str]
            if not pagos_agencia.empty
            else pd.DataFrame()
        )
        pagos_ayer_agencia = (
            pagos_agencia[pagos_agencia["fecha_deteccion"] == ayer_str]
            if not pagos_agencia.empty
            else pd.DataFrame()
        )

        try:
            ws = doc_mora.worksheet(agencia)
            ws.batch_clear([RANGO_DATOS, "S1:S2000"])

            # 4.1 ESCRIBIR LA MORA CLÁSICA (Arriba)
            filas_mora_clasica = 0
            if not df_agencia.empty:
                valores_mora = df_agencia.values.tolist()
                ws.update("A2", valores_mora, value_input_option="USER_ENTERED")
                filas_mora_clasica = len(df_agencia)

            # 4.2 ESCRIBIR LA LISTA PREVENTIVA IA (Al fondo)
            try:
                conn_ia = sqlite3.connect(DB_LOCAL)
                # Llamamos a los advertidos de esta agencia específica
                query_ia = f"SELECT PAGARE, CUENTA, SOCIO, ANALISTA, SALDO_CAPITAL, Probabilidad AS [NIVEL RIESGO] FROM lista_preventiva_ia WHERE AGENCIA = '{agencia}'"
                df_ia_agencia = pd.read_sql(query_ia, conn_ia)
                conn_ia.close()

                if not df_ia_agencia.empty:
                    # Calculamos el espacio: 5 filas debajo del último moroso (o fila 5 si no hay mora)
                    fila_inicio_ia = (
                        filas_mora_clasica + 7 if filas_mora_clasica > 0 else 5
                    )

                    # Título llamativo
                    ws.update(
                        f"A{fila_inicio_ia}",
                        [
                            [
                                "🚨 LISTA PREVENTIVA IA (SOCIOS AL DÍA QUE CAERÁN EN MORA EL PRÓXIMO MES)"
                            ]
                        ],
                        value_input_option="USER_ENTERED",
                    )

                    # Encabezados
                    encabezados_ia = df_ia_agencia.columns.tolist()
                    ws.update(
                        f"A{fila_inicio_ia + 1}",
                        [encabezados_ia],
                        value_input_option="USER_ENTERED",
                    )

                    # Datos Predictivos
                    valores_ia = df_ia_agencia.values.tolist()
                    ws.update(
                        f"A{fila_inicio_ia + 2}",
                        valores_ia,
                        value_input_option="USER_ENTERED",
                    )
            except Exception as e:
                # Si la tabla IA aún no existe o hay error, pasamos en silencio para no arruinar la mora
                pass

            # 4.3 CONSTRUIR EL MURO DE LA VICTORIA (Lado derecho)
            datos_col_s = []

            # --- SECCIÓN HOY ---
            datos_col_s.append([f"🏆 PAGOS DE HOY ({fecha_hoy_obj.strftime('%d/%m')})"])
            if not pagos_hoy_agencia.empty:
                for _, row in pagos_hoy_agencia.iterrows():
                    datos_col_s.append([row["texto_mostrar"]])
            else:
                datos_col_s.append(["Sin pagos registrados aún."])

            datos_col_s.append([""])  # Espacio en blanco separador

            # --- SECCIÓN AYER ---
            datos_col_s.append(
                [
                    f"📅 PAGOS DE AYER ({(fecha_hoy_obj - timedelta(days=1)).strftime('%d/%m')})"
                ]
            )
            if not pagos_ayer_agencia.empty:
                for _, row in pagos_ayer_agencia.iterrows():
                    datos_col_s.append([row["texto_mostrar"]])
            else:
                datos_col_s.append(["Sin pagos registrados."])

            # Inyectar Muro de la Victoria en la columna S (S1)
            ws.update("S1", datos_col_s, value_input_option="USER_ENTERED")

        except gspread.exceptions.WorksheetNotFound:
            pass
        except Exception as e:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error escribiendo pestaña '{agencia}': {e}"
            )

        # 🔥 PAUSA ANTIBLOQUEO DE GOOGLE (Espera 3 segundos antes de ir a la siguiente agencia)
        time.sleep(10)

    # =========================================================================
    # 📸 GUARDAR LA NUEVA FOTO CON SALDOS
    # =========================================================================
    conn_sqlite = sqlite3.connect(DB_LOCAL)
    columnas_clave = [
        c
        for c in ["PAGARE", "AGENCIA", "SOCIO", "COMPROMISO", "SALDO_PRES"]
        if c in df_final.columns
    ]

    if columnas_clave:
        df_memoria = df_final[columnas_clave].copy()
        if "SALDO_PRES" in df_memoria.columns:
            df_memoria["SALDO_PRES"] = pd.to_numeric(
                df_memoria["SALDO_PRES"], errors="coerce"
            ).fillna(0)
        df_memoria.to_sql("memoria_ayer", conn_sqlite, if_exists="replace", index=False)
    conn_sqlite.close()

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Sincronización en la nube terminada con éxito."
    )
