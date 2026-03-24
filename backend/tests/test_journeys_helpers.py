"""Unit tests for pure helper functions in routes/journeys.py."""

from datetime import datetime, timedelta, timezone

import pytest

# Import the helpers directly (they are module-level functions)
from routes.journeys import _parse_days, _parse_times, _date_bounds, _fmt, _delay_min


# ---------------------------------------------------------------------------
# _parse_days
# ---------------------------------------------------------------------------

class TestParseDays:
    def test_parses_comma_separated_ints(self):
        assert _parse_days("1,2,3,4,5") == [1, 2, 3, 4, 5]

    def test_parses_single_day(self):
        assert _parse_days("0") == [0]

    def test_returns_none_for_none_input(self):
        assert _parse_days(None) is None

    def test_returns_none_for_empty_string(self):
        assert _parse_days("") is None

    def test_returns_none_on_invalid_value(self):
        assert _parse_days("1,two,3") is None

    def test_strips_whitespace(self):
        assert _parse_days("1, 2, 3") == [1, 2, 3]

    def test_all_days(self):
        assert _parse_days("0,1,2,3,4,5,6") == [0, 1, 2, 3, 4, 5, 6]


# ---------------------------------------------------------------------------
# _parse_times
# ---------------------------------------------------------------------------

class TestParseTimes:
    def test_parses_single_time(self):
        assert _parse_times("07:11") == [431]  # 7*60+11

    def test_parses_multiple_times(self):
        assert _parse_times("07:11,07:40") == [431, 460]

    def test_returns_none_for_none(self):
        assert _parse_times(None) is None

    def test_returns_none_for_empty_string(self):
        assert _parse_times("") is None

    def test_skips_invalid_tokens(self):
        # "notaTime" has no ":", so it's skipped; valid times still parsed
        result = _parse_times("07:11,notaTime,16:15")
        assert result == [431, 975]  # 16*60+15 = 975

    def test_midnight(self):
        assert _parse_times("00:00") == [0]

    def test_end_of_day(self):
        assert _parse_times("23:59") == [1439]  # 23*60+59

    def test_strips_whitespace(self):
        assert _parse_times("07:11, 07:40") == [431, 460]


# ---------------------------------------------------------------------------
# _date_bounds
# ---------------------------------------------------------------------------

class TestDateBounds:
    def test_defaults_to_days_ago_to_now(self):
        before = datetime.now(timezone.utc)
        df, dt = _date_bounds(None, None, 30)
        after = datetime.now(timezone.utc)

        assert before - timedelta(days=30) - timedelta(seconds=1) <= df
        assert df <= after - timedelta(days=30) + timedelta(seconds=1)
        assert before <= dt <= after + timedelta(seconds=1)

    def test_explicit_date_from(self):
        df, _ = _date_bounds("2024-01-15", None, 30)
        assert df == datetime(2024, 1, 15, tzinfo=timezone.utc)

    def test_explicit_date_to_gets_end_of_day(self):
        _, dt = _date_bounds(None, "2024-01-20", 30)
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 20
        assert dt.hour == 23
        assert dt.minute == 59
        assert dt.second == 59

    def test_invalid_date_from_falls_back_to_default(self):
        before = datetime.now(timezone.utc) - timedelta(days=30) - timedelta(seconds=2)
        df, _ = _date_bounds("not-a-date", None, 30)
        assert df >= before

    def test_invalid_date_to_falls_back_to_now(self):
        before = datetime.now(timezone.utc) - timedelta(seconds=2)
        _, dt = _date_bounds(None, "not-a-date", 30)
        assert dt >= before

    def test_both_explicit(self):
        df, dt = _date_bounds("2024-03-01", "2024-03-31", 30)
        assert df.date().isoformat() == "2024-03-01"
        assert dt.date().isoformat() == "2024-03-31"

    def test_timezone_aware_output(self):
        df, dt = _date_bounds(None, None, 7)
        assert df.tzinfo is not None
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# _fmt and _delay_min
# ---------------------------------------------------------------------------

class TestFmt:
    def test_returns_isoformat_for_datetime(self):
        ts = datetime(2024, 3, 5, 10, 30, 0, tzinfo=timezone.utc)
        assert _fmt(ts) == ts.isoformat()

    def test_returns_none_for_none(self):
        assert _fmt(None) is None


class TestDelayMin:
    def test_converts_seconds_to_minutes(self):
        assert _delay_min(120) == 2.0

    def test_rounds_to_one_decimal(self):
        assert _delay_min(130) == 2.2

    def test_returns_none_for_none(self):
        assert _delay_min(None) is None

    def test_zero_seconds(self):
        assert _delay_min(0) == 0.0

    def test_negative_delay(self):
        # Early departure — allowed in the data model
        assert _delay_min(-60) == -1.0
