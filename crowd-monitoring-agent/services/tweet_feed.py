"""
Raw simulated tweet feed for an incident -- no sentiment judgment, no LLM, no
NLP scoring, just the realistic-looking generated content itself (see
../simulation/tweet_simulator.py). Used when the pipeline should show what
people are "saying" rather than analyze it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "simulation"))
from tweet_simulator import generate_tweets  # noqa: E402


def tweets_for_context(context, count=15):
    area = context["area"].get("locality") or context["area"].get("city") or ""
    city = context["area"].get("city") or ""
    streets = context["vendors"].get("streets") or []
    incident_type = context["flag"].get("reason", "crush_inward")
    return generate_tweets(area, city, streets, incident_type, count)
