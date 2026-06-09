"""
Shared helper utilities: filter building, validation, and error response helpers.
"""

import re
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------

def sanitize_filter_value(value: str) -> str:
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