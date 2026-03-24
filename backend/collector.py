"""
Data collector for the commute route: Ternitz <-> Wien Westbahnhof (V2)

Commute legs:
  to_wien:    Ternitz --[CJX]--> Wien Meidling --[U6]--> Wien Westbahnhof
  to_ternitz: Wien Westbahnhof --[U6]--> Wien Meidling --[CJX]--> Ternitz

Writes to V2 schema: trips, trip_stops, remarks, collection_runs, api_errors.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from config import (
    API_BASE_URL,
    TERNITZ_STATION_ID,
    WIEN_MEIDLING_STATION_ID,
    WIEN_WESTBAHNHOF_STATION_ID,
    WIENER_NEUSTADT_STATION_ID,
    BADEN_STATION_ID,
    POLL_DURATION_MINUTES,
    RELEVANT_TRAIN_LINE,
    RELEVANT_SUBWAY_LINE,
)
from database import SessionLocal
from models import (
    ApiError,
    CollectionRun,
    CollectionRunStatus,
    Line,
    Remark,
    Trip,
    TripDirection,
    TripStatus,
    TripStop,
)
from utils import compute_service_day, ensure_service_day, get_line_by_code

logger = logging.getLogger(__name__)
TIMEOUT = httpx.Timeout(30.0)


# ---------------------------------------------------------------------------
# Direction / filtering helpers (preserved from V1)
# ---------------------------------------------------------------------------

# For Wien Meidling U6: exclude all non-subway modes to avoid HAFAS errors
_SUBWAY_ONLY = {
    "national": "false",
    "nationalExpress": "false",
    "interregional": "false",
    "regional": "false",
    "suburban": "false",
}

# CJX Wien-bound keywords (departure direction field)
_WIEN_BOUND_KEYWORDS = {"wien", "laa"}
_NOT_WIEN_BOUND_KEYWORDS = {"payerbach", "reichenau", "wiener neustadt"}

# CJX arrival provenance keywords (inverted: where the train came FROM)
_SOUTH_ORIGIN_KEYWORDS = {"payerbach", "reichenau", "ternitz", "semmering"}
_WIEN_ORIGIN_KEYWORDS = {"wien", "laa"}
_NOT_WIEN_ORIGIN_KEYWORDS = {"wiener neustadt"}  # guard against "wien" substring

_U6_TO_WIEN = "floridsdorf"      # U6 northbound → passes Wien Westbahnhof
_U6_TO_TERNITZ = "siebenhirten"  # U6 southbound → passes Wien Westbahnhof


def _line_name(item: dict) -> str:
    return ((item.get("line") or {}).get("name") or "").upper()


def _dir_str(item: dict) -> str:
    return (item.get("direction") or item.get("provenance") or "").lower()


def _is_cjx(item: dict) -> bool:
    return _line_name(item).startswith(RELEVANT_TRAIN_LINE)


def _is_u6(item: dict) -> bool:
    return _line_name(item) == RELEVANT_SUBWAY_LINE


def _cjx_is_wien_bound(item: dict) -> bool:
    dest = _dir_str(item)
    if any(kw in dest for kw in _NOT_WIEN_BOUND_KEYWORDS):
        return False
    return any(kw in dest for kw in _WIEN_BOUND_KEYWORDS)


def _cjx_arrival_is_wien_bound(item: dict) -> bool:
    """For CJX arrivals at intermediate stations: is this train heading to Wien?

    Uses provenance (origin) to decide — logic is inverted vs departures:
      provenance from south (Payerbach/Ternitz) → heading to Wien → True
      provenance from Wien/Laa               → heading to Ternitz → False
    """
    prov = (item.get("provenance") or item.get("direction") or "").lower()
    if any(kw in prov for kw in _SOUTH_ORIGIN_KEYWORDS):
        return True
    if any(kw in prov for kw in _NOT_WIEN_ORIGIN_KEYWORDS):
        return False
    if any(kw in prov for kw in _WIEN_ORIGIN_KEYWORDS):
        return False
    return False


# ---------------------------------------------------------------------------
# Known stop_sequence per line code + direction
# ---------------------------------------------------------------------------

_STOP_SEQUENCE: dict[tuple[str, TripDirection], dict[str, int]] = {
    (RELEVANT_TRAIN_LINE, TripDirection.to_wien): {
        TERNITZ_STATION_ID: 1,
        WIENER_NEUSTADT_STATION_ID: 2,
        BADEN_STATION_ID: 3,
        WIEN_MEIDLING_STATION_ID: 4,
    },
    (RELEVANT_TRAIN_LINE, TripDirection.to_ternitz): {
        WIEN_MEIDLING_STATION_ID: 1,
        BADEN_STATION_ID: 2,
        WIENER_NEUSTADT_STATION_ID: 3,
        TERNITZ_STATION_ID: 4,
    },
    (RELEVANT_SUBWAY_LINE, TripDirection.to_wien): {
        WIEN_MEIDLING_STATION_ID: 1,
        WIEN_WESTBAHNHOF_STATION_ID: 2,
    },
    (RELEVANT_SUBWAY_LINE, TripDirection.to_ternitz): {
        WIEN_WESTBAHNHOF_STATION_ID: 1,
        WIEN_MEIDLING_STATION_ID: 2,
    },
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_dt(s: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime string (with timezone offset or Z) to datetime."""
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _trip_status(item: dict) -> TripStatus:
    if item.get("cancelled"):
        return TripStatus.cancelled
    delay = item.get("delay")
    if delay is not None and delay > 0:
        return TripStatus.delayed
    if item.get("when") is not None:
        return TripStatus.active
    return TripStatus.scheduled


# ---------------------------------------------------------------------------
# Low-level HTTP fetch (returns data + optional error dict)
# ---------------------------------------------------------------------------

def _fetch(
    station_id: str,
    endpoint: str,
    extra_params: dict | None = None,
) -> tuple[list[dict], dict | None]:
    """Fetch departures or arrivals from the ÖBB API.

    Returns:
        ``(items, None)`` on success, ``([], error_info_dict)`` on failure.
    """
    url = f"{API_BASE_URL}/stops/{station_id}/{endpoint}"
    params: dict = {
        "duration": POLL_DURATION_MINUTES,
        "bus": "false",
        "tram": "false",
        "ferry": "false",
    }
    if extra_params:
        params.update(extra_params)

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if isinstance(data, dict) and data.get("isHafasError"):
            return [], {
                "endpoint": endpoint,
                "url": url,
                "http_status_code": None,
                "error_type": "hafas_error",
                "error_message": data.get("message", "HAFAS error"),
                "is_hafas_error": True,
                "response_body": str(data)[:2000],
            }

        items = data if isinstance(data, list) else data.get(endpoint, [])
        return items, None

    except httpx.HTTPStatusError as exc:
        return [], {
            "endpoint": endpoint,
            "url": url,
            "http_status_code": exc.response.status_code,
            "error_type": "http_status_error",
            "error_message": str(exc),
            "is_hafas_error": False,
            "response_body": exc.response.text[:2000],
        }
    except Exception as exc:
        return [], {
            "endpoint": endpoint,
            "url": url,
            "http_status_code": None,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "is_hafas_error": False,
            "response_body": None,
        }


# ---------------------------------------------------------------------------
# Collector — handles one full polling cycle
# ---------------------------------------------------------------------------

class _Collector:
    """Writes one polling cycle's results into the V2 schema."""

    def __init__(self, db: Session, run: CollectionRun) -> None:
        self.db = db
        self.run = run
        self._ensured_dates: set[date] = set()
        self._station_errors: set[str] = set()  # station IDs with API errors this cycle

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_service_date(self, planned_when_str: str | None) -> date:
        """Compute and lazily ensure the service date for a planned time string."""
        planned_dt = _parse_dt(planned_when_str) if planned_when_str else None
        svc_date = compute_service_day(planned_dt or datetime.now(timezone.utc))
        if svc_date not in self._ensured_dates:
            ensure_service_day(self.db, svc_date)
            self._ensured_dates.add(svc_date)
        return svc_date

    def _log_api_error(self, station_id: str, error_info: dict) -> None:
        self.db.add(ApiError(
            collection_run_id=self.run.id,
            station_id=station_id,
            endpoint=error_info["endpoint"],
            url=error_info.get("url"),
            http_status_code=error_info.get("http_status_code"),
            error_type=error_info.get("error_type"),
            error_message=error_info.get("error_message"),
            is_hafas_error=error_info.get("is_hafas_error", False),
            response_body=error_info.get("response_body"),
        ))
        self.run.api_calls_failed += 1
        self._station_errors.add(station_id)

    def _upsert_trip(
        self,
        api_trip_id: str,
        service_date: date,
        line: Line,
        direction: TripDirection,
        item: dict,
    ) -> Trip:
        """Insert-or-update a Trip; increments run counters.

        HAFAS can return different tripId values for the same physical train when
        queried from different stations.  We therefore fall back to matching on
        (train_number, service_date, direction, line_id) before creating a new row.
        """
        trip = (
            self.db.query(Trip)
            .filter_by(api_trip_id=api_trip_id, service_date=service_date)
            .first()
        )
        new_status = _trip_status(item)
        line_obj = item.get("line") or {}
        dest = item.get("direction") or (item.get("destination") or {}).get("name")
        prov = item.get("provenance")
        train_number = line_obj.get("fahrtNr")

        if trip is None and train_number:
            # Fallback: find an existing trip for the same train run
            trip = (
                self.db.query(Trip)
                .filter_by(
                    train_number=train_number,
                    service_date=service_date,
                    direction=direction,
                    line_id=line.id,
                )
                .first()
            )
            if trip:
                trip.status = new_status
                self.run.trips_updated += 1
                return trip

        if trip is None:
            trip = Trip(
                api_trip_id=api_trip_id,
                service_date=service_date,
                line_id=line.id,
                direction=direction,
                train_number=train_number,
                destination_name=dest,
                origin_name=prov,
                status=new_status,
            )
            self.db.add(trip)
            self.db.flush()
            self.run.trips_new += 1
        else:
            trip.status = new_status
            self.run.trips_updated += 1

        return trip

    def _upsert_trip_stop(
        self,
        trip: Trip,
        line_code: str,
        station_id: str,
        endpoint: str,
        item: dict,
    ) -> TripStop:
        """Insert-or-update a TripStop; increments run counters.

        Fields populated depend on the endpoint:
          departures → planned_departure, actual_departure, departure_delay_seconds
          arrivals   → planned_arrival,   actual_arrival,   arrival_delay_seconds
        """
        planned_when = item.get("plannedWhen")
        actual_when = item.get("when")
        delay = item.get("delay")
        actual_platform = item.get("platform")
        planned_platform = item.get("plannedPlatform")
        platform = actual_platform or planned_platform
        platform_changed = bool(
            actual_platform and planned_platform and actual_platform != planned_platform
        )
        cancelled_at_stop = bool(item.get("cancelled"))
        stop_seq = _STOP_SEQUENCE.get((line_code, trip.direction), {}).get(station_id)

        ts = (
            self.db.query(TripStop)
            .filter_by(trip_id=trip.id, station_id=station_id)
            .first()
        )
        is_new = ts is None

        if is_new:
            ts = TripStop(
                trip_id=trip.id,
                station_id=station_id,
                stop_sequence=stop_seq,
                cancelled_at_stop=cancelled_at_stop,
                platform=platform,
                platform_changed=platform_changed,
            )
            self.db.add(ts)
        else:
            ts.cancelled_at_stop = cancelled_at_stop
            ts.platform = platform
            ts.platform_changed = platform_changed
            if stop_seq is not None and ts.stop_sequence is None:
                ts.stop_sequence = stop_seq

        if endpoint == "departures":
            ts.planned_departure = _parse_dt(planned_when)
            ts.actual_departure = _parse_dt(actual_when)
            ts.departure_delay_seconds = delay
        else:  # arrivals
            ts.planned_arrival = _parse_dt(planned_when)
            ts.actual_arrival = _parse_dt(actual_when)
            ts.arrival_delay_seconds = delay

        if is_new:
            self.db.flush()
            self.run.trip_stops_new += 1
        else:
            self.run.trip_stops_updated += 1

        return ts

    def _upsert_remarks(self, trip_stop: TripStop, remarks_raw: list[dict]) -> None:
        """UPSERT remarks for a trip_stop; deduplicates by content."""
        for remark in remarks_raw:
            remark_text = remark.get("text")
            if not remark_text:
                continue
            stmt = (
                pg_insert(Remark)
                .values(
                    entity_type="trip_stop",
                    entity_id=trip_stop.id,
                    remark_type=remark.get("type"),
                    remark_code=remark.get("code"),
                    remark_text=remark_text,
                )
                .on_conflict_do_update(
                    constraint="uq_remark_dedup",
                    set_={"last_seen_at": func.now()},
                )
            )
            self.db.execute(stmt)

    def _process(
        self,
        items: list[dict],
        station_id: str,
        endpoint: str,
        direction: TripDirection,
        line: Line,
    ) -> None:
        """Upsert trips, trip_stops, and remarks for a filtered list of API items."""
        for item in items:
            api_trip_id = item.get("tripId")
            planned_when = item.get("plannedWhen")
            if not api_trip_id or not planned_when:
                continue

            svc_date = self._get_service_date(planned_when)
            trip = self._upsert_trip(api_trip_id, svc_date, line, direction, item)
            ts = self._upsert_trip_stop(trip, line.code, station_id, endpoint, item)
            self._upsert_remarks(ts, item.get("remarks") or [])

    def _call(
        self,
        station_id: str,
        endpoint: str,
        direction: TripDirection,
        line: Line,
        filter_fn,
        extra_params: dict | None = None,
    ) -> None:
        """Fetch + filter + process one station × endpoint × direction combination."""
        self.run.api_calls_made += 1
        items, error_info = _fetch(station_id, endpoint, extra_params)
        if error_info:
            logger.warning(
                "API error %s/%s: %s",
                station_id, endpoint, error_info.get("error_message"),
            )
            self._log_api_error(station_id, error_info)
            return
        self._process([i for i in items if filter_fn(i)], station_id, endpoint, direction, line)

    def _detect_diversions(self, cjx_line: Line) -> None:
        """Mark CJX trips as diverted when they have Ternitz + Meidling stops but no Baden stop.

        Skipped entirely when Baden data could not be collected this cycle — otherwise
        every completed trip would be falsely flagged as diverted.
        Also explicitly resets is_diverted to False when the Baden stop IS present.
        """
        if BADEN_STATION_ID in self._station_errors:
            logger.warning(
                "Skipping diversion detection: Baden (%s) had API errors this cycle",
                BADEN_STATION_ID,
            )
            return

        for svc_date in self._ensured_dates:
            trips = (
                self.db.query(Trip)
                .filter_by(line_id=cjx_line.id, service_date=svc_date)
                .all()
            )
            for trip in trips:
                stop_ids = {
                    row[0]
                    for row in self.db.query(TripStop.station_id)
                    .filter_by(trip_id=trip.id)
                    .all()
                }
                has_ternitz  = TERNITZ_STATION_ID in stop_ids
                has_meidling = WIEN_MEIDLING_STATION_ID in stop_ids
                has_baden    = BADEN_STATION_ID in stop_ids

                if has_ternitz and has_meidling and not has_baden:
                    trip.is_diverted = True
                elif has_ternitz and has_meidling and has_baden:
                    trip.is_diverted = False

    # ------------------------------------------------------------------
    # Main collection
    # ------------------------------------------------------------------

    def collect(self) -> None:
        cjx = get_line_by_code(self.db, RELEVANT_TRAIN_LINE)
        u6 = get_line_by_code(self.db, RELEVANT_SUBWAY_LINE)

        # ── CJX @ Ternitz ──────────────────────────────────────────────
        self._call(TERNITZ_STATION_ID, "departures", TripDirection.to_wien, cjx,
                   lambda i: _is_cjx(i) and _cjx_is_wien_bound(i))
        self._call(TERNITZ_STATION_ID, "arrivals", TripDirection.to_ternitz, cjx,
                   lambda i: _is_cjx(i))

        # ── CJX @ Wiener Neustadt (intermediate, delay tracking) ───────
        self._call(WIENER_NEUSTADT_STATION_ID, "departures", TripDirection.to_wien, cjx,
                   lambda i: _is_cjx(i) and _cjx_is_wien_bound(i))
        self._call(WIENER_NEUSTADT_STATION_ID, "arrivals", TripDirection.to_ternitz, cjx,
                   lambda i: _is_cjx(i) and not _cjx_arrival_is_wien_bound(i))

        # ── CJX @ Baden bei Wien (intermediate, diversion detection) ───
        self._call(BADEN_STATION_ID, "departures", TripDirection.to_wien, cjx,
                   lambda i: _is_cjx(i) and _cjx_is_wien_bound(i))
        self._call(BADEN_STATION_ID, "arrivals", TripDirection.to_ternitz, cjx,
                   lambda i: _is_cjx(i) and not _cjx_arrival_is_wien_bound(i))

        # ── CJX @ Wien Meidling ────────────────────────────────────────
        self._call(WIEN_MEIDLING_STATION_ID, "arrivals", TripDirection.to_wien, cjx,
                   lambda i: _is_cjx(i) and _cjx_arrival_is_wien_bound(i))
        self._call(WIEN_MEIDLING_STATION_ID, "departures", TripDirection.to_ternitz, cjx,
                   lambda i: _is_cjx(i) and not _cjx_is_wien_bound(i))

        # ── U6 @ Wien Meidling (single API call, both directions) ──────
        # Must use _SUBWAY_ONLY params; both directions come from the same response.
        self.run.api_calls_made += 1
        u6_items, u6_err = _fetch(WIEN_MEIDLING_STATION_ID, "departures", _SUBWAY_ONLY)
        if u6_err:
            logger.warning("API error U6 Meidling/departures: %s", u6_err.get("error_message"))
            self._log_api_error(WIEN_MEIDLING_STATION_ID, u6_err)
        else:
            self._process(
                [i for i in u6_items if _is_u6(i) and _U6_TO_WIEN in _dir_str(i)],
                WIEN_MEIDLING_STATION_ID, "departures", TripDirection.to_wien, u6,
            )
            self._process(
                [i for i in u6_items if _is_u6(i) and _U6_TO_TERNITZ in _dir_str(i)],
                WIEN_MEIDLING_STATION_ID, "departures", TripDirection.to_ternitz, u6,
            )

        # ── U6 @ Wien Westbahnhof ──────────────────────────────────────
        self._call(WIEN_WESTBAHNHOF_STATION_ID, "departures", TripDirection.to_ternitz, u6,
                   lambda i: _is_u6(i) and _U6_TO_TERNITZ in _dir_str(i))
        self._call(WIEN_WESTBAHNHOF_STATION_ID, "arrivals", TripDirection.to_wien, u6,
                   lambda i: _is_u6(i))

        self._detect_diversions(cjx)


# ---------------------------------------------------------------------------
# Public entry point (called by the scheduler)
# ---------------------------------------------------------------------------

def collect_data() -> None:
    db = SessionLocal()
    started_at = datetime.now(timezone.utc)

    # Commit the CollectionRun immediately so it persists even if collection fails.
    run = CollectionRun(status=CollectionRunStatus.running, triggered_by="scheduler")
    db.add(run)
    db.commit()
    run_id = run.id

    try:
        _Collector(db, run).collect()

        duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        run.completed_at = datetime.now(timezone.utc)
        run.duration_ms = duration_ms
        run.status = (
            CollectionRunStatus.partial
            if run.api_calls_failed > 0
            else CollectionRunStatus.completed
        )
        db.commit()
        logger.info(
            "Collection complete: +%d/%d trips, +%d/%d trip_stops (%dms)",
            run.trips_new, run.trips_updated,
            run.trip_stops_new, run.trip_stops_updated,
            duration_ms,
        )

    except Exception as exc:
        db.rollback()
        logger.error("Collection failed: %s", exc, exc_info=True)
        try:
            run = db.get(CollectionRun, run_id)
            if run:
                run.status = CollectionRunStatus.failed
                run.error_summary = str(exc)[:500]
                run.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass

    finally:
        db.close()
