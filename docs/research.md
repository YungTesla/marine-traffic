# Marine Traffic AI Training Database - Research

## Project Doel
Een database bouwen met GPS-posities van schepen die elkaar passeren, om een AI-model te trainen voor autonome scheepsnavigatie zonder botsingen.

---

## Beschikbare AIS Data Bronnen

### Gratis Opties

#### 1. AISStream.io (Aanbevolen)
- **Website**: https://aisstream.io/
- **Type**: WebSocket API (real-time streaming)
- **Endpoint**: `wss://stream.aisstream.io/v0/stream`
- **Kosten**: Gratis
- **Authenticatie**: API key vereist (account aanmaken)
- **Data format**: JSON
- **Beschikbare velden**:
  - MMSI (vessel identificatie)
  - Latitude/Longitude
  - Speed
  - Course/Heading
  - Ship properties
  - Voyage details
- **SDK's beschikbaar**: Python, JavaScript, Golang, Java
- **Dekking**: Wereldwijd netwerk van AIS-stations
- **Voordeel**: Real-time streaming, geen kosten

#### 2. AISHub
- **Website**: https://www.aishub.net/
- **Type**: Data sharing model
- **Kosten**: Gratis (in ruil voor je eigen AIS data delen)
- **Data format**: JSON, XML, CSV
- **Vereiste**: Je moet zelf AIS data aanleveren om toegang te krijgen
- **Tool**: AIS Dispatcher app beschikbaar (Windows/Linux)

#### 3. OpenAIS
- **Website**: https://open-ais.org/
- **Type**: Open source tools
- **Doel**: Tools voor analyse van bestaande AIS datasets
- **Geschikt voor**: Exploratie en verwerking van al beschikbare data

### Commerciele Opties

#### MarineTraffic / Kpler
- **Website**: https://www.kpler.com/product/maritime/data-services
- **API's beschikbaar**:
  - AIS real-time tracking (13.000+ receivers)
  - Real-time Events (port calls, bunkering, ship-to-ship)
  - Predictive Events (ML-powered ETA's)
  - Past Events (historische data vanaf 2010)
  - Ship Database (eigenschappen, eigendom, foto's)
  - Custom Data Extracts
- **Kosten**: Niet openbaar, contact vereist
- **Documentatie**: https://servicedocs.marinetraffic.com/

#### VesselFinder
- **Website**: https://api.vesselfinder.com/docs/
- **Type**: Credit-based systeem
- **Data**: Real-time AIS, port calls, vessel particulars
- **Format**: JSON, XML

#### MyShipTracking
- **Website**: https://api.myshiptracking.com/
- **Type**: Trial beschikbaar
- **Data**: Live en historische terrestrial data

#### Datalastic
- **Website**: https://datalastic.com/
- **Type**: Commercieel
- **SDK's**: Python, Ruby, PHP, Java, Go, .Net

---

## Technische Overwegingen

### Wat is een "Ship Encounter"?
Te definieren parameters:
- **Afstandsdrempel**: Bijv. < 1 nautische mijl (1852 meter)
- **CPA (Closest Point of Approach)**: Minimale verwachte afstand
- **TCPA (Time to CPA)**: Tijd tot dichtste nadering
- **Approach angle**: Hoek van nadering (crossing, overtaking, head-on)

### Benodigde Data per Positie
```
- mmsi: Unieke scheeps-ID
- timestamp: Tijdstip van meting
- latitude: Breedtegraad
- longitude: Lengtegraad
- speed_over_ground: Snelheid (knopen)
- course_over_ground: Koers (graden)
- heading: Richting boeg (graden)
- ship_type: Type schip
- ship_length: Lengte schip
- ship_width: Breedte schip
```

### Database Schema Voorstel

```sql
-- Schepen
CREATE TABLE vessels (
    mmsi VARCHAR(9) PRIMARY KEY,
    name VARCHAR(255),
    ship_type INTEGER,
    length DECIMAL(6,2),
    width DECIMAL(6,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Posities (time-series)
CREATE TABLE positions (
    id BIGSERIAL PRIMARY KEY,
    mmsi VARCHAR(9) REFERENCES vessels(mmsi),
    timestamp TIMESTAMP NOT NULL,
    latitude DECIMAL(9,6) NOT NULL,
    longitude DECIMAL(9,6) NOT NULL,
    speed DECIMAL(5,2),
    course DECIMAL(5,2),
    heading DECIMAL(5,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Encounters (ontmoetingen)
CREATE TABLE encounters (
    id BIGSERIAL PRIMARY KEY,
    vessel_a_mmsi VARCHAR(9) REFERENCES vessels(mmsi),
    vessel_b_mmsi VARCHAR(9) REFERENCES vessels(mmsi),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    min_distance DECIMAL(10,2), -- meters
    encounter_type VARCHAR(50), -- crossing, overtaking, head-on
    cpa DECIMAL(10,2), -- closest point of approach (meters)
    tcpa INTEGER, -- time to CPA (seconds)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Encounter posities (alle posities tijdens encounter)
CREATE TABLE encounter_positions (
    id BIGSERIAL PRIMARY KEY,
    encounter_id BIGINT REFERENCES encounters(id),
    mmsi VARCHAR(9) REFERENCES vessels(mmsi),
    timestamp TIMESTAMP NOT NULL,
    latitude DECIMAL(9,6) NOT NULL,
    longitude DECIMAL(9,6) NOT NULL,
    speed DECIMAL(5,2),
    course DECIMAL(5,2),
    heading DECIMAL(5,2)
);
```

### Technologie Stack Suggesties

**Database**:
- PostgreSQL met PostGIS extensie (voor geografische queries)
- TimescaleDB (voor time-series optimalisatie)
- Of: InfluxDB voor pure time-series

**Backend**:
- Python (goede AIS libraries, ML integratie)
- Libraries: `websockets`, `asyncio`, `sqlalchemy`, `geopandas`

**Encounter Detectie Algoritme**:
1. Maintain sliding window van actieve schepen
2. Gebruik spatial index (R-tree) voor efficiente nearby queries
3. Bereken afstand tussen alle schepen binnen bounding box
4. Detecteer wanneer afstand < threshold
5. Track encounter tot afstand > threshold

---

## Volgende Stappen

1. [ ] Account aanmaken bij AISStream.io
2. [ ] API key verkrijgen
3. [ ] Python project opzetten
4. [ ] Database kiezen en opzetten (PostgreSQL + PostGIS)
5. [ ] WebSocket connectie implementeren
6. [ ] Encounter detectie algoritme bouwen
7. [ ] Data opslag implementeren
8. [ ] Monitoring/dashboard (optioneel)

---

## Bronnen

- AISStream.io: https://aisstream.io/
- AISHub: https://www.aishub.net/
- OpenAIS: https://open-ais.org/
- VesselFinder API: https://api.vesselfinder.com/docs/
- MarineTraffic Docs: https://servicedocs.marinetraffic.com/
- Kpler Maritime: https://www.kpler.com/product/maritime/data-services
- AISStream GitHub: https://github.com/aisstream/aisstream
