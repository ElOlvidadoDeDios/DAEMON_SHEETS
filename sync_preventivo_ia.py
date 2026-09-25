import pandas as pd
import sqlite3
import pyodbc
from datetime import datetime
import config
import xgboost as xgb
import pickle
import numpy as np
from sql_queries import QUERY_MORA_PREVENTIVA_IA

DB_LOCAL = "mora_gestion.db"


def ejecutar_ia_preventiva():
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] 🤖 Iniciando Motor de IA Preventiva..."
    )
    conn = sqlite3.connect(DB_LOCAL)
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS historial_ia (pagare TEXT PRIMARY KEY, probabilidad REAL, fecha_alerta DATE)"
    )
    conn.commit()

    try:
        conn_sql = pyodbc.connect(config.DB_TRANSACMIF)
        df_sanos = pd.read_sql(QUERY_MORA_PREVENTIVA_IA, conn_sql)
        conn_sql.close()
    except Exception as e:
        print(f"Error SQL: {e}")
        return

    if df_sanos.empty:
        return

    try:
        # Cargamos el cerebro y las columnas con el mismo nombre para que no haya errores
        with open("modelo_ews_v2.pkl", "rb") as f:
            modelo = pickle.load(f)
        with open("columnas_ews_v2.pkl", "rb") as f:
            columnas_entrenamiento = pickle.load(f)

        df_ml = df_sanos.copy()
        df_ml["Ingreso_Mensual"] = df_ml["Ingreso_Mensual"].replace(0, np.nan)
        df_ml["Excedente_Mensual"] = df_ml["Excedente_Mensual"].replace(0, np.nan)

        # 🔥 CORRECCIÓN CLAVE: Renombramos para que XGBoost reconozca sus variables
        df_ml = df_ml.rename(
            columns={
                "IdAgenciaCalculada": "Agencia",
                "SALDO_CAPITAL": "Saldo_Capital",
                "CUOTAS_ATRASADAS": "Cuotas_Atrasadas",
                "DIAS_ATRASO": "Dias_Atraso_En_Cierre",
            }
        )

        # Ocultamos texto
        cols_visuales = ["AGENCIA", "PAGARE", "CUENTA", "SOCIO", "ANALISTA"]
        X_raw = df_ml.drop(columns=cols_visuales, errors="ignore")

        X = pd.get_dummies(X_raw, drop_first=True, dummy_na=True)
        # Usamos el mismo nombre que cargamos arriba
        X = X.reindex(columns=columnas_entrenamiento, fill_value=0)

        df_sanos["Probabilidad"] = np.round(modelo.predict_proba(X)[:, 1] * 100, 2)
        df_alertas = df_sanos[df_sanos["Probabilidad"] >= 75].copy()

        # 1. Guardar la lista para mostrarla al fondo del Excel hoy
        df_mostrar = df_alertas[
            [
                "AGENCIA",
                "PAGARE",
                "CUENTA",
                "SOCIO",
                "ANALISTA",
                "SALDO_CAPITAL",
                "Probabilidad",
            ]
        ].copy()
        df_mostrar["Probabilidad"] = df_mostrar["Probabilidad"].apply(
            lambda x: f"🔴 RIESGO ALTO ({x}%)"
        )
        df_mostrar.to_sql("lista_preventiva_ia", conn, if_exists="replace", index=False)

        # 2. Guardar en el historial de memoria para el "⚠️ Se advirtió" del futuro
        hoy = datetime.now().strftime("%Y-%m-%d")
        for _, row in df_alertas.iterrows():
            c.execute(
                "INSERT INTO historial_ia (pagare, probabilidad, fecha_alerta) VALUES (?, ?, ?) ON CONFLICT(pagare) DO UPDATE SET probabilidad=excluded.probabilidad",
                (str(row["PAGARE"]).strip(), float(row["Probabilidad"]), hoy),
            )
        conn.commit()
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] ✅ IA terminó. {len(df_alertas)} clientes sanos advertidos."
        )
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Error IA: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    ejecutar_ia_preventiva()
