#!/usr/bin/env python3
"""
Runs the three named "case" scenarios (concert panic, mass dispersal, riot)
plus one long randomized stress test, scores the detector against ground
truth it never gets to see, and writes a report + SVG snapshot per case into
cases/<name>/. See cases/INDEX.md (written at the end) for the summary.

This is a fully separate, offline, fast-forwarded simulation - it does not
touch the live simulator/detector/map-app processes, which keep running
untouched the whole time.
"""
import json
import os
import random
import statistics

from case_runner import (
    Device, Detector, TICK_SECONDS, N_DEVICES, GRACE_SECONDS,
    LAT_MIN, LAT_MAX, LON_MIN, LON_MAX,
    haversine_km, point_in_cell, apply_panic, apply_convergence,
)
from render import render_snapshot

SCRIPT_DIR = os.path.dirname(__file__)
BASELINE_TICKS = 30   # 60s of normal behaviour before the scenario
RECOVERY_TICKS = 40   # 80s after, to check flags correctly stop


def fresh_population(seed, now=0.0):
    random.seed(seed)
    return [Device(f"SUB-{i:08d}", now) for i in range(1, N_DEVICES + 1)]


def run_baseline_recovery(devices, detector, now, n_ticks):
    for _ in range(n_ticks):
        for d in devices:
            d.maybe_turn(now)
            d.step(TICK_SECONDS)
        now += TICK_SECONDS
        detector.process_tick(devices, now)
    return now


def snapshot_of(devices):
    return [{"id": d.id, "lat": d.lat, "lon": d.lon, "mode": d.mode} for d in devices]


def scenario_concert_panic(devices, detector, now):
    center_lat = random.uniform(LAT_MIN + 0.02, LAT_MAX - 0.02)
    center_lon = random.uniform(LON_MIN + 0.03, LON_MAX - 0.03)
    radius_km = random.uniform(0.8, 1.3)
    speed_range = (10.0, 18.0)
    duration_s = random.uniform(25, 40)
    start = now
    end = start + duration_s
    render_snap, highlight_ids = None, set()

    while now < end:
        apply_panic(devices, center_lat, center_lon, radius_km, speed_range)
        highlight_ids |= {d.id for d in devices if haversine_km(d.lat, d.lon, center_lat, center_lon) <= radius_km}
        for d in devices:
            d.maybe_turn(now)
            d.step(TICK_SECONDS)
        now += TICK_SECONDS
        detector.process_tick(devices, now)
        if render_snap is None and now >= start + duration_s / 2:
            render_snap = snapshot_of(devices)

    gt = [{"type": "panic_outward", "start": start, "end": end,
           "lat": center_lat, "lon": center_lon, "radius_km": round(radius_km, 2)}]
    narrative = (f"A concert just let out near ({center_lat:.4f},{center_lon:.4f}). Something scares the crowd "
                 f"within a {radius_km:.1f}km radius and {len(highlight_ids)} people suddenly run, "
                 f"{speed_range[0]:.0f}-{speed_range[1]:.0f} km/h, for about {duration_s:.0f}s.")
    return now, gt, render_snap, highlight_ids, narrative


def scenario_mass_dispersal(devices, detector, now):
    fraction = random.uniform(0.04, 0.07)
    n_participants = max(20, round(len(devices) * fraction))
    participant_ids = random.sample([d.id for d in devices], n_participants)
    n_groups = random.randint(3, 5)
    random.shuffle(participant_ids)
    groups = [participant_ids[i::n_groups] for i in range(n_groups)]
    targets = [(random.uniform(LAT_MIN + 0.02, LAT_MAX - 0.02),
                random.uniform(LON_MIN + 0.03, LON_MAX - 0.03)) for _ in range(n_groups)]
    speed_range = (5.0, 12.0)
    duration_s = random.uniform(30, 50)
    start, end = now, now + duration_s
    render_snap = None

    while now < end:
        for gid, (tlat, tlon) in enumerate(targets):
            apply_convergence(devices, groups[gid], tlat, tlon, speed_range)
        for d in devices:
            d.maybe_turn(now)
            d.step(TICK_SECONDS)
        now += TICK_SECONDS
        detector.process_tick(devices, now)
        if render_snap is None and now >= start + duration_s * 0.7:
            render_snap = snapshot_of(devices)

    gt = [{"type": "crush_inward", "start": start, "end": end, "lat": tlat, "lon": tlon}
          for (tlat, tlon) in targets]
    narrative = (f"A big event just ended. {n_participants} people ({fraction:.0%} of the area) break into "
                 f"{n_groups} separate groups and head toward {n_groups} different parts of the city at once "
                 f"(walking/transit pace), over about {duration_s:.0f}s.")
    return now, gt, render_snap, set(participant_ids), narrative


def scenario_riot(devices, detector, now):
    center_lat = random.uniform(LAT_MIN + 0.03, LAT_MAX - 0.03)
    center_lon = random.uniform(LON_MIN + 0.04, LON_MAX - 0.04)
    radius_km = random.uniform(1.5, 2.2)
    speed_range = (12.0, 22.0)
    pulse1_dur = random.uniform(30, 45)
    lull_dur = random.uniform(8, 15)
    pulse2_dur = random.uniform(30, 45)
    start = now
    render_snap, highlight_ids = None, set()

    p1_end = now + pulse1_dur
    while now < p1_end:
        apply_panic(devices, center_lat, center_lon, radius_km, speed_range)
        highlight_ids |= {d.id for d in devices if haversine_km(d.lat, d.lon, center_lat, center_lon) <= radius_km}
        for d in devices:
            d.maybe_turn(now)
            d.step(TICK_SECONDS)
        now += TICK_SECONDS
        detector.process_tick(devices, now)
        if render_snap is None and now >= start + pulse1_dur * 0.6:
            render_snap = snapshot_of(devices)

    lull_end = now + lull_dur
    while now < lull_end:
        for d in devices:
            d.maybe_turn(now)
            d.step(TICK_SECONDS)
        now += TICK_SECONDS
        detector.process_tick(devices, now)

    center2_lat = max(LAT_MIN, min(LAT_MAX, center_lat + random.uniform(-0.01, 0.01)))
    center2_lon = max(LON_MIN, min(LON_MAX, center_lon + random.uniform(-0.015, 0.015)))
    p2_end = now + pulse2_dur
    while now < p2_end:
        apply_panic(devices, center2_lat, center2_lon, radius_km, speed_range)
        highlight_ids |= {d.id for d in devices if haversine_km(d.lat, d.lon, center2_lat, center2_lon) <= radius_km}
        for d in devices:
            d.maybe_turn(now)
            d.step(TICK_SECONDS)
        now += TICK_SECONDS
        detector.process_tick(devices, now)

    gt = [{"type": "panic_outward", "start": start, "end": p1_end,
           "lat": center_lat, "lon": center_lon, "radius_km": round(radius_km, 2)},
          {"type": "panic_outward", "start": lull_end, "end": p2_end,
           "lat": center2_lat, "lon": center2_lon, "radius_km": round(radius_km, 2)}]
    narrative = (f"Unrest breaks out near ({center_lat:.4f},{center_lon:.4f}), {radius_km:.1f}km radius, "
                 f"people running {speed_range[0]:.0f}-{speed_range[1]:.0f} km/h for ~{pulse1_dur:.0f}s, "
                 f"a brief {lull_dur:.0f}s lull, then it flares up again nearby for ~{pulse2_dur:.0f}s.")
    return now, gt, render_snap, highlight_ids, narrative


def point_cell_matches_gt(flag, gt_event):
    gi, gj = flag["cell"]
    return point_in_cell(gt_event["lat"], gt_event["lon"], gi, gj)


def evaluate(ground_truth, flags):
    results = []
    matched = set()
    for gt in ground_truth:
        window_end = gt["end"] + GRACE_SECONDS
        matches = [f for f in flags
                   if gt["start"] <= f["sim_time"] <= window_end
                   and f["reason"] == gt["type"]
                   and point_cell_matches_gt(f, gt)]
        detected = len(matches) > 0
        latency = (matches[0]["sim_time"] - gt["start"]) if detected else None
        if detected:
            matched.update(id(f) for f in matches)
        results.append({"ground_truth": gt, "detected": detected,
                         "latency_seconds": latency, "matching_flags": len(matches)})
    false_positives = [f for f in flags if id(f) not in matched]
    return results, false_positives


def write_case(name, seed, ground_truth, results, false_positives, render_snap, highlight_ids, narrative, final_sim_time):
    out_dir = os.path.join(SCRIPT_DIR, name)
    os.makedirs(out_dir, exist_ok=True)

    svg_path = os.path.join(out_dir, "snapshot.svg")
    if render_snap is not None:
        render_snapshot(
            svg_path, render_snap,
            [{"cell": _nearest_cell(r["ground_truth"]), "reason": r["ground_truth"]["type"]} for r in results],
            title=name.replace("_", " ").title(),
            subtitle=narrative,
            highlight_ids=highlight_ids,
        )

    detected_count = sum(1 for r in results if r["detected"])
    recall = detected_count / len(results) if results else None
    latencies = [r["latency_seconds"] for r in results if r["detected"]]

    report = {
        "case": name, "seed": seed, "narrative": narrative,
        "n_ground_truth_events": len(results), "n_detected": detected_count,
        "recall": recall,
        "latencies_seconds": latencies,
        "n_false_positives": len(false_positives),
        "false_positives": false_positives,
        "per_event": results,
        "final_sim_time_seconds": final_sim_time,
    }
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)

    md = [f"# Case: {name.replace('_', ' ').title()}", "", narrative, "", f"Random seed: `{seed}` (so this exact run can be reproduced)", "",
          f"- Ground-truth events: {len(results)}",
          f"- Detected: {detected_count}/{len(results)} (recall = {recall:.0%})" if recall is not None else "- Detected: n/a",
          f"- Detection latency: {', '.join(f'{l:.0f}s' for l in latencies) if latencies else 'n/a'}",
          f"- False positives during this run: {len(false_positives)}", ""]
    for r in results:
        gt = r["ground_truth"]
        status = f"DETECTED after {r['latency_seconds']:.0f}s" if r["detected"] else "MISSED"
        md.append(f"- `{gt['type']}` at ({gt['lat']:.4f},{gt['lon']:.4f}), "
                  f"active {gt['start']:.0f}s-{gt['end']:.0f}s -> **{status}**")
    md.append("")
    md.append(f"![snapshot](snapshot.svg)" if render_snap is not None else "_(no snapshot captured)_")
    with open(os.path.join(out_dir, "report.md"), "w") as f:
        f.write("\n".join(md))

    return report


def _nearest_cell(gt_event):
    from case_runner import cell_index
    return cell_index(gt_event["lat"], gt_event["lon"])


def run_named_case(name, scenario_fn):
    seed = random.randrange(10 ** 9)
    devices = fresh_population(seed)
    detector = Detector()
    now = run_baseline_recovery(devices, detector, 0.0, BASELINE_TICKS)
    now, ground_truth, render_snap, highlight_ids, narrative = scenario_fn(devices, detector, now)
    now = run_baseline_recovery(devices, detector, now, RECOVERY_TICKS)
    results, false_positives = evaluate(ground_truth, detector.flags)
    return write_case(name, seed, ground_truth, results, false_positives, render_snap, highlight_ids, narrative, now)


def run_aggregate_stress_test(n_ticks=3000):
    seed = random.randrange(10 ** 9)
    devices = fresh_population(seed)
    detector = Detector()
    now = 0.0
    ground_truth = []
    active = None

    for _ in range(n_ticks):
        if active is None and random.random() < 0.01:
            if random.random() < 0.5:
                active = {"type": "panic_outward",
                          "lat": random.uniform(LAT_MIN + 0.02, LAT_MAX - 0.02),
                          "lon": random.uniform(LON_MIN + 0.03, LON_MAX - 0.03),
                          "radius_km": random.uniform(0.3, 0.6),
                          "start": now, "end": now + random.uniform(20, 40)}
            else:
                pids = random.sample([d.id for d in devices], max(5, round(len(devices) * 0.01)))
                active = {"type": "crush_inward", "participants": pids,
                          "lat": random.uniform(LAT_MIN + 0.02, LAT_MAX - 0.02),
                          "lon": random.uniform(LON_MIN + 0.03, LON_MAX - 0.03),
                          "start": now, "end": now + random.uniform(20, 40)}
            ground_truth.append(active)

        if active and now >= active["end"]:
            active = None

        if active:
            if active["type"] == "panic_outward":
                apply_panic(devices, active["lat"], active["lon"], active["radius_km"], (7.0, 15.0))
            else:
                apply_convergence(devices, active["participants"], active["lat"], active["lon"], (10.0, 20.0))

        for d in devices:
            d.maybe_turn(now)
            d.step(TICK_SECONDS)
        now += TICK_SECONDS
        detector.process_tick(devices, now)

    results, false_positives = evaluate(ground_truth, detector.flags)
    detected_count = sum(1 for r in results if r["detected"])
    latencies = [r["latency_seconds"] for r in results if r["detected"]]
    n_confirmed_flags = len(detector.flags)
    precision = (n_confirmed_flags - len(false_positives)) / n_confirmed_flags if n_confirmed_flags else None
    recall = detected_count / len(results) if results else None

    out_dir = os.path.join(SCRIPT_DIR, "aggregate_evaluation")
    os.makedirs(out_dir, exist_ok=True)
    report = {
        "seed": seed, "n_ticks": n_ticks, "simulated_minutes": round(now / 60, 1),
        "n_incidents_injected": len(ground_truth), "n_detected": detected_count,
        "recall": recall, "precision": precision,
        "n_confirmed_flags_total": n_confirmed_flags, "n_false_positives": len(false_positives),
        "latencies_seconds": latencies,
        "median_latency_seconds": statistics.median(latencies) if latencies else None,
        "mean_latency_seconds": statistics.mean(latencies) if latencies else None,
        "per_incident": results,
    }
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)

    md = [
        "# Aggregate randomized evaluation", "",
        f"Simulated {report['simulated_minutes']} minutes ({n_ticks} ticks) of a 750-device population, "
        f"with randomly-timed, randomly-placed incidents the detector was never shown directly.", "",
        f"Random seed: `{seed}`", "",
        f"- Incidents injected: {len(ground_truth)}",
        f"- Detected: {detected_count} (**recall = {recall:.0%}**)" if recall is not None else "- Detected: n/a",
        f"- Confirmed flags raised in total: {n_confirmed_flags}",
        f"- Of those, false positives (no matching incident): {len(false_positives)} "
        f"(**precision = {precision:.0%}**)" if precision is not None else "",
        f"- Detection latency: median {report['median_latency_seconds']:.0f}s, "
        f"mean {report['mean_latency_seconds']:.0f}s" if latencies else "- Detection latency: n/a (nothing detected)",
    ]
    with open(os.path.join(out_dir, "report.md"), "w") as f:
        f.write("\n".join(md))
    return report


def main():
    print("Running named cases (concert_panic, mass_dispersal, riot)...")
    r1 = run_named_case("concert_panic", scenario_concert_panic)
    r2 = run_named_case("mass_dispersal", scenario_mass_dispersal)
    r3 = run_named_case("riot", scenario_riot)

    print("Running aggregate randomized stress test (this takes longer)...")
    agg = run_aggregate_stress_test(n_ticks=3000)

    index = ["# Location Intelligence - Case Registry", "",
             "Each case is a separate, randomly-parameterized scenario run through the exact same",
             "detection algorithm used by the live system (`social-media-sentiment-agent/crowd_anomaly_agent.py`),",
             "scored against ground truth the detector never gets to see.", ""]
    for name, r in [("concert_panic", r1), ("mass_dispersal", r2), ("riot", r3)]:
        recall_txt = f"{r['recall']:.0%}" if r['recall'] is not None else "n/a"
        index.append(f"- [{name}]({name}/report.md) - recall {recall_txt}, "
                     f"false positives {r['n_false_positives']}, seed `{r['seed']}`")
    index.append("")
    if agg['recall'] is not None and agg['precision'] is not None and agg['median_latency_seconds'] is not None:
        index.append(f"- [aggregate_evaluation](aggregate_evaluation/report.md) - "
                     f"{agg['n_incidents_injected']} random incidents over {agg['simulated_minutes']} simulated minutes, "
                     f"recall {agg['recall']:.0%}, precision {agg['precision']:.0%}, "
                     f"median latency {agg['median_latency_seconds']:.0f}s")
    else:
        index.append(f"- [aggregate_evaluation](aggregate_evaluation/report.md) - "
                     f"{agg['n_incidents_injected']} incidents injected, {agg['n_detected']} detected, "
                     f"{agg['n_confirmed_flags_total']} total flags raised")
    with open(os.path.join(SCRIPT_DIR, "INDEX.md"), "w") as f:
        f.write("\n".join(index))

    print("\nDone. See cases/INDEX.md")


if __name__ == "__main__":
    main()
