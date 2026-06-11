 """
Shared helper utilities: filter building, validation, and error response helpers.
"""

import re
import logging
from utils.query_templates import ( AccountDetailsKPI, PharmacyDetailsKPI)
                                 
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------

def sanitize_filter_value(value: str)  -> str:
    """
    Sanitize a filter value to prevent SQL injection.
    Only allows alphanumeric characters, spaces, hyphens, commas, parentheses, and periods.
    Escapes single quotes by doubling them.

    Args:
        value: Raw input value from query parameter

    Returns:
        Sanitized value safe for SQL inclusion
    """
    sanitized = value.replace("'", "''")
    sanitized = re.sub(r"[^a-zA-Z0-9\s\-,.()\+]", "", sanitized)
    return sanitized


def build_days_open_filter(raw_value: str, db_column: str) -> str:
    """
    Build a range filter clause for daysOpen, or return empty string if invalid.

    Supports single range "min-max" or comma-separated multiple ranges "0-30,31-60,61-100".
    Validates that the input contains only digits, hyphens, and commas, then extracts
    all numeric values and uses their overall min and max to generate a BETWEEN-style condition.

    Args:
        raw_value: The raw daysOpen parameter value (e.g. "30-60" or "0-30,31-60")
        db_column: The database column name for days open

    Returns:
        SQL fragment like "Days_Open >= 0 AND Days_Open <= 60 " or empty string if invalid
    """
    if not re.fullmatch(r'[\d,\-]+', raw_value.strip()):
        logger.warning(
            f"Invalid daysOpen format: {raw_value}. "
            "Expected only digits, hyphens, and commas (e.g. '0-30,31-60')."
        )
        return ""
    numbers = [int(n) for n in re.findall(r'\d+', raw_value)]
    if not numbers:
        logger.warning(f"No numeric values found in daysOpen: {raw_value}.")
        return ""
    min_val = min(numbers)
    max_val = max(numbers)
    return f"{db_column} >= {min_val} AND {db_column} <= {max_val} "


def build_in_clause_filter(raw_value: str, db_column: str) -> str:
    """
    Build an IN clause filter from comma-separated values, or return empty string if none valid.

    Sanitizes each value, converts to uppercase, and generates a SQL IN clause.

    Args:
        raw_value: Comma-separated string of filter values (e.g. "BrandA,BrandB")
        db_column: The database column name to filter on

    Returns:
        SQL fragment like "UPPER(brand) IN ('BRANDA','BRANDB') " or empty string if no valid values
    """
    sanitized_values = [
        sanitize_filter_value(v.strip().upper())
        for v in raw_value.split(',')
        if sanitize_filter_value(v.strip().upper())
    ]
    if not sanitized_values:
        return ""
    values_str = "','".join(sanitized_values)
    return f"UPPER({db_column}) IN ('{values_str}') "


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def create_error_response(error_type: str, message: str, tile_name: str = None) -> dict:
    """
    Create a consistent error response object.

    Args:
        error_type: The type of error (e.g., "Invalid date format", "Unknown tile")
        message: Detailed error message
        tile_name: Optional tile name for tile-specific errors

    Returns:
        Dictionary with consistent error format

    Examples:
        >>> create_error_response("Invalid date format", "Expected YYYY-MM-DD", "anomalous-transactions")
        {"error": "Invalid date format", "message": "Expected YYYY-MM-DD", "tileName": "anomalous-transactions"}
        >>> create_error_response("Missing parameter", "tilename is required")
        {"error": "Missing parameter", "message": "tilename is required"}
    """
    error_response = {
        "error": error_type,
        "message": message,
    }
    if tile_name:
        error_response["tileName"] = tile_name
    return error_response


def validate_optional_param(query_params: dict, param_name: str, validator, error_label: str, tile_name: str) -> tuple:
    """
    Validate a single optional query parameter using the given validator callable.

    Args:
        query_params: Dictionary of query parameters
        param_name: The key to look up in query_params
        validator: Callable that accepts the value and returns (is_valid, error_msg, ...)
        error_label: Error type label for the response (e.g. "Invalid date format")
        tile_name: Tile name for error reporting

    Returns:
        Tuple of (is_valid, error_response_or_empty_dict)
    """
    value = query_params.get(param_name)
    if not value:
        return True, {}
    result = validator(value)
    is_valid, error_msg = result[0], result[1]
    if not is_valid:
        return False, create_error_response(error_label, error_msg, tile_name)
    return True, {}


def validate_anomalous_transactions_time_period(
    query_params,
    tile_name
):
    """
    Validate time period parameter.
    """
    if not query_params:
        return None

    time_period = query_params.get("time-period")
    valid_time_periods = [
        "monthly",
        "quarterly",
        "half-yearly",
        "yearly"
    ]

    if time_period not in valid_time_periods:
        return create_error_response(
            INVALID_TIME_PERIOD,
            (
                f"Time period '{time_period}' is not valid. "
                f"Valid options are: {', '.join(valid_time_periods)}"
            ),
            tile_name
        )

    return None


def build_no_data_response():
    """
    Build empty chart response.
    """
    return {
        "categories": [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
        ],
        "series": [
            {
                "name": "340B Anomalies Detected",
                "data": [0] * 12,
                "type": "area",
                "yAxis": 0
            },
            {
                "name": "340B Volume ($MM)",
                "data": [0] * 12,
                "type": "area",
                "yAxis": 1
            }
        ],
        "error": NO_DATA_AVAILABLE,
    }


def build_anomalous_transactions_chart_data(result):
    """
    Build dual-series chart data.
    """
    categories = []
    anomaly_counts = []
    volume_amounts = []

    for row in result:
        categories.append(row.TimePeriod)
        anomaly_counts.append(row.anomaly_count or 0)
        volume_amounts.append(
            float(row.chargeback) / 1e6
            if row.chargeback
            else 0
        )

    return {
        "categories": categories,
        "series": [
            {
                "name": "340B Anomalies Detected",
                "data": anomaly_counts,
                "type": "area",
                "yAxis": 0
            },
            {
                "name": "340B Volume ($MM)",
                "data": volume_amounts,
                "type": "area",
                "yAxis": 1
            }
        ]
    }


def validate_confidence_accounts_query_params(query_params, tile_name):
    """
    Validate query parameters and return error response if invalid.
    """
    if not query_params:
        return None

    is_valid, error_response = validate_query_parameters(
        query_params,
        tile_name
    )

    return None if is_valid else error_response


def build_confidence_accounts_donut_data(result):
    """
    Build confidence accounts donut chart response.
    """
    return {
        "series": [
            {
                "name": "Confidence Score",
                "data": [
                    {
                        "name": row.name,
                        "y": row.count
                    }
                    for row in result
                ]
            }
        ]
    }





def get_curr_prev_timeperiod(max_date, timeperiod, tile_name):
    """
    Calculate current and previous period labels based on time period.
    """
    if max_date is None:
        logger.warning(
            f"Missing max_date parameter for time period calculation in {tile_name}"
        )
        error_response = {
            "error": "Missing max_date parameter",
            "message": "max_date query parameter is required for time period calculation",
            "tileName": tile_name
        }
        return None, None, error_response

    date_obj = datetime.strptime(max_date, "%Y-%m-%d")

    if timeperiod == "quarterly":
        curr_period = f"Q{(date_obj.month - 1) // 3 + 1}'{date_obj.strftime('%y')}"
        prev_date_obj = date_obj - relativedelta(months=3)
        prev_period = f"Q{(prev_date_obj.month - 1) // 3 + 1}'{prev_date_obj.strftime('%y')}"

    elif timeperiod == "monthly":
        curr_period = date_obj.strftime("%b'%y")
        prev_date_obj = date_obj - relativedelta(months=1)
        prev_period = prev_date_obj.strftime("%b'%y")

    elif timeperiod == "half-yearly":
        curr_period = (
            f"H2'{date_obj.strftime('%y')}"
            if date_obj.month >= 6
            else f"H1'{date_obj.strftime('%y')}"
        )

        prev_date_obj = date_obj - relativedelta(months=6)

        prev_period = (
            f"H2'{prev_date_obj.strftime('%y')}"
            if prev_date_obj.month >= 6
            else f"H1'{prev_date_obj.strftime('%y')}"
        )

    elif timeperiod == "yearly":
        curr_period = date_obj.strftime("%Y")
        prev_date_obj = date_obj - relativedelta(months=12)
        prev_period = prev_date_obj.strftime("%Y")

    else:
        logger.warning(f"Invalid or missing time period parameter: {timeperiod}")
        error_response = {
            "error": INVALID_TIME_PERIOD,
            "message": "Time period parameter must be one of: monthly, quarterly, half-yearly, yearly",
            "tileName": tile_name
        }
        return None, None, error_response

    return curr_period, prev_period, None


def build_score_growth_response(result, curr_period, prev_period):
    """
    Build score growth response.
    """
    return [
        {
            "name": score_row.name,
            "desc": score_row.desc,
            "y": round(
                (
                    (score_row.curr_chargeback - score_row.prev_chargeback)
                    / score_row.prev_chargeback
                ) * 100,
                1
            ) if score_row.prev_chargeback else None,
            "currentPeriod": curr_period,
            "previousPeriod": prev_period
        }
        for score_row in result
    ]

def validate_growth_query_params(query_params, tile_name):
    """Validate query parameters and return error response if invalid."""
    if not query_params:
        return None

    is_valid, error_response = validate_query_parameters(
        query_params,
        tile_name
    )

    return None if is_valid else error_response


def build_growth_donut_data(result):
    """Build donut chart response data."""
    return {
        "series": [
            {
                "name": "Growth Rate",
                "data": [
                    {"name": row.name, "y": row.y}
                    for row in result
                ]
            }
        ]
    }

def map_row_to_response(row):
    return {
        "name": row.name,
        "lat": float(row.lat) if row.lat is not None else 0.0,
        "lon": float(row.lon) if row.lon is not None else 0.0,
        "value": float(row.value) if row.value is not None else 0.0,
        "size": row.size
    }



def process_account_kpis(
    template,
    query_params,
    session,
    tile_name,
    valid_filter_column_map,
    query_placeholder_values
    ):

    count = 0
    result = {}

    current_period = None
    previous_period = None

    no_data_str = "No data available for the specified parameters for the KPIs"

    for kpi in template:

        row = process_summary_kpis(
            kpi.value,
            query_params,
            session,
            tile_name,
            valid_filter_column_map.get(kpi.name, {}),
            query_placeholder_values
        )

        if "error" in row:
            return row, current_period, previous_period, count, no_data_str

        result[kpi.name] = {
            "current_value": row.get("current_value", 0),
            "previous_value": row.get("previous_value", 0)
        }

        current_period = row.get(
            "current_period",
            current_period
        )

        previous_period = row.get(
            "previous_period",
            previous_period
        )

        if "no_data" in row:

            logger.warning(
                f"No data returned for KPI {kpi.name} in {tile_name}"
            )

            count += 1

            no_data_str = (
                no_data_str + f" {kpi.name},"
            )

    return (
        result,
        current_period,
        previous_period,
        count,
        no_data_str
    )

def build_account_kpi_response(
            result,
            current_period,
            previous_period,
            no_data_str,
            count):

     return {
            "totalAnomalies": result.get("TOT_ANOMALIES", {}).get("current_value", 0),
            "totalAnomaliesCompareToPrevious": calculate_percentage_change(
                result.get("TOT_ANOMALIES", {}).get("current_value"),
                result.get("TOT_ANOMALIES", {}).get("previous_value")
            ),
            "totalWAC": result.get("TOT_WAC_SALES", {}).get("current_value",0),
            "totalWACCompareToPrevious": calculate_percentage_change(
                result.get("TOT_WAC_SALES", {}).get("current_value"),
                result.get("TOT_WAC_SALES", {}).get("previous_value")
            ),
            "totalChargebacks": result.get("TOT_CHBK", {}).get("current_value",0),
            "totalChargebacksCompareToPrevious": calculate_percentage_change(
                result.get("TOT_CHBK", {}).get("current_value"),
                result.get("TOT_CHBK", {}).get("previous_value")
            ),
             "currentPeriod": current_period,
             "previousPeriod": previous_period,
             "nodataResponse": no_data_str if count > 0 else None
            }
# def get_account_detail_query(id_type):
#     if id_type == "340B":

#         return text("""
#             SELECT
#                 anomalyId, accountId, pharmacyId, anomalyEntityName,
#                 linkageScore, brand, date, daysOpen, region,
#                 chargeback, wac, units, dollars, state, city, action
#             FROM vwAccountDetailAnomalies
#             WHERE `accountId` = :id_value
#         """)

#     return text("""
#         SELECT
#             anomalyId, accountId, pharmacyId, anomalyEntityName,
#             linkageScore, brand, date, daysOpen, region,
#             chargeback, wac, units, dollars, state, city, action
#         FROM vwPharmacyDetailAnomalies
#         WHERE pharmacyId = :id_value
#     """)

def build_account_detail_anomaly(row):

    return {
        "anomalyId": row.anomalyId or "",
        "accountId": row.accountId or "",
        "pharmacyId": row.pharmacyId or "",
        "anomalyEntityName": row.anomalyEntityName,
        "linkageScore": int(row.linkageScore or 0),
        "brand": row.brand or "",
        "anomalyDate": row.date or "",
        "daysOpen": row.daysOpen or "0 Days",
        "region": row.region or "",
        "chargeback": format_monetary_value(row.chargeback),
        "wac": format_monetary_value(row.wac),
        "units": row.units,
        "dollars": format_monetary_value(row.dollars),
        "state": row.state,
        "city": row.city,
        "action": row.action or ""
    }


# def get_account_detail_overall_query(id_type):

#     if id_type == "340B":

#         return text("""
#             SELECT
#                 anomalyId, accountId, pharmacyId, anomalyEntityName,
#                 linkageScore, brand, date, daysOpen, region,
#                 chargeback, wac, units, dollars, state, city, action
#             FROM vwAccountDetailAnomaliesOverall
#             WHERE `accountId` = :id_value
#         """)

#     return text("""
#         SELECT
#             anomalyId, accountId, pharmacyId, anomalyEntityName,
#             linkageScore, brand, date, daysOpen, region,
#             chargeback, wac, units, dollars, state, city, action
#         FROM vwPharmacyDetailAnomaliesOverall
#         WHERE pharmacyId = :id_value
#     """)


def build_account_detail_anomaly_response(row):

    return {
        "anomalyId": row.anomalyId or "",
        "accountId": row.accountId or "",
        "pharmacyId": row.pharmacyId or "",
        "anomalyEntityName": row.anomalyEntityName,
        "linkageScore": int(row.linkageScore or 0),
        "brand": row.brand or "",
        "anomalyDate": row.date or "",
        "daysOpen": row.daysOpen or "0 Days",
        "region": row.region or "",
        "chargeback": format_monetary_value(row.chargeback),
        "wac": format_monetary_value(row.wac),
        "units": row.units,
        "dollars": row.dollars,
        "state": row.state,
        "city": row.city,
        "action": row.action or ""
    }




def get_requested_tiles(query_params):
    tilename_param = query_params.get("tilename", "")
    
    if not tilename_param:
        return None, create_error_response(
            MISSING_REQUIRED_PARAMETER,
            "Please specify one or more tile names using ?tilename=tile1,tile2"
        )
    
    return [name.strip() for name in tilename_param.split(',')],None


def validate_tiles(requested_tiles):
    for tile_name in requested_tiles:
        is_valid, error_msg = validate_tile_name(tile_name)
        if not is_valid:
            return create_error_response(
                "Invalid tile name",
                f"Tile '{tile_name}': {error_msg}",
                tile_name
            )
    return None


def get_additional_params(query_params):
    return {
        key: value
        for key, value in query_params.items()
        if key != 'tilename' and value
    }


def process_tile(tile_name, additional_params, dual_series_tiles, requested_tiles):
    tile_data = get_tile_data(tile_name, additional_params)

    if tile_data is None:
        return create_error_response(
            "Unknown tile",
            f"Tile '{tile_name}' is not recognized. Please check the tile name and try again.",
            tile_name
        )

    if tile_name in dual_series_tiles:
        if isinstance(tile_data, dict) and 'error' in tile_data:
            return tile_data

        is_valid, error_response = validate_dual_series_batch_compatibility(
            tile_data, tile_name, requested_tiles
        )

        return error_response if not is_valid else tile_data

    return tile_databuild_account_detail_anomaly
