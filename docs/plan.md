# Plan: Ship Encounter Database voor Autonome Navigatie AI

## Context
We bouwen een systeem dat real-time AIS scheepsposities streamt via AISStream.io (gratis WebSocket API), encounters detecteert tussen schepen die elkaar passeren, en deze opslaat in een database. Het doel is een trainingsdataset voor een AI-model dat leert hoe schepen veilig kunnen passeren.

## Architectuur Overzicht

```
AISStream.io WebSocket
        │
        ▼
  [AIS Collector]  ──► real-time positie updates
        │
        ▼
  [Encounter Detector]  ──► detecteert schepen < 3 NM van elkaar
        │
        ▼
  [SQLite Database]  ──► vessels, positions, encounters
```

## Tech Stack
- **Python 3.13** met `asyncio` + `websockets`
- **SQLite** (prototype, geen setup nodig - later PostgreSQL/TimescaleDB)
- **Haversine** formule voor afstandsberekening
- **COLREGS-classificatie** voor encounter types

## Bestanden aan te maken

### 1. `requirements.txt`
```
websockets
torch>=2.0
numpy>=1.24
pandas>=2.0
scikit-learn>=1.3
xgboost>=2.0
gymnasium>=0.29
stable-baselines3>=2.0
matplotlib>=3.7
folium>=0.14
tensorboard>=2.14
```

### 2. `src/config.py` - Configuratie
- API key (uit environment variable `AISSTREAM_API_KEY`)
- Bounding box (default: NL/BE/DE/PL/FR kustwateren)
- Encounter drempels:
  - `ENCOUNTER_DISTANCE_NM = 3.0` (nautische mijlen)
  - `ENCOUNTER_END_DISTANCE_NM = 5.0` (encounter eindigt)
  - Min snelheid filter: `MIN_SPEED_KN = 0.5` (negeer stilliggende schepen)

### 3. `src/database.py` - Database setup + operaties
- SQLite met 4 tabellen:
  - **vessels**: `mmsi` (PK), `name`, `ship_type`, `length`, `width`, `updated_at`
  - **positions**: `id`, `mmsi` (FK), `timestamp`, `lat`, `lon`, `sog`, `cog`, `heading`
  - **encounters**: `id`, `vessel_a_mmsi`, `vessel_b_mmsi`, `start_time`, `end_time`, `min_distance_m`, `encounter_type`, `cpa_m`, `tcpa_s`
  - **encounter_positions**: `id`, `encounter_id` (FK), `mmsi`, `timestamp`, `lat`, `lon`, `sog`, `cog`, `heading`
- Functies: `init_db()`, `upsert_vessel()`, `insert_position()`, `create_encounter()`, `update_encounter()`, `insert_encounter_position()`
- Index op `positions(mmsi, timestamp)` en `encounter_positions(encounter_id)`

### 4. `src/ais_client.py` - WebSocket connectie naar AISStream.io
- Async WebSocket client
- Subscription: filter op `PositionReport` en `ShipStaticData`
- Default bounding box: NL/BE/DE/PL/FR kustwateren `[[43.0, -5.0], [55.5, 19.0]]`
- Reconnect logica bij disconnect
- Parsed `PositionReport` → `VesselPosition` dataclass
- Parsed `ShipStaticData` → vessel upsert

### 5. `src/encounter_detector.py` - Encounter detectie logica
- Houdt in-memory dict bij van laatste posities per MMSI
- Bij elke nieuwe positie: check afstand tot alle andere actieve schepen
- **Haversine** afstandsberekening
- **CPA/TCPA berekening** via vector-methode:
  ```
  rel_pos = pos_b - pos_a
  rel_vel = vel_b - vel_a
  tcpa = -(rel_pos · rel_vel) / (rel_vel · rel_vel)
  cpa = |rel_pos + tcpa * rel_vel|
  ```
- **COLREGS classificatie** op basis van relatieve koers:
  - Head-on: koersverschil 170°-190° (bijna tegengesteld)
  - Overtaking: schip nadert van > 112.5° achterlijker
  - Crossing: overige situaties
- Encounter lifecycle:
  1. **Start**: afstand < 3 NM, beide schepen varen (SOG > 0.5 kn)
  2. **Track**: blijf posities opslaan voor beide schepen
  3. **End**: afstand > 5 NM of schip verdwijnt (>5 min geen update)

### 6. `src/main.py` - Entry point
- Init database
- Start AIS WebSocket stream
- Pipe posities door encounter detector
- Log statistieken (actieve schepen, lopende encounters, totaal encounters)
- Graceful shutdown met SIGINT/SIGTERM

## Implementatie Volgorde

1. **`src/config.py`** - Configuratie constanten
2. **`requirements.txt`** - Dependencies
3. **`src/database.py`** - Database schema + CRUD operaties
4. **`src/ais_client.py`** - WebSocket client met reconnect
5. **`src/encounter_detector.py`** - Encounter detectie + CPA/TCPA + COLREGS classificatie
6. **`src/main.py`** - Alles samenbrengen
7. **`.env.example`** - Voorbeeld env file met `AISSTREAM_API_KEY=`

## Uitbreidingen na Core (afgerond)

### Fase 2: Docker
- `Dockerfile` — Python 3.13-slim, non-root user, healthcheck
- `docker-compose.yml` — Single service, named volume, log rotation
- `Makefile` — Docker workflow commando's (up, down, logs, backup, etc.)

### Fase 3: ML Pipeline
- `src/ml/features.py` — Feature engineering (sin/cos encoding, normalisatie)
- `src/ml/data_extraction.py` — SQLite → pandas DataFrames (3 extractiefuncties)
- `src/ml/trajectory_model.py` — LSTM Encoder-Decoder voor trajectory prediction
- `src/ml/risk_classifier.py` — XGBoost risk classificatie (HIGH/MEDIUM/LOW)
- `src/ml/behavioral_cloning.py` — MLP ManeuverPolicy
- `src/ml/train_trajectory.py`, `train_risk.py`, `train_bc.py` — Training scripts

### Fase 4: RL & Evaluatie
- `src/ml/maritime_env.py` — Gymnasium environment voor collision avoidance (17D obs, 9 acties)
- `src/ml/train_rl.py` — PPO training met curriculum learning en TensorBoard
- `src/ml/evaluate.py` — Visualisatie (trajectory plots, Folium encounter maps, data summary)

### Fase 5: Testing
- `test_pipeline.py` — End-to-end simulatie test (haversine, CPA/TCPA, COLREGS, pipeline)

## Verificatie
1. `pip install -r requirements.txt`
2. `export AISSTREAM_API_KEY=<jouw_key>` (key ophalen op https://aisstream.io)
3. `python -m src.main`
4. Verwacht output: log van binnenkomende posities en gedetecteerde encounters
5. Check database: `sqlite3 encounters.db "SELECT COUNT(*) FROM positions; SELECT COUNT(*) FROM encounters;"`
6. Test: `python test_pipeline.py`
7. Docker: `make up && make logs`
