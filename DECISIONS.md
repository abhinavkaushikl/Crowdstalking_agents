# Decisions

Running log of non-obvious technical/architectural choices and why. Newest at the bottom. Append, don't rewrite history.

---

**Detection = plain statistics, not ML.**
`crowd_anomaly_agent.py` uses a proportion-threshold test (is X% of a cell's devices coherently moving the same way) plus a rolling z-score test for variance — not a trained model.
*Why:* no real labeled incident data exists to train against (only synthetic simulator data is available, which would mean training on our own fake generation rules and calling it "learned"). Threshold tests are also fully auditable — you can hand-trace exactly why a real dispatch decision fired, which matters for an emergency-response context. See also: the real-world-data backtest decision below.

**Fixed 4x4 grid, not density-based clustering.**
Cells are a static grid over the Frankfurt bbox, not an adaptive clustering algorithm (e.g. DBSCAN).
*Why:* simplicity, and it's what the detector was already built with. Flagged as the single highest-value future improvement if false negatives near cell boundaries become a real problem (a small incident straddling two cells can get diluted below threshold in both) — not urgent, no evidence yet that it's actually hurt a real test.

**`crush_inward` needed its own minimum-speed gate — found via backtesting against REAL pedestrian data, not synthetic.**
Downloaded real recorded pedestrian trajectories (ETH/UCY campus + street scenes, actual video-tracked humans) and replayed them through the unmodified detector. Result: 5 false `crush_inward` flags across ~651s of real footage, all real students converging on a building entrance/path junction at 2.1-2.8 km/h (real mundane foot traffic, not an incident). Every genuine incident ever live-tested in this project measured 9-16 km/h. Added `CRUSH_MIN_SPEED_KMH = 4.0` (mirroring `panic_outward`'s existing `PANIC_MIN_SPEED_KMH = 6.0`, which already protected it from the same class of bug). Re-verified: 0 false positives on the same real data after the fix, genuine protest detection still fires correctly (70%+ convergence, 9+ km/h).
*Why this matters generally:* this is the concrete example of why "it stays quiet on normal traffic" must be validated against real data, not just our own synthetic simulator — the simulator's random-walk devices have no concept of a "destination" the way real pedestrians do, so this exact bug was invisible to every synthetic test we ran.

**Radial-fraction threshold is a z-score against the random-heading null (capped at 0.55), not a fixed 0.55 — found when devices moved onto the street graph.**
Once `live_position_simulator.py` moved devices along real OSM streets, a genuine `crush_inward` incident only reached ~0.51-0.57 of a cell's devices (streets zigzag / run tangentially, so not everyone is within +-60 deg of the target), straddling the old fixed 0.55 line: in an in-process rerun with 6000 devices, seed 1 never flagged and seed 3 flagged 4x vs 11x. `fraction_threshold()` now uses `RADIAL_NULL_P=1/3` (chance a random heading falls in the cone) + `RADIAL_Z=5` standard errors, clamped to [0.40, 0.55]. Large cells (~450 devices) flag at ~0.44; sparse cells (~45) still need the old 0.55. Min-speed gates are unchanged, so slow mundane funneling is still excluded.
*Known cost:* panic spillover can now also raise a `crush_inward` in a neighbouring cell (seen in 1 of 5 panic seeds). The real-pedestrian (ETH/UCY) backtest data is not in the repo, so the false-positive check after this change was only synthetic no-incident runs (0 flags, 4 seeds x 60 ticks) — re-run the real-data backtest if you have the data. `cases/case_runner.py` is a separate offline copy with its own old constants and was NOT updated.

**Hotspot circle = centroid of the devices that actually tripped the threshold, not the whole grid cell.**
`crowd_anomaly_agent.py`'s `hotspot_from_points()` filters to just the subset of a flagged cell's devices with the qualifying radial component, then computes their centroid + max radius. The detection math/thresholds are untouched — this only adds richer geometry to an already-triggered flag.
*Why:* the raw grid cell is ~5x6km; rendering the whole cell as "the danger zone" would be visually useless and misleading. User explicitly asked for a tight zone marker, not the full cell.

**Dedup/debounce key = the detector's own grid cell index, not the hotspot's lat/lon.**
`crowd-monitoring-agent/lib/dedup_store.js` keys on `${reason}:cell[gi,gj]`.
*Why:* found live — the hotspot centroid drifts tick-to-tick as devices keep moving (confirmed: the same ongoing incident produced 3 different rounded-lat/lon keys within 20 seconds), which spuriously re-triggered the whole pipeline multiple times for one incident. The grid cell index is stable for an incident's whole life (it's exactly what the detector itself already uses internally to track "same ongoing thing" via its own `strikes` dict).

**Node.js for `crowd-monitoring-agent/`, not Python.**
*Why:* lets it directly reuse already-working, already-tested code (`map-app/lib/geocode.js`, `reddit.js`, `cache.js`, `tools.js`) via relative `require()` instead of porting it to Python. Groq's API is a plain HTTPS JSON endpoint either way — no language advantage. The two existing Python daemons (`live_position_simulator.py`, `crowd_anomaly_agent.py`) only talk to anything else via JSON files on disk, so there's no tight-coupling reason they need to share a language with this new piece.

**Reuse via relative `require()` across sibling folders, not copying files.**
`context_agent.js` does `require('../map-app/lib/geocode')` directly rather than duplicating the file.
*Why:* avoids drift (one source of truth); matches the project's existing convention — `map-app/server.js` already reaches into `../simulation/` and `../social-media-sentiment-agent/` via relative paths the same way.

**No MCP (Model Context Protocol) for the agent tool-calling layer — deferred, not rejected.**
*Why:* Groq's `chat/completions` endpoint takes plain OpenAI-style `tools`/`tool_choice` in the request body; it's an inference API, not an MCP host or client. There's no path by which MCP "drives" a Groq-powered loop. MCP would only become relevant later if Claude Desktop/Claude Code itself needed to call these same tools interactively — at that point, wrapping the *same* tool functions in a thin MCP server is near-zero rework. Building that wrapper now, before anything needs it, would just be a second unused entry point.

**LLM provider = Groq, not local Ollama.**
Explicit user choice. Groq key to be supplied later; all Groq-dependent code must degrade gracefully (typed fallback, never throw/crash) when the key is unset, so the rest of the pipeline (Stage 1) stays fully testable without it.

**Search API = Google Custom Search, not Brave.**
Explicit user choice (asked directly, confirmed). 100 free queries/day, no billing account. Stage 2's 5-minute per-hotspot re-run cadence exists specifically to protect this quota.

**All "action" tools are mocked — hard, repeated requirement.**
`notify_emergency_services`, `trigger_automated_alert`, `send_mass_alert`, `email_vendors`, and the planned `tip_nearby_services`/`tip_shopkeepers` all return a structured fake confirmation (`status: 'MOCK_*'`) and must never make a real network call to an external party. Stated explicitly and repeatedly by the user ("we will not mail anyone, or call anyone, just a tool build").

**Stage 1 (Context Agent) has no LLM call.**
Reverse-geocoding, vendor lookup, and subscriber lookup are pure data fetches with no ambiguity for an LLM to resolve.
*Why:* don't spend latency/cost on a judgment call where there's no judgment to make. Reserve Groq calls for Stage 2 (search-query selection, sentiment synthesis) and Stage 3 (deciding what to tip whom), where reasoning genuinely changes the outcome.

**Build order is explicitly sequenced: Stage 1 -> Stage 2 -> (confirm both work) -> Stage 3.**
Explicit user instruction, not a technical constraint — Stage 3 could technically be built in parallel since it only consumes Stage 1+2's output, but the user wants each stage proven working before the next is started.

**Groq model = `openai/gpt-oss-120b`, not `llama-3.3-70b-versatile`.**
The originally-planned model doesn't exist on this account/key (`model_not_found`). Queried `GET /v1/models` with the real key to get the actual available list; `openai/gpt-oss-120b` (large, built for tool-calling) and `openai/gpt-oss-20b` (smaller/faster) were available. Picked the 120b for better structured-JSON/synthesis quality, same reasoning as the original plan.

**`max_tokens` must budget for gpt-oss's hidden reasoning tokens, not just the visible answer.**
`openai/gpt-oss-*` models on Groq return a separate `reasoning` field and spend tokens on it before the final `content` — confirmed live: `max_tokens: 20` produced zero `content` (`finish_reason: "length"`, all 20 tokens consumed by reasoning). `groq_client.js` defaults to `max_tokens: 2000` for this reason. Only `message.content` is read; `reasoning` is ignored.

**Stage 2's final structured JSON is a dedicated extra call, not the tool-loop's natural last message.**
After the tool-calling loop finishes searching, one more call is made with the full conversation + an explicit "now output ONLY this JSON shape" instruction and `response_format: {type:'json_object'}`. Avoids mixing `tools` and strict `response_format` in the same call (kept them in separate requests rather than risk an unsupported combination), and guarantees parseable output regardless of how the model naturally would have ended the tool-calling conversation.

**`get_nearby_vendors` (Stage 1) also returns real street names now, not just shops.**
`extract.py` already returned both `streets` and `places` from one polygon lookup; `tools.js` was silently discarding `streets`. Fixed to surface both from the same call (no extra shell-out). Driven by the Social Media Hunter needing real street names to ground its search queries, rather than only the coarse locality name.

**Social Media Hunter's sentiment output is a numeric score + tags + intent, not just a category label.**
Explicit user requirement. `sentiment_score` is a standard -1.0..1.0 polarity scale (kept alongside the categorical `sentiment` label for human readability), `tags` is a free-ish array of short situation-type strings (e.g. "protest", "celebration", "unclear"), `intent_analysis` is a short free-text read on what the crowd appears to be doing. All three come from the same single structured-JSON call as the summary/confidence/sources — no extra API round-trip.

**`crowd_monitoring_output.json` reaches the UI via a new `GET /api/crowd-intel` proxy, matched to the active flag by grid-cell key.**
Mirrors the existing `/api/crowd-risk` proxy exactly. The frontend computes the same `${reason}:cell[gi,gj]` key `crowd-monitoring-agent/lib/dedup_store.js` uses server-side, so the UI always shows the hunter result for the specific incident currently being displayed, not just whatever the poller last wrote.
