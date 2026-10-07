# sync_ranking.py

import pandas as pd
import pyodbc
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import config
from sql_queries import QUERY_BASE_RANKING
import random


def generar_comentario(asesor, puesto_actual, variacion):
    # Si no hay historial (ej. el primer día que se corre el script), frenar aquí.
    if variacion is None:
        return "Nuevo en la tabla. Registrando su primer puntaje en el radar."

    # Lógica de comentarios dinámicos basados en rendimiento (SIN EMOJIS)
    if puesto_actual == 1 and variacion == 0:
        opciones = [
            f"El rey/reina indiscutible. {asesor.split(',')[0]} defiende el 1er puesto.",
            f"Nadie lo baja. Sigue reinando en la cima.",
            f"Primer lugar otro dia consecutivo. Un desempeno legendario.",
        ]
        return random.choice(opciones)
    elif puesto_actual == 1 and variacion > 0:
        return (
            "Hazana alcanzada. Escalo hasta la cima y se corona en el 1er puesto hoy."
        )
    elif variacion > 3:
        return f"Modo turbo activado. Subio {int(variacion)} puestos de golpe."
    elif variacion > 0:
        return f"Escalando posiciones. Subio {int(variacion)} escalones desde ayer."
    elif variacion < 0:
        return f"Resbalo un poco (bajo {int(abs(variacion))} puestos), pero la semana no acaba."
    elif variacion == 0:
        return f"Se mantiene firme y constante en el puesto {puesto_actual}."
    else:
        return "Nuevo competidor en el radar. Ingresa al ranking general."


def calcular_puntaje_negocio(valor, maximo, peso):
    # Si el valor es negativo o cero, no merece puntos.
    # Si el máximo general es 0 o negativo, nadie gana puntos.
    if pd.isna(valor) or valor <= 0 or maximo <= 0:
        return 0.0
    return (valor / maximo) * peso


def ejecutar_ranking():
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Calculando Ranking de Asesores (40-40-20)..."
    )

    # 1. Obtener datos crudos de SQL Server (Operaciones y Crecimiento)
    try:
        conn = pyodbc.connect(config.DB_DWH)
        df_sql = pd.read_sql(QUERY_BASE_RANKING, conn)
    except Exception as e:
        print(f"Error extrayendo base SQL: {e}")
        return

    # 2. Contar Seguros vendidos desde Google Sheets
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            config.CREDS_FILE, config.SCOPE
        )
        client = gspread.authorize(creds)
        doc = client.open(config.SHEET_SEGUROS)

        # Usar get_all_values() para esquivar el error de las columnas duplicadas
        hoja_asesores = doc.worksheet("ASESORES").get_all_values()

        # Mapeamos a mano: Columna 0 es el ID, Columna 1 es el Nombre
        mapa_nombres_id = {}
        for row in hoja_asesores[1:]:  # Omitimos la cabecera (fila 0)
            if len(row) >= 2 and str(row[1]).strip():
                # 🚀 CORRECCIÓN: Limpieza agresiva de dobles espacios en nombres
                nombre_limpio = " ".join(str(row[1]).split()).upper()
                mapa_nombres_id[nombre_limpio] = str(row[0]).strip()

        conteo_seguros = {}
        for ws in doc.worksheets():
            if ws.title != "ASESORES":
                # Columna A tiene los nombres de los asesores
                nombres = ws.col_values(1)[1:]
                for nom in nombres:
                    # 🚀 CORRECCIÓN: Limpieza agresiva también al leer las ventas
                    nom_limpio = " ".join(str(nom).split()).upper()
                    if nom_limpio:
                        conteo_seguros[nom_limpio] = (
                            conteo_seguros.get(nom_limpio, 0) + 1
                        )

        # Convertir conteo a DataFrame con IdSAsesor
        data_seguros = []
        for nombre, cantidad in conteo_seguros.items():
            id_asesor = mapa_nombres_id.get(nombre)
            if id_asesor:
                data_seguros.append(
                    {"IdSAsesor": id_asesor, "Seguros_Vendidos": cantidad}
                )
        df_seguros = pd.DataFrame(data_seguros)
        # 🚀 NUEVO BLINDAJE 1: Agrupar para que no haya IDs duplicados
        if not df_seguros.empty:
            df_seguros = df_seguros.groupby("IdSAsesor", as_index=False)[
                "Seguros_Vendidos"
            ].sum()

    except Exception as e:
        print(f"Error procesando Google Sheets de Seguros: {e}")
        df_seguros = pd.DataFrame(columns=["IdSAsesor", "Seguros_Vendidos"])

    # 3. Fusionar datos y aplicar matemáticas
    import re

    # 🚀 CORRECCIÓN: Limpiar espacios invisibles en los IDs antes del cruce SQL/Sheets
    df_sql["IdSAsesor"] = df_sql["IdSAsesor"].astype(str).str.strip()
    if not df_seguros.empty:
        df_seguros["IdSAsesor"] = df_seguros["IdSAsesor"].astype(str).str.strip()

    df_master = pd.merge(df_sql, df_seguros, on="IdSAsesor", how="left")

    # Rellenar nulos con 0 para los asesores que no vendieron seguros
    df_master["Seguros_Vendidos"] = df_master["Seguros_Vendidos"].fillna(0).astype(int)

    # Encontrar a los líderes absolutos de cada categoría
    max_op = df_master["Operaciones"].max()
    max_crec = df_master["Crecimiento_Neto_150"].max()
    max_seg = df_master["Seguros_Vendidos"].max()

    # Calcular puntajes reales (negativos automáticamente se vuelven 0)
    df_master["Puntos_Op"] = (
        df_master["Operaciones"]
        .apply(lambda x: calcular_puntaje_negocio(x, max_op, 40))
        .round(2)
    )

    df_master["Puntos_Crec"] = (
        df_master["Crecimiento_Neto_150"]
        .apply(lambda x: calcular_puntaje_negocio(x, max_crec, 40))
        .round(2)
    )

    df_master["Puntos_Seg"] = (
        df_master["Seguros_Vendidos"]
        .apply(lambda x: calcular_puntaje_negocio(x, max_seg, 20))
        .round(2)
    )

    df_master["Puntaje_Total"] = (
        df_master["Puntos_Op"] + df_master["Puntos_Crec"] + df_master["Puntos_Seg"]
    ).round(2)

    # Calcular el ranking actual (1 es el puntaje más alto)
    df_master["Puesto_Actual"] = (
        df_master["Puntaje_Total"].rank(method="min", ascending=False).astype(int)
    )

    # 4. Historial y Comentarios Dinámicos
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    fecha_ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        query_ayer = f"SELECT IdSAsesor, Puesto_Actual AS Puesto_Anterior FROM [DWH_Gestion_Cartera].[dbo].[ranking_asesor_10] WHERE Fecha_Calculo = '{fecha_ayer}'"
        df_ayer = pd.read_sql(query_ayer, conn)
        # 🚀 NUEVO BLINDAJE 2: Limpiar la basura de ayer para que no nos contamine el cruce hoy
        df_ayer = df_ayer.drop_duplicates(subset=["IdSAsesor"], keep="last")
    except:
        df_ayer = pd.DataFrame(columns=["IdSAsesor", "Puesto_Anterior"])

    df_master = pd.merge(df_master, df_ayer, on="IdSAsesor", how="left")

    comentarios = []
    for _, row in df_master.iterrows():
        p_actual = row["Puesto_Actual"]
        p_ayer = row["Puesto_Anterior"]

        if pd.isna(p_ayer):
            variacion = None
        else:
            variacion = p_ayer - p_actual

        comentarios.append(generar_comentario(row["Asesor"], p_actual, variacion))

    df_master["Comentario_Creativo"] = comentarios
    df_master["Fecha_Calculo"] = fecha_hoy

    df_insert = df_master[
        [
            "Fecha_Calculo",
            "IdSAsesor",
            "Asesor",
            "Agencia",
            "Operaciones",
            "Crecimiento_Neto_150",
            "Seguros_Vendidos",
            "Puntos_Op",
            "Puntos_Crec",
            "Puntos_Seg",
            "Puntaje_Total",
            "Puesto_Actual",
            "Puesto_Anterior",
            "Comentario_Creativo",
        ]
    ]
    # 🚀 CORRECCIÓN: Convertimos todo a "object" para que Pandas suelte los NaN y acepte los None (NULL) puros
    df_insert = df_insert.astype(object).where(pd.notnull(df_insert), None)

    # 5. Guardar en SQL
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM [DWH_Gestion_Cartera].[dbo].[ranking_asesor_10] WHERE Fecha_Calculo = ?",
        fecha_hoy,
    )

    sql_insert = """
        INSERT INTO [DWH_Gestion_Cartera].[dbo].[ranking_asesor_10] (
            [Fecha_Calculo], [IdSAsesor], [Asesor], [Agencia], [Operaciones], [Crecimiento_Neto_150], [Seguros_Vendidos], 
            [Puntos_Op], [Puntos_Crec], [Puntos_Seg], [Puntaje_Total], [Puesto_Actual], [Puesto_Anterior], [Comentario_Creativo]
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    cursor.executemany(sql_insert, df_insert.values.tolist())
    conn.commit()
    conn.close()

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Ranking actualizado y guardado en DWH. Total analizados: {len(df_insert)}"
    )
