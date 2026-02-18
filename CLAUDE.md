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
  business_analyst.py      - Business analyse utility (KPI's, datakwaliteit, ML-readiness)
  ml/
    __init__.py
    features.py            - Feature engineering: sin/cos encoding, normalisatie, trajectory features
    data_extraction.py     - SQLite -> pandas DataFrames voor ML training (3 extractiefuncties)
    data_export.py         - Data export naar CSV/Parquet met filtering en kwaliteitsmetrics
    trajectory_model.py    - LSTM Encoder-Decoder voor trajectory prediction (PyTorch)
    train_trajectory.py    - Training script voor trajectory model
    risk_classifier.py     - XGBoost risk classificatie (HIGH/MEDIUM/LOW)
    train_risk.py          - Training script voor risk classifier
    behavioral_cloning.py  - MLP ManeuverPolicy voor behavioral cloning (PyTorch)
    train_bc.py            - Training script voor behavioral cloning
    maritime_env.py        - Gymnasium RL environment voor collision avoidance
    train_rl.py            - PPO training script met curriculum learning
    evaluate.py            - Evaluatie en visualisatie utilities
scripts/
  export_ml_data.py        - CLI tool voor data export met filters en format opties
test_pipeline.py           - End-to-end test (simulatie zonder API key)
tests/
  test_ais_client.py       - Tests voor AIS client
  test_data_export.py      - Tests voor data export functionaliteit
  test_encounter_detector.py - Tests voor haversine, CPA/TCPA, COLREGS
pytest.ini                   - Pytest configuratie
Dockerfile                 - Python 3.13-slim, non-root user, healthcheck
docker-compose.yml         - Single service (ais-collector), named volume (db-data)
Makefile                   - Docker workflow commando's
.claude/
  skills/
    business-analyst/      - /business-analyst slash command (Claude agent)
    pm-orchestrator/       - /pm slash command (PM Orchestrator agent)
    evaluator/             - /evaluator slash command (Evaluator agent)
.github/
  pull_request_template.md - PR template voor gestructureerde PR beschrijvingen
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
# Unit tests (pytest)
pytest                      # Run alle unit tests
pytest tests/test_encounter_detector.py  # Run specifieke test module
pytest -v                   # Verbose output

# End-to-end test
python test_pipeline.py     # E2E test (geen API key nodig)
```

> **Unit tests:** De core functies (haversine, CPA/TCPA, COLREGS) hebben pytest unit tests in `tests/`
> **E2E test:** `test_pipeline.py` simuleert de volledige pipeline zonder API key

## Belangrijke Constanten

Bron: `src/config.py`

| Constante | Waarde | Betekenis |
|-----------|--------|-----------|
| `ENCOUNTER_DISTANCE_NM` | 3.0 | Start encounter als schepen < 3 NM van elkaar |
| `ENCOUNTER_END_DISTANCE_NM` | 5.0 | Eind encounter als schepen > 5 NM uit elkaar |
| `MIN_SPEED_KN` | 0.5 | Negeer stilliggende schepen (< 0.5 knopen) |
| `VESSEL_TIMEOUT_S` | 300 | Verwijder schip na 5 min zonder positie-update |
| `STATS_INTERVAL_S` | 30 | Log statistieken elke 30 seconden |
| `BOUNDING_BOXES` | `[[[43.0, -5.0], [55.5, 19.0]]]` | NL/BE/DE/PL/FR kustwateren |

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
  ml/data_export.py       -> Export naar CSV/Parquet met filtering
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
| overtaking | <= 15° | Schip nadert van achteren |
| crossing | 15° - 170° | Overige situaties |

## Veelvoorkomende Ontwikkeltaken

- **Nieuw AIS message type**: Pas `MESSAGE_TYPES` in `config.py` aan en voeg parser toe in `ais_client.py`
- **Encounter drempels aanpassen**: Wijzig constanten in `src/config.py`
- **Database schema wijzigen**: Pas `SCHEMA` string in `database.py` aan (geen migratie framework — handmatig)
- **Nieuwe ML features**: Voeg functies toe aan `src/ml/features.py`
- **Data export voor ML training**: `python scripts/export_ml_data.py <type> <output> [filters]` — zie ML Module sectie
- **Database bekijken**: `sqlite3 encounters.db "SELECT COUNT(*) FROM encounters;"`
- **Database backup**: `make db-backup`
- **Business analyse**: `/business-analyst` slash command of `python -m src.business_analyst`
- **Feature implementeren (end-to-end)**: `/pm <beschrijving>` — PM Orchestrator plant, delegeert en levert op

## Business Analyst Agent

Claude Code slash command: `/business-analyst`

Analyseert het project, de database en de infrastructuur. Logt bevindingen in `business-analyst.md` en werkt `TODO.md` bij met nieuwe backlog items en re-ranking.

**Wat de agent doet:**
1. Database analyse (volumes, encounters, kwaliteit, temporeel)
2. Code & infra inventarisatie (git, .env, dependencies, ML modellen)
3. ML-readiness beoordeling per model
4. Bevindingen schrijven naar `business-analyst.md`
5. `TODO.md` updaten met nieuwe items en re-ranken

**Python utility:** `src/business_analyst.py`
```bash
python -m src.business_analyst              # Volledig rapport
python -m src.business_analyst kpis         # KPI dashboard
python -m src.business_analyst quality      # Datakwaliteit
python -m src.business_analyst ml-readiness # ML gereedheid
python -m src.business_analyst --json       # JSON output
```

## PM Orchestrator Agent

Claude Code slash command: `/pm`

Ontvangt een issue of feature request, maakt een plan, delegeert naar subagents, bewaakt kwaliteit en levert een merge-klare branch (of PR) op. Werkt altijd in een git worktree, nooit op main.

**Wat de agent doet:**
1. Issue analyseren, scope bepalen, plan maken
2. Git worktree opzetten (werkt nooit op main)
3. Subagents inzetten op basis van capability gaps:
   - BA Agent: requirements analyse (wanneer scope vaag is)
   - Engineer Agent: code implementatie
   - QA Agent: tests schrijven en uitvoeren
   - Security Agent: beveiligingsscan
   - Docs Agent: documentatie bijwerken
   - DevOps Agent: build/CI/deploy controleren
4. Evaluatie gate doorlopen (tests, security, docs, acceptatiecriteria)
5. PR aanmaken via `gh pr create` (of branch opleveren als geen remote)
6. Worktree opruimen

**Gebruik:**
```bash
/pm Implementeer een data retentie beleid dat oude posities automatisch opschoont
/pm Fix #12: dubbele encounter detectie bij gelijktijdige positie-updates
```

**Branch conventies:** `feat/<beschrijving>`, `fix/<beschrijving>`, `chore/<beschrijving>`

**Commit conventies:** `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`

**Worktree locatie:** `../wt/<branch-naam>/` (relatief t.o.v. project root)

## Evaluator Agent

Claude Code slash command: `/evaluator`

Evalueert de logs van andere agents (BA, PM), controleert consistentie, verifieert claims tegen de werkelijke projectstaat, en werkt de backlog bij met nieuwe acties.

**Wat de agent doet:**
1. Logs verzamelen: `business-analyst.md`, `PM.md`, `TODO.md`, `collector.log`
2. Actuele staat verifiëren (database, git, bestanden)
3. Cross-referentie: zijn BA aanbevelingen opgepakt? Zijn PM items afgevinkt? Kloppen de KPI's nog?
4. Kwaliteitsbeoordeling per agent (actualiteit, volledigheid, actiegerichtheid)
5. Projectvoortgang en risicoprofiel beoordelen
6. Evaluatierapport schrijven naar `evaluator.md`
7. `TODO.md` bijwerken met nieuwe acties (label: `[EVAL]`)

**Gebruik:**
```bash
/evaluator
```

**Output bestanden:**
- `evaluator.md` — Append-only evaluatielog met beoordelingen en bevindingen
- `TODO.md` — Bijgewerkt met nieuwe acties en herprioritering

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

**Data Export** (`data_export.py` + `scripts/export_ml_data.py`)
- Export encounters naar CSV/Parquet formaten voor ML training
- Filtering: encounter type, datum range, data kwaliteit
- Kwaliteitsmetrieken: completeness score (0.0-1.0), positie counts, duration, CPA aanwezigheid
- CLI tool: `python scripts/export_ml_data.py <type> <output> [filters]`
- Export types:
  - `trajectories` — Trajectory segments voor LSTM training
  - `encounters` — Encounter features voor risk classificatie
  - `pairs` — State-action paren voor BC/RL
  - `summary` — Dataset samenvatting met kwaliteitsmetrics
- Voorbeelden:
  ```bash
  # Export high-quality encounters naar Parquet
  python scripts/export_ml_data.py encounters output/data.parquet \
      --format parquet --quality 0.9 --min-positions 20

  # Export crossing encounters uit Q1 2026
  python scripts/export_ml_data.py pairs output/crossing.csv \
      --type crossing --start 2026-01-01 --end 2026-03-31

  # Dataset summary met kwaliteitsmetrics
  python scripts/export_ml_data.py summary output/summary.csv \
      --quality 0.7 --min-duration 120
  ```
