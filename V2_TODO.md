# V2 TODO — Train Delay Tracker

Datenmodell und Datenbankschema sind fertig (Branch: `claude/rebuild-data-model-v2-iz3fm`).
Diese Liste dokumentiert was noch umzuschreiben ist, damit die App vollständig auf V2 läuft.

---

## 1. Utilities (Voraussetzung für alles andere)

### `backend/utils.py` — neu erstellen
- [ ] `compute_service_day(planned_utc: datetime) -> date`
  - `Europe/Vienna`-Timezone, 04:00-Uhr-Grenze
  - Mitternachts-Züge korrekt dem Vortag zuordnen
- [ ] `ensure_service_day(db, service_date: date) -> ServiceDay`
  - Insert-or-get für `service_days`-Table
  - Berechnet `is_weekday`, `day_of_week`, `is_austrian_holiday`, `holiday_name`
  - Benötigt `pip install holidays` (requirements.txt ergänzen)
- [ ] `get_line_by_code(db, code: str) -> Line`
  - Cached lookup für CJX/U6 line_id (wird im Collector sehr oft aufgerufen)

---

## 2. Collector (`backend/collector.py`) — vollständig umschreiben

Größtes einzelnes Stück Arbeit. Schreibt aktuell in `train_observations`. Muss auf V2 umgestellt werden.

### CollectionRun tracking
- [ ] Beim Start jedes Polling-Zyklus: `CollectionRun` anlegen (status=`running`)
- [ ] Am Ende: `completed_at`, `duration_ms`, Status auf `completed`/`partial`/`failed` setzen
- [ ] Counters aktualisieren: `trips_new`, `trips_updated`, `trip_stops_new`, `trip_stops_updated`

### API-Fehler in DB loggen
- [ ] Bei jedem fehlgeschlagenen API-Call: `ApiError`-Row anlegen
  - `collection_run_id`, `station_id`, `endpoint`, `url`, `http_status_code`, `error_type`, `error_message`
  - `response_body`: ersten 2000 Zeichen truncaten

### Service Day
- [ ] Vor dem ersten Upsert: `ensure_service_day(db, compute_service_day(planned_utc))` aufrufen

### Trip-Upsert (ersetzt `train_observations`-UPSERT)
- [ ] Richtungserkennung bleibt gleich (Keyword-Matching), aber **Ergebnis landet in `trips.direction`** (einmal pro Trip, nicht pro Observation)
- [ ] Lookup: `SELECT id FROM trips WHERE api_trip_id = :tid AND service_date = :date`
  - Wenn nicht vorhanden: INSERT mit `line_id`, `direction`, `service_date`, `train_number`, `destination_name`, `origin_name`
  - Wenn vorhanden: UPDATE `last_updated_at`, `status`, ggf. `is_diverted`

### TripStop-Upsert (ersetzt `train_observations`-UPSERT)
- [ ] Pro Beobachtung (Station × Trip): UPSERT in `trip_stops`
  - Key: `(trip_id, station_id)`
  - Herkunftsstation (Ternitz/Westbahnhof) → nur `planned_departure` + `departure_delay_seconds`
  - Zielstation (Meidling/Ternitz) → nur `planned_arrival` + `arrival_delay_seconds`
  - Zwischenstationen → beide Richtungen wenn API liefert
  - `platform`, `platform_changed`, `cancelled_at_stop` setzen
- [ ] `first_seen_at` nur beim ersten INSERT setzen

### Remarks normalisieren
- [ ] ÖBB-API liefert `remarks` als Array von `{type, text}` → in `remarks`-Table schreiben
  - `entity_type = 'trip_stop'`, `entity_id = trip_stop.id`
  - UPSERT mit Dedup-Constraint `(entity_type, entity_id, remark_type, remark_code, remark_text)`
  - `last_seen_at` auf NOW() updaten bei Konflikt

### Diversion-Erkennung
- [ ] Nach Abschluss eines Polling-Zyklus: CJX-Trips prüfen
  - Hat Trip Stops bei Ternitz + Meidling aber KEIN Stop bei Baden → `trips.is_diverted = TRUE`
  - Muss nur für Trips des aktuellen Service-Days laufen

---

## 3. API-Routen — alle auf V2-Schema umschreiben

### `backend/routes/departures.py`
- [ ] Query umschreiben: `train_observations` → `trip_stops JOIN trips JOIN lines`
- [ ] Filter: `direction`, `product` (jetzt via `lines.product_type`), `status` (via `trips.status`)
- [ ] Response-Shape prüfen: bleibt kompatibel oder Breaking Change?

### `backend/routes/stats.py`
- [ ] `GET /api/stats` — Aggregation über `trip_stops` + `trips`
  - Delay-Stats: `departure_delay_seconds` für Abfahrtsstation, `arrival_delay_seconds` für Ankunftsstation
  - Cancelled: `trips.status = 'cancelled'` ODER `trip_stops.cancelled_at_stop = TRUE`
- [ ] `GET /api/delays/hourly` — GROUP BY `EXTRACT(HOUR FROM planned_departure AT TIME ZONE 'Europe/Vienna')`
- [ ] `GET /api/delays/daily` — GROUP BY `service_days.day_of_week`
- [ ] `GET /api/delays/trend` — GROUP BY `trips.service_date`
- [ ] `GET /api/delays/distribution` — Buckets auf `departure_delay_seconds`
- [ ] `GET /api/delays/by-station` — GROUP BY `trip_stops.station_id` mit Station JOIN

### `backend/routes/commute.py`
- [ ] `GET /api/commute/overview` — Slots aus `commute_slots`-Table lesen (nicht mehr aus config.py)
  - Matche Trips über `trip_stops.planned_departure::time ≈ commute_slots.anchor_time_local`
  - Toleranz aus `commute_slots.time_tolerance_minutes`
- [ ] `GET /api/commute/trips` — Flexible Verbindungssuche über `connections`-Table
- [ ] `GET /api/commute/earliest-date` — `MIN(service_date)` aus `service_days`

### `backend/routes/journeys.py`
- [ ] `GET /api/journeys` — Delay-Buildup via `trip_stops` geordnet nach `stop_sequence`
  - Viel einfacher als V1-CTE: `SELECT * FROM trip_stops WHERE trip_id = :id ORDER BY stop_sequence`
- [ ] `GET /api/journeys/stats` — Aggregation über `trip_stops` für gefilterte Trips
- [ ] `GET /api/diversions` — `SELECT * FROM trips WHERE is_diverted = TRUE`
  - `is_diverted` ist jetzt explizites Flag, kein CTE mehr nötig

### `backend/routes/health.py`
- [ ] Letzten `collection_runs`-Eintrag mitgeben: `last_collection_at`, `last_collection_status`

---

## 4. Config (`backend/config.py`) aufräumen

- [ ] `MORNING_JOURNEYS` dict entfernen — Daten jetzt in `commute_slots`-Table
- [ ] `EVENING_JOURNEY` dict entfernen — ditto
- [ ] `MORNING_TRAINS`, `EVENING_TRAIN`, `COMMUTE_TIME_TOLERANCE_MINUTES` entfernen
- [ ] `RELEVANT_TRAIN_LINE`, `RELEVANT_SUBWAY_LINE` können bleiben (noch für Collector nützlich)
- [ ] Station-ID-Konstanten bleiben (für Collector/Seed nützlich)

---

## 5. Datenmigration V1 → V2

- [ ] Alembic Migration `0002_migrate_v1_data.py` schreiben
  - Nur relevant wenn existierende Daten aus `train_observations` übernommen werden sollen
  - Schritte:
    1. `service_days` für alle historischen Dates aus `train_observations.planned_time` anlegen
    2. `trips` aus distinct `(trip_id, service_date, direction, line_product)` ableiten
    3. `trip_stops` aus jeder `train_observations`-Zeile ableiten
    4. `remarks` aus JSONB-Blobs in einzelne Rows normalisieren
    5. `is_diverted` auf Trips setzen (bestehende Logik aus `journeys.py`)
  - Kann als einmalig laufendes Script statt Alembic-Migration gemacht werden

---

## 6. Dependencies (`backend/requirements.txt`)

- [ ] `holidays>=0.46` hinzufügen (für österreichische Feiertage in `ensure_service_day`)

---

## 7. Dockerfile

- [ ] `CMD` prüfen: Alembic läuft aktuell via `main.py` lifespan (subprocess)
  - Alternative: direkt im Dockerfile `CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app ..."]`
  - Vorteil: Migration schlägt fehl bevor der Server startet → klares Fehler-Signal
  - Entscheidung treffen und umsetzen

---

## 8. Frontend (`backend/static/`)

- [ ] API-Response-Shapes nach Routenumbau prüfen
- [ ] Neue Daten anzeigen die V2 bietet:
  - [ ] Verbindungszuverlässigkeit (connection_made %)
  - [ ] Diversion-Anzeige (is_diverted Flag)
  - [ ] Collection-Health (wann war letzter erfolgreicher Run)
  - [ ] Remarks/Warnungen pro Zug

---

## Reihenfolge (empfohlen)

```
1. utils.py (compute_service_day, ensure_service_day)
2. collector.py umschreiben
3. config.py aufräumen
4. API-Routen (departures → stats → commute → journeys)
5. health.py erweitern
6. Frontend
7. Datenmigration (optional, wenn Altdaten gebraucht werden)
```

---

## Was NICHT mehr geändert werden muss

- `backend/models.py` ✅ fertig
- `backend/database.py` ✅ fertig
- `backend/seed.py` ✅ fertig
- `backend/alembic/` ✅ fertig
- `db/init.sql` ✅ fertig
- `backend/main.py` ✅ fertig
- `backend/requirements.txt` (alembic) ✅ fertig
