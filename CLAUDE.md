# Location Intelligence Agen

A map-based location intelligence and crowd-monitoring platform: draw a polygon to see what's inside it (streets/shops), simulate a city's live population, detect real crowd anomalies (panic/riots) from that telemetry with plain statistics, and react to detected incidents with an agentic pipeline — all local/offline except where a real external API is explicitly wired in.

See also: `ARCHITECTURE.md` (how the pieces connect), `DECISIONS.md` (why things are built this way), `PROGRESS.md` (what's done / next).

## Folder structure

| Folder | Language | Purpose |
|---|---|---|
| `map-app/` | Node/Express | The map UI (MapLibre GL), polygon drawing, city search, "Live" device overlay, "Citizen.AI" incident response panel |
| `osm-extract/` | Python | Offline OSM data (Frankfurt, Berlin `.osm.pbf` + pre-built `.index.json`) and `extract.py` — polygon → streets/shops lookup |
| `simulation/` | Python | `live_position_simulator.py` — simulates N devices as a city's population (normal traffic + optional forced panic/protest incidents) |
| `social-media-sentiment-agent/` | Python | `crowd_anomaly_agent.py` — the actual crowd-anomaly detector (despite the folder name, this is NOT social-media based; name is legacy) |
| `crowd-monitoring-agent/` | Node | The new agentic response pipeline: reacts to detector flags automatically (context gathering → live intelligence search → mocked tip/alert dispatch) |

## Hard constraints (do not violate these without being explicitly told to)

- **No real external contact, ever.** Every "action" tool (call emergency services, send mass alert, email vendors, post social alert, tip services/shopkeepers) is explicitly mocked — it returns a structured fake confirmation and must never place a real call, send a real email/SMS, or post anywhere real. This is a firm, repeated user requirement.
- **Detection stays deterministic statistics, not ML.** `crowd_anomaly_agent.py`'s thresholds are plain, auditable proportion/z-score tests — no trained model. This was a deliberate choice (see `DECISIONS.md`): no real labeled incident data exists to train against, and explainability matters for an emergency-response context.
- **LLM calls only where judgment adds value.** Don't spend an LLM call on a step that's just a deterministic data fetch (e.g. the Context Agent in `crowd-monitoring-agent/`). Reserve Groq calls for steps that genuinely need reasoning (search-query selection, sentiment synthesis).
- **No budget for paid APIs unless explicitly told otherwise.** Current real integrations are all free-tier: Nominatim (geocoding), Reddit API (free script app), Google Custom Search (100/day free), Groq (free-tier LLM, key supplied by user).

## Data flow in one line

`live_position_simulator.py` → `live_positions.json` → `crowd_anomaly_agent.py` → `crowd_risk.json` → (`map-app`'s Citizen.AI panel, manually triggered) **and** (`crowd-monitoring-agent/poller.js`, automatically triggered) → `crowd_monitoring_output.json`.

## Running things

```bash
# terminal 1: simulate a city (10k devices, normal traffic + a forced incident for testing)
cd simulation && python3 -I live_position_simulator.py --devices 10000 --tick 2 \
  --force-protests 1 --force-protest-at 8 --force-protest-radius-km 4.2

# terminal 2: the detector
cd social-media-sentiment-agent && python3 -I crowd_anomaly_agent.py

# terminal 3: the map UI
cd map-app && node server.js   # http://localhost:3000

# terminal 4: the agentic response pipeline
cd crowd-monitoring-agent && node poller.js
```

## Keep these docs current

When you (Claude) make an architectural decision, finish a build phase, or change how components connect — update `DECISIONS.md`, `PROGRESS.md`, and/or `ARCHITECTURE.md` in the same turn, not as an afterthought.
