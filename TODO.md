# Marine Traffic Project - Status & TODO

## Huidige Status

**Code: 100% compleet** — Alle modules uit het oorspronkelijke plan (docs/plan.md) zijn geimplementeerd:
- Core pipeline (AIS client, encounter detector, database, main loop)
- Docker setup (Dockerfile, docker-compose, Makefile)
- ML pipeline (4 modellen: LSTM trajectory, XGBoost risk, MLP behavioral cloning, PPO RL)
- Evaluatie & visualisatie utilities
- End-to-end test (test_pipeline.py)

**Operationeel: 0%** — Het project is nog nooit gedraaid:
- Database is leeg (0 rijen in alle tabellen)
- Geen `.env` file aangemaakt (geen API key geconfigureerd)
- Geen ML modellen getraind
- Geen TensorBoard logs of training output
- Geen backups

**Infrastructuur: basis aanwezig, niet productie-klaar**:
- Geen git repository geinitialiseerd
- Geen CI/CD pipeline
- Geen monitoring/alerting
- Geen data retentie beleid

---

## TODO - Geprioriteerd

### Fase 1: Fundament (moet eerst)

- [ ] **Git repository initialiseren** — `git init`, initial commit, remote toevoegen
- [ ] **Dependencies fixen** — `joblib` ontbreekt in requirements.txt (wordt wel gebruikt in risk_classifier.py). Versies pinnen voor reproduceerbaarheid
- [ ] **.env aanmaken** — API key van aisstream.io invullen, data collectie starten

### Fase 2: Data verzamelen

- [ ] **Collector starten** — `make up` of `python -m src.main` — data laten binnenlopen
- [ ] **Database monitoring** — regelmatig `make db-stats` checken, eerste encounters valideren
- [ ] **Eerste backup maken** — `make db-backup` na eerste dag data

### Fase 3: ML modellen trainen (zodra voldoende data)

- [ ] **Trajectory model trainen** — `python -m src.ml.train_trajectory`
- [ ] **Risk classifier trainen** — `python -m src.ml.train_risk`
- [ ] **Behavioral cloning trainen** — `python -m src.ml.train_bc`
- [ ] **RL agent trainen** — `python -m src.ml.train_rl`
- [ ] **Evaluatie draaien** — `python -m src.ml.evaluate` voor visualisaties

### Fase 4: Productie-hardening

- [ ] **Tests uitbreiden** — ML modules zijn volledig ongetest (~1865 regels). Pytest opzetten, tests schrijven voor features.py, data_extraction.py, maritime_env.py
- [ ] **CI/CD pipeline** — GitHub Actions voor tests, Docker build, linting
- [ ] **Input validatie** — AIS berichten valideren (lat/lon bereik, onmogelijke snelheden, positiesprongen)
- [ ] **Reconnect logica verbeteren** — Exponential backoff (nu vast 5s), max retries, auth failure detectie
- [ ] **Resource limits** — CPU/memory limits toevoegen aan docker-compose.yml
- [ ] **Data retentie** — Automatisch oude posities opschonen (DB groeit oneindig)

### Fase 5: Nice to have

- [ ] **Query API** — FastAPI endpoint voor encounters/vessels opvragen (nu alleen via sqlite3 CLI)
- [ ] **Monitoring** — Prometheus metrics, structured logging (JSON), alerting
- [ ] **Data export** — CSV/JSON/Parquet export voor analyse buiten SQLite
- [ ] **Database migratie strategie** — Alembic of versioned schema voor toekomstige wijzigingen
- [ ] **Pre-commit hooks** — Black, ruff, mypy voor code kwaliteit
- [ ] **Backup automatisering** — Scheduled backups ipv handmatig

---

## Geschatte data volumes (ter referentie)

| Metric | Schatting |
|--------|-----------|
| Posities/dag | ~24.000 |
| Encounters/dag | ~10-100 |
| DB groei/jaar | ~10-50 GB (zonder cleanup) |
| Min. encounters voor ML | ~500-1000 |
