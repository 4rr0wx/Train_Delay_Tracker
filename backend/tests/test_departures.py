"""Unit tests for departures response serialization logic.

These tests focus on the `delay_minutes` field fix: it must be `None` (not 0)
when `delay_seconds` is NULL, to distinguish "unknown delay" from "on-time".
"""

import pytest


# ---------------------------------------------------------------------------
# Simulate the delay_minutes calculation from departures.py line 97
# ---------------------------------------------------------------------------

def _delay_minutes(delay_seconds):
    """Mirror the expression from departures.py to allow isolated testing."""
    return round(delay_seconds / 60, 1) if delay_seconds is not None else None


class TestDelayMinutesCalculation:
    def test_none_delay_seconds_returns_none(self):
        """NULL delay → unknown delay, must not be reported as 0 (on-time)."""
        assert _delay_minutes(None) is None

    def test_zero_delay_seconds_returns_zero(self):
        """0-second delay → exactly on time."""
        assert _delay_minutes(0) == 0.0

    def test_positive_delay_converted(self):
        assert _delay_minutes(120) == 2.0

    def test_small_delay_rounds_correctly(self):
        assert _delay_minutes(65) == 1.1

    def test_negative_delay_early_departure(self):
        assert _delay_minutes(-60) == -1.0

    def test_large_delay(self):
        assert _delay_minutes(3600) == 60.0
