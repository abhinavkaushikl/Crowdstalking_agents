#!/usr/bin/env python3
"""
Runs the REAL Social Media Hunter (real Groq call) against SYNTHETIC search
content from services/mock_search.py, since Google/Reddit keys aren't set
yet. This exercises the actual sentiment-judgment logic end-to-end against
known ground truth (each scenario's expected_sentiment), instead of eyeballing
one example.

Needs GROQ_API_KEY set; Google/Reddit keys are not required (mock covers them).

Usage (run from the crowd-monitoring-agent directory):
    python3 -m tests.test_sentiment_simulated                # all scenarios
    python3 -m tests.test_sentiment_simulated riot            # just one
"""
import json
import sys
import time

from dotenv import load_dotenv
load_dotenv()

from agents.context_agent import build_context
from agents.social_media_hunter import hunt_social_media
from services import groq_client as groq
from services.mock_search import SCENARIOS, set_scenario

# A real Frankfurt point so Stage 1 returns real street/area names - the
# scenario itself comes entirely from the mock, not from this location.
TEST_LAT, TEST_LON = 50.1109, 8.6821

# Free-tier Groq TPM is low enough that back-to-back calls trip it even with
# the client's own retry/backoff - confirmed live. A small gap between whole
# scenarios (on top of that retry logic) keeps a multi-scenario run reliable
# instead of leaning entirely on retries.
GAP_BETWEEN_SCENARIOS_SECONDS = 3


def run_one(scenario_name):
    actual_scenario = set_scenario(scenario_name)
    spec = SCENARIOS[actual_scenario]

    fake_flag = {
        "reason": "crush_inward",
        "detail": f"[simulated:{actual_scenario}] test flag",
        "device_count": 400,
        "mean_speed_kmh": 9.0,
        "hotspot": {"lat": TEST_LAT, "lon": TEST_LON, "radius_km": 1.0},
    }
    context = build_context(fake_flag)
    intel = hunt_social_media(context)

    score = intel.get("sentiment_score") or 0
    got_negative = score < -0.15
    # polarity is the real correctness check (did it catch "something's
    # wrong" vs "nothing's wrong"); the exact label is shown for context only
    # -- "concerned" vs "alarmed" for the same riot is a reasonable judgment
    # call by the model, not a wrong one.
    polarity_ok = got_negative == spec["expected_negative"]

    mark = "OK " if polarity_ok else "   "
    print(f"[{mark}] scenario={actual_scenario:<18} expected_sentiment~={spec['expected_sentiment']:<10} "
          f"got={intel.get('sentiment')!s:<10} score={score} tags={intel.get('tags')}")
    print(f"       summary: {intel.get('situation_summary')}")
    if intel.get("error"):
        print(f"       ERROR: {intel['error']}")
    print()
    return polarity_ok


def main():
    if not groq.has_key():
        print("GROQ_API_KEY is not set - the Social Media Hunter will just return its fallback for every scenario.")

    if len(sys.argv) > 1:
        names = [sys.argv[1]]
    else:
        names = list(SCENARIOS)

    results = []
    for i, name in enumerate(names):
        if i > 0:
            time.sleep(GAP_BETWEEN_SCENARIOS_SECONDS)
        results.append(run_one(name))

    n_ok = sum(results)
    print(f"{n_ok}/{len(results)} scenarios got the right polarity (negative vs. not).")


if __name__ == "__main__":
    main()
