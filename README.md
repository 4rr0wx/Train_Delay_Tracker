# Train Delay Tracker (Pendler Verspätungsstatistik)

Ein intelligentes Monitoring-System zur Verfolgung und Analyse von Zugverspätungen auf der Pendlerstrecke **Ternitz ↔ Wien Westbahnhof**.

## 🚂 Projektiebersicht

Der **Train Delay Tracker** ist eine automatisierte Lösung, die kontinuierlich Verspätungsdaten von Zügen und U-Bahn-Zügen auf einer spezifischen österreichischen Pendlerstrecke erfasst und analysiert. Das System sammelt Daten von der ÖBB-API, speichert sie in einer PostgreSQL-Datenbank und stellt umfangreiche Statistiken und Analysen über eine REST-API und ein Web-Dashboard bereit.

### Überwachte Strecke

Die Anwendung verfolgt folgende Fahrtbeine:

- **Zur Wien**: Ternitz --[CJX]--> Wien Meidling --[U6]--> Wien Westbahnhof
- **Zu Ternitz**: Wien Westbahnhof (U6) --[U6]--> Wien Meidling --[CJX]--> Ternitz

**Beobachtete Züge:**
- CJX-Züge (Regionalzüge der ÖBB)
- U6 U-Bahn-Züge (Wiener Linien)

## 🏗️ Architektur

Das Projekt folgt einer **Client-Server-Architektur** mit Docker-Containerisierung:

### Backend (Python/FastAPI)
- **FastAPI-Webserver** mit REST-API-Endpoints
- **APScheduler** für periodische Datenerfassung (alle 5 Minuten)
- **SQLAlchemy ORM** für Datenbankoperationen
- **HTTPX-HTTP-Client** für API-Kommunikation mit ÖBB

### Persistierung
- **PostgreSQL 16** für relationale Datenbank
- Strukturierte Tabellen für Stationen und Zugbeobachtungen
- Automatisches Upsert von Beobachtungen

### Frontend
- Statische HTML/CSS/JavaScript-Anwendung
- Direkt von FastAPI serviert

## 🔧 Technologie-Stack

| Komponente | Technologie |
|-----------|------------|
| Backend-Framework | FastAPI 0.115.0 |
| ASGI-Server | Uvicorn 0.30.0 |
| ORM | SQLAlchemy 2.0.35 |
| Datenbankdriver | psycopg2-binary 2.9.9 |
| HTTP-Client | httpx 0.27.0 |
| Task-Scheduler | APScheduler 3.10.4 |
| Containerisierung | Docker & Docker Compose |
| Datenbank | PostgreSQL 16 |

## 📊 API-Endpoints

### Gesundheitsstatus
- `GET /api/health` - Prüft die Anwendungsgesundheit

### Abfahrten & Ankünfte
- `GET /api/departures?direction=[to_wien|to_ternitz]&limit=20&product=[regional|subway]`
  - Ruft die jüngsten Abfahrts-/Ankunftsdaten ab

### Verspätungsstatistiken
- `GET /api/stats` - Zusammenfassende Verspätungsstatistiken
  - Parameter: `direction`, `days` (1-365), `product`
  - Rückgabe: Durchschnitt, Median, Cancellationen, Pünktlichkeitsquoten

- `GET /api/delays/hourly` - Durchschnittliche Verspätungen pro Stunde
  - Zeigt, zu welchen Tageszeiten die meisten Verspätungen auftreten

- `GET /api/delays/daily` - Durchschnittliche Verspätungen pro Wochentag
  - Identifiziert Wochentage mit schlechterer Pünktlichkeit

- `GET /api/delays/trend` - Trendanalyse der Verspätungen
  - Zeigt zeitliche Trends über mehrere Tage

- `GET /api/delays/distribution` - Häufigkeitsverteilung der Verspätungen
  - Kategorisiert Verspätungen in Buckets (pünktlich, 1-2 Min, 2-5 Min, etc.)

## 📦 Installation & Setup

### Voraussetzungen
- Docker & Docker Compose
- Oder: Python 3.10+, PostgreSQL 16

### Mit Docker Compose

1. **Repository klonen:**
   ```bash
   git clone https://github.com/4rr0wx/Train_Delay_Tracker.git
   cd Train_Delay_Tracker
   ```

2. **Umgebungsvariablen setzen** (optional):
   ```bash
   export DB_PASSWORD=your_secure_password
   ```

3. **Container starten:**
   ```bash
   docker-compose up -d
   ```

4. **Anwendung öffnen:**
   - API: http://localhost:8080/api
   - Dashboard: http://localhost:8080

### Manuelles Setup (Entwicklung)

1. **Python-Umgebung erstellen:**
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # oder venv\Scripts\activate auf Windows
   ```

2. **Abhängigkeiten installieren:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Datenbankverbindung konfigurieren:**
   ```bash
   export DATABASE_URL="postgresql://tracker:tracker_secret@localhost:5432/train_tracker"
   export API_BASE_URL="https://oebb.macistry.com/api"
   ```

4. **PostgreSQL-Datenbank einrichten:**
   ```sql
   CREATE DATABASE train_tracker;
   CREATE USER tracker WITH PASSWORD 'tracker_secret';
   GRANT ALL PRIVILEGES ON DATABASE train_tracker TO tracker;
   ```

5. **Anwendung starten:**
   ```bash
   python main.py
   ```

## 🗄️ Datenbankschema

### Tabelle: `stations`
| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | VARCHAR(20) | Eindeutige Stations-ID (ÖBB) |
| `name` | VARCHAR(200) | Stationsname |

### Tabelle: `train_observations`
| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | INTEGER | Eindeutige Observations-ID |
| `trip_id` | VARCHAR(255) | Zugnummer |
| `station_id` | VARCHAR(20) | Stations-ID |
| `direction` | VARCHAR(10) | Fahrtrichtung (to_wien/to_ternitz) |
| `line_name` | VARCHAR(100) | Name der Zuglinie |
| `line_product` | VARCHAR(50) | Zugtyp (regional, subway, etc.) |
| `destination` | VARCHAR(200) | Zielstation |
| `planned_time` | TIMESTAMP | Geplante Ankunfts-/Abfahrtszeit |
| `actual_time` | TIMESTAMP | Tatsächliche Ankunfts-/Abfahrtszeit |
| `delay_seconds` | INTEGER | Verspätung in Sekunden |
| `cancelled` | BOOLEAN | Wurde die Fahrt storniert |
| `platform` | VARCHAR(20) | Bahnsteig |
| `remarks` | JSON | Zusätzliche Hinweise/Anmerkungen |
| `first_seen_at` | TIMESTAMP | Zeitstempel der Erstsichtung |
| `last_updated_at` | TIMESTAMP | Zeitstempel der letzten Aktualisierung |

## 🔄 Datenerfassungsprozess

Die Anwendung erfasst automatisch Zugdaten über folgende Schritte:

1. **Periodischer Abruf** (alle 5 Minuten)
   - APScheduler triggert `collect_data()`

2. **API-Abfragen** an ÖBB-API (`https://oebb.macistry.com/api`)
   - Abfahrten von Ternitz (CJX Wien-gebunden)
   - Ankünfte in Ternitz (CJX von Wien)
   - Abfahrten von Wien Meidling (U6)
   - Abfahrten/Ankünfte von Wien Westbahnhof (U6)

3. **Filterung & Normalisierung**
   - Nur relevante Züge (CJX, U6) werden behalten
   - Fahrtrichtung wird ermittelt
   - Daten werden in ein standardisiertes Format parsiert

4. **Datenbank-Upsert**
   - Neue Beobachtungen werden eingefügt
   - Bestehende Einträge (nach trip_id + planned_time) werden aktualisiert
   - Timestamps werden bei Änderungen aktualisiert

## 📈 Beispiele für API-Nutzung

### Verspätungsstatistiken für die letzten 30 Tage (Wien-gebunden)
```bash
curl "http://localhost:8080/api/stats?direction=to_wien&days=30"
```

**Antwort:**
```json
{
  "direction": "to_wien",
  "period_days": 30,
  "total_trains": 450,
  "cancelled_count": 2,
  "cancellation_rate_pct": 0.4,
  "delay_stats": {
    "average_minutes": 3.2,
    "median_minutes": 2.1,
    "max_minutes": 45,
    "on_time_pct": 65.3,
    "under_5min_pct": 88.2
  }
}
```

### Aktuelle Abfahrten
```bash
curl "http://localhost:8080/api/departures?direction=to_wien&limit=10"
```

### Stundliche Verspätungstrends
```bash
curl "http://localhost:8080/api/delays/hourly?direction=to_wien&days=7"
```

## 🚀 Deployment

Die Anwendung ist optimiert für Docker-Deployment:

```bash
# Production-Build
docker-compose up -d

# Logs anschauen
docker-compose logs -f app

# Container stoppen
docker-compose down
```

Die Anwendung läuft auf `http://localhost:8080` und die API ist unter `http://localhost:8080/api` verfügbar.

## 📝 Umgebungsvariablen

| Variable | Beschreibung | Standard |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL-Verbindungsstring | postgresql://... |
| `API_BASE_URL` | ÖBB-API-Basisadresse | https://oebb.macistry.com/api |
| `TERNITZ_STATION_ID` | ÖBB-Station-ID für Ternitz | 1131839 |
| `WIEN_MEIDLING_STATION_ID` | ÖBB-Station-ID für Wien Meidling | 1191201 |
| `WIEN_WESTBAHNHOF_STATION_ID` | ÖBB-Station-ID für Wien Westbahnhof | 915006 |
| `POLL_INTERVAL_MINUTES` | Abfrageintervall in Minuten | 5 |
| `DB_PASSWORD` | Passwort für PostgreSQL | tracker_secret |

## 🤝 Beiträge

Beiträge sind willkommen! Bitte beachten Sie:
1. Fork das Repository
2. Erstellen Sie einen Feature-Branch (`git checkout -b feature/improvement`)
3. Committen Sie Ihre Änderungen
4. Push zu dem Branch
5. Öffnen Sie einen Pull Request

## 📄 Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert - siehe `LICENSE`-Datei für Details.

## 📧 Kontakt & Support

- **GitHub Issues**: Für Fehlerberichte und Feature-Requests
- **E-Mail**: Kontaktieren Sie den Projektmaintainer

## 🔍 Weitere Ressourcen

- [FastAPI-Dokumentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy ORM-Dokumentation](https://docs.sqlalchemy.org/)
- [ÖBB Hafas-API](https://oebb.macistry.com/)
- [Docker-Dokumentation](https://docs.docker.com/)
- [PostgreSQL-Dokumentation](https://www.postgresql.org/docs/)

---

**Last Updated**: 2025-02-15
**Version**: 1.0.0
