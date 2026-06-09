from enum import Enum

class PowerBIReports(Enum):

    SALES_VS_DISCOUNTS = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN MONTHNAME(DATE_KEY)||'\\''||TO_CHAR(YEAR(DATE_KEY))
    WHEN 'half-yearly'=LOWER(:time_period) THEN YEAR(DATE_KEY)||IFF(MONTH(DATE_KEY)>6,'H2','H1')
    WHEN 'yearly'=LOWER(:time_period) THEN TO_CHAR(YEAR(DATE_KEY))
    ELSE YEAR(DATE_KEY)||'Q'||QUARTER(DATE_KEY)
    END AS TIMEPERIOD,
    COALESCE(MAX(WHSL_INVC_SHP_DT),DATE('1900-01-01')) AS MAX_DATE,
    SUM(WAC_SALES) AS WAC_SALES,
    SUM(TOT_CHGB_AMT) AS CHARGEBACK

FROM COM_US_IMDNA_ADL.AWB_PWSA0001520_340B_DIVERSION_DETECTN.VW_WAC_SALES
WHERE WHSL_INVC_SHP_DT BETWEEN DATEADD('MONTH',-18,DATE(:max_date)) AND DATE(:max_date) {query_params}
GROUP BY 1 ORDER BY 2;"""

    DEMAND_PERC = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN MONTHNAME(DATE_KEY)||'\\''||TO_CHAR(YEAR(DATE_KEY))
    WHEN 'half-yearly'=LOWER(:time_period) THEN YEAR(DATE_KEY)||IFF(MONTH(DATE_KEY)>6,'H2','H1')
    WHEN 'yearly'=LOWER(:time_period) THEN TO_CHAR(YEAR(DATE_KEY))
    ELSE YEAR(DATE_KEY)||'Q'||QUARTER(DATE_KEY)
    END AS TIMEPERIOD,
    COALESCE(MAX(DEMAND_DATE),DATE('1900-01-01')) AS MAX_DATE,
    ROUND(DIV0(SUM(CASE WHEN UPPER(METRIC)='PHS SALES' THEN ACTUAL_DEMAND ELSE 0 END),SUM(CASE WHEN UPPER(METRIC)='GROSS SALES' THEN ACTUAL_DEMAND ELSE 0 END))*100,2) AS PERC_DEMAND

FROM COM_US_IMDNA_ADL.AWB_PWSA0001520_340B_DIVERSION_DETECTN.VW_ACTUAL_DEMAND 
WHERE  DEMAND_DATE BETWEEN DATEADD('MONTH',-18,DATE(:max_date)) AND DATE(:max_date) {query_params}
GROUP BY 1 ORDER BY 2;"""


    CECP_SPLIT = """SELECT 
    CASE 
        WHEN 'monthly'=LOWER(:time_period) THEN MONTHNAME(DATE_KEY)||'\\''||TO_CHAR(YEAR(DATE_KEY))
        WHEN 'half-yearly'=LOWER(:time_period) THEN YEAR(DATE_KEY)||IFF(MONTH(DATE_KEY)>6,'H2','H1')
        WHEN 'yearly'=LOWER(:time_period) THEN TO_CHAR(YEAR(DATE_KEY))
    ELSE YEAR(DATE_KEY)||'Q'||QUARTER(DATE_KEY)
    END AS TIMEPERIOD,
    COALESCE(MAX(WHSL_INVC_SHP_DT),DATE('1900-01-01')) AS MAX_DATE, /* Adding date for ordering purposes. */
    SUM( CASE 
        WHEN PHARMACY_TYPE='Covered Entity' THEN WAC_SALES
        ELSE 0
    END ) AS CE_WAC,
    SUM( CASE 
        WHEN PHARMACY_TYPE='Contract Pharmacy' THEN WAC_SALES
        ELSE 0
    END ) AS CP_WAC,
    ROUND(DIV0(SUM(TOT_CHGB_AMT),SUM(WAC_SALES))*100,2) AS PERC_DISCOUNT

    FROM COM_US_IMDNA_ADL.AWB_PWSA0001520_340B_DIVERSION_DETECTN.VW_WAC_SALES
    WHERE WHSL_INVC_SHP_DT BETWEEN DATEADD('MONTH',-18,DATE(:max_date)) AND DATE(:max_date) {query_params} 
GROUP BY 1 ORDER BY 2;"""

    WAC_340B_CECP = """SELECT
    CASE 
        WHEN 'monthly'=LOWER(:time_period) THEN MONTHNAME(DATE_KEY)||'\\''||TO_CHAR(YEAR(DATE_KEY))
        WHEN 'half-yearly'=LOWER(:time_period) THEN YEAR(DATE_KEY)||IFF(MONTH(DATE_KEY)>6,'H2','H1')
        WHEN 'yearly'=LOWER(:time_period) THEN TO_CHAR(YEAR(DATE_KEY))
    ELSE YEAR(DATE_KEY)||'Q'||QUARTER(DATE_KEY)
    END AS TIMEPERIOD,
    COALESCE(MAX(WHSL_INVC_SHP_DT),DATE('1900-01-01')) AS MAX_DATE, /* Adding date for ordering purposes. */
    SUM( CASE 
        WHEN PHARMACY_TYPE='Covered Entity' THEN WAC_SALES
        ELSE 0
    END ) AS CE_WAC,
    SUM( CASE 
        WHEN PHARMACY_TYPE='Contract Pharmacy' THEN WAC_SALES
        ELSE 0
    END ) AS CP_WAC,
    ROUND(DIV0(SUM( CASE 
        WHEN PHARMACY_TYPE='Covered Entity' THEN WAC_SALES
        ELSE 0
    END ), SUM(WAC_SALES))*100) AS PERC_CE_WAC,
    ROUND(DIV0(SUM( CASE 
        WHEN PHARMACY_TYPE='Contract Pharmacy' THEN WAC_SALES
        ELSE 0
    END ),SUM(WAC_SALES))*100) AS PERC_CP_WAC,
    SUM(WAC_SALES) AS WAC

    FROM COM_US_IMDNA_ADL.AWB_PWSA0001520_340B_DIVERSION_DETECTN.VW_WAC_SALES
    WHERE  WHSL_INVC_SHP_DT BETWEEN DATEADD('MONTH',-18,DATE(:max_date)) AND DATE(:max_date) {query_params}
GROUP BY 1 ORDER BY 2;"""

    CHBK_340B_CECP = """SELECT
    CASE 
        WHEN 'monthly'=LOWER(:time_period) THEN MONTHNAME(DATE_KEY)||'\\''||TO_CHAR(YEAR(DATE_KEY))
        WHEN 'half-yearly'=LOWER(:time_period) THEN YEAR(DATE_KEY)||IFF(MONTH(DATE_KEY)>6,'H2','H1')
        WHEN 'yearly'=LOWER(:time_period) THEN TO_CHAR(YEAR(DATE_KEY))
    ELSE YEAR(DATE_KEY)||'Q'||QUARTER(DATE_KEY)
    END AS TIMEPERIOD,
    COALESCE(MAX(WHSL_INVC_SHP_DT),DATE('1900-01-01')) AS MAX_DATE, /* Adding date for ordering purposes. */
    SUM( CASE 
        WHEN PHARMACY_TYPE='Covered Entity' THEN TOT_CHGB_AMT
        ELSE 0
    END ) AS CE_CHBK,
    SUM( CASE 
        WHEN PHARMACY_TYPE='Contract Pharmacy' THEN TOT_CHGB_AMT
        ELSE 0
    END ) AS CP_CHBK,
    ROUND(DIV0(SUM( CASE 
        WHEN PHARMACY_TYPE='Covered Entity' THEN TOT_CHGB_AMT
        ELSE 0
    END ), SUM(TOT_CHGB_AMT))*100) AS PERC_CE_CHBK,
    ROUND(DIV0(SUM( CASE 
        WHEN PHARMACY_TYPE='Contract Pharmacy' THEN TOT_CHGB_AMT
        ELSE 0
    END ),SUM(TOT_CHGB_AMT))*100) AS PERC_CP_CHBK,
    SUM(TOT_CHGB_AMT) AS CHBK

    FROM COM_US_IMDNA_ADL.AWB_PWSA0001520_340B_DIVERSION_DETECTN.VW_WAC_SALES
    WHERE  WHSL_INVC_SHP_DT BETWEEN DATEADD('MONTH',-18,DATE(:max_date)) AND DATE(:max_date) {query_params}
GROUP BY 1 ORDER BY 2;"""

    CHBK_PER_DAY = """SELECT
    TO_CHAR(DATE_KEY,'MM/DD/YYYY') AS DATE_KEY,
    MAX(DATE_KEY) AS MAX_DATE,
    ROUND(SUM(TOT_CHGB_AMT)) AS CHBK
    FROM COM_US_IMDNA_ADL.AWB_PWSA0001520_340B_DIVERSION_DETECTN.VW_WAC_SALES
    WHERE  WHSL_INVC_SHP_DT BETWEEN DATEADD('MONTH',-3,DATE(:max_date)) AND DATE(:max_date) {query_params}
GROUP BY 1 ORDER BY 2;"""

    TOP_ACCOUTS_BY_HCP = """SELECT 
    A.PARENT_340B_ID AS PARENT_340B_ID,
    A.PARENT_ENTITY_NAME AS ACCOUNT_NAME,
    HCP_COUNT,
    SUM(WAC_SALES) AS TOT_WAC_SALES,
    TOT_WAC_SALES/HCP_COUNT AS AVG_HCP_PURCHASE
FROM
COM_US_IMDNA_ADL.AWB_PWSA0001520_340B_DIVERSION_DETECTN.VW_WAC_SALES A
LEFT JOIN ( SELECT DISTINCT PARENT_340B_ID,COUNT(DISTINCT HCP_NPI) AS HCP_COUNT from COM_US_IMDNA_ADL.AWB_PWSA0001520_340B_DIVERSION_DETECTN.VW_HCP_AFFL GROUP BY ALL) B
ON A.PARENT_340B_ID=B.PARENT_340B_ID
WHERE WHSL_INVC_SHP_DT BETWEEN DATEADD('MONTH',-3,DATE(:max_date)) AND DATE(:max_date) {query_params}
GROUP BY ALL ORDER BY TOT_WAC_SALES DESC LIMIT 100;"""


class OverviewSummaryKPI(Enum):

    TOT_340B_UNITS = """SELECT CASE 
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Date`,'%y'))
        WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT('Q',QUARTER(`Date`),'\\'',DATE_FORMAT(`Date`,'%y')) END AS `TimePeriod`,
    MAX(`Date`) as max_date,
    SUM(`Quantity`) AS value 
    FROM 340B_340BPurchases
    WHERE `Date` <= DATE(:max_date) {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""

    TOT_340B_WAC = """SELECT CASE 
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Date`,'%y'))
        WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT('Q',QUARTER(`Date`),'\\'',DATE_FORMAT(`Date`,'%y')) END AS `TimePeriod`,
    MAX(`Date`) as max_date,
    SUM(`WAC`) AS value 
    FROM 340B_340BPurchases
    WHERE `Date` <= DATE(:max_date) {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""

    ACTIVE_ANOMALIES = """SELECT CASE 
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Anomaly_Date`, '%b'),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Anomaly_Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Anomaly_Date`)
    ELSE CONCAT('Q',QUARTER(`Anomaly_Date`),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y')) END AS `TimePeriod`,
    MAX(`Anomaly_Date`) AS max_date,
    COUNT(DISTINCT `Anomaly_ID`) AS value
    FROM `vwAnomalousTransactions` 
    WHERE `Anomaly_Date` <= DATE(:max_date) AND Anomaly_Status NOT IN ('Closed', 'Resolved (after letter)', 'False Positive') {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""

    RISK_EXPOSURE = """SELECT CASE 
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Anomaly_Date`, '%b'),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Anomaly_Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Anomaly_Date`)
    ELSE CONCAT('Q',QUARTER(`Anomaly_Date`),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y')) END AS `TimePeriod`,
    MAX(`Anomaly_Date`) AS max_date,
    ROUND(SUM(`Anomaly_ChargeBack`),2) AS value
    FROM `vwAnomalousTransactions` 
    WHERE `Anomaly_Date` <= DATE(:max_date) AND Anomaly_Status NOT IN ('Closed', 'Resolved (after letter)', 'False Positive') {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""

    TOTAL_CE_COUNT = """SELECT CASE 
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Date`,'%y'))
        WHEN 'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT('Q',QUARTER(`Date`),'\\'',DATE_FORMAT(`Date`,'%y')) 
    END AS `TimePeriod`,
    MAX(`Date`) AS max_date,
    COUNT(DISTINCT `340BID`) AS value
    FROM `340B_340BPurchases`
    WHERE `Date` <= DATE(:max_date)
    AND `Quantity` > 0
    {query_params}
    GROUP BY 1
    ORDER BY 2 DESC
    LIMIT 2;"""


class OverviewPageCharts(Enum):

    PER_VOLUME_340B = """SELECT 
    CASE
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Date`),IF(MONTH(`Date`) >6,'H2','H1'))
        WHEN 'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
        ELSE CONCAT(YEAR(`Date`),'Q',QUARTER(`Date`)) END AS `TimePeriod`,
    MAX(`Date`) AS `MaxDate`,
    SUM(CASE WHEN `CECP` = 'CE' THEN `Quantity` ELSE 0 END) as quantity,
    ROUND(
        SUM(CASE WHEN `340BFlag` = '340B' THEN `Quantity` ELSE 0 END)
        / NULLIF(SUM(`Quantity`), 0) * 100, 2
    ) AS volume_percentage
    FROM `340B_ProcessedData`
    WHERE `Date` BETWEEN DATE_SUB(DATE(:max_date), INTERVAL 18 MONTH) AND DATE(:max_date) {query_params}
    GROUP BY 1 ORDER BY 2 ;"""

    PUR_VS_DISP = """SELECT 
    CASE
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Date`),IF(MONTH(`Date`) >6,'H2','H1'))
        WHEN 'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
        ELSE CONCAT(YEAR(`Date`),'Q',QUARTER(`Date`)) END AS `TimePeriod`,
    MAX(`Date`) AS `MaxDate`,
    SUM(CASE WHEN `Flag`= CAST('Purchase' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci THEN `Quantity` ELSE 0 END) AS `purchaseQuantity`,
    SUM(CASE WHEN `Flag`= CAST('Dispense' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci THEN `Quantity` ELSE 0 END) AS `dispenseQuantity`

    FROM vwDispenseVsPurchaseVolume
    WHERE `Date` BETWEEN DATE_SUB(DATE(:max_date), INTERVAL 18 MONTH) AND DATE(:max_date) {query_params}
    GROUP BY 1 ORDER BY 2 ;"""

    PUR_VS_DISP_CORP = """SELECT 
    CONCAT(YEAR(`Date`),'Q',QUARTER(`Date`)) AS `period_id`,
    CONCAT(YEAR(`Date`),'-Q',QUARTER(`Date`)) AS `period_label`,
    `EntityName` AS `org_name`,
    `State` AS `state`,
    MAX(`Date`) AS `MaxDate`,
    SUM(CASE WHEN `Flag`= CAST('Purchase' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci THEN `Quantity` ELSE 0 END) AS `purchase_qty`,
    SUM(CASE WHEN `Flag`= CAST('Dispense' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci THEN `Quantity` ELSE 0 END) AS `dispense_qty`,
    SUM(CASE WHEN `Flag`= CAST('Purchase' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci THEN `Quantity` ELSE 0 END) - SUM(CASE WHEN `Flag`= CAST('Dispense' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci THEN `Quantity` ELSE 0 END) AS `diff_qty`

    FROM vwDispenseVsPurchaseVolume
    WHERE `Date` BETWEEN DATE_SUB(DATE(:max_date), INTERVAL 18 MONTH) AND DATE(:max_date) {query_params}
    GROUP BY 1, 2, 3, 4 ORDER BY 2 DESC;"""

    PUR_VS_DISP_STATE = """SELECT 
    CONCAT(YEAR(`Date`),'Q',QUARTER(`Date`)) AS `period_id`,
    CONCAT(YEAR(`Date`),'-Q',QUARTER(`Date`)) AS `period_label`,
    `State` AS `state`,
    MAX(`Date`) AS `MaxDate`,
    SUM(CASE WHEN `Flag`= CAST('Purchase' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci THEN `Quantity` ELSE 0 END) AS `purchase_qty`,
    SUM(CASE WHEN `Flag`= CAST('Dispense' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci THEN `Quantity` ELSE 0 END) AS `dispense_qty`,
    SUM(CASE WHEN `Flag`= CAST('Purchase' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci THEN `Quantity` ELSE 0 END) - SUM(CASE WHEN `Flag`= CAST('Dispense' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci THEN `Quantity` ELSE 0 END) AS `diff_qty`

    FROM vwDispenseVsPurchaseVolume
    WHERE `Date` BETWEEN DATE_SUB(DATE(:max_date), INTERVAL 18 MONTH) AND DATE(:max_date) {query_params}
    GROUP BY 1, 2, 3 ORDER BY 2 DESC;"""


class AllAnomaliesSummaryKPI(Enum):

    ANOMALY_ACCOUNT_COUNT = """SELECT CASE 
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Anomaly_Date`, '%b'),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Anomaly_Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Anomaly_Date`)
    ELSE CONCAT('Q',QUARTER(`Anomaly_Date`),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y')) END AS `TimePeriod`,
    MAX(`Anomaly_Date`) as max_date,
    COUNT(DISTINCT `Anomaly_340BID`) AS value 
    FROM `vwAnomalousTransactions`
    WHERE `Anomaly_Date` <= DATE(:max_date) AND `Anomaly_Status` NOT IN ('Closed', 'Resolved (after letter)', 'False Positive') {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""

    ACTIVE_ANOMALIES = OverviewSummaryKPI.ACTIVE_ANOMALIES.value

    RISK_EXPOSURE = OverviewSummaryKPI.RISK_EXPOSURE.value

    RISK_UNITS = """SELECT CASE 
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Anomaly_Date`, '%b'),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Anomaly_Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Anomaly_Date`)
    ELSE CONCAT('Q',QUARTER(`Anomaly_Date`),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y')) END AS `TimePeriod`,
    MAX(`Anomaly_Date`) AS max_date,
    ROUND(SUM(`Anomaly_Units`)) AS value
    FROM `vwAnomalousTransactions`
    WHERE `Anomaly_Date` <= DATE(:max_date) AND `Anomaly_Status` NOT IN ('Closed', 'Resolved (after letter)', 'False Positive') {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""


class AllAnomaliesPageCharts(Enum):

    ANOMALIES_BY_SCORE_ACCOUNTS = """SELECT 
    CASE 
        WHEN Anomaly_LinkageScore >= 90 THEN 'High Confidence'
        WHEN Anomaly_LinkageScore >= 50 THEN 'Medium Confidence'
        ELSE 'Low Confidence'
    END AS name,
    COUNT(*) AS count
    FROM `vwAnomalousTransactions`
    WHERE Anomaly_Status NOT IN ('Closed', 'Resolved (after letter)', 'False Positive') {query_params}
    GROUP BY 1 ORDER BY count DESC;"""

    ANOMALIES_BY_SCORE_GROWTH = """SELECT
    CASE
        WHEN Anomaly_LinkageScore < 50 THEN '<50%'
        WHEN Anomaly_LinkageScore BETWEEN 50 AND 59 THEN '60%'
        WHEN Anomaly_LinkageScore BETWEEN 60 AND 69 THEN '70%'
        WHEN Anomaly_LinkageScore BETWEEN 70 AND 79 THEN '80%'
        WHEN Anomaly_LinkageScore BETWEEN 80 AND 89 THEN '90%'
        WHEN Anomaly_LinkageScore >= 90 THEN '>90%'
    END AS name,
    CASE
        WHEN Anomaly_LinkageScore < 50 THEN '<50% Anomaly Score'
        WHEN Anomaly_LinkageScore BETWEEN 50 AND 59 THEN '50-59% Anomaly Score'
        WHEN Anomaly_LinkageScore BETWEEN 60 AND 69 THEN '60-69% Anomaly Score'
        WHEN Anomaly_LinkageScore BETWEEN 70 AND 79 THEN '70-79% Anomaly Score'
        WHEN Anomaly_LinkageScore BETWEEN 80 AND 89 THEN '80-89% Anomaly Score'
        WHEN Anomaly_LinkageScore >= 90 THEN '90% plus Anomaly Score'
    END AS `desc`,
    CASE
        WHEN Anomaly_LinkageScore < 50 THEN 1
        WHEN Anomaly_LinkageScore BETWEEN 50 AND 59 THEN 2
        WHEN Anomaly_LinkageScore BETWEEN 60 AND 69 THEN 3
        WHEN Anomaly_LinkageScore BETWEEN 70 AND 79 THEN 4
        WHEN Anomaly_LinkageScore BETWEEN 80 AND 89 THEN 5
        WHEN Anomaly_LinkageScore >= 90 THEN 6
    END AS segment_id,
    SUM( CASE 
            WHEN 'monthly'=LOWER(:time_period)
                AND YEAR(`Anomaly_Date`) = YEAR(DATE(:max_date)) 
                AND MONTH(`Anomaly_Date`)=MONTH(DATE(:max_date)) 
            THEN `Anomaly_ChargeBack`
            WHEN 'quarterly'=LOWER(:time_period)
                AND (`Anomaly_Date` > DATE_SUB(DATE(:max_date), INTERVAL 3 MONTH)
                AND `Anomaly_Date` <= DATE(:max_date))
            THEN `Anomaly_ChargeBack`
            WHEN 'half-yearly'=LOWER(:time_period)
                AND `Anomaly_Date` > DATE_SUB(DATE(:max_date), INTERVAL 6 MONTH)
                AND `Anomaly_Date` <= DATE(:max_date)
            THEN `Anomaly_ChargeBack`
            WHEN 'yearly'=LOWER(:time_period) 
                AND `Anomaly_Date` > DATE_SUB(DATE(:max_date), INTERVAL 12 MONTH) 
                AND `Anomaly_Date` <= DATE(:max_date)
            THEN `Anomaly_ChargeBack`
        ELSE 0 END ) as curr_chargeback,

    SUM( CASE 
            WHEN 'monthly'=LOWER(:time_period) 
                AND YEAR(`Anomaly_Date`) = YEAR(DATE(:max_date)) 
                AND MONTH(`Anomaly_Date`)=MONTH(DATE_SUB(DATE(:max_date), INTERVAL 1 MONTH)) 
            THEN `Anomaly_ChargeBack`
            WHEN 'quarterly'=LOWER(:time_period) 
                AND `Anomaly_Date` > DATE_SUB(DATE(:max_date), INTERVAL 6 MONTH) 
                AND `Anomaly_Date` <= DATE_SUB(DATE(:max_date), INTERVAL 3 MONTH) 
            THEN `Anomaly_ChargeBack`
            WHEN 'half-yearly'=LOWER(:time_period) 
                AND `Anomaly_Date` > DATE_SUB(DATE(:max_date), INTERVAL 12 MONTH) 
                AND `Anomaly_Date` <= DATE_SUB(DATE(:max_date), INTERVAL 6 MONTH) 
            THEN `Anomaly_ChargeBack`
            WHEN 'yearly'=LOWER(:time_period) 
                AND `Anomaly_Date` > DATE_SUB(DATE(:max_date), INTERVAL 24 MONTH) 
                AND `Anomaly_Date` <= DATE_SUB(DATE(:max_date), INTERVAL 12 MONTH) 
            THEN `Anomaly_ChargeBack`
        ELSE 0 END ) as prev_chargeback

    FROM vwAnomalousTransactions

    WHERE `Anomaly_Date` BETWEEN DATE_SUB(DATE(:max_date), INTERVAL 6 MONTH) AND DATE(:max_date) {query_params}

    GROUP BY 1,2,3 ORDER BY 3 DESC;"""

    ANOMALOUS_TRANSACTIONS = """SELECT 
    CASE
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Anomaly_Date`, '%b'),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Anomaly_Date`),IF(MONTH(`Anomaly_Date`) >6,'H2','H1'))
        WHEN 'yearly'=LOWER(:time_period) THEN YEAR(`Anomaly_Date`)
        ELSE CONCAT(YEAR(`Anomaly_Date`),'Q',QUARTER(`Anomaly_Date`)) END AS `TimePeriod`,
    MAX(`Anomaly_Date`) AS max_date,
    COUNT(DISTINCT `Anomaly_ID`) AS anomaly_count,
    SUM(`Anomaly_ChargeBack`) as chargeback

    FROM `vwAnomalousTransactions`
    WHERE `Anomaly_Date` BETWEEN DATE_SUB(DATE(:max_date), INTERVAL 18 MONTH) AND DATE(:max_date) {query_params}
    GROUP BY 1 ORDER BY 2;"""

    GROWTH_BY_DRIVERS_340B = """SELECT
            Anomaly_Status AS actions,
            COUNT(*) AS value
        FROM `vwAnomalousTransactions`
        WHERE Anomaly_Status IS NOT NULL {query_params}
        GROUP BY Anomaly_Status
        ORDER BY value DESC;"""
    
    ANOMALY_CHARGEBACK_MAP = """SELECT
        CONCAT(`City`,', ',`State`) AS name,
        `Latitude` as lat,
        `Longitude` as lon,
        SUM(`Anomaly_ChargeBack`) AS value,
        CASE 
            WHEN SUM(`Anomaly_ChargeBack`) >= 50000 THEN 'large'
            WHEN SUM(`Anomaly_ChargeBack`) >= 25000 THEN 'medium'
            ELSE 'small'
        END AS size

        FROM `vwAnomalousTransactions`
        WHERE 1=1 {query_params}
    GROUP BY 1,2,3
    HAVING SUM(`Anomaly_ChargeBack`) > 0
    ORDER BY value DESC LIMIT 20;"""

    ANOMALY_PRIORITY_MAP = """SELECT
        CONCAT(`City`,', ',`State`) AS name,
        `Latitude` as lat,
        `Longitude` as lon,
        AVG(`Anomaly_LinkageScore`) AS value,
        CASE 
            WHEN AVG(`Anomaly_LinkageScore`) >= 90 THEN 'high'
            WHEN AVG(`Anomaly_LinkageScore`) >= 50 THEN 'medium'
            ELSE 'low'
        END AS size

        FROM `vwAnomalousTransactions`
        WHERE 1=1 {query_params}
    GROUP BY 1,2,3
    HAVING AVG(`Anomaly_LinkageScore`) > 0
    ORDER BY value DESC LIMIT 20;"""

class AllAccountsSummaryKPI(Enum):

    ACCOUNT_COUNT = """SELECT CASE 
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Date`,'%y'))
        WHEN 'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT('Q',QUARTER(`Date`),'\\'',DATE_FORMAT(`Date`,'%y')) 
    END AS `TimePeriod`,
    MAX(`Date`) AS max_date,
    COUNT(DISTINCT `340BID`) AS value
    FROM `340B_ProcessedData`
    WHERE `Date` <= DATE(:max_date)
    AND `340BID` IS NOT NULL
    AND `Quantity` > 0
    {query_params}
    GROUP BY 1
    ORDER BY 2 DESC
    LIMIT 2;"""

    TOTAL_PHARMACIES = """SELECT CASE 
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Date`,'%y'))
        WHEN 'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT('Q',QUARTER(`Date`),'\\'',DATE_FORMAT(`Date`,'%y')) 
    END AS `TimePeriod`,
    MAX(`Date`) AS max_date,
    COUNT(DISTINCT `PharmacyID`) AS value
    FROM `340B_ProcessedData`
    WHERE `Date` <= DATE(:max_date)
    AND `PharmacyID` IS NOT NULL
    AND `Quantity` > 0
    {query_params}
    GROUP BY 1
    ORDER BY 2 DESC
    LIMIT 2;"""
    
    TOT_ANOMALIES_ACCOUNTS = """SELECT 
        CASE
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Anomaly_Date`, '%b'),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Anomaly_Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Anomaly_Date`)
    ELSE CONCAT('Q',QUARTER(`Anomaly_Date`),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y')) END AS `TimePeriod`,
    MAX(`Anomaly_Date`) AS max_date,
    COUNT(DISTINCT `Anomaly_ID`) AS value
    FROM `vwAnomalousTransactions`
    WHERE Anomaly_Date <= DATE(:max_date) {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""

    TOT_RISK_ACCOUNTS = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Anomaly_Date`, '%b'),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y'))
    WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Anomaly_Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Anomaly_Date`,'%y'))
    WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Anomaly_Date`)
    ELSE CONCAT('Q',QUARTER(`Anomaly_Date`),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y')) END AS `TimePeriod`,
    MAX(`Anomaly_Date`) AS max_date,
    SUM(`Anomaly_Chargeback`) AS value
    FROM `vwAnomalousTransactions`
    WHERE Anomaly_Date <= DATE(:max_date) {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""



class AccountDetailsKPI(Enum):

    TOT_ANOMALIES = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Anomaly_Date`, '%b'),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y'))
    WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Anomaly_Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Anomaly_Date`,'%y'))
    WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Anomaly_Date`)
    ELSE CONCAT('Q',QUARTER(`Anomaly_Date`),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y')) END AS `TimePeriod`,
    MAX(`Anomaly_Date`) AS max_date,
    COUNT(DISTINCT `Anomaly_ID`) AS value
    FROM `vwAnomalousTransactions`
    WHERE Anomaly_Date <= DATE(:max_date) AND `Anomaly_340BID` = :account_id {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""

    TOT_WAC_SALES = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
    WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Date`),IF(MONTH(`Date`) >6,'H2','H1'))
    WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT(YEAR(`Date`),'Q',QUARTER(`Date`)) END AS `TimePeriod`,
    MAX(`Date`) AS max_date,
    SUM(`WAC`) AS value
    FROM `340B_ProcessedData`
    WHERE `Date` <= DATE(:max_date) AND `340BID` = :account_id {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""

    TOT_CHBK = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
    WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Date`),IF(MONTH(`Date`) >6,'H2','H1'))
    WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT(YEAR(`Date`),'Q',QUARTER(`Date`)) END AS `TimePeriod`,
    MAX(`Date`) AS max_date,
    SUM(`Chargeback`) AS value
    FROM `340B_ProcessedData`
    WHERE `Date` <= DATE(:max_date) AND `340BID` = :account_id {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""

class PharmacyDetailsKPI(Enum):

    TOT_ANOMALIES = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Anomaly_Date`, '%b'),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y'))
    WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(IF(MONTH(`Anomaly_Date`) >6,'H2\\'','H1\\''),DATE_FORMAT(`Anomaly_Date`,'%y'))
    WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Anomaly_Date`)
    ELSE CONCAT('Q',QUARTER(`Anomaly_Date`),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y')) END AS `TimePeriod`,
    MAX(`Anomaly_Date`) AS max_date,
    COUNT(DISTINCT `Anomaly_ID`) AS value
    FROM `vwAnomalousTransactions`
    WHERE Anomaly_Date <= DATE(:max_date) AND `Pharmacy_ID` = :account_id {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""

    TOT_WAC_SALES = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
    WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Date`),IF(MONTH(`Date`) >6,'H2','H1'))
    WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT(YEAR(`Date`),'Q',QUARTER(`Date`)) END AS `TimePeriod`,
    MAX(`Date`) AS max_date,
    SUM(`WAC`) AS value
    FROM `340B_ProcessedData`
    WHERE `Date` <= DATE(:max_date) AND `PharmacyID` = :account_id {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""

    TOT_CHBK = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
    WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Date`),IF(MONTH(`Date`) >6,'H2','H1'))
    WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT(YEAR(`Date`),'Q',QUARTER(`Date`)) END AS `TimePeriod`,
    MAX(`Date`) AS max_date,
    SUM(`Chargeback`) AS value
    FROM `340B_ProcessedData`
    WHERE `Date` <= DATE(:max_date) AND `PharmacyID` = :account_id {query_params}
    GROUP BY 1 ORDER BY 2 DESC LIMIT 2;"""

class AccountDetailsCharts(Enum):

    ANOMALIES_BY_CE = """SELECT 
        CASE
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Anomaly_Date`, '%b'),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Anomaly_Date`),IF(MONTH(`Anomaly_Date`) >6,'H2','H1'))
        WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Anomaly_Date`)
        ELSE CONCAT(YEAR(`Anomaly_Date`),'Q',QUARTER(`Anomaly_Date`)) END AS `TimePeriod`,
        MAX(`Anomaly_Date`) AS max_date,
    COUNT(DISTINCT `Anomaly_ID`) AS value
    FROM `vwAnomalousTransactions`
    WHERE `Anomaly_340BID` = :account_id 
    AND Anomaly_LinkageScore >= 2
    AND Anomaly_Date > DATE_SUB(DATE(:max_date), INTERVAL 18 MONTH) AND `Anomaly_date` <= DATE(:max_date) {query_params}
    GROUP BY 1 ORDER BY 2;"""

    ANOMALIES_BY_CP = """SELECT 
        CASE
        WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Anomaly_Date`, '%b'),'\\'',DATE_FORMAT(`Anomaly_Date`,'%y'))
        WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Anomaly_Date`),IF(MONTH(`Anomaly_Date`) >6,'H2','H1'))
        WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Anomaly_Date`)
        ELSE CONCAT(YEAR(`Anomaly_Date`),'Q',QUARTER(`Anomaly_Date`)) END AS `TimePeriod`,
        MAX(`Anomaly_Date`) AS max_date,
    COUNT(DISTINCT `Anomaly_ID`) AS value
    FROM `vwAnomalousTransactions`
    WHERE `Pharmacy_ID` = :account_id 
    AND Anomaly_LinkageScore >= 2
    AND Anomaly_Date > DATE_SUB(DATE(:max_date), INTERVAL 18 MONTH) AND `Anomaly_date` <= DATE(:max_date) {query_params}
    GROUP BY 1 ORDER BY 2;"""

    PUR_BY_CE = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
    WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Date`),IF(MONTH(`Date`) >6,'H2','H1'))
    WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT(YEAR(`Date`),'Q',QUARTER(`Date`)) END AS `TimePeriod`,
    MAX(`Date`) AS max_date,
    SUM(`Quantity`) AS value
    
    FROM `340B_ProcessedData`
    WHERE `Date` <= DATE(:max_date) AND `Date` > DATE_SUB(DATE(:max_date), INTERVAL 18 MONTH) AND `340BID` = :account_id {query_params}
    GROUP BY 1 ORDER BY 2 ;"""

    PUR_BY_CP = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
    WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Date`),IF(MONTH(`Date`) >6,'H2','H1'))
    WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT(YEAR(`Date`),'Q',QUARTER(`Date`)) END AS `TimePeriod`,
    MAX(`Date`) AS max_date,
    SUM(`Quantity`) AS value
    
    FROM `340B_ProcessedData`
    WHERE `Date` <= DATE(:max_date) AND `Date` > DATE_SUB(DATE(:max_date), INTERVAL 18 MONTH) AND `PharmacyID` = :account_id {query_params}
    GROUP BY 1 ORDER BY 2 ;"""

    DISP_BY_CE = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
    WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Date`),IF(MONTH(`Date`) >6,'H2','H1'))
    WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT(YEAR(`Date`),'Q',QUARTER(`Date`)) END AS `TimePeriod`,
    MAX(`Date`) AS max_date,
    SUM(`Quantity`) AS value
    
    FROM `340B_340BDispenses`
    WHERE `Date` <= DATE(:max_date) AND `Date` > DATE_SUB(DATE(:max_date), INTERVAL 18 MONTH) AND `340BID` = :account_id {query_params}
    GROUP BY 1 ORDER BY 2;"""

    DISP_BY_CP = """SELECT 
    CASE
    WHEN 'monthly'=LOWER(:time_period) THEN CONCAT(DATE_FORMAT(`Date`, '%b'),'\\'',DATE_FORMAT(`Date`,'%y'))
    WHEN 'half-yearly'=LOWER(:time_period) THEN CONCAT(YEAR(`Date`),IF(MONTH(`Date`) >6,'H2','H1'))
    WHEN  'yearly'=LOWER(:time_period) THEN YEAR(`Date`)
    ELSE CONCAT(YEAR(`Date`),'Q',QUARTER(`Date`)) END AS `TimePeriod`,
    MAX(`Date`) AS max_date,
    SUM(`Quantity`) AS value

    FROM `340B_Non340BDispenses`
    WHERE `Date` <= DATE(:max_date) AND `Date` > DATE_SUB(DATE(:max_date), INTERVAL 18 MONTH) AND `PharmacyID` = :account_id {query_params}
    GROUP BY 1 ORDER BY 2 ;"""

class AnomalyDetailsKPI(Enum):

    ANOMALIES_BY_SCORE = """SELECT `Anomaly_ID`,
        `Anomaly_Brand`,
        `Anomaly_340BID`,
        `Pharmacy_ID`,
        `Anomaly_Date`,
        `Anomaly_Detected_By`,
        `Anomaly_Source`,
        `Anomaly_Status`,
        `Anomaly_LinkageScore`,
        `Anomaly_Units`,
        `Anomaly_ChargeBack`,
        `Anomaly_WAC`

    FROM vwAnomalousTransactions WHERE Anomaly_ID = :anomaly_id"""

    ACCOUNT_HEADER = """SELECT DISTINCT 
        `accountName`,
        `address`
    FROM vwAccountDetailHeader WHERE UPPER(accountId) = UPPER(:account_id);"""

    PHARMACY_HEADER = """SELECT DISTINCT 
        `accountName`,
        `address`
    FROM vwPharmacyDetailHeader WHERE UPPER(accountId) = UPPER(:pharmacy_id);"""

    ANOMALY_TIMELINE = """
        SELECT 
            DATE_FORMAT(Date, '%Y %b') AS category,
            SUM(CASE WHEN table_source = '340B_purchase' THEN Quantity ELSE 0 END) AS purchase_quantity,
            SUM(CASE WHEN table_source = 'non340b_purchase' THEN Quantity ELSE 0 END) AS non_340b_purchase_quantity,
            SUM(CASE WHEN table_source = '340B_dispense' THEN Quantity ELSE 0 END) AS dispense_quantity,
            SUM(CASE WHEN table_source = 'non340b_dispense' THEN Quantity ELSE 0 END) AS non_340b_dispense_quantity
        FROM (
            SELECT Date, Quantity, '340B_purchase' AS table_source
            FROM `340B_340BPurchases`
            WHERE Date >= DATE_SUB(:anomaly_date, INTERVAL 6 MONTH)
            AND Date <= DATE_ADD(:anomaly_date, INTERVAL 6 MONTH)
            AND 340BID = :id_340b
            UNION ALL
            SELECT Date, Quantity, 'non340b_purchase' AS table_source
            FROM `340B_Non340BPurchases`
            WHERE Date >= DATE_SUB(:anomaly_date, INTERVAL 6 MONTH)
            AND Date <= DATE_ADD(:anomaly_date, INTERVAL 6 MONTH)
            AND PharmacyID = :pharmacy_id
            UNION ALL
            SELECT Date, Quantity, '340B_dispense' AS table_source
            FROM `340B_340BDispenses`
            WHERE Date >= DATE_SUB(:anomaly_date, INTERVAL 6 MONTH)
            AND Date <= DATE_ADD(:anomaly_date, INTERVAL 6 MONTH)
            AND 340BID = :id_340b
            UNION ALL
            SELECT Date, Quantity, 'non340b_dispense' AS table_source
            FROM `340B_Non340BDispenses`
            WHERE Date >= DATE_SUB(:anomaly_date, INTERVAL 6 MONTH)
            AND Date <= DATE_ADD(:anomaly_date, INTERVAL 6 MONTH)
            AND PharmacyID = :pharmacy_id
        ) combined_data
        GROUP BY MONTH(Date)
        ORDER BY YEAR(Date), MONTH(Date);"""
    
    PUR_DISP_BY_ACCOUNT = """SELECT `accountId`,
        `pharmacyId`,
        `pharmacyName`,
        `address`,
        `Brand_name`,
        `non340bPurchaseQty`,
        `non340bDispenseQty`,
        `totalQty`
    FROM vwPurchaseDispenseByAccount WHERE UPPER(accountId) = UPPER(:account_id) AND UPPER(Brand_name) = UPPER(:brand);"""

    PUR_DISP_BY_PHARMACY = """SELECT `pharmacyId`,
        `accountId`,
        `accountName`,
        `address`,
        `Brand_name`,
        `purchaseQty`,
        `dispenseQty`,
        `totalQty`
    FROM vwPurchaseDispenseByPharmacy WHERE UPPER(pharmacyId) = UPPER(:pharmacy_id) AND UPPER(Brand_name) = UPPER(:brand);"""

    RISK_THEORY = """SELECT `Risk_Theory_AnomalyID`,
        `Risk_Theory_Description`,
        `Risk_Theory_Status`,
        `Risk_Theroy_ID` AS `Risk_Theory_ID`

    FROM 340B_RiskTheories WHERE `Risk_Theory_AnomalyID` = :anomaly_id;"""



class PurchaseDispenseExp(Enum):

    PUR_DISP_EXP = """SELECT 
    DATE_FORMAT(Date, '%Y %b') AS category,
    MAX(`Date`) AS `MaxDate`,
    SUM(CASE WHEN `Flag`= CAST('Purchase' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci AND `340BID`= :id_340b THEN `Quantity` ELSE 0 END) AS `ce_purchase_qty`,
    SUM(CASE WHEN `Flag`= CAST('Purchase' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci AND `PharmacyID`= :pharmacy_id THEN `Quantity` ELSE 0 END) AS `cp_purchase_qty`,
    SUM(CASE WHEN `Flag`= CAST('Dispense' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci AND `340BID`= :id_340b THEN `Quantity` ELSE 0 END) AS `ce_dispense_qty`,
    SUM(CASE WHEN `Flag`= CAST('Dispense' AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci AND `PharmacyID`= :pharmacy_id THEN `Quantity` ELSE 0 END) AS `cp_dispense_qty`

    FROM vwDispenseVsPurchaseVolume
    WHERE `Date` BETWEEN DATE_SUB(DATE(:max_date), INTERVAL 24 MONTH) AND DATE(:max_date) AND (`340BID`=:id_340b OR `PharmacyID`=:pharmacy_id) {query_params}
    GROUP BY 1 ORDER BY 2;"""

    explain :-

    This SQL query generates a monthly Purchase vs Dispense volume report for the last 24 months.

    It reads data from:  vwDispenseVsPurchaseVolume

    and groups records by: DATE_FORMAT(Date, '%Y %b')

    which converts dates into values like:

    | Date       | Category |
    | ---------- | -------- |
    | 2026-01-10 | 2026 Jan |
    | 2026-01-20 | 2026 Jan |
    | 2026-02-05 | 2026 Feb |
   
     So all January records are grouped together.

     Sample DATa:


     | Date       | Flag     | 340BID | PharmacyID | Quantity |
    | ---------- | -------- | ------ | ---------- | -------- |
    | 2026-01-05 | Purchase | 100    | 200        | 50       |
    | 2026-01-10 | Purchase | 100    | 200        | 30       |
    | 2026-01-15 | Dispense | 100    | 200        | 20       |
    | 2026-01-20 | Dispense | 100    | 200        | 10       |
    | 2026-02-05 | Purchase | 100    | 200        | 40       |
    | 2026-02-10 | Dispense | 100    | 200        | 25       |


    id_340b = 100
    pharmacy_id = 200
    max_date = '2026-02-28'


    DATE_FORMAT(Date, '%Y %b') AS category

     output
    | category |
    | -------- |
    | 2026 Jan |
    | 2026 Feb |


     2. MaxDate

       MAX(Date)


     3. ce_purchase_qty

      SUM(
         CASE
           WHEN Flag='Purchase'
           AND 340BID=:id_340b
           THEN Quantity
           ELSE 0
         END
        )


      SUM(
 CASE
   WHEN Flag='Purchase'
   AND PharmacyID=:pharmacy_id
   THEN Quantity
   ELSE 0
 END
)

      WHERE Clause


      WHERE Date BETWEEN
DATE_SUB(DATE(:max_date), INTERVAL 24 MONTH)
AND DATE(:max_date)


Filter con :

AND (
      340BID = :id_340b
      OR
      PharmacyID = :pharmacy_id
    )


Simple Summary

This query creates a monthly dashboard report showing:

Total Purchase Quantity for a 340B Entity (ce_purchase_qty)
Total Purchase Quantity for a Pharmacy (cp_purchase_qty)
Total Dispense Quantity for a 340B Entity (ce_dispense_qty)
Total Dispense Quantity for a Pharmacy (cp_dispense_qty)