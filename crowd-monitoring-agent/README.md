# crowd-monitoring-agent

Python. Reacts automatically to flags from `../social-media-sentiment-agent/crowd_anomaly_agent.py`.

## Layout

```
crowd-monitoring-agent/
├── poller.py                   # entrypoint - watches crowd_risk.json, runs the pipeline per flag
├── config/
│   └── settings.yaml           # non-secret, tunable settings (model name, limits, intervals)
├── agents/
│   ├── context_agent.py        # Stage 1 - deterministic context gathering, no LLM/keys needed
│   └── social_media_hunter.py  # Stage 2 - Groq-driven sentiment/intent judgment
├── services/                   # external integrations, one per provider
│   ├── groq_client.py          # Groq chat/completions + tool-calling loop
│   ├── google_search.py        # Google Custom Search JSON API
│   └── reddit_search.py        # Reddit OAuth search API
├── tools/
│   ├── registry.py             # generic tool-calling framework (schema + trace + dispatch)
│   └── search_tools.py         # registers web_search/reddit_search against services/
├── utils/
│   ├── config_loader.py        # reads config/settings.yaml
│   ├── geo.py                  # haversine_km, circle_polygon
│   └── dedup_store.py          # per-hotspot re-run/cooldown tracking
├── tests/
│   ├── test_stage1.py          # Phase A - zero API keys
│   └── test_stage2.py          # Phase B - real Groq + search calls
├── .env / .env.example         # secrets (API keys) - never committed, see .gitignore
└── requirements.txt
```

**Secrets vs. settings**: API keys/credentials live in `.env` (read via `os.environ`
through `python-dotenv`) and are never written to `config/settings.yaml`. Everything
non-secret and human-tunable (model name, timeouts, limits, poll interval) lives in
`config/settings.yaml` instead of being a magic number buried in some file.

## Pipeline stages

1. **Context Agent** (`agents/context_agent.py`) — deterministic, no LLM, no API keys
   needed. Reverse-geocodes the flagged point, looks up real nearby streets + vendors
   (imports `osm-extract/extract.py` directly) and nearby affected subscribers (live
   device telemetry).
2. **Social Media Hunter** (`agents/social_media_hunter.py`) — Groq tool-calling loop via
   `tools/search_tools.py`'s registry: searches Google first, then Reddit, grounded in the
   real street names Stage 1 found. Judges sentiment with a numeric score (-1..1), tags,
   and an intent analysis.
3. **Dispatch/Tip Agent** (Phase C, not built yet) — sends mocked "tip" alerts to nearby
   services/shopkeepers. No real email/call/SMS is ever sent.

`poller.py` watches `crowd_risk.json` every `poller.poll_seconds` (config/settings.yaml),
debounces by the detector's own grid-cell index (stable across ticks, unlike the hotspot
centroid which drifts), and runs the pipeline stages in a background thread per new
incident, writing `crowd_monitoring_output.json`.

`tools/registry.py` is the single source of truth for every tool a stage can call: it's a
small registry (`@search_registry.tool(...)`) that generates the Groq-compatible JSON
schema, runs the implementation, and records a timed, structured trace (`tool`, `args`,
`result`, `ok`, `duration_ms`) for every call — visible in each pipeline result's
`tool_trace`.

## Setup

```
pip3 install --user -r requirements.txt
cp .env.example .env   # fill in keys as you get them; stage 1 needs none
```

## Testing each phase standalone

Run these from this directory (`crowd-monitoring-agent/`) so the `agents`/`services`/
`tools`/`utils` packages resolve correctly.

**Phase A (works today, zero keys):**
```
python3 -m tests.test_stage1 <lat> <lon> [reason]
# e.g. python3 -m tests.test_stage1 50.12438 8.67738 crush_inward
```

**Phase B (once GROQ_API_KEY + GOOGLE_CSE_API_KEY/CX are set):**
```
python3 -m tests.test_stage2 <lat> <lon> [reason]
```

**Full pipeline, live:**
```
# in separate terminals / background:
python3 -I ../simulation/live_position_simulator.py --devices 10000 --tick 2 \
  --force-protests 1 --force-protest-at 8 --force-protest-radius-km 2.2
python3 -I ../social-media-sentiment-agent/crowd_anomaly_agent.py
python3 -u poller.py    # -u (unbuffered) matters if output is redirected to a
                         # log file -- otherwise print() output can sit in
                         # Python's stdout buffer and not appear until exit
# watch crowd_monitoring_output.json fill in, or GET /api/crowd-intel on
# map-app's server once it's running
```
