"""Unit tests for backend/utils.py."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from utils import compute_service_day, ensure_service_day, get_line_by_code, _line_id_cache


# ---------------------------------------------------------------------------
# compute_service_day
# ---------------------------------------------------------------------------

class TestComputeServiceDay:
    """The service day changes at 04:00 Vienna local time (UTC+1 in winter, UTC+2 in summer)."""

    def test_midday_utc_is_same_calendar_day(self):
        # 12:00 UTC in winter = 13:00 Vienna → same calendar day
        dt = datetime(2024, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
        assert compute_service_day(dt) == date(2024, 3, 5)

    def test_evening_utc_is_same_calendar_day(self):
        # 21:00 UTC in winter = 22:00 Vienna → same calendar day
        dt = datetime(2024, 3, 5, 21, 0, 0, tzinfo=timezone.utc)
        assert compute_service_day(dt) == date(2024, 3, 5)

    def test_midnight_train_belongs_to_previous_day(self):
        # 00:30 UTC in winter = 01:30 Vienna → before 04:00 cutoff → previous day
        dt = datetime(2024, 3, 6, 0, 30, 0, tzinfo=timezone.utc)
        assert compute_service_day(dt) == date(2024, 3, 5)

    def test_exactly_at_cutoff_belongs_to_same_day(self):
        # 03:00 UTC in winter = 04:00 Vienna → exactly at cutoff → current day
        dt = datetime(2024, 3, 5, 3, 0, 0, tzinfo=timezone.utc)
        assert compute_service_day(dt) == date(2024, 3, 5)

    def test_one_minute_before_cutoff_belongs_to_previous_day(self):
        # 02:59 UTC in winter = 03:59 Vienna → just before cutoff → previous day
        dt = datetime(2024, 3, 5, 2, 59, 0, tzinfo=timezone.utc)
        assert compute_service_day(dt) == date(2024, 3, 4)

    def test_naive_datetime_treated_as_utc(self):
        # Naive datetime should be treated as UTC
        dt_naive = datetime(2024, 3, 5, 12, 0, 0)  # no tzinfo
        dt_aware = datetime(2024, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
        assert compute_service_day(dt_naive) == compute_service_day(dt_aware)

    def test_summer_time_cutoff(self):
        # Austria is UTC+2 in summer (CEST). 02:00 UTC = 04:00 Vienna → same day.
        dt = datetime(2024, 7, 15, 2, 0, 0, tzinfo=timezone.utc)
        assert compute_service_day(dt) == date(2024, 7, 15)

    def test_summer_one_minute_before_cutoff_is_previous_day(self):
        # 01:59 UTC in summer = 03:59 Vienna → before 04:00 cutoff → previous day
        dt = datetime(2024, 7, 15, 1, 59, 0, tzinfo=timezone.utc)
        assert compute_service_day(dt) == date(2024, 7, 14)

    def test_new_years_midnight_belongs_to_previous_year(self):
        # 00:00 UTC on Jan 1 = 01:00 Vienna → before 04:00 → Dec 31 service day
        dt = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert compute_service_day(dt) == date(2024, 12, 31)

    def test_returns_date_object(self):
        dt = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        result = compute_service_day(dt)
        assert isinstance(result, date)


# ---------------------------------------------------------------------------
# ensure_service_day
# ---------------------------------------------------------------------------

class TestEnsureServiceDay:
    def _make_db(self, existing=None):
        db = MagicMock()
        db.get.return_value = existing
        return db

    def test_returns_existing_row_without_creating(self):
        from models import ServiceDay
        existing = MagicMock(spec=ServiceDay)
        db = self._make_db(existing=existing)

        result = ensure_service_day(db, date(2024, 3, 5))

        assert result is existing
        db.add.assert_not_called()
        db.flush.assert_not_called()

    def test_creates_new_row_for_weekday(self):
        db = self._make_db(existing=None)

        result = ensure_service_day(db, date(2024, 3, 5))  # Tuesday

        db.add.assert_called_once()
        db.flush.assert_called_once()
        assert result.is_weekday is True
        assert result.day_of_week == 1  # 0=Mon, 1=Tue

    def test_creates_new_row_for_weekend(self):
        db = self._make_db(existing=None)

        result = ensure_service_day(db, date(2024, 3, 9))  # Saturday

        db.add.assert_called_once()
        assert result.is_weekday is False
        assert result.day_of_week == 5  # Saturday

    def test_marks_austrian_national_holiday(self):
        db = self._make_db(existing=None)

        # Austrian National Day (Nationalfeiertag) is October 26
        result = ensure_service_day(db, date(2024, 10, 26))

        assert result.is_austrian_holiday is True
        assert result.holiday_name is not None

    def test_marks_ordinary_day_as_non_holiday(self):
        db = self._make_db(existing=None)

        result = ensure_service_day(db, date(2024, 3, 5))  # Ordinary Tuesday

        assert result.is_austrian_holiday is False
        assert result.holiday_name is None

    def test_marks_christmas_as_holiday(self):
        db = self._make_db(existing=None)

        result = ensure_service_day(db, date(2024, 12, 25))

        assert result.is_austrian_holiday is True


# ---------------------------------------------------------------------------
# get_line_by_code
# ---------------------------------------------------------------------------

class TestGetLineByCode:
    def setup_method(self):
        # Clear the module-level cache before each test
        _line_id_cache.clear()

    def test_returns_line_from_db(self):
        from models import Line
        mock_line = MagicMock(spec=Line)
        mock_line.id = 42
        db = MagicMock()
        db.query.return_value.filter_by.return_value.one_or_none.return_value = mock_line
        db.get.return_value = mock_line

        result = get_line_by_code(db, "CJX")

        assert result is mock_line

    def test_raises_for_missing_line(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.one_or_none.return_value = None

        with pytest.raises(ValueError, match="CJX"):
            get_line_by_code(db, "CJX")

    def test_caches_line_id_after_first_lookup(self):
        from models import Line
        mock_line = MagicMock(spec=Line)
        mock_line.id = 7
        db = MagicMock()
        db.query.return_value.filter_by.return_value.one_or_none.return_value = mock_line
        db.get.return_value = mock_line

        get_line_by_code(db, "U6")
        get_line_by_code(db, "U6")

        # DB query (filter_by) called only once; db.get called twice (once per call)
        db.query.return_value.filter_by.assert_called_once()

    def test_raises_for_stale_cache(self):
        """If the cached ID no longer exists in DB, ValueError must be raised."""
        from models import Line
        mock_line = MagicMock(spec=Line)
        mock_line.id = 99
        db = MagicMock()
        db.query.return_value.filter_by.return_value.one_or_none.return_value = mock_line
        db.get.return_value = mock_line

        # Populate the cache
        get_line_by_code(db, "CJX")
        assert "CJX" in _line_id_cache

        # Simulate row being deleted from DB
        db.get.return_value = None

        with pytest.raises(ValueError, match="stale cache"):
            get_line_by_code(db, "CJX")

    def test_stale_cache_entry_is_removed_on_error(self):
        """After a stale-cache error the entry should be removed so the next
        call can re-query the DB."""
        from models import Line
        mock_line = MagicMock(spec=Line)
        mock_line.id = 99
        db = MagicMock()
        db.query.return_value.filter_by.return_value.one_or_none.return_value = mock_line
        db.get.return_value = mock_line

        get_line_by_code(db, "CJX")

        # Row vanishes
        db.get.return_value = None
        with pytest.raises(ValueError):
            get_line_by_code(db, "CJX")

        # Cache entry must be gone
        assert "CJX" not in _line_id_cache
