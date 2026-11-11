# Architecture

## Pipeline overview

```
simulation/live_position_simulator.py
  -- N devices (normal city traffic: driving/walking/stationary mix across the
     whole city bbox), optional tight "concert cluster", optional forced
     panic_outward incident, optional forced multi-location --force-protests
     (crush_inward) at random real detector-grid-cell centers.
  -- writes simulation/live_positions.json every --tick seconds.
        |
        v
social-media-sentiment-agent/crowd_anomaly_agent.py
  -- buckets devices into a fixed 4x4 grid over the Frankfurt bbox
     (LAT 50.015-50.19, LON 8.473-8.8 -- must match the simulator's own
     constants, they're kept in sync by convention, not by import).
  -- per cell, per tick: proportion-threshold test (panic_outward /
     crush_inward) + rolling z-score test (variance_spike). Requires 3
     consecutive confirming ticks before logging (persistence filter).
  -- panic_outward requires mean_speed >= 6.0 km/h; crush_inward requires
     mean_speed >= 4.0 km/h (added after backtesting against real pedestrian
     data -- see DECISIONS.md).
  -- on a confirmed flag, computes a tight "hotspot" (centroid + radius of
     just the devices that tripped the threshold, not the whole ~5km cell).
  -- writes social-media-sentiment-agent/crowd_risk.json: {generated_at,
     flags: [{reason, detail, device_count, mean_speed_kmh, hotspot, cell,
     cell_center, bounds, ...}]}. Flags decay out of the file 12s after their
     last confirming tick.
        |
        +---------------------------------------+
        v                                        v
map-app/server.js                      crowd-monitoring-agent/poller.js
  GET /api/crowd-risk proxies            watches crowd_risk.json every 3s,
  crowd_risk.json as-is.                 debounces by `${reason}:cell[gi,gj]`
        |                                (NOT by hotspot lat/lon -- that
        v                                drifts tick-to-tick, see DECISIONS.md),
map-app/public/app.js                    runs the pipeline below for any
  polls /api/crowd-risk every 1.5s,      genuinely new/stale hotspot.
  renders the "crowd-risk-hotspot"             |
  circle layers (dark-to-light gradient        v
  + crisp ring, capped at 2km, color by   crowd-monitoring-agent/context_agent.js
  reason: red=panic, yellow=protest),      (Stage 1 -- deterministic, no LLM)
  and the left "Citizen.AI" panel          resolves {lat,lon,radius_km} from
  (dispatch/alert buttons are still        the flag's hotspot (or cell_center
  MANUALLY clicked mocks; the "Social      fallback for hotspot-less flags),
  Media Hunter" section is autonomous --   then in parallel:
  it polls /api/crowd-intel and shows        - reverseGeocode() [geocode.js]
  whatever the pipeline below already        - get_nearby_vendors [tools.js]
  produced on its own, no click needed).
                                              - get_affected_subscribers [tools.js]
                                                    |
                                                    v
                                          crowd-monitoring-agent/social_media_hunter.js
                                          (Stage 2 -- Groq tool-calling loop,
                                          DONE -- Phase B)
                                          tools, in mandated order: web_search
                                          (Google CSE) first, reddit_search
                                          (reddit.js) second -- queries grounded
                                          in the REAL street names Stage 1 found,
                                          not raw detector jargon. Output:
                                          {situation_summary, sentiment,
                                          sentiment_score (-1..1), tags[],
                                          intent_analysis, confidence, sources}.
                                                    |
                                                    v
                                          crowd-monitoring-agent/dispatch_agent.js
                                          (Stage 3 -- NOT YET BUILT -- Phase C,
                                          build only after 1+2 confirmed)
                                          tools: tip_nearby_services,
                                          tip_shopkeepers -- all MOCKED.
                                                    |
                                                    v
                                          crowd-monitoring-agent/crowd_monitoring_output.json
                                                    |
                                                    v
                                          map-app/server.js: GET /api/crowd-intel
                                          (proxies the file, mirrors the existing
                                          /api/crowd-risk proxy)
                                                    |
                                                    v
                                          map-app/public/app.js: "🕵️ Social Media
                                          Hunter" section in the Citizen.AI panel
                                          (sentiment bar, tags, intent, sources) --
                                          matched to the active flag by the same
                                          ${reason}:cell[gi,gj] key the poller uses.
```

## Shared offline map data

`osm-extract/` holds pre-built `.index.json` files (one per city: Frankfurt, Berlin) — a flat JSON of named streets + shop/food points, built once from the full `.osm.pbf` via `extract.py --build-index` (full-file scan, ~1-2 min, one-time). Queries then read the small index instead of re-scanning the full `.pbf` (~65x faster: 25s -> 0.4s). Both `map-app/server.js`'s `/api/lookup` and `crowd-monitoring-agent`'s `get_nearby_vendors` tool shell out to the same `extract.py --index ... --points-json ...` CLI.

## Reused libraries (live in `map-app/lib/`, required by relative path from sibling folders, not copied)

- `geocode.js` — `reverseGeocode(lat, lng)` via Nominatim (free, no key). Live-tested.
- `reddit.js` — `searchReddit(query)` via Reddit's official OAuth app-only flow. Written, not yet live-tested (needs `REDDIT_CLIENT_ID`/`SECRET`).
- `cache.js` — in-memory TTL cache; already has unused `GOOGLE`/`INSIGHT` TTL entries anticipating stage 2's need.
- `tools.js` — OpenAI/Groq-compatible `TOOL_SCHEMAS`/`TOOL_IMPLS` for `get_nearby_vendors`, `get_affected_subscribers`, and the mocked action tools (`notify_emergency_services`, `trigger_automated_alert`, `send_mass_alert`, `email_vendors`).

`crowd-monitoring-agent/context_agent.js` requires `../map-app/lib/geocode` and `../map-app/lib/tools` directly.

## Why two separate "incident reaction" paths (Citizen.AI panel vs crowd-monitoring-agent)

They currently do overlapping things on purpose, from two different triggers:
- **Citizen.AI panel** (`map-app`) = human-in-the-loop demo UI. A person watching the map clicks a button; nothing happens unless they do.
- **crowd-monitoring-agent** = the actual autonomous agent being built per the user's explicit request — reacts on its own, no human click needed. This is the one that will eventually call an LLM to decide what to do, not just show a static toast.

Longer-term, `crowd_monitoring_output.json` is expected to feed back into the Citizen.AI panel (a new UI section) once Phase B/C exist — not yet wired.
