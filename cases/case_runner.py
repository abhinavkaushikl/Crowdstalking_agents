#!/usr/bin/env python3
"""
Offline evaluation harness for the crowd-anomaly detector.

This does NOT touch the live simulator/detector/map-app processes - it runs
its own fast, in-memory copy of the exact same movement model and detection
algorithm (same constants as live_position_simulator.py / crowd_anomaly_agent.py),
driven by a virtual clock instead of real wall-clock time, so a full case
(minutes of simulated time) finishes in a couple of seconds.

It produces, per case, in cases/<case_name>/:
  - report.json   : ground truth vs. what the detector actually flagged
  - report.md      : human-readable summary (recall / false positives / latency)
  - snapshot.svg    : a rendered view of device positions + flagged cells at the
                      moment of peak detection (NOT a browser screenshot - this
                      session has no Chrome/browser control available, so this is
                      a direct plot of the same underlying data the live map
                      would show)

Every run uses a freshly random seed (printed and saved for traceability, but
not fixed), so locations/timings/participant counts differ each time.

Usage: python3 -I case_runner.py
"""
import json
import math
import os
import random
import statistics
import time

SCRIPT_DIR = os.path.dirname(__file__)

LAT_MIN, LAT_MAX = 50.0150, 50.1900
LON_MIN, LON_MAX = 8.4730, 8.8000

MODES = {"stationary": (0.0, 1.5), "walking": (3.0, 6.0), "driving": (15.0, 70.0)}
MODE_NAMES = list(MODES.keys())
MODE_WEIGHTS = [40, 35, 25]
TICK_SECONDS = 2.0
N_DEVICES = 750

# --- detector constants, identical to social-media-sentiment-agent/crowd_anomaly_agent.py ---
GRID_N = 4
MIN_DEVICES_PER_CELL = 20
OUTWARD_FRACTION_THRESHOLD = 0.55
INWARD_FRACTION_THRESHOLD = 0.55
PANIC_MIN_SPEED_KMH = 6.0
VARIANCE_ZSCORE_THRESHOLD = 4.0
PERSISTENCE_TICKS = 3
BASELINE_WINDOW = 30
GRACE_SECONDS = 10  # how long after an incident ends a flag still counts as a true positive


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def cell_index(lat, lon):
    gi = min(max(int((lat - LAT_MIN) / (LAT_MAX - LAT_MIN) * GRID_N), 0), GRID_N - 1)
    gj = min(max(int((lon - LON_MIN) / (LON_MAX - LON_MIN) * GRID_N), 0), GRID_N - 1)
    return gi, gj


def cell_center(gi, gj):
    lat_step = (LAT_MAX - LAT_MIN) / GRID_N
    lon_step = (LON_MAX - LON_MIN) / GRID_N
    return LAT_MIN + (gi + 0.5) * lat_step, LON_MIN + (gj + 0.5) * lon_step


def cell_bounds(gi, gj):
    lat_step = (LAT_MAX - LAT_MIN) / GRID_N
    lon_step = (LON_MAX - LON_MIN) / GRID_N
    return (LAT_MIN + gi * lat_step, LAT_MIN + (gi + 1) * lat_step,
            LON_MIN + gj * lon_step, LON_MIN + (gj + 1) * lon_step)


def point_in_cell(lat, lon, gi, gj):
    lat_min, lat_max, lon_min, lon_max = cell_bounds(gi, gj)
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


class Device:
    __slots__ = ("id", "lat", "lon", "heading", "mode", "speed", "next_turn_at")

    def __init__(self, dev_id, now):
        self.id = dev_id
        self.lat = random.uniform(LAT_MIN, LAT_MAX)
        self.lon = random.uniform(LON_MIN, LON_MAX)
        self.heading = random.uniform(0, 360)
        self.mode = random.choices(MODE_NAMES, weights=MODE_WEIGHTS, k=1)[0]
        lo, hi = MODES[self.mode]
        self.speed = random.uniform(lo, hi)
        self.next_turn_at = now + random.uniform(5, 20)

    def maybe_turn(self, now):
        if now < self.next_turn_at:
            return
        self.heading = (self.heading + random.choice([-1, 1]) * random.uniform(30, 120)) % 360
        if random.random() < 0.15:
            self.mode = random.choices(MODE_NAMES, weights=MODE_WEIGHTS, k=1)[0]
        lo, hi = MODES[self.mode]
        self.speed = random.uniform(lo, hi)
        self.next_turn_at = now + random.uniform(5, 20)

    def step(self, dt_seconds):
        distance_km = self.speed * (dt_seconds / 3600.0)
        rad = math.radians(self.heading)
        dlat = (distance_km / 111.32) * math.cos(rad)
        dlon = (distance_km / (111.32 * math.cos(math.radians(self.lat)) + 1e-9)) * math.sin(rad)
        new_lat, new_lon = self.lat + dlat, self.lon + dlon
        if not (LAT_MIN <= new_lat <= LAT_MAX):
            self.heading = (180 - self.heading) % 360
            new_lat = max(LAT_MIN, min(LAT_MAX, new_lat))
        if not (LON_MIN <= new_lon <= LON_MAX):
            self.heading = (360 - self.heading) % 360
            new_lon = max(LON_MIN, min(LON_MAX, new_lon))
        self.lat, self.lon = new_lat, new_lon


class Detector:
    """Exact re-implementation of crowd_anomaly_agent.py's algorithm, operating
    directly on in-memory Device objects each tick instead of polling a JSON file."""

    def __init__(self):
        self.prev = {}
        self.baselines = {}
        self.strikes = {}
        self.flags = []  # confirmed flags: dict(sim_time, cell, reason, detail, device_count, mean_speed)

    def process_tick(self, devices, sim_time):
        cells = {}
        for d in devices:
            prev = self.prev.get(d.id)
            self.prev[d.id] = (d.lat, d.lon)
            if prev is None:
                continue
            plat, plon = prev
            dx_km = (d.lon - plon) * 111.32 * math.cos(math.radians(plat))
            dy_km = (d.lat - plat) * 111.32
            move_dist_km = math.hypot(dx_km, dy_km)
            speed_kmh = move_dist_km / (TICK_SECONDS / 3600.0)

            gi, gj = cell_index(d.lat, d.lon)
            radial_component = 0.0
            if move_dist_km > 1e-6:
                clat, clon = cell_center(gi, gj)
                out_x = (plon - clon) * 111.32 * math.cos(math.radians(clat))
                out_y = (plat - clat) * 111.32
                out_norm = math.hypot(out_x, out_y) + 1e-9
                radial_component = (dx_km * out_x + dy_km * out_y) / (move_dist_km * out_norm)

            cells.setdefault((gi, gj), []).append((speed_kmh, radial_component))

        for (gi, gj), samples in cells.items():
            count = len(samples)
            if count < MIN_DEVICES_PER_CELL:
                continue
            speeds = [s for s, _ in samples]
            radials = [r for _, r in samples]
            mean_speed = statistics.mean(speeds)
            var_speed = statistics.pvariance(speeds) if count > 1 else 0.0
            frac_outward = sum(1 for r in radials if r > 0.5) / count
            frac_inward = sum(1 for r in radials if r < -0.5) / count

            base = self.baselines.setdefault((gi, gj), {"var_speed": []})
            reasons = []
            if frac_outward >= OUTWARD_FRACTION_THRESHOLD and mean_speed >= PANIC_MIN_SPEED_KMH:
                reasons.append(("panic_outward", f"{frac_outward:.0%} of {count} moving outward, {mean_speed:.1f} km/h"))
            if frac_inward >= INWARD_FRACTION_THRESHOLD:
                reasons.append(("crush_inward", f"{frac_inward:.0%} of {count} converging"))
            hist = base["var_speed"]
            if len(hist) >= 5:
                bm, bs = statistics.mean(hist), (statistics.pstdev(hist) or 1e-6)
                z = (var_speed - bm) / bs
                if z > VARIANCE_ZSCORE_THRESHOLD:
                    reasons.append(("variance_spike", f"variance z-score {z:.1f}"))
            hist.append(var_speed)
            if len(hist) > BASELINE_WINDOW:
                hist.pop(0)

            seen = set()
            for reason, detail in reasons:
                key = (gi, gj, reason)
                self.strikes[key] = self.strikes.get(key, 0) + 1
                seen.add(reason)
                if self.strikes[key] >= PERSISTENCE_TICKS:
                    self.flags.append({
                        "sim_time": sim_time, "cell": (gi, gj), "reason": reason,
                        "detail": detail, "device_count": count, "mean_speed_kmh": round(mean_speed, 1),
                    })
                    self.strikes[key] = 0
            for k in list(self.strikes.keys()):
                if k[0] == gi and k[1] == gj and k[2] not in seen:
                    self.strikes[k] = 0


def apply_panic(devices, center_lat, center_lon, radius_km, speed_range):
    for d in devices:
        if haversine_km(d.lat, d.lon, center_lat, center_lon) <= radius_km:
            d.heading = (bearing_deg(center_lat, center_lon, d.lat, d.lon) + random.uniform(-15, 15)) % 360
            d.speed = random.uniform(*speed_range)


def apply_convergence(devices, participant_ids, target_lat, target_lon, speed_range):
    targets = {d.id: d for d in devices}
    for pid in participant_ids:
        d = targets.get(pid)
        if d is None:
            continue
        d.heading = (bearing_deg(d.lat, d.lon, target_lat, target_lon) + random.uniform(-8, 8)) % 360
        d.speed = random.uniform(*speed_range)
