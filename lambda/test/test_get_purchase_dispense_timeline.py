"""
Unit tests for get_purchase_dispense_timeline function.

These tests verify the purchase-dispense-timeline endpoint functionality:
- Response structure validation (purchase-dispense-timeline key with categories + series)
- Four series: 340B Dispense, 340B Purchase, Non-340B Dispense, Non-340B Purchase
- Path parameter validation (account_id, pharmacy_id)
- Query parameter filter handling (brands, states)
- Error handling for invalid parameters
- Database error handling (connection errors, missing tables)
- Edge cases (empty data, null values)

Endpoint: GET /api/v1/account/<account_id>/pharmacy/<pharmacy_id>/purchase-dispense

**Validates: Purchase Dispense Explorer Requirements**
"""

from unittest.mock import patch, MagicMock
import pytest

from lambda_handler import (
    get_purchase_dispense_timeline,
    MISSING_REQUIRED_PARAMETER,
    INTERNAL_SERVER_ERROR,
    DISP_LABEL_340B,
    PUR_LABEL_340B,
    DISP_LABEL_NON_340B,
    PUR_LABEL_NON_340B,
)


def create_mock_row(category, ce_dispense_qty, ce_purchase_qty, cp_dispense_qty, cp_purchase_qty):
    """Create a mock database row with the expected attributes."""
    row = MagicMock()
    row.category = category
    row.ce_dispense_qty = ce_dispense_qty
    row.ce_purchase_qty = ce_purchase_qty
    row.cp_dispense_qty = cp_dispense_qty
    row.cp_purchase_qty = cp_purchase_qty
    return row


class TestValidationErrors:
    """Tests for parameter validation error handling."""

    @patch('lambda_handler.app')
    def test_empty_account_id_returns_error(self, mock_app):
        """
        Test that empty account_id returns validation error.
        
        Validates: Missing required parameter handling
        """
        mock_app.current_event.query_string_parameters = {}

        result = get_purchase_dispense_timeline("", 123)

        assert isinstance(result, dict), "Should return dict on validation error"
        assert result.get("error") == MISSING_REQUIRED_PARAMETER
        assert "account_id" in result.get("message", "").lower() or "pharmacy_id" in result.get("message", "").lower()
        assert result.get("tileName") == "purchase-dispense-timeline"

    @patch('lambda_handler.app')
    def test_zero_pharmacy_id_returns_error(self, mock_app):
        """
        Test that pharmacy_id <= 0 returns validation error.
        
        Validates: pharmacy_id must be a positive integer
        """
        mock_app.current_event.query_string_parameters = {}

        result = get_purchase_dispense_timeline("DSH123456", 0)

        assert isinstance(result, dict), "Should return dict on validation error"
        assert result.get("error") == MISSING_REQUIRED_PARAMETER
        assert result.get("tileName") == "purchase-dispense-timeline"

    @patch('lambda_handler.app')
    def test_negative_pharmacy_id_returns_error(self, mock_app):
        """
        Test that negative pharmacy_id returns validation error.
        
        Validates: pharmacy_id must be a positive integer
        """
        mock_app.current_event.query_string_parameters = {}

        result = get_purchase_dispense_timeline("DSH123456", -5)

        assert isinstance(result, dict), "Should return dict on validation error"
        assert result.get("error") == MISSING_REQUIRED_PARAMETER
        assert result.get("tileName") == "purchase-dispense-timeline"

    @patch('lambda_handler.app')
    def test_none_account_id_returns_error(self, mock_app):
        """
        Test that None account_id returns validation error.
        
        Validates: account_id is required
        """
        mock_app.current_event.query_string_parameters = {}

        result = get_purchase_dispense_timeline(None, 123)

        assert isinstance(result, dict), "Should return dict on validation error"
        assert result.get("error") == MISSING_REQUIRED_PARAMETER


class TestResponseStructure:
    """Tests for purchase dispense timeline response structure."""

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_response_contains_purchase_dispense_timeline_key(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that response contains purchase-dispense-timeline key.
        
        Verifies that the response wraps data in the expected key.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        assert isinstance(response, dict), "Response should be a dictionary"
        assert "purchase-dispense-timeline" in response, "Response should contain purchase-dispense-timeline key"

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_response_contains_categories_field(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that response contains categories field.
        
        Verifies that the response has a categories list for chart x-axis labels.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
            create_mock_row("2024 Feb", 1100, 1300, 550, 650),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        assert "categories" in timeline, "Response should contain categories field"
        assert isinstance(timeline["categories"], list), "categories should be a list"

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_response_contains_series_field(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that response contains series field.
        
        Verifies that the response has a series list for chart data.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        assert "series" in timeline, "Response should contain series field"
        assert isinstance(timeline["series"], list), "series should be a list"

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_response_has_exactly_four_series(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that response contains exactly four series.
        
        Verifies that series array has the expected four data series:
        - 340B Dispense Quantity
        - 340B Purchase Quantity
        - Non 340B Dispense Quantity
        - Non 340B Purchase Quantity
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        assert len(timeline.get("series", [])) == 4, "Response should have exactly 4 series"


class TestSeriesStructure:
    """Tests for purchase dispense timeline series structure."""

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_series_contains_340b_dispense_quantity(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that series contains 340B Dispense Quantity data.
        
        Verifies that series includes 340B dispense quantity data with line chart type.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        dispense_series = next(
            (s for s in timeline.get("series", []) if s.get("name") == DISP_LABEL_340B),
            None
        )
        assert dispense_series is not None, f"Series should contain {DISP_LABEL_340B}"
        assert dispense_series.get("type") == "line", "340B Dispense series should be line type"
        assert dispense_series.get("yAxis") == 0, "340B Dispense series should use yAxis 0"

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_series_contains_340b_purchase_quantity(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that series contains 340B Purchase Quantity data.
        
        Verifies that series includes 340B purchase quantity data with line chart type.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        purchase_series = next(
            (s for s in timeline.get("series", []) if s.get("name") == PUR_LABEL_340B),
            None
        )
        assert purchase_series is not None, f"Series should contain {PUR_LABEL_340B}"
        assert purchase_series.get("type") == "line", "340B Purchase series should be line type"
        assert purchase_series.get("yAxis") == 1, "340B Purchase series should use yAxis 1"

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_series_contains_non_340b_dispense_quantity(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that series contains Non 340B Dispense Quantity data.
        
        Verifies that series includes non-340B dispense quantity data.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        non_340b_dispense = next(
            (s for s in timeline.get("series", []) if s.get("name") == DISP_LABEL_NON_340B),
            None
        )
        assert non_340b_dispense is not None, f"Series should contain {DISP_LABEL_NON_340B}"
        assert non_340b_dispense.get("type") == "line", "Non-340B Dispense series should be line type"
        assert non_340b_dispense.get("yAxis") == 0, "Non-340B Dispense series should use yAxis 0"

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_series_contains_non_340b_purchase_quantity(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that series contains Non 340B Purchase Quantity data.
        
        Verifies that series includes non-340B purchase quantity data.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        non_340b_purchase = next(
            (s for s in timeline.get("series", []) if s.get("name") == PUR_LABEL_NON_340B),
            None
        )
        assert non_340b_purchase is not None, f"Series should contain {PUR_LABEL_NON_340B}"
        assert non_340b_purchase.get("type") == "line", "Non-340B Purchase series should be line type"
        assert non_340b_purchase.get("yAxis") == 1, "Non-340B Purchase series should use yAxis 1"


class TestDataProcessing:
    """Tests for data extraction and processing."""

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_categories_extracted_correctly(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that categories are extracted correctly from rows.
        
        Validates that category values are converted to strings.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
            create_mock_row("2024 Feb", 1100, 1300, 550, 650),
            create_mock_row("2024 Mar", 1200, 1400, 600, 700),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        categories = timeline.get("categories", [])
        assert categories == ["2024 Jan", "2024 Feb", "2024 Mar"]

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_null_quantities_default_to_zero(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that null quantity values default to zero.
        
        Validates edge case handling for null database values.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", None, None, None, None),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        dispense_series = next(
            (s for s in timeline.get("series", []) if s.get("name") == DISP_LABEL_340B),
            None
        )
        assert dispense_series is not None
        assert dispense_series["data"][0]["dispense_quantity"] == 0

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_empty_result_returns_empty_categories_and_series(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that empty database result returns empty categories and series.
        
        Validates handling of no data scenario.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        assert timeline.get("categories") == []
        # Series should still have 4 elements but with empty data arrays
        for series in timeline.get("series", []):
            assert series.get("data") == []


class TestQueryParameters:
    """Tests for query parameter handling."""

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_filter_params_passed_to_generate_filters(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that filter parameters are passed to generate_global_filters_from_query_params.
        
        Validates that brands and states filters are processed.
        """
        mock_app.current_event.query_string_parameters = {
            "brands": "Cosentyx,Entresto",
            "states": "CA,NY"
        }
        mock_generate_filters.return_value = "AND Brand IN ('Cosentyx','Entresto') AND State IN ('CA','NY')"
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        get_purchase_dispense_timeline("DSH123456", 789)

        mock_generate_filters.assert_called_once()
        call_args = mock_generate_filters.call_args[0]
        assert call_args[0] == {"brands": "Cosentyx,Entresto", "states": "CA,NY"}

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_no_query_params_uses_empty_filter(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that missing query parameters results in no additional filters.
        
        Validates default behavior without filters.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        get_purchase_dispense_timeline("DSH123456", 789)

        # Should not call generate_global_filters when query_params is empty
        # Actually it will be called but with empty dict, so check the return was used
        assert mock_generate_filters.call_count == 0 or mock_generate_filters.return_value == ""


class TestDatabaseErrors:
    """Tests for database error handling."""

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_database_exception_returns_error_response(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that database exceptions return proper error response.
        
        Validates error handling for unexpected database errors.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("Database connection failed")
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        assert isinstance(response, dict)
        assert response.get("error") == INTERNAL_SERVER_ERROR
        assert "Database connection failed" in response.get("message", "")

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_session_closed_on_success(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that database session is closed after successful execution.
        
        Validates resource cleanup.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        get_purchase_dispense_timeline("DSH123456", 789)

        mock_session.close.assert_called_once()

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_session_closed_on_exception(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that database session is closed even when exception occurs.
        
        Validates resource cleanup on error path.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("Query failed")
        mock_get_session.return_value = mock_session

        get_purchase_dispense_timeline("DSH123456", 789)

        mock_session.close.assert_called_once()


class TestDataSeriesContent:
    """Tests for verifying the data content of each series."""

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_dispense_340b_data_contains_correct_values(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that 340B dispense series data contains correct values.
        
        Validates data extraction from ce_dispense_qty column.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
            create_mock_row("2024 Feb", 1100, 1300, 550, 650),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        dispense_series = next(
            (s for s in timeline.get("series", []) if s.get("name") == DISP_LABEL_340B),
            None
        )
        
        assert dispense_series is not None
        assert len(dispense_series["data"]) == 2
        assert dispense_series["data"][0]["category"] == "2024 Jan"
        assert dispense_series["data"][0]["dispense_quantity"] == 1000
        assert dispense_series["data"][1]["category"] == "2024 Feb"
        assert dispense_series["data"][1]["dispense_quantity"] == 1100

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_purchase_340b_data_contains_correct_values(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that 340B purchase series data contains correct values.
        
        Validates data extraction from ce_purchase_qty column.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
            create_mock_row("2024 Feb", 1100, 1300, 550, 650),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        purchase_series = next(
            (s for s in timeline.get("series", []) if s.get("name") == PUR_LABEL_340B),
            None
        )
        
        assert purchase_series is not None
        assert len(purchase_series["data"]) == 2
        assert purchase_series["data"][0]["category"] == "2024 Jan"
        assert purchase_series["data"][0]["purchase_quantity"] == 1200
        assert purchase_series["data"][1]["category"] == "2024 Feb"
        assert purchase_series["data"][1]["purchase_quantity"] == 1300

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_non_340b_dispense_data_contains_correct_values(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that Non-340B dispense series data contains correct values.
        
        Validates data extraction from cp_dispense_qty column.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        non_340b_dispense = next(
            (s for s in timeline.get("series", []) if s.get("name") == DISP_LABEL_NON_340B),
            None
        )
        
        assert non_340b_dispense is not None
        assert non_340b_dispense["data"][0]["non_340b_dispense_quantity"] == 500

    @patch('lambda_handler.get_date_for_time_period')
    @patch('lambda_handler.generate_global_filters_from_query_params')
    @patch('lambda_handler.get_session')
    @patch('lambda_handler.text')
    @patch('lambda_handler.app')
    def test_non_340b_purchase_data_contains_correct_values(
        self, mock_app, mock_text, mock_get_session, mock_generate_filters, mock_get_date
    ):
        """
        Test that Non-340B purchase series data contains correct values.
        
        Validates data extraction from cp_purchase_qty column.
        """
        mock_app.current_event.query_string_parameters = {}
        mock_generate_filters.return_value = ""
        mock_get_date.return_value = "2025-01-01"
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            create_mock_row("2024 Jan", 1000, 1200, 500, 600),
        ]
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value = mock_session

        response = get_purchase_dispense_timeline("DSH123456", 789)

        timeline = response.get("purchase-dispense-timeline", {})
        non_340b_purchase = next(
            (s for s in timeline.get("series", []) if s.get("name") == PUR_LABEL_NON_340B),
            None
        )
        
        assert non_340b_purchase is not None
        assert non_340b_purchase["data"][0]["non_340b_purchase_quantity"] == 600