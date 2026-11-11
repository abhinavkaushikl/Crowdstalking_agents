"""
Tracks when a given hotspot was last run through the pipeline, so a flag
that's still active on the next poll tick doesn't re-trigger expensive work
(especially the Social Media Hunter's Google/Groq calls) every few seconds.

Keys on the detector's own grid cell index, not the hotspot lat/lon - the
centroid drifts tick-to-tick as devices keep moving (confirmed live in the
Node version: the same ongoing incident produced 3 different rounded-lat/lon
keys within 20 seconds), while the grid cell is stable for an incident's
whole life.
"""
import time

from utils.config_loader import get as config_get

RERUN_AFTER_SECONDS = config_get("dedup.rerun_after_seconds", 300)
FORGET_AFTER_SECONDS = config_get("dedup.forget_after_seconds", 600)

_last_run_at = {}
_last_seen_at = {}


def key_for(flag):
    return f"{flag['reason']}:cell[{flag['cell'][0]},{flag['cell'][1]}]"


def should_run(flag):
    key = key_for(flag)
    now = time.time()
    _last_seen_at[key] = now
    last = _last_run_at.get(key)
    if last and now - last < RERUN_AFTER_SECONDS:
        return False
    return True


def mark_run(flag):
    _last_run_at[key_for(flag)] = time.time()


def forget_stale():
    now = time.time()
    for key in list(_last_seen_at.keys()):
        if now - _last_seen_at[key] > FORGET_AFTER_SECONDS:
            del _last_seen_at[key]
            _last_run_at.pop(key, None)
