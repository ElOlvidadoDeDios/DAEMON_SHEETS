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

QUERY_MORA_POTENCIAL = """
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
    ISNULL(S.RAZON_SOCIAL, LTRIM(RTRIM(S.APE_PATERNO)) + ' ' + LTRIM(RTRIM(S.APE_MATERNO)) + ', ' + LTRIM(RTRIM(S.NOMBRE))) AS [SOCIO],
    TP.NOM_PROD AS [PRODUCTO],
    FORMAT(C.SALDO_PRES, 'N2', 'es-ES') AS [SALDO PRES.],
    T_PER.RAZON AS [ANALISTA],
    C.DIAS_REALES AS [DIAS_ATRASO]
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
