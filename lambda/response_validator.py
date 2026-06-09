"""
Response Format Validation Module

This module provides comprehensive validation for tile response formats to ensure:
1. All required fields are present in tile responses
2. Proper handling of null/empty database results
3. Response structure is maintained even with missing data
4. Response schemas match documentation

Validates: Requirements 7.1, 7.4, 7.5
"""

from typing import Dict, Any, Tuple, List, Optional

# Try to import Logger, but allow module to work without it for testing
try:
    from aws_lambda_powertools import Logger
    logger = Logger(child=True)
except ImportError:
    # Fallback logger for testing
    import logging
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)


# ============================================================================
# Response Schema Definitions
# ============================================================================
#
# IMPORTANT: When adding a new tile, you MUST add its schema here to enable
# full validation coverage. Without a schema, the tile will still work but
# will only get basic null handling without field validation.
#
# Schema Structure:
# -----------------
# For dictionary responses:
#   "tile-name": {
#       "required_fields": ["field1", "field2"],  # Fields that must be present
#       "field_types": {                          # Expected types for each field
#           "field1": (int, float),               # Can be tuple for multiple types
#           "field2": str
#       },
#       "nested_fields": {                        # For nested objects
#           "field1": ["nestedField1", "nestedField2"]
#       }
#   }
#
# For array responses:
#   "tile-name": {
#       "required_fields": [],                    # Empty for array responses
#       "array_item_fields": ["field1", "field2"], # Fields in each array item
#       "field_types": {                          # Types for array item fields
#           "field1": str,
#           "field2": (int, float)
#       }
#   }
#
# For chart responses with series:
#   "tile-name": {
#       "required_fields": ["categories", "series"],
#       "field_types": {
#           "categories": list,
#           "series": list
#       },
#       "series_count": 2,                        # Expected number of series
#       "series_fields": ["name", "data", "type", "yAxis"]
#   }
#
# See .kiro/steering/tile-development-guide.md for detailed examples and best practices.
# ============================================================================

TILE_SCHEMAS = {
    "summary-kpis": {
        "required_fields": [
            "coveredEntities",
            "coveredEntitiesCompareToPrevious",
            "activeAnomalies",
            "activeAnomaliesCompareToPrevious",
            "unitVolume340b",
            "unitVolume340bCompareToPrevious",
            "riskExposure",
            "riskExposureCompareToPrevious"
        ],
        "nested_fields": {
            "unitVolume340b": ["count", "dollars"]
        },
        "field_types": {
            "coveredEntities": (int, float),
            "coveredEntitiesCompareToPrevious": (str, int, float),
            "activeAnomalies": (int, float),
            "activeAnomaliesCompareToPrevious": (str, int, float),
            "unitVolume340b": dict,
            "unitVolume340bCompareToPrevious": (str, int, float),
            "riskExposure": (int, float),
            "riskExposureCompareToPrevious": (str, int, float)
        }
    },
    "340b-covered-entity-volume": {
        "required_fields": ["categories", "series"],
        "field_types": {
            "categories": list,
            "series": list
        },
        "series_count": 2,
        "series_fields": ["name", "data", "type", "yAxis"]
    },
    "dispense-vs-purchase-volume": {
        "required_fields": ["categories", "series"],
        "field_types": {
            "categories": list,
            "series": list
        },
        "series_count": 2,
        "series_fields": ["name", "data", "type", "yAxis"]
    },
    "quarterly-dispense-purchase-comparison-by-corp": {
        "required_fields": ["meta", "staticColumns", "measures", "rows"],
        "nested_fields": {
            "meta": ["periodType", "periods"],
            "staticColumns": [],  # Array of objects
            "measures": [],  # Array of objects
            "rows": []  # Array of objects
        },
        "field_types": {
            "meta": dict,
            "staticColumns": list,
            "measures": list,
            "rows": list
        }
    },
    "quarterly-dispense-purchase-comparison-by-state": {
        "required_fields": ["meta", "staticColumns", "measures", "rows"],
        "nested_fields": {
            "meta": ["periodType", "periods"],
            "staticColumns": [],  # Array of objects
            "measures": [],  # Array of objects
            "rows": []  # Array of objects
        },
        "field_types": {
            "meta": dict,
            "staticColumns": list,
            "measures": list,
            "rows": list
        }
    },
    "anomaly-kpis": {
        "required_fields": [
            "coveredEntities",
            "coveredEntitiesCompareToPrevious",
            "activeAnomalies",
            "activeAnomaliesCompareToPrevious",
            "totalRiskCost",
            "totalRiskCostCompareToPrevious",
            "totalRiskUnits",
            "totalRiskUnitsCompareToPrevious"
        ],
        "field_types": {
            "coveredEntities": (int, float),
            "coveredEntitiesCompareToPrevious": (str, int, float),
            "activeAnomalies": (int, float),
            "activeAnomaliesCompareToPrevious": (str, int, float),
            "totalRiskCost": (int, float),
            "totalRiskCostCompareToPrevious": (str, int, float),
            "totalRiskUnits": (int, float),
            "totalRiskUnitsCompareToPrevious": (str, int, float)
        }
    },
    "340b-growth-by-drivers": {
        "required_fields": [],  # Array of objects
        "array_item_fields": ["actions", "value"],
        "field_types": {
            "actions": str,
            "value": (int, float)
        }
    },
    "anomalies-list": {
        "required_fields": [],  # Array of objects
        "array_item_fields": [
            "anomalyId", "linkageScore", "anomalyEntityName", "brand",
            "anomalyDate", "daysOpen", "region", "units", "dollars",
            "action", "state", "city"
        ]
    },
    "top-340b-accounts": {
        "required_fields": [],  # Array of objects
        "array_item_fields": [
            "id", "name", "anomalies", "brands", "region", "chargeback", "wac"
        ],
        "field_types": {
            "id": str,  # Unique account identifier (340B_ID)
            "name": str,
            "anomalies": (int, float),
            "brands": str,  # Comma-separated brand names
            "region": str,
            "chargeback": str,  # Formatted monetary value
            "wac": str  # Formatted monetary value
        }
    },
    "accounts-summary-kpis": {
        "required_fields": [
            "threeFourtyBAccounts",
            "threeFourtyBAccountsCompareToPrevious",
            "contractPharmacyAccounts",
            "contractPharmacyAccountsCompareToPrevious",
            "totalAnomalies",
            "totalAnomaliesCompareToPrevious",
            "totalChargebacks",
            "totalChargebacksCompareToPrevious"
        ],
        "field_types": {
            "threeFourtyBAccounts": (int, float),
            "threeFourtyBAccountsCompareToPrevious": (str, int, float),
            "contractPharmacyAccounts": (int, float),
            "contractPharmacyAccountsCompareToPrevious": (str, int, float),
            "totalAnomalies": (int, float),
            "totalAnomaliesCompareToPrevious": (str, int, float),
            "totalChargebacks": str,  # Formatted as "$XXXk"
            "totalChargebacksCompareToPrevious": (str, int, float)
        }
    },
    "contract-pharmacy-accounts": {
        "required_fields": [],  # Array of objects
        "array_item_fields": [
            "id", "name", "anomalies", "brands", "region", "chargeback", "wac"
        ],
        "field_types": {
            "id": str,  # Unique account identifier (Pharmacy_ID)
            "name": str,
            "anomalies": (int, float),
            "brands": str,  # Comma-separated brand names
            "region": str,
            "chargeback": str,  # Formatted monetary value
            "wac": str  # Formatted monetary value
        }
    },
    "account-detail-header": {
        "required_fields": ["accountName", "address"],
        "field_types": {
            "accountName": str,
            "address": str,
            "340bId": str,  # Optional - present for 340B accounts
            "pharmacyId": str,  # Optional - present for pharmacy accounts
            "idType": str  # Optional - "340B" or "Pharmacy"
        }
    },
    "account-detail-kpis": {
        "required_fields": [
            "totalAnomalies",
            "totalAnomaliesCompareToPrevious",
            "totalWAC",
            "totalWACCompareToPrevious",
            "totalChargebacks",
            "totalChargebacksCompareToPrevious"
        ],
        "field_types": {
            "totalAnomalies": (int, float),
            "totalAnomaliesCompareToPrevious": (str, int, float),
            "totalWAC": str,  # Formatted as "$XXXk" or "$XXXM"
            "totalWACCompareToPrevious": (str, int, float),
            "totalChargebacks": str,  # Formatted as "$XXXk" or "$XXXM"
            "totalChargebacksCompareToPrevious": (str, int, float),
            "340bId": str,  # Optional - present for 340B accounts
            "pharmacyId": str,  # Optional - present for pharmacy accounts
            "idType": str  # Optional - "340B" or "Pharmacy"
        }
    },
    "account-detail-anomalous-transactions-volume": {
        "required_fields": ["categories", "series"],
        "field_types": {
            "categories": list,
            "series": list
        },
        "series_count": 1,
        "series_fields": ["name", "data", "type", "yAxis"]
    },
    "account-detail-covered-entity-purchase-trends": {
        "required_fields": ["categories", "series"],
        "field_types": {
            "categories": list,
            "series": list
        },
        "series_count": 1,
        "series_fields": ["name", "data", "type", "yAxis"]
    },
    "account-detail-covered-entity-dispense-trends": {
        "required_fields": ["categories", "series"],
        "field_types": {
            "categories": list,
            "series": list
        },
        "series_count": 1,
        "series_fields": ["name", "data", "type", "yAxis"]
    },
    "account-detail-anomalies": {
        "required_fields": [],  # Array of objects
        "array_item_fields": [
            "anomalyId", "linkageScore", "brand", "date", "daysOpen",
            "region", "chargeback", "wac", "action"
        ],
        "field_types": {
            "anomalyId": str,  # 8-character hash identifier
            "linkageScore": (int, float),
            "brand": str,
            "date": str,  # MM/DD/YYYY format
            "daysOpen": str,  # "X Day" or "X Days" format
            "region": str,
            "chargeback": str,  # Formatted monetary value
            "wac": str,  # Formatted monetary value
            "action": str
        }
    }
}


# ============================================================================
# Validation Functions
# ============================================================================

def validate_response_format(tile_data: Any, tile_name: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Validate that a tile response matches its documented schema.
    
    This function ensures:
    - All required fields are present
    - Field types match expected types
    - Nested structures are valid
    - Response structure is maintained even with null/empty data
    
    Args:
        tile_data: The tile response data to validate
        tile_name: Name of the tile for schema lookup
    
    Returns:
        Tuple of (is_valid, error_response_or_empty_dict)
        - is_valid: True if response is valid, False otherwise
        - error_response_or_empty_dict: Error response dict if invalid, empty dict if valid
    
    Validates: Requirements 7.1, 7.4
    """
    # Skip validation for error responses
    if isinstance(tile_data, dict) and "error" in tile_data:
        return True, {}
    
    # Check if we have a schema for this tile
    if tile_name not in TILE_SCHEMAS:
        # No schema defined - allow response (backward compatibility)
        logger.warning(f"No validation schema defined for tile: {tile_name}")
        return True, {}
    
    schema = TILE_SCHEMAS[tile_name]
    
    # Validate response is not None
    if tile_data is None:
        return False, {
            "error": "Null response",
            "message": "Tile response cannot be null",
            "tileName": tile_name
        }
    
    # Handle array responses (e.g., anomalies-list, 340b-growth-by-drivers)
    if "array_item_fields" in schema:
        return _validate_array_response(tile_data, tile_name, schema)
    
    # Validate dictionary responses
    if not isinstance(tile_data, dict):
        return False, {
            "error": "Invalid response type",
            "message": f"Expected dictionary, got {type(tile_data).__name__}",
            "tileName": tile_name
        }
    
    # Validate required fields
    missing_fields = []
    for field in schema.get("required_fields", []):
        if field not in tile_data:
            missing_fields.append(field)
    
    if missing_fields:
        return False, {
            "error": "Missing required fields",
            "message": f"Response missing required fields: {', '.join(missing_fields)}",
            "tileName": tile_name
        }
    
    # Validate field types
    type_errors = []
    for field, expected_type in schema.get("field_types", {}).items():
        if field in tile_data:
            value = tile_data[field]
            # Allow None values for optional fields
            if value is not None:
                if not isinstance(value, expected_type):
                    type_errors.append(
                        f"{field}: expected {expected_type}, got {type(value).__name__}"
                    )
    
    if type_errors:
        return False, {
            "error": "Invalid field types",
            "message": f"Type validation failed: {'; '.join(type_errors)}",
            "tileName": tile_name
        }
    
    # Validate nested fields
    for parent_field, child_fields in schema.get("nested_fields", {}).items():
        if parent_field in tile_data and tile_data[parent_field] is not None:
            parent_value = tile_data[parent_field]
            if isinstance(parent_value, dict) and child_fields:
                missing_nested = []
                for child_field in child_fields:
                    if child_field not in parent_value:
                        missing_nested.append(f"{parent_field}.{child_field}")
                
                if missing_nested:
                    return False, {
                        "error": "Missing nested fields",
                        "message": f"Response missing nested fields: {', '.join(missing_nested)}",
                        "tileName": tile_name
                    }
    
    # Validate series structure for chart tiles
    if "series_count" in schema:
        is_valid, error_response = _validate_series_structure(
            tile_data, tile_name, schema
        )
        if not is_valid:
            return False, error_response
    
    return True, {}


def _validate_array_response(
    tile_data: Any, 
    tile_name: str, 
    schema: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Validate array-type tile responses.
    
    Args:
        tile_data: The tile response data (should be a list)
        tile_name: Name of the tile
        schema: Schema definition for the tile
    
    Returns:
        Tuple of (is_valid, error_response_or_empty_dict)
    """
    if not isinstance(tile_data, list):
        return False, {
            "error": "Invalid response type",
            "message": f"Expected list, got {type(tile_data).__name__}",
            "tileName": tile_name
        }
    
    # Empty arrays are valid (no data scenario)
    if len(tile_data) == 0:
        return True, {}
    
    # Validate array items have required fields
    array_item_fields = schema.get("array_item_fields", [])
    if array_item_fields:
        for i, item in enumerate(tile_data):
            if not isinstance(item, dict):
                return False, {
                    "error": "Invalid array item type",
                    "message": f"Array item {i} must be a dictionary",
                    "tileName": tile_name
                }
            
            missing_fields = []
            for field in array_item_fields:
                if field not in item:
                    missing_fields.append(field)
            
            if missing_fields:
                return False, {
                    "error": "Missing array item fields",
                    "message": f"Array item {i} missing fields: {', '.join(missing_fields)}",
                    "tileName": tile_name
                }
    
    return True, {}


def _validate_series_structure(
    tile_data: Dict[str, Any],
    tile_name: str,
    schema: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Validate series structure for chart tiles.
    
    Args:
        tile_data: The tile response data
        tile_name: Name of the tile
        schema: Schema definition for the tile
    
    Returns:
        Tuple of (is_valid, error_response_or_empty_dict)
    """
    series = tile_data.get("series", [])
    expected_count = schema.get("series_count")
    
    if len(series) != expected_count:
        return False, {
            "error": "Invalid series count",
            "message": f"Expected {expected_count} series, got {len(series)}",
            "tileName": tile_name
        }
    
    # Validate each series has required fields
    series_fields = schema.get("series_fields", [])
    for i, series_item in enumerate(series):
        if not isinstance(series_item, dict):
            return False, {
                "error": "Invalid series item type",
                "message": f"Series item {i} must be a dictionary",
                "tileName": tile_name
            }
        
        missing_fields = []
        for field in series_fields:
            if field not in series_item:
                missing_fields.append(field)
        
        if missing_fields:
            return False, {
                "error": "Missing series fields",
                "message": f"Series item {i} missing fields: {', '.join(missing_fields)}",
                "tileName": tile_name
            }
    
    return True, {}


def handle_null_data_gracefully(
    db_result: Any,
    tile_name: str,
    default_structure: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Handle null or empty database results gracefully by maintaining response structure.
    
    This function ensures that even when the database returns null or empty results,
    the API response maintains the expected structure with appropriate default values.
    
    Args:
        db_result: The result from the database query (may be None or empty)
        tile_name: Name of the tile for error reporting
        default_structure: Optional default structure to return for null/empty data
    
    Returns:
        Dictionary with maintained structure and default values
    
    Validates: Requirement 7.5
    """
    # If db_result is already an error response, return it as-is
    if isinstance(db_result, dict) and "error" in db_result:
        return db_result
    
    # If db_result is None or empty, return default structure
    if db_result is None or (isinstance(db_result, (list, dict)) and len(db_result) == 0):
        if default_structure is not None:
            return default_structure
        
        # Return tile-specific default structures
        return _get_default_structure_for_tile(tile_name)
    
    return db_result


def _get_default_structure_for_tile(tile_name: str) -> Dict[str, Any]:
    """
    Get default structure for a tile when no data is available.
    
    Args:
        tile_name: Name of the tile
    
    Returns:
        Dictionary with default structure and zero/empty values
    """
    if tile_name not in TILE_SCHEMAS:
        # Return empty dict for unknown tiles
        return {}
    
    schema = TILE_SCHEMAS[tile_name]
    default_structure = {}
    
    # Handle array responses
    if "array_item_fields" in schema:
        return []
    
    # Build default structure from schema
    for field in schema.get("required_fields", []):
        field_type = schema.get("field_types", {}).get(field)
        
        if field_type == dict:
            # Handle nested objects
            nested_fields = schema.get("nested_fields", {}).get(field, [])
            default_structure[field] = {
                nested_field: 0 for nested_field in nested_fields
            }
        elif field_type == list:
            default_structure[field] = []
        elif field_type in [(int, float), int, float]:
            default_structure[field] = 0
        elif field_type in [(str, int, float), str]:
            default_structure[field] = "N/A"
        else:
            default_structure[field] = None
    
    return default_structure


def validate_and_sanitize_response(
    tile_data: Any,
    tile_name: str
) -> Tuple[bool, Dict[str, Any]]:
    """
    Comprehensive validation and sanitization of tile responses.
    
    This function combines format validation and null data handling to ensure
    all responses are valid and maintain proper structure.
    
    Args:
        tile_data: The tile response data to validate and sanitize
        tile_name: Name of the tile
    
    Returns:
        Tuple of (is_valid, sanitized_response_or_error)
        - is_valid: True if response is valid, False if there's an error
        - sanitized_response_or_error: Sanitized response if valid, error dict if invalid
    
    Validates: Requirements 7.1, 7.4, 7.5
    """
    # Handle null/empty data gracefully
    sanitized_data = handle_null_data_gracefully(tile_data, tile_name)
    
    # Validate response format
    is_valid, error_response = validate_response_format(sanitized_data, tile_name)
    
    if not is_valid:
        return False, error_response
    
    return True, sanitized_data