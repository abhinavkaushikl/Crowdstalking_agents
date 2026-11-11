#!/usr/bin/env python3
"""
Population-level crowd anomaly detector - never flags an individual.

Watches live_positions.json and, per spatial grid cell, checks whether many
devices are moving in a correlated, unusual way AT THE SAME TIME:
  - panic_outward : a large share of devices in a cell are suddenly moving
                     away from a common point, faster than normal
  - crush_inward  : a large share are suddenly converging on a common point
  - variance_spike: the spread of speeds in a cell jumps far above its own
                     recent baseline (something changed, even if direction
                     isn't yet coherent)

Everything here is a statistic over however many devices happen to be in a
cell (count, mean, variance, fraction-aligned) - no subscriber_id is ever
part of a flag, and the detector deliberately ignores the simulator's
"_debug_incident" ground truth field (that's only for us to verify it works).

Usage:
    python3 -I crowd_anomaly_agent.py
Stop with Ctrl+C.
"""
import argparse
import collections
import datetime
import json
import math
import os
import statistics
import time

SCRIPT_DIR = os.path.dirname(__file__)

LAT_MIN, LAT_MAX = 50.0150, 50.1900
LON_MIN, LON_MAX = 8.4730, 8.8000

# Grid resolution is a statistical choice, not just a visual one. A random,
# UNCORRELATED heading has ~1/3 chance of landing within +-60 deg of any given
# direction, so a cell's "fraction moving outward" fluctuates a lot by pure
# chance when a cell only holds a handful of devices (std-err ~ sqrt(p(1-p)/n)).
# At n=5-9 (8x8 grid over 750 devices) that noise alone crosses a 0.55
# threshold constantly - confirmed empirically (dozens of false "flags" per
# tick, scattered across unrelated cells, in a live test run). Using fewer,
# bigger cells (n~45+) pushes that same threshold to a ~3-sigma, genuinely
# rare event under pure chance, so a flag means something.
GRID_N = 4  # 4x4 cells, ~4.8km x 5.9km each over Frankfurt -> ~45 devices/cell at N=750
MIN_DEVICES_PER_CELL = 20

OUTWARD_FRACTION_THRESHOLD = 0.55  # ceiling: the threshold never gets stricter than this
INWARD_FRACTION_THRESHOLD = 0.55
# Devices that walk real streets can't all head straight at/away from a point
# (zigzags, tangential roads), so even a genuine incident tops out around
# 0.51-0.57 of a cell -- right on a fixed 0.55 line, which made detection a coin
# flip once movement became street-constrained. Under "no incident" a random
# heading is within +-60 deg of any direction with p0 = 1/3, so the threshold is
# instead set RADIAL_Z standard errors above that null (see fraction_threshold),
# which relaxes toward RADIAL_FRACTION_FLOOR in well-populated cells and falls
# back to the old 0.55 in sparse ones.
RADIAL_NULL_P = 1.0 / 3.0
RADIAL_Z = 5.0
RADIAL_FRACTION_FLOOR = 0.40
PANIC_MIN_SPEED_KMH = 6.0
# Backtested against real recorded pedestrian video (ETH/UCY campus datasets):
# real students funneling toward a building entrance/path junction -- ordinary,
# not an incident -- coherently "converge" at 2.1-2.8 km/h. Every incident this
# codebase has actually triggered (live-tested) measured 9-16 km/h. 4.0 sits
# clearly above the real mundane-funneling band and clearly below real-incident
# speeds, so it separates the two without the cushion panic_outward's 6.0 has.
CRUSH_MIN_SPEED_KMH = 4.0
VARIANCE_ZSCORE_THRESHOLD = 4.0
PERSISTENCE_TICKS = 3
BASELINE_WINDOW = 30


def fraction_threshold(count, ceiling):
    """Smallest aligned-fraction that is RADIAL_Z standard errors above the
    random-heading null for a cell holding `count` devices, clamped to
    [RADIAL_FRACTION_FLOOR, ceiling]."""
    se = math.sqrt(RADIAL_NULL_P * (1 - RADIAL_NULL_P) / count)
    return min(ceiling, max(RADIAL_FRACTION_FLOOR, RADIAL_NULL_P + RADIAL_Z * se))


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
    return {
        "lat_min": LAT_MIN + gi * lat_step, "lat_max": LAT_MIN + (gi + 1) * lat_step,
        "lon_min": LON_MIN + gj * lon_step, "lon_max": LON_MIN + (gj + 1) * lon_step,
    }


ACTIVE_FLAG_DECAY_SECONDS = 12  # how long a polygon stays on the map after its last confirmation


def haversine_km_simple(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def hotspot_from_points(points):
    """Centroid + covering radius of the specific devices behind a flag, so the
    map can draw a tight circle on the real incident instead of the whole
    (several-km) detector grid cell. Detection thresholds above are untouched;
    this only describes geometry for a flag that already fired."""
    if not points:
        return None
    clat = sum(p[0] for p in points) / len(points)
    clon = sum(p[1] for p in points) / len(points)
    radius_km = max(haversine_km_simple(clat, clon, p[0], p[1]) for p in points)
    return {"lat": round(clat, 5), "lon": round(clon, 5), "radius_km": round(max(radius_km, 0.05), 3)}


class CrowdAnomalyAgent:
    def __init__(self, log_path, risk_path):
        self.log_path = log_path
        self.risk_path = risk_path
        self.prev = {}  # subscriber_id -> (lat, lon, timestamp)
        self.baselines = collections.defaultdict(
            lambda: {"mean_speed": collections.deque(maxlen=BASELINE_WINDOW),
                     "var_speed": collections.deque(maxlen=BASELINE_WINDOW)})
        self.strikes = collections.defaultdict(int)
        self.active_flags = {}  # (gi,gj,reason) -> {record..., "last_seen": epoch_seconds}

    def _log(self, record):
        with open(self.log_path, "a") as f:
            f.write(json.dumps(record) + "\n")
        print(f"[CROWD FLAG] cell={record['cell']} {record['reason']} "
              f"devices={record['device_count']} {record['detail']}")
        key = (record["cell"][0], record["cell"][1], record["reason"])
        self.active_flags[key] = {**record, "last_seen": time.time()}

    def write_risk_snapshot(self, checked_at):
        now = time.time()
        for key in list(self.active_flags.keys()):
            if now - self.active_flags[key]["last_seen"] > ACTIVE_FLAG_DECAY_SECONDS:
                del self.active_flags[key]

        snapshot = {"generated_at": checked_at, "flags": list(self.active_flags.values())}
        # per-PID tmp filename -- two instances racing on a shared ".tmp" path
        # (e.g. an old process not actually killed, confirmed to happen live)
        # otherwise crashes: process A's os.replace() can consume process B's
        # tmp file out from under it, raising FileNotFoundError.
        tmp_path = f"{self.risk_path}.{os.getpid()}.tmp"
        with open(tmp_path, "w") as f:
            json.dump(snapshot, f)
        os.replace(tmp_path, self.risk_path)

    def process_tick(self, devices, checked_at):
        cells = collections.defaultdict(list)  # (gi,gj) -> list of (speed_kmh, radial_component, lat, lon)

        for dev in devices:
            sub_id = dev["subscriber_id"]
            ts = datetime.datetime.fromisoformat(dev["timestamp"])
            lat, lon = dev["latitude"], dev["longitude"]

            prev = self.prev.get(sub_id)
            self.prev[sub_id] = (lat, lon, ts)
            if prev is None:
                continue
            plat, plon, pts = prev
            dt_seconds = (ts - pts).total_seconds()
            if dt_seconds <= 0:
                continue

            dx_km = (lon - plon) * 111.32 * math.cos(math.radians(plat))
            dy_km = (lat - plat) * 111.32
            move_dist_km = math.hypot(dx_km, dy_km)
            speed_kmh = move_dist_km / (dt_seconds / 3600.0)

            gi, gj = cell_index(lat, lon)
            radial_component = 0.0
            if move_dist_km > 1e-6:
                clat, clon = cell_center(gi, gj)
                out_x = (plon - clon) * 111.32 * math.cos(math.radians(clat))
                out_y = (plat - clat) * 111.32
                out_norm = math.hypot(out_x, out_y) + 1e-9
                radial_component = (dx_km * out_x + dy_km * out_y) / (move_dist_km * out_norm)

            cells[(gi, gj)].append((speed_kmh, radial_component, lat, lon))

        for (gi, gj), samples in cells.items():
            count = len(samples)
            if count < MIN_DEVICES_PER_CELL:
                continue

            speeds = [s for s, _, _, _ in samples]
            radials = [r for _, r, _, _ in samples]
            mean_speed = statistics.mean(speeds)
            var_speed = statistics.pvariance(speeds) if count > 1 else 0.0
            frac_outward = sum(1 for r in radials if r > 0.5) / count
            frac_inward = sum(1 for r in radials if r < -0.5) / count

            base = self.baselines[(gi, gj)]
            reasons = []

            if (frac_outward >= fraction_threshold(count, OUTWARD_FRACTION_THRESHOLD)
                    and mean_speed >= PANIC_MIN_SPEED_KMH):
                reasons.append(("panic_outward",
                                 f"{frac_outward:.0%} of {count} devices moving away from a common point, "
                                 f"mean speed {mean_speed:.1f} km/h"))

            if (frac_inward >= fraction_threshold(count, INWARD_FRACTION_THRESHOLD)
                    and mean_speed >= CRUSH_MIN_SPEED_KMH):
                reasons.append(("crush_inward",
                                 f"{frac_inward:.0%} of {count} devices converging on a common point, "
                                 f"mean speed {mean_speed:.1f} km/h"))

            if len(base["var_speed"]) >= 5:
                base_mean = statistics.mean(base["var_speed"])
                base_std = statistics.pstdev(base["var_speed"]) or 1e-6
                zscore = (var_speed - base_mean) / base_std
                if zscore > VARIANCE_ZSCORE_THRESHOLD:
                    reasons.append(("variance_spike",
                                     f"speed variance z-score {zscore:.1f} vs this cell's recent baseline"))

            base["mean_speed"].append(mean_speed)
            base["var_speed"].append(var_speed)

            seen = set()
            for reason, detail in reasons:
                key = (gi, gj, reason)
                self.strikes[key] += 1
                seen.add(reason)
                if self.strikes[key] >= PERSISTENCE_TICKS:
                    clat, clon = cell_center(gi, gj)
                    if reason == "panic_outward":
                        hotspot = hotspot_from_points([(lat, lon) for _, r, lat, lon in samples if r > 0.5])
                    elif reason == "crush_inward":
                        hotspot = hotspot_from_points([(lat, lon) for _, r, lat, lon in samples if r < -0.5])
                    else:
                        hotspot = None  # variance_spike has no directional subset; cell-level only
                    self._log({
                        "checked_at": checked_at,
                        "cell": [gi, gj],
                        "cell_center": [round(clat, 5), round(clon, 5)],
                        "bounds": cell_bounds(gi, gj),
                        "hotspot": hotspot,
                        "device_count": count,
                        "mean_speed_kmh": round(mean_speed, 1),
                        "speed_variance": round(var_speed, 2),
                        "reason": reason,
                        "detail": detail,
                    })
                    self.strikes[key] = 0
            for (gi2, gj2, reason) in list(self.strikes.keys()):
                if (gi2, gj2) == (gi, gj) and reason not in seen:
                    self.strikes[(gi2, gj2, reason)] = 0

        self.write_risk_snapshot(checked_at)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--positions",
                     default=os.path.join(SCRIPT_DIR, "..", "simulation", "live_positions.json"))
    ap.add_argument("--log", default=os.path.join(SCRIPT_DIR, "crowd_anomalies_log.jsonl"))
    ap.add_argument("--risk-out", default=os.path.join(SCRIPT_DIR, "crowd_risk.json"))
    ap.add_argument("--poll", type=float, default=0.5)
    args = ap.parse_args()

    agent = CrowdAnomalyAgent(args.log, args.risk_out)
    print(f"Monitoring {args.positions} for population-level crowd anomalies -> {args.log}")
    print(f"grid={GRID_N}x{GRID_N} min_devices_per_cell={MIN_DEVICES_PER_CELL} persistence={PERSISTENCE_TICKS} ticks")
    print("Ctrl+C to stop.")

    last_seen = None
    try:
        while True:
            if os.path.exists(args.positions):
                try:
                    with open(args.positions) as f:
                        snapshot = json.load(f)
                except (json.JSONDecodeError, OSError):
                    snapshot = None

                if snapshot and snapshot["generated_at"] != last_seen:
                    last_seen = snapshot["generated_at"]
                    agent.process_tick(snapshot["devices"], snapshot["generated_at"])

            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
