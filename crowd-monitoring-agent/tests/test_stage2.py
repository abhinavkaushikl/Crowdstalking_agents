#!/usr/bin/env python3
"""Phase B test: python3 -m tests.test_stage2 <lat> <lon> [reason]
Runs REAL stage 1 (geocode + streets + vendors + subscribers) then REAL
stage 2 / Social Media Hunter (actually calls the Groq API and whatever
search tools have keys configured). Run from the crowd-monitoring-agent
directory."""
import json
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

from agents.context_agent import build_context
from agents.social_media_hunter import hunt_social_media
from services import groq_client as groq


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 -m tests.test_stage2 <lat> <lon> [reason]")
        sys.exit(1)
    lat, lon = float(sys.argv[1]), float(sys.argv[2])
    reason = sys.argv[3] if len(sys.argv) > 3 else "crush_inward"

    print(f"GROQ_API_KEY set: {groq.has_key()}")
    print(f"GROQ_MODEL: {groq.DEFAULT_MODEL}")
    print(f"GOOGLE_CSE configured: {bool(os.environ.get('GOOGLE_CSE_API_KEY') and os.environ.get('GOOGLE_CSE_CX'))}")
    print(f"REDDIT configured: {bool(os.environ.get('REDDIT_CLIENT_ID') and os.environ.get('REDDIT_CLIENT_SECRET'))}")
    print()

    fake_flag = {
        "reason": reason,
        "detail": f"[test] {reason} at ({lat},{lon})",
        "device_count": 650,
        "mean_speed_kmh": 9.5,
        "hotspot": {"lat": lat, "lon": lon, "radius_km": 1.5}
    }

    print("--- Stage 1 (context) ---")
    context = build_context(fake_flag)
    print(f"area: {context['area'].get('locality')}, {context['area'].get('city')}")
    print(f"vendors found: {context['vendors'].get('vendor_count')}, streets found: {context['vendors'].get('street_count')}")
    print()

    print("--- Stage 2 (Social Media Hunter) ---")
    t0 = time.time()
    intel = hunt_social_media(context)
    print(f"({round((time.time() - t0) * 1000)}ms)")
    print(json.dumps(intel, indent=2))


if __name__ == "__main__":
    main()
