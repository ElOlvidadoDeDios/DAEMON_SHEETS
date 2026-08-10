import gspread
import pyodbc
import time
from datetime import datetime

# 1. CONFIGURACIÓN DE CONEXIONES
# Reemplaza con los datos de tu servidor SQL
SQL_CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=TU_SERVIDOR;"
    "DATABASE=TRANSACMIF;"
    "UID=tu_usuario;"
    "PWD=tu_contraseña;"
)

# Configura tu archivo de credenciales de Google (JSON)
GC = gspread.service_account(filename="credenciales.json")
# Abre tu documento de Google Sheets por el nombre o ID
SPREADSHEET = GC.open("Reporte_Productividad_En_Vivo")

# Selecciona la Hoja Nro 5 (Recuerda que en Python el índice empieza en 0, así que la hoja 5 es el índice 4)
HOJA_REPORTE = SPREADSHEET.get_worksheet(5)

# Celda que actuará como nuestro "Botón" (Ej. A1)
CELDA_GATILLO = "I1"


def ejecutar_consulta_sql():
    """Ejecuta la consulta de mora y retorna los resultados."""
    print(f"[{datetime.now()}] Conectando a SQL Server...")

    # Aquí pegas la consulta SQL gigante y automatizada que armamos
    query = """
    SELECT
    -- Traduce el código de la agencia a su nombre real, separando agencias digitales y sucursales (ej. Wanchaq/Magisterio)
    CASE (
        CASE
            WHEN T_ANA.ID_AGE = '98' THEN
                CASE
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%10' THEN '10' 
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%11' THEN '11' 
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%12' THEN '12' 
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%13' THEN '13' 
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%6'  THEN '06' 
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%7'  THEN '07' 
                    ELSE '98'
                END
            WHEN T_ANA.ID_AGE = '01' THEN
                CASE
                    WHEN RTRIM(T_ANA.ID_USER) LIKE '%9' THEN '09'
                    ELSE '01'
                END
            ELSE T_ANA.ID_AGE
        END
    )
        WHEN '01' THEN 'Wanchaq'
        WHEN '02' THEN 'San Jerónimo'
        WHEN '03' THEN 'Quillabamba'
        WHEN '04' THEN 'Sicuani'
        WHEN '05' THEN 'Molino'
        WHEN '06' THEN 'Juliaca'
        WHEN '07' THEN 'Lima Los Olivos'
        WHEN '08' THEN 'Tica Tica'
        WHEN '09' THEN 'Magisterio'
        WHEN '10' THEN 'Lima SJL'
        WHEN '11' THEN 'Chiclayo'
        WHEN '12' THEN 'Arequipa'
        WHEN '13' THEN 'Pucallpa'
        ELSE 'Otra Agencia'
    END AS [AGENCIA],
    
    -- Extrae el nombre completo o la razón social del cliente
    ISNULL(S.RAZON_SOCIAL, LTRIM(RTRIM(S.APE_PATERNO)) + ' ' + LTRIM(RTRIM(S.APE_MATERNO)) + ', ' + LTRIM(RTRIM(S.NOMBRE))) AS [SOCIO],
    
    -- Obtiene el nombre del tipo de crédito (ej. PYME 1, Consumo)
    TP.NOM_PROD AS [PRODUCTO],
    
    -- Muestra el saldo capital pendiente formateado con separadores de miles y decimales
    FORMAT(C.SALDO_PRES, 'N2', 'es-ES') AS [SALDO PRES.],
    
    -- Muestra el nombre completo del analista de créditos responsable
    T_PER.RAZON AS [ANALISTA],
    
    -- Muestra la cantidad de días de atraso reales del crédito
    C.DIAS_REALES AS [DIAS_ATRASO]

-- Tabla base de la foto de cartera mensual
FROM PREEC C

-- Cruce para obtener los datos personales del cliente
INNER JOIN SOCIOS S 
    ON C.CUENTA = S.CUENTA

-- Cruce con créditos en vivo para validar la vigencia actual
INNER JOIN PRESTAMO P 
    ON C.PAGARE = P.PAGARE

-- Cruce con el catálogo para obtener el nombre del producto
LEFT JOIN TIPOPROD TP 
    ON C.TIPO_PROD = TP.TIPO_PROD

-- Cruces con el módulo de SEGURIDAD para validar al analista:
-- 1. Obtiene el registro activo del analista
INNER JOIN SEGURIDAD.DBO.ANAREC T_ANA 
    ON T_ANA.ID_ANAREC = C.ID_ANA AND T_ANA.FLAG_ANAREC = 'A'
-- 2. Obtiene el usuario de sistema del analista
INNER JOIN SEGURIDAD.dbo.USUARIOS T_USU 
    ON T_USU.ID_USER = T_ANA.ID_USER
-- 3. Valida que el usuario pertenezca operativamente al grupo de CREDITOS
INNER JOIN SEGURIDAD.dbo.GRUPOUSER T_GRU 
    ON T_GRU.ID_GRUPO = T_USU.ID_GRUPO AND T_GRU.NOM_GRUPO = 'CREDITOS'
-- 4. Obtiene el nombre real del personal
INNER JOIN SEGURIDAD.dbo.PERSONAL T_PER 
    ON T_PER.DNI = T_USU.DNI
-- 5. Obtiene el cargo oficial del personal
INNER JOIN SEGURIDAD.dbo.TCARGO_USER T_CAR 
    ON T_CAR.ID_CARGO = T_PER.ID_CARGO

WHERE 
    -- Filtra exclusivamente la cartera del mes en evaluación
    C.PERIODO = CONVERT(VARCHAR(6), GETDATE(), 112)
    
    -- FILTRO AUTOMÁTICO: Excluye la mora administrativa (días de gracia) igualando el corte al día actual del mes
    AND C.DIAS_REALES >= DAY(GETDATE())
    
    -- Verifica que el crédito tenga saldo pendiente en el cierre mensual
    AND C.SALDO_PRES > 0             
    
    -- Verifica que tenga al menos una cuota vencida
    AND C.NCUO_ATRASADAS > 0         
    
    -- Valida en tiempo real que el crédito no haya sido cancelado hoy
    AND P.SALDO_PRES > 0 
    
    -- Excluye a jefes de agencia o administrativos; solo deja a analistas operativos
    AND T_CAR.DESCRIP LIKE '%ANALISTA DE CREDITOS%'
    
    -- Excluye carteras reasignadas a pre-castigo, recuperadores externos o gestores de tramos altos
    AND T_USU.ID_USER NOT IN (
        'PRECASTIGO' 
        , 'RJULI6', 'RJULIACA', 'RLIMA7', 'RQUILLA3', 'RSICUA4' 
        , 'LHR5', 'HTEJ5', 'TKPN5', 'GHVJ5', 'OTA5', 'SDHF5', 'CMN5', 'HQND5', 'RTRES' 
    )

ORDER BY 
    -- Ordena la lista final desde la deuda más alta hasta la más baja
    C.SALDO_PRES DESC;
    """

    conn = pyodbc.connect(SQL_CONN_STR)
    cursor = conn.cursor()
    cursor.execute(query)

    # Extraer los nombres de las columnas
    columnas = [column[0] for column in cursor.description]
    # Extraer todas las filas de datos
    datos = [list(row) for row in cursor.fetchall()]

    conn.close()
    return columnas, datos


def escuchar_hoja():
    """El daemon que corre infinitamente esperando el click."""
    print("Daemon iniciado. Escuchando la Hoja 5...")

    while True:
        try:
            # Leemos el valor de la celda (el checkbox)
            estado_boton = HOJA_REPORTE.acell(CELDA_GATILLO).value

            if estado_boton == "TRUE":
                print(f"[{datetime.now()}] ¡Botón presionado! Iniciando extracción...")

                # 1. Cambiamos el estado a "Procesando..." para que el usuario vea que algo pasa
                HOJA_REPORTE.update(CELDA_GATILLO, "PROCESANDO...")

                # 2. Ejecutamos el SQL
                columnas, datos = ejecutar_consulta_sql()

                # 3. Limpiamos la hoja (dejando la fila 1 intacta si ahí está tu botón)
                # (Ajusta los rangos según dónde quieras pegar la data)
                HOJA_REPORTE.batch_clear(["A3:Z1000"])

                # 4. Escribimos los encabezados y los datos a partir de la celda A3
                HOJA_REPORTE.update("A3", [columnas] + datos)

                # 5. Apagamos el botón (Lo regresamos a FALSE)
                HOJA_REPORTE.update(CELDA_GATILLO, "FALSE")
                print(f"[{datetime.now()}] Reporte actualizado con éxito.")

        except Exception as e:
            print(f"Error en el Daemon: {e}")

        # Pausa de 5 segundos antes de volver a revisar (para no saturar la cuota de la API de Google)
        time.sleep(5)


if __name__ == "__main__":
    escuchar_hoja()
