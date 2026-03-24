"""Unit tests for pure helper functions in routes/stats.py."""

import pytest

from routes.stats import _product_clause, _anchor_station
from config import (
    TERNITZ_STATION_ID,
    WIEN_MEIDLING_STATION_ID,
    WIEN_WESTBAHNHOF_STATION_ID,
)


# ---------------------------------------------------------------------------
# _product_clause
# ---------------------------------------------------------------------------

class TestProductClause:
    def test_returns_clause_when_product_given(self):
        clause = _product_clause("regional")
        assert "l.product_type = :product" in clause

    def test_returns_empty_string_when_no_product(self):
        assert _product_clause(None) == ""

    def test_returns_empty_string_for_falsy_product(self):
        assert _product_clause("") == ""


# ---------------------------------------------------------------------------
# _anchor_station
# ---------------------------------------------------------------------------

class TestAnchorStation:
    def test_to_wien_regional_anchors_at_ternitz(self):
        assert _anchor_station("to_wien", "regional") == TERNITZ_STATION_ID

    def test_to_wien_no_product_anchors_at_ternitz(self):
        assert _anchor_station("to_wien", None) == TERNITZ_STATION_ID

    def test_to_wien_subway_anchors_at_meidling(self):
        assert _anchor_station("to_wien", "subway") == WIEN_MEIDLING_STATION_ID

    def test_to_ternitz_subway_anchors_at_westbahnhof(self):
        assert _anchor_station("to_ternitz", "subway") == WIEN_WESTBAHNHOF_STATION_ID

    def test_to_ternitz_regional_anchors_at_meidling(self):
        assert _anchor_station("to_ternitz", "regional") == WIEN_MEIDLING_STATION_ID

    def test_to_ternitz_no_product_anchors_at_meidling(self):
        assert _anchor_station("to_ternitz", None) == WIEN_MEIDLING_STATION_ID
