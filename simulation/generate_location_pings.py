#!/usr/bin/env python3
"""
Generates a SYNTHETIC time-series of location pings per subscriber, so that
speed/heading can be derived by diffing consecutive lat/lon + timestamp pairs
(see synthetic_subscribers_frankfurt.csv for the one-row-per-subscriber master
table this joins against on subscriber_id). Every value is randomly generated.
"""
import csv
import math
import random
import datetime
import os

random.seed(7)

N_SUBSCRIBERS = 750_000
PINGS_PER_SUB = 6
INTERVAL_MIN = 10  # minutes between pings -> 50 min trajectory window

OUT_PATH = os.path.join(os.path.dirname(__file__), "location_pings_frankfurt.csv")

LAT_MIN, LAT_MAX = 50.0150, 50.1900
LON_MIN, LON_MAX = 8.4730, 8.8000

NETWORK_TYPES = ["5G"] * 55 + ["4G"] * 40 + ["3G"] * 5

# movement_mode: (probability_weight, speed_kmh_range, max_turn_deg_per_step)
MODES = [
    ("stationary", 40, (0.0, 1.5), 60),
    ("walking",    35, (3.0, 6.0), 35),
    ("driving",    25, (15.0, 70.0), 12),
]
MODE_NAMES = [m[0] for m in MODES]
MODE_WEIGHTS = [m[1] for m in MODES]
MODE_SPEED = {m[0]: m[2] for m in MODES}
MODE_TURN = {m[0]: m[3] for m in MODES}

# Pre-generate ~400 synthetic cell tower sites (same layout style as the
# subscriber master generator) and a coarse grid -> nearest-tower lookup so
# every ping can get a plausible cell_id/lac in O(1) instead of brute force.
N_TOWERS = 400
TOWERS = []
for i in range(N_TOWERS):
    TOWERS.append({
        "cell_id": f"FRA-{i:04d}",
        "lac": f"{random.randint(10000, 19999)}",
        "lat": random.uniform(LAT_MIN, LAT_MAX),
        "lon": random.uniform(LON_MIN, LON_MAX),
    })

GRID_N = 60
lat_step = (LAT_MAX - LAT_MIN) / GRID_N
lon_step = (LON_MAX - LON_MIN) / GRID_N
NEAREST_TOWER_GRID = [[None] * GRID_N for _ in range(GRID_N)]
for gi in range(GRID_N):
    cell_lat = LAT_MIN + (gi + 0.5) * lat_step
    for gj in range(GRID_N):
        cell_lon = LON_MIN + (gj + 0.5) * lon_step
        best_idx, best_d2 = 0, float("inf")
        for idx, t in enumerate(TOWERS):
            d2 = (t["lat"] - cell_lat) ** 2 + (t["lon"] - cell_lon) ** 2
            if d2 < best_d2:
                best_d2, best_idx = d2, idx
        NEAREST_TOWER_GRID[gi][gj] = best_idx


def nearest_tower(lat, lon):
    gi = min(max(int((lat - LAT_MIN) / lat_step), 0), GRID_N - 1)
    gj = min(max(int((lon - LON_MIN) / lon_step), 0), GRID_N - 1)
    return TOWERS[NEAREST_TOWER_GRID[gi][gj]]


def move(lat, lon, heading_deg, speed_kmh, minutes):
    distance_km = speed_kmh * (minutes / 60.0)
    rad = math.radians(heading_deg)
    dlat = (distance_km / 111.32) * math.cos(rad)
    dlon = (distance_km / (111.32 * math.cos(math.radians(lat)) + 1e-9)) * math.sin(rad)
    new_lat = lat + dlat
    new_lon = lon + dlon
    # bounce off the bbox edges instead of wandering out of Frankfurt
    if not (LAT_MIN <= new_lat <= LAT_MAX):
        heading_deg = (180 - heading_deg) % 360
        new_lat = max(LAT_MIN, min(LAT_MAX, new_lat))
    if not (LON_MIN <= new_lon <= LON_MAX):
        heading_deg = (360 - heading_deg) % 360
        new_lon = max(LON_MIN, min(LON_MAX, new_lon))
    return new_lat, new_lon, heading_deg


NOW = datetime.datetime(2026, 10, 22, 12, 0, 0)
START = NOW - datetime.timedelta(minutes=INTERVAL_MIN * (PINGS_PER_SUB - 1))
PING_TIMES = [START + datetime.timedelta(minutes=INTERVAL_MIN * i) for i in range(PINGS_PER_SUB)]

HEADER = [
    "subscriber_id", "ping_seq", "timestamp", "latitude", "longitude",
    "cell_id", "lac", "signal_strength_dbm", "network_type",
    "movement_mode", "speed_kmh", "heading_deg",
]


def gen_trajectory(sub_i):
    mode = random.choices(MODE_NAMES, weights=MODE_WEIGHTS, k=1)[0]
    lo, hi = MODE_SPEED[mode]
    max_turn = MODE_TURN[mode]

    lat = random.uniform(LAT_MIN, LAT_MAX)
    lon = random.uniform(LON_MIN, LON_MAX)
    heading = random.uniform(0, 360)

    rows = []
    for seq, ts in enumerate(PING_TIMES):
        speed = round(random.uniform(lo, hi), 1)
        tower = nearest_tower(lat, lon)
        rows.append([
            f"SUB-{sub_i:08d}", seq, ts.isoformat(),
            round(lat, 6), round(lon, 6),
            tower["cell_id"], tower["lac"],
            random.randint(-115, -55), random.choice(NETWORK_TYPES),
            mode, speed, round(heading, 1),
        ])
        heading = (heading + random.uniform(-max_turn, max_turn)) % 360
        lat, lon, heading = move(lat, lon, heading, speed, INTERVAL_MIN)
    return rows


def main():
    with open(OUT_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        batch = []
        for sub_i in range(1, N_SUBSCRIBERS + 1):
            batch.extend(gen_trajectory(sub_i))
            if len(batch) >= 20_000:
                writer.writerows(batch)
                batch.clear()
        if batch:
            writer.writerows(batch)
    n_rows = N_SUBSCRIBERS * PINGS_PER_SUB
    size_mb = os.path.getsize(OUT_PATH) / (1024 * 1024)
    print(f"Wrote {n_rows} rows ({N_SUBSCRIBERS} subscribers x {PINGS_PER_SUB} pings) "
          f"to {OUT_PATH} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
