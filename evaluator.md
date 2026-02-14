# Evaluator Log — Marine Traffic

## Evaluatie — 2026-02-06

### Samenvatting

Het project heeft een sterke eerste operationele run achter de rug: 8.778 voltooide encounters in ~1.5 uur, ML-readiness bereikt voor 3 van 4 modellen. De belangrijkste blokkeerder is het ontbreken van een merge naar main — twee branches wachten op integratie. Daarnaast bevat de documentatie interne inconsistenties en is er een ongedocumenteerde branch (`fix/duplicate-collector-prevention`).

### Skill Log Review

#### Business Analyst

| Criterium | Score |
|-----------|-------|
| Actualiteit | ACTUEEL |
| Volledigheid | ONVOLLEDIG |
| Actiegerichtheid | GOED |
| Prioritering | CORRECT |

**Opmerkingen:**
- KPI's zijn van 22:10, collector is gestopt sinds 22:10 — cijfers zijn definitief en dus actueel.
- **Onvolledig punt 1:** Encounter type verdeling is WEL beschikbaar in de database (crossing: 4.442, overtaking: 3.270, head-on: 1.066) maar het BA rapport zegt "na merge kan dit opnieuw berekend worden". Dit is onjuist — de data is al beschikbaar.
- **Onvolledig punt 2:** Trajectory LSTM readiness wordt geschat op "~0-50 vessels met 20+ posities (schatting, te meten)" — maar de BA heeft deze meting niet uitgevoerd. Een simpele SQL query had dit beantwoord.
- **Onvolledig punt 3:** De `fix/duplicate-collector-prevention` branch (4 commits) wordt nergens in het BA rapport genoemd.
- Aanbevelingen zijn concreet en prioriteiten kloppen.
- BA vermeldt correct dat database groei ~1.1 GB/dag is (KRITIEK).

#### PM Orchestrator

| Criterium | Score |
|-----------|-------|
| Oplevering | VOLLEDIG |
| Evaluatie gates | PASS |
| Scope discipline | GOED |
| Backlog sync | ACHTER |

**Opmerkingen:**
- De PM run voor `fix/encounter-completion` is goed gedocumenteerd en opgeleverd (3 root causes, 5 tests, PASS evaluatie).
- **Backlog sync probleem:** Er bestaat een branch `fix/duplicate-collector-prevention` (4 commits: process lock mechanisme) die NIET gedocumenteerd is in PM.md. Deze branch heeft significante deletions (+135, -403 lines) — het lijkt erop dat de feature is toegevoegd en deels teruggedraaid. Status is onduidelijk.
- PM.md bevat slechts 1 entry. Als de duplicate-prevention branch ook door de PM is gemaakt, ontbreekt deze entry.
- Merge naar main is nog steeds niet uitgevoerd — de PM levert branches op maar faciliteert geen merge.

### Backlog Gezondheid

| Criterium | Score |
|-----------|-------|
| Compleetheid | GATEN |
| Prioritering | CORRECT |
| Stale items | AANWEZIG |
| Fase-indeling | CORRECT |
| Balans | GOED |

**Details:**
- **Gaten:** De branch `fix/duplicate-collector-prevention` is niet opgenomen in de backlog als item (TODO regel 59 noemt "Process lock mechanisme" als nieuw item, maar de bestaande branch wordt niet gerefereerd).
- **Stale data:** TODO.md regel 13 vermeldt "4.884 schepen, 9.826 posities, 7.763 encounters" — dit zijn verouderde cijfers. De Data Volumes sectie (regel 80-88) heeft wél actuele data. Interne inconsistentie.
- **Stale items:** "Dubbel collector proces stoppen" (regel 34) is afgevinkt als OPGELOST, maar dit was een symptoombestrijding (handmatig processen killen). De structurele oplossing (process lock, regel 59) staat nog open.
- **Ontbrekend:** Collector is gestopt sinds 22:10 — nergens in de backlog staat het herstarten als actie.
- **Ontbrekend:** 8 uncommitted bestanden op main (inclusief .claude/, .github/, PM.md, business-analyst.md, collector.log, src/business_analyst.py) — dit moet gecommit worden.
- **Balans is goed:** Mix van fundament (fase 1-2), ML (fase 3), hardening (fase 4) en nice-to-have (fase 5).

### Projectvoortgang

| Aspect | Status | Trend |
|--------|--------|-------|
| Data collectie | GESTOPT | Stagnerend (collector uit sinds 22:10) |
| ML readiness | BIJNA | Verbeterend (3/4 modellen gereed, training niet gestart) |
| Infrastructuur | MINIMAAL | Stagnerend (geen remote, geen CI/CD, geen Docker) |
| Code kwaliteit | VOLDOENDE | Verbeterend (5 nieuwe tests via PM, ML modules nog ongetest) |
| Risicoprofiel | MEDIUM | Stabiel (geen remote = dataverlies risico) |

### Inconsistenties & Verouderde Informatie

1. **TODO.md interne inconsistentie** — Header (regel 13) toont oude cijfers (4.884 schepen, 9.826 posities, 7.763 encounters), Data Volumes sectie (regel 80-88) toont actuele cijfers (8.018 schepen, 78.939 posities, 8.778 encounters). Bron: TODO.md.
2. **BA rapport claimt encounter type data onbeschikbaar** — "Na merge van fix/encounter-completion branch kan type-analyse gedaan worden" (BA regel 49), maar de database bevat reeds encounter type data: crossing 4.442, overtaking 3.270, head-on 1.066. Bron: business-analyst.md vs database.
3. **Ongedocumenteerde branch** — `fix/duplicate-collector-prevention` (4 commits, +135/-403 lines) bestaat maar is niet gedocumenteerd in PM.md en slechts indirect gerefereerd in TODO.md. Status en inhoud onduidelijk. Bron: git branch -a.
4. **BA vermeldt 7.763 encounter_positions** — "alle 7.763 encounters hebben bijbehorende posities" (BA regel 56). Dit getal komt overeen met het oude encounter totaal, niet het actuele (15.111). De encounter_positions zijn waarschijnlijk niet bijgewerkt sinds de completion bugfix. Bron: business-analyst.md.
5. **Collector status niet erkend** — De collector is gestopt sinds 22:10, maar noch het BA rapport noch de backlog vermelden dit als actueel probleem of actie. Bron: verificatie-check (geen recente posities).

### Nieuwe Acties (toegevoegd aan backlog)

1. **[HOOG]** Uncommitted bestanden committen — 8 bestanden op main zijn untracked/modified (.claude/, .github/, PM.md, business-analyst.md, collector.log, src/business_analyst.py, .gitignore, CLAUDE.md, TODO.md). [EVAL]
2. **[HOOG]** Branch fix/duplicate-collector-prevention status ophelderen — Branch bevat 4 commits met veel deletions. Mergen, verwijderen, of documenteren? [EVAL]
3. **[MEDIUM]** TODO.md header data actualiseren — Regel 13 bevat verouderde cijfers, inconsistent met Data Volumes sectie. [EVAL]
4. **[MEDIUM]** Collector herstarten — Gestopt sinds 22:10, geen actieve data collectie. Trajectory model vereist langere reeksen. [EVAL]
5. **[MEDIUM]** Trajectory model readiness meten — SQL query uitvoeren: `SELECT COUNT(*) FROM (SELECT mmsi FROM positions GROUP BY mmsi HAVING COUNT(*) >= 20)`. [EVAL]
6. **[LAAG]** BA rapport encounter type data aanvullen — Data is beschikbaar maar niet opgenomen in het rapport. [EVAL]

### Aanbevelingen voor Agents

- **BA:** Voer bij volgende run de trajectory readiness meting daadwerkelijk uit (SQL query). Neem encounter type verdeling op in het rapport — data is al beschikbaar. Erken de huidige collector status (draaiend/gestopt).
- **PM:** Prioriteer merge van `fix/encounter-completion` naar main. Documenteer de `fix/duplicate-collector-prevention` branch in PM.md (of verwijder als niet meer relevant). Overweeg uncommitted bestanden als eerste taak.
- **Collector:** Herstart de collector voor trajectory data opbouw. Overweeg Docker mode voor stabiliteit en auto-restart.
