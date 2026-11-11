#!/usr/bin/env python3
"""
Continuously monitors live_positions.json (written by live_position_simulator.py)
and flags anomalous movement for the simulated population.

Time factor: speed is never assumed from a fixed tick interval. Every device
carries its own "timestamp", and speed = haversine_distance / real_elapsed_time
between that device's last two seen positions - so the monitor is correct even
if ticks arrive late, jittered, or irregularly.

Usage:
    python3 -I monitoring_agent.py
    python3 -I monitoring_agent.py --speed-cap 120 --teleport-cap 300 --persistence 2
Stop with Ctrl+C.
"""
import argparse
import datetime
import json
import math
import os
import statistics
import time

SCRIPT_DIR = os.path.dirname(__file__)


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_snapshot(path):
    with open(path) as f:
        return json.load(f)


class MonitoringAgent:
    def __init__(self, speed_cap, teleport_cap, zscore_cap, persistence, log_path):
        self.speed_cap = speed_cap
        self.teleport_cap = teleport_cap
        self.zscore_cap = zscore_cap
        self.persistence = persistence
        self.log_path = log_path
        self.prev = {}          # subscriber_id -> (lat, lon, timestamp)
        self.strikes = {}       # (subscriber_id, reason) -> consecutive count

    def _log(self, record):
        with open(self.log_path, "a") as f:
            f.write(json.dumps(record) + "\n")
        print(f"[FLAG] {record['subscriber_id']} {record['reason']} "
              f"speed={record['computed_speed_kmh']}km/h dt={record['dt_seconds']}s "
              f"at ({record['latitude']},{record['longitude']})")

    def _strike(self, sub_id, reason, record):
        key = (sub_id, reason)
        self.strikes[key] = self.strikes.get(key, 0) + 1
        if self.strikes[key] >= self.persistence:
            self._log(record)
            self.strikes[key] = 0  # avoid re-logging every tick once confirmed

    def _clear_other_strikes(self, sub_id, seen_reasons):
        for key in list(self.strikes.keys()):
            if key[0] == sub_id and key[1] not in seen_reasons:
                self.strikes[key] = 0

    def process_tick(self, devices):
        computed_speeds = {}
        distances = {}
        dts = {}

        for dev in devices:
            sub_id = dev["subscriber_id"]
            ts = datetime.datetime.fromisoformat(dev["timestamp"])
            lat, lon = dev["latitude"], dev["longitude"]

            prev = self.prev.get(sub_id)
            if prev is not None:
                plat, plon, pts = prev
                dt_seconds = (ts - pts).total_seconds()
                if dt_seconds > 0:
                    dist_km = haversine_km(plat, plon, lat, lon)
                    speed_kmh = dist_km / (dt_seconds / 3600.0)
                    computed_speeds[sub_id] = speed_kmh
                    distances[sub_id] = dist_km
                    dts[sub_id] = dt_seconds

            self.prev[sub_id] = (lat, lon, ts)

        if len(computed_speeds) < 2:
            return

        mean_speed = statistics.mean(computed_speeds.values())
        stdev_speed = statistics.pstdev(computed_speeds.values()) or 1e-6

        by_id = {d["subscriber_id"]: d for d in devices}
        for sub_id, speed in computed_speeds.items():
            dev = by_id[sub_id]
            zscore = (speed - mean_speed) / stdev_speed
            seen_reasons = []

            record_base = {
                "subscriber_id": sub_id,
                "checked_at": datetime.datetime.now().isoformat(),
                "latitude": dev["latitude"],
                "longitude": dev["longitude"],
                "computed_speed_kmh": round(speed, 1),
                "dt_seconds": round(dts[sub_id], 2),
                "distance_km": round(distances[sub_id], 4),
            }

            if speed > self.teleport_cap:
                seen_reasons.append("teleport_jump")
                self._strike(sub_id, "teleport_jump",
                             {**record_base, "reason": "teleport_jump",
                              "detail": f"implies speed > {self.teleport_cap} km/h over {dts[sub_id]:.1f}s - likely GPS jump/spoofing, not real movement"})
            elif speed > self.speed_cap:
                seen_reasons.append("excessive_speed")
                self._strike(sub_id, "excessive_speed",
                             {**record_base, "reason": "excessive_speed",
                              "detail": f"exceeds configured cap of {self.speed_cap} km/h"})

            if abs(zscore) > self.zscore_cap:
                seen_reasons.append("population_outlier")
                self._strike(sub_id, "population_outlier",
                             {**record_base, "reason": "population_outlier",
                              "detail": f"z-score {zscore:.2f} vs current population mean {mean_speed:.1f} km/h"})

            self._clear_other_strikes(sub_id, seen_reasons)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positions",
                     default=os.path.join(SCRIPT_DIR, "..", "simulation", "live_positions.json"))
    ap.add_argument("--log", default=os.path.join(SCRIPT_DIR, "anomalies_log.jsonl"))
    ap.add_argument("--poll", type=float, default=0.5, help="seconds between checks for a new snapshot")
    ap.add_argument("--speed-cap", type=float, default=120.0, help="km/h - flag above this")
    ap.add_argument("--teleport-cap", type=float, default=300.0, help="km/h - implausible, likely a data/GPS glitch")
    ap.add_argument("--zscore-cap", type=float, default=3.0, help="flag if |z-score| vs current population exceeds this")
    ap.add_argument("--persistence", type=int, default=2, help="consecutive anomalous ticks required before logging")
    args = ap.parse_args()

    agent = MonitoringAgent(args.speed_cap, args.teleport_cap, args.zscore_cap, args.persistence, args.log)

    print(f"Monitoring {args.positions} -> alerts in {args.log}")
    print(f"speed_cap={args.speed_cap}km/h teleport_cap={args.teleport_cap}km/h "
          f"zscore_cap={args.zscore_cap} persistence={args.persistence} ticks")
    print("Ctrl+C to stop.")

    last_seen = None
    try:
        while True:
            if os.path.exists(args.positions):
                try:
                    snapshot = load_snapshot(args.positions)
                except (json.JSONDecodeError, OSError):
                    snapshot = None  # simulator mid-write, skip this poll

                if snapshot and snapshot["generated_at"] != last_seen:
                    last_seen = snapshot["generated_at"]
                    agent.process_tick(snapshot["devices"])

            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
