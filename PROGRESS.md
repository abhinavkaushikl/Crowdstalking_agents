# Progress

## Done

**Map app (`map-app/`)**
- MapLibre GL viewer over OpenFreeMap tiles, 3D buildings, terrain, polygon drawing with real lat/lng vertex output (mapbox-gl-draw + MapLibre compatibility fixes).
- City search with fly-to (Frankfurt, Berlin).
- Offline polygon -> streets/shops lookup (`/api/lookup`), backed by a pre-built OSM index per city (`osm-extract/*.index.json`) for ~65x faster queries than re-scanning the raw `.pbf` each time (25s -> 0.4s).
- Fixed a real race condition: overlapping `draw.create`/`draw.update` events could leave a polygon's lookup permanently stuck on "Looking up..." — fixed with a generation-counter guard + parallel (not sequential) per-polygon fetches.
- "Live" overlay: polls simulated device positions + crowd-risk flags, renders devices as colored dots and flags as a tight gradient "danger zone" circle (dark center -> pale edge, crisp boundary ring, capped at 2km, color-coded: red = panic, yellow = protest/mass gathering).
- "Citizen.AI" left panel: incident summary, real distance-sorted affected-subscriber list, real nearby-vendor list (via `/api/lookup`), and manual mock action buttons (call emergency, Police/Medical/Fire/Rescue, trigger alert, send mass message, email vendors) — all human-clicked, verified working via live browser testing.
- Panel minimize/expand toggle.

**Simulation (`simulation/live_position_simulator.py`)**
- N simulated devices, normal city-wide traffic (driving/walking/stationary mix).
- "Concert cluster" mode: tightly packed devices at one venue, reflecting-boundary movement.
- Mixed mode: N normal + M concert-cluster devices in one run.
- Forced deterministic `panic_outward` incident (location/radius/timing/duration all controllable) — needed because the original random incident generator was too rare/unreliable for demos.
- Forced multi-location `--force-protests N`: N simultaneous `crush_inward` incidents at random real detector-grid-cell centers (centers chosen from the detector's own grid so alignment is always correct, not an arbitrary point).

**Detector (`social-media-sentiment-agent/crowd_anomaly_agent.py`)**
- `panic_outward` / `crush_inward` / `variance_spike`, 3-tick persistence filter, tight hotspot geometry per flag.
- **Backtested against real recorded human movement** (ETH/UCY pedestrian trajectory datasets, ~651s of real video-tracked people) — found and fixed a real false-positive bug (`crush_inward` was missing a minimum-speed gate that `panic_outward` already had). 0 false positives on real data after the fix; genuine detection re-verified still working live.

**Agentic pipeline (`crowd-monitoring-agent/`) — Phase A done**
- `context_agent.js` (Stage 1, deterministic, no LLM): reverse-geocode + nearby vendors + nearby subscribers for a flagged location.
- `poller.js`: watches `crowd_risk.json`, debounces by detector grid-cell index, runs the pipeline, writes `crowd_monitoring_output.json`.
- `lib/dedup_store.js`: the debounce tracker (fixed a real bug here — see `DECISIONS.md`).
- `test_stage1.js`: standalone CLI test, needs zero API keys.
- Verified live end-to-end: poller auto-detected a real flag and ran Stage 1 with zero manual triggering; real area name, real 1660-vendor lookup, real subscriber distances all confirmed correct.

**Phase B — Live Intelligence Agent (Stage 2) — done and verified live**
- `lib/groq_client.js` (Groq chat-completions wrapper + standard tool-calling loop, capped at 4 rounds), `lib/google_search.js`, `lib/live_intel_tools.js`, `live_intel_agent.js`, `test_stage2.js` all built.
- `GROQ_API_KEY` supplied by user and confirmed working. Model `llama-3.3-70b-versatile` does not exist on this account — switched to `openai/gpt-oss-120b` (confirmed available).
- `GOOGLE_CSE_API_KEY`/`CX` and `REDDIT_CLIENT_ID`/`SECRET` still not set — both search tools correctly degrade to `{error, results: []}` rather than crashing; verified live that the agent still produces an honest, non-hallucinated answer (`confidence: "low"`, empty `sources`) when search comes back empty.
- Verified via `poller.js` on a real live flag (not just the CLI test): real random location (Rosenhöhe, Offenbach am Main), sensible search queries chosen by the model, full pipeline wrote to `crowd_monitoring_output.json` with zero manual triggering.
- Missing-`GROQ_API_KEY` fallback path also directly tested — returns the typed fallback, never throws.

**Stage 2 renamed/reshaped: "Social Media Hunter" (`social_media_hunter.js`)**
- `get_nearby_vendors` (Stage 1) now also surfaces real street names for the zone (`tools.js` was discarding `extract.py`'s `streets` output before — fixed, no extra shell-out needed, same lookup already returned both).
- System prompt now mandates web_search (Google) first, reddit_search second, and queries grounded in the real street/area names instead of raw detector jargon.
- Output schema expanded: `sentiment_score` (-1.0 to 1.0 numeric), `tags` (array, e.g. "protest"/"celebration"/"unclear"), `intent_analysis` (what the crowd appears to be doing), alongside the existing `situation_summary`/`sentiment`/`confidence`/`sources`.
- **Wired back to the UI**: new `GET /api/crowd-intel` proxy in `map-app/server.js`, new "🕵️ Social Media Hunter" section in the Citizen.AI panel (sentiment score bar, tags, intent, confidence, sources) — matched to the active flag via the same stable grid-cell key `poller.js` uses. Verified live end-to-end: real streets found (349 in one test), Google called first, honest low-confidence output rendered correctly in the browser when search tools have no keys yet.

**Detector fix after street-graph movement** — fixed-0.55 radial threshold made detection a coin flip on street-constrained devices; now a z-score vs the 1/3 random-heading null (see `DECISIONS.md`). Verified in-process: 8/8 protest seeds and 5/5 panic seeds detected, 0 flags on no-incident controls.

## In progress / next

**Live-test Reddit + Google search once credentials exist** — not blocking, the pipeline already works end-to-end without them (graceful degradation confirmed); would just sharpen the sentiment/summary quality.

## Planned (do not start until Phase B is confirmed working)

**Phase C — Dispatch/Tip Agent (Stage 3)**
- `lib/tip_tools.js` (`tip_nearby_services`, `tip_shopkeepers` — mocked), `dispatch_agent.js`, `test_stage3.js`.

## Not started / explicitly out of scope for now

- UI wiring of `crowd_monitoring_output.json` into the Citizen.AI panel (noted as a future step, not designed).
- MCP wrapper around the tool functions (deferred — see `DECISIONS.md`).
- Scaling the detector past prototype scale (tested comfortably at 10,000 simulated devices; a real 700,000-subscriber deployment would need a streaming architecture rewrite — Kafka + vectorized per-cell math — not just more hardware under the current pure-Python/JSON-file prototype).
