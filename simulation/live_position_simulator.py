#!/usr/bin/env python3
"""
Runs continuously and keeps a set of SYNTHETIC devices moving in real time
(walking / driving / stationary), writing the latest positions to
live_positions.json every tick so another process (e.g. map-app) can poll it.

No calculation of speed from static data - this generates live movement
directly: each tick moves every device by (speed * real elapsed time) along
the real OSM street graph (osm-extract/data/*.index.json), turning only at
actual street intersections instead of a free-space random heading.

Usage:
    python3 -I live_position_simulator.py
    python3 -I live_position_simulator.py --devices 500 --tick 1.0
Stop with Ctrl+C.
"""
import argparse
import json
import os
import random
import sys
import time
import datetime

# python -I (isolated mode, used by this project's run instructions) does not
# add the script's own directory to sys.path on this Python build, which
# breaks the local street_graph import below unless we add it ourselves.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from street_graph import load_street_graph, haversine_km, bearing_deg

LAT_MIN, LAT_MAX = 50.0150, 50.1900
LON_MIN, LON_MAX = 8.4730, 8.8000

STREET_INDEX_PATH = os.path.join(
    os.path.dirname(__file__), "..", "osm-extract", "data", "Frankfurt.index.json"
)

MODES = {
    "stationary": (0.0, 1.5),
    "walking":    (3.0, 6.0),
    "driving":    (15.0, 70.0),
}
MODE_NAMES = list(MODES.keys())
MODE_WEIGHTS = [40, 35, 25]

N_TOWERS = 400

# Must match crowd_anomaly_agent.py's own GRID_N/bbox exactly. Forced protest/riot
# incidents are centered on a detector grid cell's own center (not an arbitrary
# point) so the "moving toward a common point" measurement -- which the detector
# computes relative to ITS cell center -- lines up cleanly instead of being diluted
# by a mismatch between where the crowd actually gathers and where the detector
# looks for it.
DETECTOR_GRID_N = 4


def grid_cell_centers():
    lat_step = (LAT_MAX - LAT_MIN) / DETECTOR_GRID_N
    lon_step = (LON_MAX - LON_MIN) / DETECTOR_GRID_N
    centers = []
    for gi in range(DETECTOR_GRID_N):
        for gj in range(DETECTOR_GRID_N):
            centers.append((LAT_MIN + (gi + 0.5) * lat_step, LON_MIN + (gj + 0.5) * lon_step))
    return centers

# Crowd-incident injection: periodically forces a cluster of nearby devices to
# move in a correlated way (everyone fleeing a point, or everyone converging
# on one) so there is something real for a population-level anomaly detector
# to catch. Ground truth is exposed under "_debug_incident" for validating
# the detector while building it - a real detector must not read that field.
INCIDENT_CHANCE_PER_TICK = 0.01   # ~ once every 3 min of sim time at a 2s tick
INCIDENT_DURATION_RANGE = (20, 40)   # seconds
INCIDENT_RADIUS_KM_RANGE = (0.3, 0.6)   # panic_outward: who's close enough to flee
CONVERGENCE_FRACTION = 0.01             # mass_convergence: ~1% of the whole population
MIN_CONVERGENCE_PARTICIPANTS = 5


def maybe_spawn_incident(active_incident, now, devices):
    if active_incident is not None:
        return active_incident
    if random.random() >= INCIDENT_CHANCE_PER_TICK:
        return None

    kind = random.choice(["panic_outward", "mass_convergence"])
    end_time = now + random.uniform(*INCIDENT_DURATION_RANGE)

    if kind == "panic_outward":
        incident = {
            "kind": kind,
            "center_lat": random.uniform(LAT_MIN, LAT_MAX),
            "center_lon": random.uniform(LON_MIN, LON_MAX),
            "radius_km": random.uniform(*INCIDENT_RADIUS_KM_RANGE),
            "end_time": end_time,
        }
        print(f"\n*** INCIDENT STARTED: panic_outward near ({incident['center_lat']:.5f},{incident['center_lon']:.5f}) "
              f"radius={incident['radius_km']:.2f}km for ~{end_time - now:.0f}s - only nearby devices flee ***\n")
    else:
        n_participants = max(MIN_CONVERGENCE_PARTICIPANTS, round(len(devices) * CONVERGENCE_FRACTION))
        participants = set(random.sample([d.id for d in devices], n_participants))
        incident = {
            "kind": kind,
            "target_lat": random.uniform(LAT_MIN, LAT_MAX),
            "target_lon": random.uniform(LON_MIN, LON_MAX),
            "participants": participants,
            "end_time": end_time,
        }
        print(f"\n*** INCIDENT STARTED: mass_convergence - {len(participants)} devices "
              f"({len(participants) / len(devices):.1%} of population) rushing toward command ground "
              f"({incident['target_lat']:.5f},{incident['target_lon']:.5f}) from scattered starting points "
              f"for ~{end_time - now:.0f}s - rest of the city stays normal ***\n")
    return incident


def build_towers():
    towers = []
    for i in range(N_TOWERS):
        towers.append({
            "cell_id": f"FRA-{i:04d}",
            "lac": f"{random.randint(10000, 19999)}",
            "lat": random.uniform(LAT_MIN, LAT_MAX),
            "lon": random.uniform(LON_MIN, LON_MAX),
        })
    return towers


def build_tower_grid(towers, grid_n=60):
    lat_step = (LAT_MAX - LAT_MIN) / grid_n
    lon_step = (LON_MAX - LON_MIN) / grid_n
    grid = [[0] * grid_n for _ in range(grid_n)]
    for gi in range(grid_n):
        cell_lat = LAT_MIN + (gi + 0.5) * lat_step
        for gj in range(grid_n):
            cell_lon = LON_MIN + (gj + 0.5) * lon_step
            best_idx, best_d2 = 0, float("inf")
            for idx, t in enumerate(towers):
                d2 = (t["lat"] - cell_lat) ** 2 + (t["lon"] - cell_lon) ** 2
                if d2 < best_d2:
                    best_d2, best_idx = d2, idx
            grid[gi][gj] = best_idx
    return grid, lat_step, lon_step, grid_n


CLUSTER_MODE_WEIGHTS_BY_NAME = {"stationary": 70, "walking": 30, "driving": 0}


class Device:
    """Moves along the real OSM street graph: walks a straight edge between
    two intersections, then picks a connected real street at the node it
    reaches, instead of a free-space heading that ignores roads entirely."""

    __slots__ = ("id", "lat", "lon", "heading", "mode", "speed", "next_turn_at",
                 "cluster_lat", "cluster_lon", "cluster_radius_km",
                 "node_from", "node_to", "frac", "bias_key")

    def __init__(self, dev_id, graph, cluster=None):
        self.id = dev_id
        self.cluster_lat = self.cluster_lon = self.cluster_radius_km = None
        self.bias_key = None
        if cluster:
            clat, clon, cradius_km = cluster
            self.cluster_lat, self.cluster_lon, self.cluster_radius_km = clat, clon, cradius_km
            a, b, frac, lat, lon = graph.random_point_near(clat, clon, cradius_km)
            self.mode = random.choices(list(CLUSTER_MODE_WEIGHTS_BY_NAME.keys()),
                                        weights=list(CLUSTER_MODE_WEIGHTS_BY_NAME.values()), k=1)[0]
        else:
            a, b, frac, lat, lon = graph.random_point()
            self.mode = random.choices(MODE_NAMES, weights=MODE_WEIGHTS, k=1)[0]
        self.node_from, self.node_to, self.frac = a, b, frac
        self.lat, self.lon = lat, lon
        lon1, lat1 = graph.node_pos[a]
        lon2, lat2 = graph.node_pos[b]
        self.heading = bearing_deg(lat1, lon1, lat2, lon2)
        lo, hi = MODES[self.mode]
        self.speed = random.uniform(lo, hi)
        self.next_turn_at = time.time() + random.uniform(5, 20)

    def maybe_turn_or_switch_mode(self, now):
        # Turning now happens naturally at real intersections (see step()).
        # This timer only governs occasional mode/speed changes (e.g. parking
        # the car, starting to walk) independent of reaching a junction.
        if now < self.next_turn_at:
            return
        if random.random() < 0.15:
            if self.cluster_lat is not None:
                self.mode = random.choices(list(CLUSTER_MODE_WEIGHTS_BY_NAME.keys()),
                                            weights=list(CLUSTER_MODE_WEIGHTS_BY_NAME.values()), k=1)[0]
            else:
                self.mode = random.choices(MODE_NAMES, weights=MODE_WEIGHTS, k=1)[0]
            lo, hi = MODES[self.mode]
            self.speed = random.uniform(lo, hi)
        self.next_turn_at = now + random.uniform(5, 20)

    def reroute_now(self, graph, bias):
        """Abandon the rest of the current edge and re-decide direction from
        node_from immediately - used the instant a device becomes affected by
        an incident, so forced demo incidents stay responsive instead of
        waiting out whatever long edge the device happened to be mid-walk on."""
        new_to = graph.choose_next_node(self.node_from, None, self.heading, bias=bias)
        if new_to is not None:
            self.node_to = new_to
            self.frac = 0.0

    def step(self, dt_seconds, graph, bias=None, contain=None):
        distance_km = self.speed * (dt_seconds / 3600.0)
        hops = 0
        while distance_km > 1e-9 and hops < 60:
            edge_len = graph.edge_length_km(self.node_from, self.node_to)
            remaining_on_edge = edge_len * (1.0 - self.frac)
            if distance_km < remaining_on_edge:
                self.frac += distance_km / edge_len if edge_len > 1e-9 else 1.0
                distance_km = 0.0
            else:
                distance_km -= remaining_on_edge
                prev = self.node_from
                self.node_from = self.node_to
                next_node = graph.choose_next_node(self.node_from, prev, self.heading,
                                                     bias=bias, contain=contain)
                if next_node is None:
                    distance_km = 0.0
                    self.frac = 1.0
                    break
                self.node_to = next_node
                self.frac = 0.0
                hops += 1

        lon1, lat1 = graph.node_pos[self.node_from]
        lon2, lat2 = graph.node_pos[self.node_to]
        self.lat = lat1 + (lat2 - lat1) * self.frac
        self.lon = lon1 + (lon2 - lon1) * self.frac
        if self.node_to != self.node_from:
            self.heading = bearing_deg(lat1, lon1, lat2, lon2)


def nearest_tower(lat, lon, towers, grid, lat_step, lon_step, grid_n):
    gi = min(max(int((lat - LAT_MIN) / lat_step), 0), grid_n - 1)
    gj = min(max(int((lon - LON_MIN) / lon_step), 0), grid_n - 1)
    return towers[grid[gi][gj]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--devices", type=int, default=750, help="number of simulated devices")
    ap.add_argument("--tick", type=float, default=2.0, help="seconds between position updates")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "live_positions.json"))
    ap.add_argument("--force-panic-at", type=float, default=None,
                     help="Deterministic demo override: seconds after startup to force a panic_outward "
                          "incident (instead of waiting on the random ~1%%/tick chance)")
    ap.add_argument("--force-panic-lat", type=float, default=None)
    ap.add_argument("--force-panic-lon", type=float, default=None)
    ap.add_argument("--force-panic-radius-km", type=float, default=2.5,
                     help="Wide enough to sweep most of a detector grid cell, so the demo reliably flags")
    ap.add_argument("--force-panic-duration", type=float, default=45.0)
    ap.add_argument("--cluster-lat", type=float, default=None,
                     help="Concert-venue mode: spawn all devices tightly packed around this point "
                          "instead of scattered across the whole city")
    ap.add_argument("--cluster-lon", type=float, default=None)
    ap.add_argument("--cluster-radius-km", type=float, default=0.15,
                     help="How tightly packed the crowd is (default 150m, like a venue/square)")
    ap.add_argument("--concert-devices", type=int, default=None,
                     help="Mixed mode: this many of --devices are a tight concert cluster at "
                          "--cluster-lat/lon, the rest wander the whole city normally (cars/walking/stationary)")
    ap.add_argument("--force-protests", type=int, default=None,
                     help="Protest/riot demo: this many simultaneous crowds converge on random distinct "
                          "detector grid cells at once (crush_inward reason -> rendered yellow)")
    ap.add_argument("--force-protest-at", type=float, default=8.0)
    ap.add_argument("--force-protest-radius-km", type=float, default=2.2)
    ap.add_argument("--force-protest-duration", type=float, default=90.0)
    args = ap.parse_args()

    # Confirmed live: omitting --force-panic-lat/lon left them as None and
    # crashed haversine_km() the moment the forced incident tried to fire
    # (TypeError: must be real number, not NoneType). Default to a random
    # point in the city, same as the organic/random incident path already does.
    if args.force_panic_at is not None:
        if args.force_panic_lat is None:
            args.force_panic_lat = random.uniform(LAT_MIN, LAT_MAX)
        if args.force_panic_lon is None:
            args.force_panic_lon = random.uniform(LON_MIN, LON_MAX)

    towers = build_towers()
    grid, lat_step, lon_step, grid_n = build_tower_grid(towers)

    print(f"Loading street graph from {STREET_INDEX_PATH} ...")
    t0 = time.time()
    street_graph = load_street_graph(STREET_INDEX_PATH, (LAT_MIN, LAT_MAX, LON_MIN, LON_MAX))
    print(f"Street graph ready: {len(street_graph.node_pos)} nodes, {len(street_graph.edges)} edges "
          f"({time.time() - t0:.1f}s) - devices will walk real streets, turning only at real intersections")

    if args.concert_devices is not None:
        if args.cluster_lat is None:
            raise SystemExit("--concert-devices requires --cluster-lat/--cluster-lon")
        n_concert = args.concert_devices
        n_city = args.devices - n_concert
        print(f"Mixed scenario: {n_city} normal city-wide devices + {n_concert} concert-cluster devices "
              f"at ({args.cluster_lat},{args.cluster_lon})")
        cluster = (args.cluster_lat, args.cluster_lon, args.cluster_radius_km)
        devices = (
            [Device(f"SUB-{i:08d}", street_graph, cluster=None) for i in range(1, n_city + 1)]
            + [Device(f"CONCERT-{i:06d}", street_graph, cluster=cluster) for i in range(1, n_concert + 1)]
        )
    else:
        cluster = (args.cluster_lat, args.cluster_lon, args.cluster_radius_km) if args.cluster_lat is not None else None
        devices = [Device(f"SUB-{i:08d}", street_graph, cluster=cluster) for i in range(1, args.devices + 1)]

    print(f"Simulating {args.devices} devices, updating every {args.tick}s -> {args.out}")
    if args.force_panic_at is not None:
        print(f"Forced panic_outward incident armed: fires at t+{args.force_panic_at:.0f}s "
              f"near ({args.force_panic_lat},{args.force_panic_lon}), radius={args.force_panic_radius_km}km, "
              f"duration={args.force_panic_duration:.0f}s")
    if args.force_protests is not None:
        print(f"Forced protest/riot demo armed: {args.force_protests} simultaneous crowds at t+"
              f"{args.force_protest_at:.0f}s, radius={args.force_protest_radius_km}km each, "
              f"duration={args.force_protest_duration:.0f}s, locations random within the city")
    print("Ctrl+C to stop.")

    active_incident = None
    active_protests = []  # list of {center_lat, center_lon, radius_km, end_time}
    forced_triggered = False
    protests_triggered = False
    suppress_organic = args.force_panic_at is not None or args.force_protests is not None
    start_time = time.time()
    last_tick = time.time()
    try:
        while True:
            now = time.time()
            dt = now - last_tick
            last_tick = now

            if (args.force_panic_at is not None and not forced_triggered
                    and active_incident is None and now - start_time >= args.force_panic_at):
                forced_triggered = True
                active_incident = {
                    "kind": "panic_outward",
                    "center_lat": args.force_panic_lat,
                    "center_lon": args.force_panic_lon,
                    "radius_km": args.force_panic_radius_km,
                    "end_time": now + args.force_panic_duration,
                }
                print(f"\n*** FORCED INCIDENT STARTED: panic_outward near "
                      f"({args.force_panic_lat},{args.force_panic_lon}) radius={args.force_panic_radius_km}km "
                      f"for {args.force_panic_duration:.0f}s ***\n")
            elif not suppress_organic:
                active_incident = maybe_spawn_incident(active_incident, now, devices)

            if active_incident and now >= active_incident["end_time"]:
                print(f"\n*** INCIDENT ENDED: {active_incident['kind']} ***\n")
                active_incident = None

            if (args.force_protests is not None and not protests_triggered
                    and now - start_time >= args.force_protest_at):
                protests_triggered = True
                centers = random.sample(grid_cell_centers(), min(args.force_protests, len(grid_cell_centers())))
                for clat, clon in centers:
                    active_protests.append({
                        "center_lat": clat, "center_lon": clon,
                        "radius_km": args.force_protest_radius_km,
                        "end_time": now + args.force_protest_duration,
                    })
                    print(f"\n*** PROTEST/RIOT STARTED: crowd converging near ({clat:.5f},{clon:.5f}) "
                          f"radius={args.force_protest_radius_km}km for {args.force_protest_duration:.0f}s ***\n")

            still_active = []
            for p in active_protests:
                if now >= p["end_time"]:
                    print(f"\n*** PROTEST/RIOT ENDED near ({p['center_lat']:.5f},{p['center_lon']:.5f}) ***\n")
                else:
                    still_active.append(p)
            active_protests = still_active

            for d in devices:
                d.maybe_turn_or_switch_mode(now)

                # bias: which real street-graph neighbor to prefer at the next
                # intersection (toward/away from an incident point), instead of
                # the old free-space "set an arbitrary heading" override.
                bias = None
                bias_key = None
                if active_incident:
                    if active_incident["kind"] == "panic_outward":
                        dist = haversine_km(d.lat, d.lon, active_incident["center_lat"], active_incident["center_lon"])
                        if dist <= active_incident["radius_km"]:
                            bias = (active_incident["center_lat"], active_incident["center_lon"], False)  # flee
                            bias_key = ("panic", id(active_incident))
                            d.speed = random.uniform(7.0, 15.0)
                    elif d.id in active_incident["participants"]:  # mass_convergence
                        bias = (active_incident["target_lat"], active_incident["target_lon"], True)  # converge
                        bias_key = ("converge", id(active_incident))
                        d.speed = random.uniform(10.0, 20.0)
                if bias is None:
                    for p in active_protests:
                        if haversine_km(d.lat, d.lon, p["center_lat"], p["center_lon"]) <= p["radius_km"]:
                            # urgent/agitated march, not a casual stroll -- kept clear of
                            # CRUSH_MIN_SPEED_KMH=4.0 in crowd_anomaly_agent.py, which exists
                            # specifically to separate this from ordinary foot traffic (backtested
                            # against real pedestrian data: normal funneling tops out ~2.8 km/h)
                            bias = (p["center_lat"], p["center_lon"], True)  # converge
                            bias_key = ("protest", id(p))
                            d.speed = random.uniform(5.0, 9.0)
                            break

                if bias_key != d.bias_key:
                    # newly entered/left an incident's pull - re-decide direction
                    # right now instead of waiting out whatever edge it's mid-walk on,
                    # so forced demo incidents stay responsive/deterministic.
                    if bias is not None:
                        d.reroute_now(street_graph, bias)
                    d.bias_key = bias_key

                contain = ((d.cluster_lat, d.cluster_lon, d.cluster_radius_km)
                           if d.cluster_lat is not None else None)
                d.step(dt, street_graph, bias=bias, contain=contain)

            tick_time = datetime.datetime.now().isoformat()
            debug_incident = None
            if active_incident:
                debug_incident = {k: v for k, v in active_incident.items() if k != "participants"}
                if "participants" in active_incident:
                    debug_incident["participant_count"] = len(active_incident["participants"])
            snapshot = {
                "generated_at": tick_time,
                "_debug_incident": debug_incident,
                "devices": [
                    {
                        "subscriber_id": d.id,
                        "timestamp": tick_time,
                        "latitude": round(d.lat, 6),
                        "longitude": round(d.lon, 6),
                        "heading_deg": round(d.heading, 1),
                        "speed_kmh": round(d.speed, 1),
                        "movement_mode": d.mode,
                        "cell_id": nearest_tower(d.lat, d.lon, towers, grid, lat_step, lon_step, grid_n)["cell_id"],
                    }
                    for d in devices
                ],
            }

            # per-PID tmp filename -- see the matching fix/comment in
            # crowd_anomaly_agent.py's write_risk_snapshot for why this
            # matters whenever two instances could ever share one output path.
            tmp_path = f"{args.out}.{os.getpid()}.tmp"
            with open(tmp_path, "w") as f:
                json.dump(snapshot, f)
            os.replace(tmp_path, args.out)

            sample = devices[0]
            print(f"[{snapshot['generated_at']}] updated {len(devices)} devices "
                  f"e.g. {sample.id} -> {sample.lat:.5f},{sample.lon:.5f} "
                  f"{sample.speed:.1f} km/h ({sample.mode})")

            elapsed = time.time() - now
            time.sleep(max(0.0, args.tick - elapsed))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
