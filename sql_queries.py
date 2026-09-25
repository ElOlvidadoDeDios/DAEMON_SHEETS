# sql_queries.py

QUERY_PRODUCTIVIDAD = """
WITH AgenciasMaestro AS (
    SELECT * FROM (VALUES 
        ('01', 'Wanchaq'), ('02', 'San Jerónimo'), ('03', 'Quillabamba'),
        ('04', 'Sicuani'), ('05', 'Molino'), ('06', 'Juliaca'),
        ('07', 'Lima Los Olivos'), ('08', 'Tica Tica'), ('09', 'Magisterio'),
        ('10', 'Lima SJL'), ('11', 'Chiclayo'), ('12', 'Arequipa'),
        ('13', 'Pucallpa')
    ) AS t(IdSAgencia, NombreAgencia)
),
TransaccionesHoy AS (
    SELECT 
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
        END AS IdSAgencia,
        T_PTM.PAGARE,
        T_PTM.MONTO_PRESTAMO
    FROM dbo.PRESTAMO T_PTM
    INNER JOIN dbo.PREEC T_PRE ON T_PRE.CUENTA = T_PTM.CUENTA AND T_PRE.OTORGA = T_PTM.OTORGA AND T_PRE.PAGARE = T_PTM.PAGARE AND T_PRE.PERIODO = CONVERT(VARCHAR(6), GETDATE(), 112)
    INNER JOIN SEGURIDAD.DBO.ANAREC T_ANA ON T_ANA.ID_ANAREC = T_PRE.ID_ANA AND T_ANA.FLAG_ANAREC = 'A'
    INNER JOIN SEGURIDAD.dbo.USUARIOS T_USU ON T_USU.ID_USER = T_ANA.ID_USER
    INNER JOIN SEGURIDAD.dbo.GRUPOUSER T_GRU ON T_GRU.ID_GRUPO = T_USU.ID_GRUPO AND T_GRU.NOM_GRUPO = 'CREDITOS'
    WHERE CAST(T_PTM.OTORGA AS DATE) = CAST(GETDATE() AS DATE)
      AND T_PTM.TIPO_PROD <> '52'
      AND T_USU.ID_USER NOT IN (
          'PRECASTIGO', 'RJULI6', 'RJULIACA', 'RLIMA7', 'RQUILLA3', 'RSICUA4',
          'LHR5', 'HTEJ5', 'TKPN5', 'GHVJ5', 'OTA5', 'SDHF5', 'CMN5', 'HQND5'
      )
)
SELECT 
    CAST(GETDATE() AS DATE) AS Fecha,
    CONVERT(VARCHAR(6), GETDATE(), 112) AS Periodo,
    CASE WHEN GROUPING(M.IdSAgencia) = 1 THEN 'TOTAL GENERAL' ELSE MAX(M.NombreAgencia) END AS NombreAgencia,
    ISNULL(COUNT(T.PAGARE), 0) AS ColocacionNumReal,
    ISNULL(SUM(T.MONTO_PRESTAMO), 0) AS ColocacionMontoReal
FROM AgenciasMaestro M
LEFT JOIN TransaccionesHoy T ON M.IdSAgencia = T.IdSAgencia
GROUP BY ROLLUP(M.IdSAgencia)
ORDER BY CASE WHEN M.IdSAgencia IS NULL THEN 1 ELSE 0 END, M.IdSAgencia;
"""

QUERY_INCLUSIVOS = """
WITH AgenciasMaestro AS (
    SELECT * FROM (VALUES 
        ('01', 'Wanchaq', 1), ('02', 'San Jerónimo', 2), ('03', 'Quillabamba', 3),
        ('04', 'Sicuani', 4), ('05', 'Molino', 5), ('06', 'Juliaca', 6),
        ('07', 'Lima Los Olivos', 7), ('08', 'Tica Tica', 8), ('09', 'Magisterio', 9),
        ('10', 'Lima SJL', 10), ('11', 'Chiclayo', 11), ('12', 'Arequipa', 12),
        ('13', 'Pucallpa', 13)
    ) AS t(IdSAgencia, NombreAgencia, Orden)
),
CreditosInclusivosMes AS (
    SELECT 
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
        END AS IdSAgencia,
        COUNT(T_PTM.PAGARE) AS CreditosInclusivos
    FROM dbo.PRESTAMO T_PTM
    INNER JOIN dbo.PREEC T_PRE ON T_PRE.CUENTA = T_PTM.CUENTA AND T_PRE.OTORGA = T_PTM.OTORGA AND T_PRE.PAGARE = T_PTM.PAGARE 
        AND T_PRE.PERIODO = CONVERT(VARCHAR(6), GETDATE(), 112)
    INNER JOIN SEGURIDAD.DBO.ANAREC T_ANA ON T_ANA.ID_ANAREC = T_PRE.ID_ANA AND T_ANA.FLAG_ANAREC = 'A'
    WHERE CAST(T_PTM.OTORGA AS DATE) >= DATEADD(month, DATEDIFF(month, 0, GETDATE()), 0)
      AND CAST(T_PTM.OTORGA AS DATE) <= CAST(GETDATE() AS DATE)
      AND T_PTM.TIPO_PROD IN ('42', '44') 
    GROUP BY T_ANA.ID_AGE, T_ANA.ID_USER
)
SELECT 
    AM.NombreAgencia AS AGENCIA,
    ISNULL(SUM(CI.CreditosInclusivos), 0) AS [CRÉDITOS PRODUCTO INCLUSIVOS]
FROM AgenciasMaestro AM
LEFT JOIN CreditosInclusivosMes CI ON AM.IdSAgencia = CI.IdSAgencia
GROUP BY AM.NombreAgencia, AM.Orden
ORDER BY AM.Orden;
"""

QUERY_MORA_POTENCIAL_V2 = """
SELECT
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
    
    C.PAGARE AS [PAGARE],
    C.CUENTA AS [CUENTA],
    ISNULL(S.RAZON_SOCIAL, LTRIM(RTRIM(S.APE_PATERNO)) + ' ' + LTRIM(RTRIM(S.APE_MATERNO)) + ', ' + LTRIM(RTRIM(S.NOMBRE))) AS [SOCIO],
    TP.NOM_PROD AS [PRODUCTO],
    T_PER.RAZON AS [ANALISTA],
    C.SALDO_PRES AS [SALDO_CAPITAL],
    C.NCUO_ATRASADAS AS [CUOTAS_ATRASADAS],
    C.DIAS_REALES AS [DIAS_ATRASO],
    P.CUOTA_FIJA AS [CUOTA_MENSUAL],
    ISNULL(LTRIM(RTRIM(S.TLF_CEL1)), '') AS [CELULAR_1],
    ISNULL(LTRIM(RTRIM(S.TLF_CEL2)), '') AS [CELULAR_2],
    ISNULL(LTRIM(RTRIM(S.TLF_FIJO1)), '') AS [TELEFONO_1],
    ISNULL(LTRIM(RTRIM(S.TLF_FIJO2)), '') AS [TELEFONO_2]

FROM PREEC C
INNER JOIN SOCIOS S ON C.CUENTA = S.CUENTA
INNER JOIN PRESTAMO P ON C.PAGARE = P.PAGARE
LEFT JOIN TIPOPROD TP ON C.TIPO_PROD = TP.TIPO_PROD
INNER JOIN SEGURIDAD.DBO.ANAREC T_ANA ON T_ANA.ID_ANAREC = C.ID_ANA AND T_ANA.FLAG_ANAREC = 'A'
INNER JOIN SEGURIDAD.dbo.USUARIOS T_USU ON T_USU.ID_USER = T_ANA.ID_USER
INNER JOIN SEGURIDAD.dbo.GRUPOUSER T_GRU ON T_GRU.ID_GRUPO = T_USU.ID_GRUPO AND T_GRU.NOM_GRUPO = 'CREDITOS'
INNER JOIN SEGURIDAD.dbo.PERSONAL T_PER ON T_PER.DNI = T_USU.DNI
INNER JOIN SEGURIDAD.dbo.TCARGO_USER T_CAR ON T_CAR.ID_CARGO = T_PER.ID_CARGO
WHERE 
    C.PERIODO = CONVERT(VARCHAR(6), GETDATE(), 112)
    AND C.DIAS_REALES >= DAY(GETDATE())
    AND C.SALDO_PRES > 0             
    AND C.NCUO_ATRASADAS > 0         
    AND P.SALDO_PRES > 0 
    AND T_CAR.DESCRIP LIKE '%ANALISTA DE CREDITOS%'
    AND T_USU.ID_USER NOT IN (
        'PRECASTIGO' 
        , 'RJULI6', 'RJULIACA', 'RLIMA7', 'RQUILLA3', 'RSICUA4' 
        , 'LHR5', 'HTEJ5', 'TKPN5', 'GHVJ5', 'OTA5', 'SDHF5', 'CMN5', 'HQND5', 'RTRES' 
    )
ORDER BY 
    C.SALDO_PRES DESC;
"""

QUERY_PLAZO_FIJO = """
-- ==============================================================================
-- ⚠️ ATENCIÓN EQUIPO DE DATOS / DESARROLLADORES:
-- Este script está configurado a propósito para replicar un ERROR HISTÓRICO 
-- del reporte PDF actual del Core Bancario.
-- 
-- EL FALLO: El reporte PDF está tomando la cuota de interés MÁS ANTIGUA 
-- del historial del cliente (ASC) en lugar de la cuota vigente, cruzando 
-- el capital de hoy con una tasa de hace meses o años.
--
-- PARA CORREGIRLO AL VALOR REAL: 
-- 1. Comenten la sección "LÓGICA DEL PDF (ERRÓNEA)"
-- 2. Descomenten la sección "LÓGICA CORRECTA (VIGENTE)"
-- ==============================================================================

SELECT
    A.AGENCIA AS [IdSAgencia],
    A.CUENTA AS [cuenta],
    LTRIM(RTRIM(ISNULL(S.APE_PATERNO, '') + ' ' + ISNULL(S.APE_MATERNO, ''))) + ', ' + LTRIM(RTRIM(ISNULL(S.NOMBRE, ''))) AS [nombre_socio],
    A.CTA_AHO AS [contrato],
    A.SALDO_ACTUAL AS [capital],
    
    -- TEA (Usamos la de la cuenta, y si no hay, calculamos sobre la cuota)
    COALESCE(
        NULLIF(A.TEA, 0), 
        ROUND((POWER((CRON_ANTIGUO.INT_VIEJO / NULLIF(A.SALDO_ACTUAL, 0)) + 1.0, 360.0 / NULLIF(A.PLAZO, 0)) - 1.0) * 100, 4),
        0
    ) AS [tea],
    
    -- =========================================================
    -- ❌ 1. LÓGICA DEL PDF (ERRÓNEA - ACTIVA ACTUALMENTE)
    -- Trae el interés más viejo del historial para cuadrar con el PDF
    -- =========================================================
    COALESCE(CRON_ANTIGUO.INT_VIEJO, 0) AS [interes],

    -- =========================================================
    -- ✅ 2. LÓGICA CORRECTA (VIGENTE - COMENTADA PARA FUTURO)
    -- Usa la TEA real matemática, o rescata el cronograma actual
    -- =========================================================
    /*
    COALESCE(
        ROUND((POWER((NULLIF(A.TEA, 0) / 100.0) + 1.0, A.PLAZO / 360.0) - 1.0) * A.SALDO_ACTUAL, 2),
        CRON_NUEVO.INT_REAL,
        0
    ) AS [interes],
    */
    
    CAST(A.FECHA_APERT AS DATE) AS [fecha_apertura],
    A.PLAZO AS [plazo_dias],
    CAST(DATEADD(day, A.PLAZO, ISNULL(A.FECHA_RENOV, A.FECHA_APERT)) AS DATE) AS [fecha_vencimiento]

FROM [TRANSACMIF].[dbo].[AHORRO] A WITH (NOLOCK)
LEFT JOIN [TRANSACMIF].[dbo].[SOCIOS] S WITH (NOLOCK)
    ON A.CUENTA = S.CUENTA 

-- =========================================================
-- ❌ EXTRACCIÓN DEL ERROR (ACTIVO)
-- Forzamos ORDER BY ASC para ir al pasado y copiar el bug del PDF
-- =========================================================
OUTER APPLY (
    SELECT TOP 1 INTERES AS INT_VIEJO
    FROM [TRANSACMIF].[dbo].[AHOCRON] C WITH (NOLOCK)
    WHERE C.CTA_AHO = A.CTA_AHO
      AND C.INTERES IS NOT NULL
      AND C.INTERES > 0
    ORDER BY C.FECHA_VENC ASC
) CRON_ANTIGUO

-- =========================================================
-- ✅ EXTRACCIÓN CORRECTA (COMENTADA PARA FUTURO)
-- Busca la última cuota completada en el tiempo presente
-- =========================================================
/*
OUTER APPLY (
    SELECT TOP 1 INTERES AS INT_REAL
    FROM [TRANSACMIF].[dbo].[AHOCRON] C WITH (NOLOCK)
    WHERE C.CTA_AHO = A.CTA_AHO
      AND C.INTERES IS NOT NULL
      AND C.INTERES > 0
      AND C.FECHA_VENC <= GETDATE()
    ORDER BY C.FECHA_VENC DESC
) CRON_NUEVO
*/

WHERE A.TIPO_AHO = '03'
    AND A.SUBTIPO_AHO IN ('102', '103')
    AND A.ESTADO = 1
    AND A.AGENCIA <> '98'
    AND A.SALDO_ACTUAL > 0
    AND DATEADD(day, A.PLAZO, ISNULL(A.FECHA_RENOV, A.FECHA_APERT)) >= CAST(GETDATE() AS DATE)
"""

QUERY_MORA_PREVENTIVA_IA = """
SELECT
    -- 1. NOMBRE DE LA AGENCIA PARA EL GOOGLE SHEETS
    CASE (
        CASE
            WHEN T_ANA.ID_AGE = '98' THEN CASE WHEN RTRIM(T_ANA.ID_USER) LIKE '%10' THEN '10' WHEN RTRIM(T_ANA.ID_USER) LIKE '%11' THEN '11' WHEN RTRIM(T_ANA.ID_USER) LIKE '%12' THEN '12' WHEN RTRIM(T_ANA.ID_USER) LIKE '%13' THEN '13' WHEN RTRIM(T_ANA.ID_USER) LIKE '%6' THEN '06' WHEN RTRIM(T_ANA.ID_USER) LIKE '%7' THEN '07' ELSE '98' END
            WHEN T_ANA.ID_AGE = '01' THEN CASE WHEN RTRIM(T_ANA.ID_USER) LIKE '%9' THEN '09' ELSE '01' END ELSE T_ANA.ID_AGE END
    )
        WHEN '01' THEN 'Wanchaq' WHEN '02' THEN 'San Jerónimo' WHEN '03' THEN 'Quillabamba' WHEN '04' THEN 'Sicuani' WHEN '05' THEN 'Molino' WHEN '06' THEN 'Juliaca' WHEN '07' THEN 'Lima Los Olivos' WHEN '08' THEN 'Tica Tica' WHEN '09' THEN 'Magisterio' WHEN '10' THEN 'Lima SJL' WHEN '11' THEN 'Chiclayo' WHEN '12' THEN 'Arequipa' WHEN '13' THEN 'Pucallpa' ELSE 'Otra Agencia'
    END AS [AGENCIA],

    C.PAGARE AS [PAGARE],
    C.CUENTA AS [CUENTA],
    ISNULL(S.RAZON_SOCIAL, LTRIM(RTRIM(S.APE_PATERNO)) + ' ' + LTRIM(RTRIM(S.APE_MATERNO)) + ', ' + LTRIM(RTRIM(S.NOMBRE))) AS [SOCIO],
    T_PER.RAZON AS [ANALISTA],
    C.SALDO_PRES AS [SALDO_CAPITAL],
    C.NCUO_ATRASADAS AS [CUOTAS_ATRASADAS],
    C.DIAS_REALES AS [DIAS_ATRASO],

    -- 2. VARIABLES PARA XGBOOST
    CASE 
        WHEN T_ANA.ID_AGE = '98' THEN CASE WHEN RTRIM(T_ANA.ID_USER) LIKE '%10' THEN '10' WHEN RTRIM(T_ANA.ID_USER) LIKE '%11' THEN '11' WHEN RTRIM(T_ANA.ID_USER) LIKE '%12' THEN '12' WHEN RTRIM(T_ANA.ID_USER) LIKE '%13' THEN '13' WHEN RTRIM(T_ANA.ID_USER) LIKE '%6' THEN '06' WHEN RTRIM(T_ANA.ID_USER) LIKE '%7' THEN '07' ELSE '98' END
        WHEN T_ANA.ID_AGE = '01' THEN CASE WHEN RTRIM(T_ANA.ID_USER) LIKE '%9' THEN '09' ELSE '01' END ELSE T_ANA.ID_AGE END AS [IdAgenciaCalculada],
    TP.NOM_PROD AS Producto_Crediticio,
    CASE WHEN DATEDIFF(MONTH, S.FECHA_APERTURA, P.OTORGA) <= 1 THEN 'NUEVO' ELSE 'RECURRENTE' END AS Tipo_Socio,
    S.TIPO_ACTI AS Actividad_Economica,
    P.MONTO_PRESTAMO AS Monto_Desembolsado,
    ISNULL(P.PLAZO, 0) AS Plazo,
    P.TEA_INTERES AS Tasa,
    P.COD_FRECUENCIA AS Frecuencia_Pago,
    ISNULL(P.CUOTA_FIJA, 0) AS Cuota_Programada,
    (C.NCUO_ATRASADAS * ISNULL(P.CUOTA_FIJA, 0)) AS Importe_Vencido, 
    ISNULL(EV.TOTAL_ING, 0) AS Ingreso_Mensual,
    ISNULL(EV.NETO, 0) AS Excedente_Mensual,
    CASE WHEN P.AMP_REF = 'A' THEN 'AMPLIACION' WHEN P.AMP_REF = 'R' THEN 'REFINANCIADO' WHEN P.AMP_REF = 'P' THEN 'PARALELO' ELSE 'NUEVO' END AS Tipo_Credito,
    CASE WHEN P.NRO_REPRO > 0 OR P.RIESGO_REFINANCIA = '1' THEN 'SI' ELSE 'NO' END AS Reprogramado_Refinanciado

FROM PREEC C WITH(NOLOCK)
INNER JOIN SOCIOS S WITH(NOLOCK) ON C.CUENTA = S.CUENTA
INNER JOIN PRESTAMO P WITH(NOLOCK) ON C.PAGARE = P.PAGARE
LEFT JOIN TIPOPROD TP WITH(NOLOCK) ON C.TIPO_PROD = TP.TIPO_PROD
INNER JOIN SEGURIDAD.DBO.ANAREC T_ANA WITH(NOLOCK) ON T_ANA.ID_ANAREC = C.ID_ANA AND T_ANA.FLAG_ANAREC = 'A'
INNER JOIN SEGURIDAD.dbo.USUARIOS T_USU WITH(NOLOCK) ON T_USU.ID_USER = T_ANA.ID_USER
INNER JOIN SEGURIDAD.dbo.PERSONAL T_PER WITH(NOLOCK) ON T_USU.DNI = T_PER.DNI
INNER JOIN SEGURIDAD.dbo.TCARGO_USER T_CAR WITH(NOLOCK) ON T_CAR.ID_CARGO = T_PER.ID_CARGO
LEFT JOIN (
    SELECT PS.PAGARE, E.TOTAL_ING, E.NETO FROM PRESOL PS WITH(NOLOCK) LEFT JOIN PRE_EVAL_ECO E WITH(NOLOCK) ON PS.NRO_SOL = E.NRO_SOLI WHERE PS.ESTADO = '3'
) EV ON C.PAGARE = EV.PAGARE
WHERE 
    C.PERIODO = CONVERT(VARCHAR(6), GETDATE(), 112)
    AND C.DIAS_REALES < DAY(GETDATE()) 
    AND C.SALDO_PRES > 0 
    AND P.SALDO_PRES > 0 
    AND T_CAR.DESCRIP LIKE '%ANALISTA DE CREDITOS%'
    AND T_USU.ID_USER NOT IN ('PRECASTIGO', 'RJULI6', 'RJULIACA', 'RLIMA7', 'RQUILLA3', 'RSICUA4', 'LHR5', 'HTEJ5', 'TKPN5', 'GHVJ5', 'OTA5', 'SDHF5', 'CMN5', 'HQND5', 'RTRES')
"""
