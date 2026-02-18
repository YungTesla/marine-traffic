# Marine Traffic Encounter Database

Real-time AIS scheepspositie collector die ontmoetingen tussen schepen detecteert en opslaat voor het trainen van autonome navigatie AI.

## Features

- **Real-time AIS streaming** via AISStream.io WebSocket API
- **Encounter detectie** wanneer schepen binnen 3 NM van elkaar komen
- **CPA/TCPA berekening** via vectormethode (Closest Point of Approach / Time to CPA)
- **COLREGS classificatie** (head-on, crossing, overtaking)
- **SQLite database** met scheepsposities en encounter trajectories
- **ML training pipeline** met vier modellen:
  - LSTM trajectory prediction
  - XGBoost risk classificatie
  - MLP behavioral cloning
  - PPO reinforcement learning voor collision avoidance
- **Data export** naar CSV/Parquet met filtering op encounter type, datum range en data kwaliteit
- **Evaluatie & visualisatie** (trajectory plots, interactieve encounter maps)

## Snel Starten

### Docker (aanbevolen)

```bash
cp .env.example .env       # Vul je AISSTREAM_API_KEY in
make up                    # Bouwt en start container
make logs                  # Bekijk live logs
```

### Lokaal

```bash
pip install -r requirements.txt
export AISSTREAM_API_KEY=jouw_key    # Haal key op via https://aisstream.io
python -m src.main
```

### Testen

```bash
pytest                     # Unit tests
python test_pipeline.py    # End-to-end test (geen API key nodig)
```

## Architectuur

```
AISStream.io WebSocket API
        │
        ▼
  ┌─────────────────────┐
  │   ais_client.py     │  Async WebSocket client, auto-reconnect
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │   main.py           │  Entry point, dispatcht berichten
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │ encounter_detector  │  Haversine, CPA/TCPA, COLREGS
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │   database.py       │  SQLite (encounters.db)
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │   ml/               │  Feature engineering + 4 modellen + evaluatie
  └─────────────────────┘
```

## Projectstructuur

```
src/
  config.py                - Configuratie constanten
  ais_client.py            - WebSocket client naar AISStream.io
  database.py              - SQLite schema en CRUD operaties
  encounter_detector.py    - Encounter detectie logica
  main.py                  - Entry point
  ml/
    features.py            - Feature engineering
    data_extraction.py     - Data extractie voor ML training
    data_export.py         - Data export naar CSV/Parquet met filtering
    trajectory_model.py    - LSTM trajectory prediction
    risk_classifier.py     - XGBoost risk classificatie
    behavioral_cloning.py  - MLP behavioral cloning
    maritime_env.py        - Gymnasium RL environment
    train_*.py             - Training scripts (trajectory, risk, bc, rl)
    evaluate.py            - Evaluatie en visualisatie
scripts/
  export_ml_data.py        - CLI tool voor data export
test_pipeline.py           - End-to-end test
```

## ML Data Export

Export encounter data naar CSV of Parquet formaten voor ML training:

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

# Alle opties bekijken
python scripts/export_ml_data.py --help
```

**Export types:**
- `trajectories` — Trajectory segments voor LSTM training
- `encounters` — Encounter features voor risk classificatie
- `pairs` — State-action paren voor behavioral cloning/RL
- `summary` — Dataset samenvatting met kwaliteitsmetrics

## Make Commando's

| Commando | Beschrijving |
|----------|-------------|
| `make up` | Start alle services |
| `make down` | Stop alle services |
| `make logs` | Bekijk live logs |
| `make restart` | Herstart services |
| `make db-stats` | Toon database statistieken |
| `make db-backup` | Maak backup naar `backups/` |
| `make shell` | Open shell in container |
| `make clean` | Verwijder alles (met bevestiging) |

## Documentatie

- [Docker setup](docs/docker-setup.md) — Gedetailleerde Docker documentatie
- [Implementatieplan](docs/plan.md) — Oorspronkelijk ontwerp en architectuur
- [Research](docs/research.md) — AIS data source research

## Environment Variabelen

| Variabele | Verplicht | Beschrijving |
|-----------|-----------|-------------|
| `AISSTREAM_API_KEY` | Ja | API key van [aisstream.io](https://aisstream.io) |
| `DB_PATH` | Nee | Pad naar SQLite database (default: `encounters.db`) |
