# Docker Setup — Marine Traffic

## Snel starten

```bash
# 1. Configuratie
cp .env.example .env
nano .env  # Vul je AISSTREAM_API_KEY in

# 2. Bouwen en starten
make up

# 3. Logs bekijken
make logs
```

## Beschikbare commando's

| Commando         | Beschrijving                                    |
|------------------|-------------------------------------------------|
| `make help`      | Toon alle beschikbare commando's                |
| `make up`        | Start alle services (bouwt image automatisch)   |
| `make down`      | Stop alle services                              |
| `make logs`      | Bekijk live logs                                |
| `make restart`   | Herstart alle services                          |
| `make status`    | Toon status van alle services                   |
| `make shell`     | Open een shell in de collector container         |
| `make db-stats`  | Toon database statistieken                      |
| `make db-backup` | Maak een backup naar `backups/`                 |
| `make clean`     | Verwijder alles inclusief data (met bevestiging)|

## Architectuur

```
AISStream.io (WebSocket)
        │
        ▼
┌──────────────────────────┐
│  ais-collector container │
│  python -m src.main      │
│                          │
│  ┌─ ais_client.py        │
│  ├─ encounter_detector   │
│  └─ database.py ─────────┼──▶ /data/encounters.db
└──────────────────────────┘         │
                                     ▼
                              Docker volume
                              (db-data)
```

## Nieuwe service toevoegen

Voeg een service toe aan `docker-compose.yml` onder `services:`. Alle services delen automatisch het `marine-traffic-net` netwerk.

Voorbeeld:

```yaml
services:
  ais-collector:
    # ... bestaande config ...

  # Nieuwe service:
  postgres:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_DB: marine_traffic
      POSTGRES_USER: marine
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pg-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U marine"]
      interval: 5s

volumes:
  db-data:
  pg-data:  # nieuw volume toevoegen
```

## Environment variabelen

| Variabele           | Verplicht | Default                  | Beschrijving              |
|---------------------|-----------|--------------------------|---------------------------|
| `AISSTREAM_API_KEY` | Ja        | -                        | API key van aisstream.io  |
| `DB_PATH`           | Nee       | `/data/encounters.db`    | Pad naar SQLite database  |

## Data & backups

De database wordt opgeslagen op een Docker named volume (`db-data`). Data blijft behouden bij container restarts en rebuilds.

```bash
# Backup maken
make db-backup

# Statistieken bekijken
make db-stats
```

## Lokaal draaien (zonder Docker)

```bash
pip install -r requirements.txt
export AISSTREAM_API_KEY=jouw_key
python -m src.main
```
