#!/usr/bin/env python3
"""Phase A test: python3 -m tests.test_stage1 <lat> <lon> [reason]
Needs zero API keys. Run from the crowd-monitoring-agent directory."""
import json
import sys

from agents.context_agent import build_context


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 -m tests.test_stage1 <lat> <lon> [reason]")
        sys.exit(1)
    lat, lon = float(sys.argv[1]), float(sys.argv[2])
    reason = sys.argv[3] if len(sys.argv) > 3 else "crush_inward"

    fake_flag = {
        "reason": reason,
        "detail": f"[test] {reason} at ({lat},{lon})",
        "device_count": 0,
        "mean_speed_kmh": 0,
        "hotspot": {"lat": lat, "lon": lon, "radius_km": 1.5}
    }
    bundle = build_context(fake_flag)
    print(json.dumps(bundle, indent=2))


if __name__ == "__main__":
    main()
