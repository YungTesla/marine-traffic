# Marine Traffic Project - Status & TODO

## Huidige Status

**Code: 100% compleet** — Alle modules uit het oorspronkelijke plan (docs/plan.md) zijn geimplementeerd:
- Core pipeline (AIS client, encounter detector, database, main loop)
- Docker setup (Dockerfile, docker-compose, Makefile)
- ML pipeline (4 modellen: LSTM trajectory, XGBoost risk, MLP behavioral cloning, PPO RL)
- Evaluatie & visualisatie utilities
- End-to-end test (test_pipeline.py)

**Operationeel: collector GESTOPT sinds 22:10** (eerste run 2026-02-06 20:34–22:10):
- Database bevat 8.018 schepen, 78.939 posities, 15.111 encounters (8.778 voltooid)
- `.env` aangemaakt met API key
- Backup aanwezig (5.8 MB verouderd, 69 MB pre-cleanup backup beschikbaar)
- Geen ML modellen getraind (data voldoende voor 3/4 modellen)
- Geen TensorBoard logs of training output

**Infrastructuur: basis aanwezig, niet productie-klaar**:
- Git repository geinitialiseerd (1 commit, geen remote)
- Geen CI/CD pipeline
- Geen monitoring/alerting
- Geen data retentie beleid

---

## TODO - Geprioriteerd

### Fase 1: Fundament (moet eerst)

- [x] **Git repository initialiseren** — `git init`, initial commit (b40dbad). Remote toevoegen staat nog open
- [x] **Dependencies fixen** — `joblib` toegevoegd aan requirements.txt, versies gepind
- [x] **.env aanmaken** — API key geconfigureerd, collector draait
- [x] **Dubbel collector proces stoppen** — OPGELOST: geen dubbele processen meer actief (PID 15639 en 15719 zijn gestopt)
- [ ] **Git remote toevoegen** — Push naar GitHub/GitLab. Code is alleen lokaal, bij schijfuitval is alles verloren
- [ ] **Uncommitted bestanden committen** — 8+ bestanden untracked/modified op main (.claude/, .github/, PM.md, business-analyst.md, collector.log, src/business_analyst.py). [EVAL]

### Fase 2: Data verzamelen

- [x] **Collector starten** — Collector draait lokaal via `python -m src.main` (niet Docker)
- [x] **Encounter completion monitoren** — OPGELOST via fix/encounter-completion branch (8.778 voltooide encounters). Merge naar main nog pending
- [ ] **Branch fix/encounter-completion mergen** — PM Orchestrator heeft bugfix branch opgeleverd, wacht op merge naar main
- [ ] **Nieuwe backup maken** — Laatste backup (5.8 MB) is verouderd. Database is nu 69 MB met 8.778 voltooide encounters
- [ ] **KRITIEK: Encounter rate valideren** — ~168 encounters/min lijkt extreem hoog. Na merge herbeoordelen: mogelijk is een deel opgelost door de completion bugfix
- [ ] **Database monitoring** — regelmatig `make db-stats` checken, eerste voltooide encounters valideren
- [ ] **Migreren naar Docker** — Gebruik `make up` voor productie-draaien met restart policy en resource limits
- [x] **Eerste backup maken** — Backup aanwezig in backups/ (5.8 MB, 2026-02-06)
- [ ] **Branch fix/duplicate-collector-prevention ophelderen** — Branch bevat 4 commits (+135/-403 lines), niet gedocumenteerd in PM.md. Mergen, verwijderen of documenteren? [EVAL]
- [ ] **Collector herstarten** — Gestopt sinds 22:10. Trajectory model vereist langere positiereeksen (20+ per vessel). [EVAL]

### Fase 3: ML modellen trainen (zodra voldoende data)

- [ ] **Risk classifier trainen** — `python -m src.ml.train_risk` — NU MOGELIJK: 8.778 voltooide encounters (>> 50 minimum)
- [ ] **Behavioral cloning trainen** — `python -m src.ml.train_bc` — NU MOGELIJK: 8.778 encounters (>> 50 minimum)
- [ ] **RL agent trainen** — `python -m src.ml.train_rl` — NU MOGELIJK: 8.778 encounters (>> 200 aanbevolen)
- [ ] **Trajectory model readiness meten** — SQL query: `SELECT COUNT(*) FROM (SELECT mmsi FROM positions GROUP BY mmsi HAVING COUNT(*) >= 20)`. Status onbekend. [EVAL]
- [ ] **Trajectory model trainen** — `python -m src.ml.train_trajectory` — vereist 100+ vessels met 20+ posities (readiness te meten)
- [ ] **Evaluatie draaien** — `python -m src.ml.evaluate` voor visualisaties

### Fase 4: Productie-hardening

- [ ] **KRITIEK: Data retentie** — Automatisch oude posities opschonen. Database gegroeid naar 69 MB in ~1.5 uur. Zonder cleanup wordt dit snel onbeheersbaar
- [ ] **Process lock mechanisme** — Voorkom dat meerdere collector instanties tegelijk draaien (PID file of file lock). Dubbel proces issue is opgelost, maar dit kan opnieuw gebeuren
- [ ] **Graceful shutdown testen** — Fix/encounter-completion branch voegt close_all_encounters() toe bij shutdown. Testen of dit werkt in productie
- [ ] **Tests uitbreiden** — ML modules zijn volledig ongetest (~1865 regels). Pytest opzetten, tests schrijven voor features.py, data_extraction.py, maritime_env.py
- [ ] **CI/CD pipeline** — GitHub Actions voor tests, Docker build, linting
- [ ] **Input validatie** — AIS berichten valideren (lat/lon bereik, onmogelijke snelheden, positiesprongen)
- [ ] **Reconnect logica verbeteren** — Exponential backoff (nu vast 5s), max retries, auth failure detectie
- [ ] **Resource limits** — CPU/memory limits toevoegen aan docker-compose.yml

### Fase 5: Nice to have

- [ ] **Query API** — FastAPI endpoint voor encounters/vessels opvragen (nu alleen via sqlite3 CLI)
- [ ] **Monitoring** — Prometheus metrics, structured logging (JSON), alerting
- [ ] **Data export** — CSV/JSON/Parquet export voor analyse buiten SQLite
- [ ] **Database migratie strategie** — Alembic of versioned schema voor toekomstige wijzigingen
- [ ] **Pre-commit hooks** — Black, ruff, mypy voor code kwaliteit
- [ ] **Backup automatisering** — Scheduled backups ipv handmatig

---

## Data Volumes (actueel, 2026-02-06)

| Metric | Laatste meting (22:10) | Groeisnelheid |
|--------|---------|-------------------|
| Schepen | 8.018 | — |
| Posities | 78.939 (~1.5 uur) | ~879/min |
| Encounters (voltooid) | 8.778 | ~98/min |
| Encounters (open) | 6.333 | — |
| Encounters (totaal) | 15.111 | ~168/min |
| DB grootte | 69 MB (~1.5 uur) | ~0.77 MB/min |
| Min. encounters voor ML | — | 500-1000 (BEREIKT voor risk/BC/RL) |
