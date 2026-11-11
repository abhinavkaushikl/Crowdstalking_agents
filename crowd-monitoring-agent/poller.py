#!/usr/bin/env python3
"""
Entrypoint. Watches social-media-sentiment-agent/crowd_risk.json (written by
crowd_anomaly_agent.py) and, for each genuinely new/stale hotspot, runs the
agent pipeline in order and writes crowd_monitoring_output.json.

Same file-handoff pattern the rest of this project already uses:
live_position_simulator.py -> live_positions.json -> crowd_anomaly_agent.py
-> crowd_risk.json -> (this file) -> crowd_monitoring_output.json

Run from this directory: python3 poller.py
"""
import json
import os
import threading
import time

from dotenv import load_dotenv
load_dotenv()

from agents.context_agent import build_context
from services.tweet_feed import tweets_for_context
from utils import dedup_store
from utils.config_loader import get as config_get

# Analyzer (Groq/NLP sentiment judgment) is disabled for now -- just show the
# raw simulated tweet feed, no analysis step. Re-enable by uncommenting.
# try:
#     from agents.social_media_hunter import hunt_social_media
# except ImportError:
#     hunt_social_media = None
hunt_social_media = None

HERE = os.path.dirname(os.path.abspath(__file__))
CROWD_RISK_PATH = os.path.join(HERE, "..", "social-media-sentiment-agent", "crowd_risk.json")
OUTPUT_PATH = os.path.join(HERE, "crowd_monitoring_output.json")
POLL_SECONDS = config_get("poller.poll_seconds", 3)

_results = {}
_results_lock = threading.Lock()


def _write_output():
    tmp = f"{OUTPUT_PATH}.{os.getpid()}.tmp"  # per-PID -- see crowd_anomaly_agent.py's matching fix
    with _results_lock:
        snapshot = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "incidents": list(_results.values())
        }
    with open(tmp, "w") as f:
        json.dump(snapshot, f)
    os.replace(tmp, OUTPUT_PATH)


def _run_pipeline(flag):
    key = dedup_store.key_for(flag)
    print(f"[poller] running pipeline for {key} ({flag['reason']})")
    try:
        context = build_context(flag)
        intel = None
        if hunt_social_media:
            try:
                intel = hunt_social_media(context)
            except Exception as e:
                intel = {
                    "situation_summary": "Social Media Hunter unavailable", "sentiment": "unclear",
                    "sentiment_score": 0, "tags": [], "intent_analysis": "Unknown",
                    "confidence": "low", "sources": [], "error": str(e)
                }

        try:
            tweets = tweets_for_context(context)
        except Exception as e:
            tweets = []
            print(f"[poller] tweet feed failed for {key}: {e}")

        with _results_lock:
            _results[key] = {
                "key": key, "context": context, "intel": intel, "tweets": tweets,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
        _write_output()
        print(f"[poller] done {key} ({len(tweets)} tweets" + (", stage 2 ran)" if intel else ")"))
    except Exception as e:
        print(f"[poller] pipeline failed for {key}: {e}")


def _tick():
    dedup_store.forget_stale()
    try:
        with open(CROWD_RISK_PATH) as f:
            parsed = json.load(f)
    except Exception:
        return  # crowd_anomaly_agent.py not running yet, or mid-write -- fine, try again next tick

    for flag in parsed.get("flags", []):
        if dedup_store.should_run(flag):
            dedup_store.mark_run(flag)
            # not joined -- let ticks keep going while this (possibly ~5-10s
            # Groq call) works, same fire-and-forget behavior as the original
            # Node poller
            threading.Thread(target=_run_pipeline, args=(flag,), daemon=True).start()


def main():
    print(f"[poller] watching {CROWD_RISK_PATH} every {POLL_SECONDS}s")
    print(f"[poller] stage 2 (social media hunter): {'ENABLED' if hunt_social_media else 'not built yet (Phase B)'}")
    try:
        while True:
            _tick()
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\n[poller] stopped.")


if __name__ == "__main__":
    main()
