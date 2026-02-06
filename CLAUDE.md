# Marine Traffic Encounter Database

## Projectbeschrijving

Real-time AIS scheepspositie collector die encounters (ontmoetingen) tussen schepen detecteert en opslaat voor het trainen van autonome navigatie AI. Data komt binnen via de AISStream.io WebSocket API, encounters worden gedetecteerd wanneer schepen binnen 3 NM van elkaar komen, en alles wordt opgeslagen in SQLite. De bounding box dekt NL/BE/DE/PL/FR kustwateren.

## Tech Stack

- **Python 3.13** met `asyncio` en `websockets`
- **SQLite** met WAL journaling (`PRAGMA journal_mode=WAL, synchronous=NORMAL`)
- **Docker** en Docker Compose
- **numpy**, **pandas**, **torch**, **scikit-learn**, **xgboost** (ML module)
- **gymnasium**, **stable-baselines3** (RL training)
- **matplotlib**, **folium**, **tensorboard** (visualisatie en evaluatie)
- Haversine afstandsberekening, CPA/TCPA vectorberekening, COLREGS classificatie

## Projectstructuur

```
src/
  __init__.py
  config.py                - Configuratie constanten (API key, drempels, bounding box)
  ais_client.py            - WebSocket client naar AISStream.io, yield VesselPosition/VesselStatic
  database.py              - SQLite schema (4 tabellen), CRUD operaties, WAL modus
  encounter_detector.py    - Haversine, CPA/TCPA, COLREGS classificatie, encounter lifecycle
  main.py                  - Entry point: asyncio loop, signal handling, stats logging
  ml/
    __init__.py
    features.py            - Feature engineering: sin/cos encoding, normalisatie, trajectory features
    data_extraction.py     - SQLite -> pandas DataFrames voor ML training (3 extractiefuncties)
    trajectory_model.py    - LSTM Encoder-Decoder voor trajectory prediction (PyTorch)
    train_trajectory.py    - Training script voor trajectory model
    risk_classifier.py     - XGBoost risk classificatie (HIGH/MEDIUM/LOW)
    train_risk.py          - Training script voor risk classifier
    behavioral_cloning.py  - MLP ManeuverPolicy voor behavioral cloning (PyTorch)
    train_bc.py            - Training script voor behavioral cloning
    maritime_env.py        - Gymnasium RL environment voor collision avoidance
    train_rl.py            - PPO training script met curriculum learning
    evaluate.py            - Evaluatie en visualisatie utilities
test_pipeline.py           - End-to-end test (simulatie zonder API key)
Dockerfile                 - Python 3.13-slim, non-root user, healthcheck
docker-compose.yml         - Single service (ais-collector), named volume (db-data)
Makefile                   - Docker workflow commando's
docs/
  plan.md                  - Oorspronkelijk implementatieplan (afgerond)
  research.md              - AIS data source research
  docker-setup.md          - Gedetailleerde Docker documentatie
```

## Bouwen en Draaien

### Docker (aanbevolen)

```bash
cp .env.example .env       # Vul AISSTREAM_API_KEY in
make up                    # Bouwt en start container
make logs                  # Bekijk live logs
make db-stats              # Database statistieken
make db-backup             # Backup naar backups/
make down                  # Stop
```

### Lokaal

```bash
pip install -r requirements.txt
export AISSTREAM_API_KEY=jouw_key
python -m src.main
```

### Testen

```bash
python test_pipeline.py    # End-to-end test (geen API key nodig, geen pytest)
```

> **Let op:** Tests gebruiken handmatige assertions, niet pytest. Run via `python test_pipeline.py`.

## Belangrijke Constanten

Bron: `src/config.py`

| Constante | Waarde | Betekenis |
|-----------|--------|-----------|
| `ENCOUNTER_DISTANCE_NM` | 3.0 | Start encounter als schepen < 3 NM van elkaar |
| `ENCOUNTER_END_DISTANCE_NM` | 5.0 | Eind encounter als schepen > 5 NM uit elkaar |
| `MIN_SPEED_KN` | 0.5 | Negeer stilliggende schepen (< 0.5 knopen) |
| `VESSEL_TIMEOUT_S` | 300 | Verwijder schip na 5 min zonder positie-update |
| `STATS_INTERVAL_S` | 30 | Log statistieken elke 30 seconden |
| `BOUNDING_BOXES` | `[[43.0, -5.0], [55.5, 19.0]]` | NL/BE/DE/PL/FR kustwateren |

Bron: `src/encounter_detector.py`

| `NM_TO_METERS` | 1852.0 | Conversie nautische mijl naar meter |
| `KNOTS_TO_MS` | 0.514444 | Conversie knopen naar m/s |
| `EARTH_RADIUS_M` | 6_371_000.0 | Aardstraal voor haversine |

## Database Schema

Bron: `src/database.py` (SCHEMA string)

**vessels** — Scheepsinformatie
- `mmsi` TEXT PK, `name`, `ship_type` INTEGER, `length` REAL, `width` REAL, `updated_at`

**positions** — Tijdreeks van posities
- `id` PK, `mmsi` FK, `timestamp`, `lat`, `lon`, `sog`, `cog`, `heading`
- Index: `idx_positions_mmsi_ts(mmsi, timestamp)`

**encounters** — Gedetecteerde ontmoetingen
- `id` PK, `vessel_a_mmsi` FK, `vessel_b_mmsi` FK, `start_time`, `end_time`, `min_distance_m`, `encounter_type`, `cpa_m`, `tcpa_s`

**encounter_positions** — Posities tijdens encounters
- `id` PK, `encounter_id` FK, `mmsi` FK, `timestamp`, `lat`, `lon`, `sog`, `cog`, `heading`
- Index: `idx_enc_pos_encounter(encounter_id)`

## Architectuur en Dataflow

```
AISStream.io WebSocket API
        |
        v
  ais_client.py           -> async generator, yield VesselPosition / VesselStatic
        |                     reconnect bij disconnect (5s backoff)
        v
  main.py                 -> dispatcht naar:
    |                         VesselStatic  -> db.upsert_vessel()
    |                         VesselPosition -> detector.update()
    v
  encounter_detector.py   -> in-memory vessel tracking
    |                         haversine() afstandscheck
    |                         compute_cpa_tcpa() vectormethode
    |                         classify_encounter() COLREGS
    v
  database.py             -> SQLite (encounters.db)
    |
    v
  ml/data_extraction.py   -> Extract training data (3 functies)
  ml/features.py          -> Feature engineering
  ml/trajectory_model.py  -> LSTM trajectory prediction
  ml/risk_classifier.py   -> XGBoost risk classificatie
  ml/behavioral_cloning.py -> MLP behavioral cloning
  ml/maritime_env.py   -> Gymnasium RL environment (PPO)
  ml/train_rl.py       -> PPO training met curriculum learning
  ml/evaluate.py       -> Visualisatie en evaluatie
```

## Conventies

- **Taal**: Nederlands voor documentatie, comments, en commit messages. Engels voor code identifiers (functienamen, variabelen, class names)
- **Data classes**: Python `dataclasses` (niet Pydantic) voor `VesselPosition`, `VesselStatic`, `ActiveEncounter`
- **Async patterns**: `asyncio` met async generators. De AIS client is een `AsyncIterator` die automatisch reconnect
- **Database**: Elke operatie opent en sluit een eigen connectie via `get_conn()` context manager. Geen connection pooling
- **Encounter key**: Altijd gesorteerd MMSI paar: `(min(a, b), max(a, b))` — zie `_encounter_key()`
- **Logging**: Standaard Python `logging`, format: `"%(asctime)s [%(levelname)s] %(name)s: %(message)s"`
- **ML features**: COG en heading worden sin/cos gecodeerd. Posities worden genormaliseerd naar meters relatief t.o.v. centroid
- **Imports**: `from src.module import ...` pattern (package-style)

## COLREGS Classificatie

Bron: `src/encounter_detector.py:classify_encounter()`

| Type | Koersverschil | Beschrijving |
|------|---------------|--------------|
| head-on | >= 170° | Schepen varen bijna recht op elkaar af |
| overtaking | <= 67.5° | Schip nadert van achteren |
| crossing | 67.5° - 170° | Overige situaties |

## Veelvoorkomende Ontwikkeltaken

- **Nieuw AIS message type**: Pas `MESSAGE_TYPES` in `config.py` aan en voeg parser toe in `ais_client.py`
- **Encounter drempels aanpassen**: Wijzig constanten in `src/config.py`
- **Database schema wijzigen**: Pas `SCHEMA` string in `database.py` aan (geen migratie framework — handmatig)
- **Nieuwe ML features**: Voeg functies toe aan `src/ml/features.py`
- **Database bekijken**: `sqlite3 encounters.db "SELECT COUNT(*) FROM encounters;"`
- **Database backup**: `make db-backup`

## Environment Variabelen

| Variabele | Verplicht | Default | Beschrijving |
|-----------|-----------|---------|-------------|
| `AISSTREAM_API_KEY` | Ja | — | API key van https://aisstream.io |
| `DB_PATH` | Nee | `encounters.db` (lokaal) / `/data/encounters.db` (Docker) | Pad naar SQLite database |

## ML Module

Vier modellen voor verschillende doeleinden:

**1. Trajectory Prediction** (`trajectory_model.py`)
- LSTM Encoder-Decoder (Seq2Seq)
- Input: 10 features (delta_x, delta_y, sog, cog_sin, cog_cos, heading_sin, heading_cos, acceleration, rate_of_turn, delta_t)
- Output: 4 features (delta_x, delta_y, sog, cog)
- Training: `python -m src.ml.train_trajectory`

**2. Risk Classification** (`risk_classifier.py`)
- XGBoost classifier met 20 features
- Labels: HIGH (< 500m), MEDIUM (500-1000m), LOW (> 1000m) — gebaseerd op `min_distance_m`
- Training: `python -m src.ml.train_risk`

**3. Behavioral Cloning** (`behavioral_cloning.py`)
- MLP ManeuverPolicy
- Input: 19 features (eigen schip + ander schip relatief + situatie)
- Output: 2 acties (turn_rate deg/s, accel_rate knots/s)
- Training: `python -m src.ml.train_bc`

**4. Reinforcement Learning** (`maritime_env.py` + `train_rl.py`)
- Gymnasium environment, PPO via Stable-Baselines3
- 17D observation space, 9 discrete acties (roer + snelheid combinaties)
- COLREGS-aware reward function met collision penalties
- Curriculum learning: head-on → crossing → alle types
- TensorBoard logging voor training metrics
- Training: `python -m src.ml.train_rl`

**Evaluatie & Visualisatie** (`evaluate.py`)
- `plot_trajectory_predictions()` — LSTM voorspellingen vs werkelijkheid
- `plot_encounter_map()` — Interactieve Folium kaart van encounters
- `data_summary()` — Database statistieken

Data extractie voor alle modellen via `src/ml/data_extraction.py`:
- `extract_trajectories()` -> trajectory segments
- `extract_encounters()` -> encounter features met risk labels
- `extract_encounter_pairs()` -> state-action paren voor BC/RL
