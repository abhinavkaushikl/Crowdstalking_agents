#!/usr/bin/env python3
"""
Pure-Python SVG renderer - no matplotlib/Pillow available in this environment,
and no browser/Chrome control either, so this draws the same device-position +
flagged-cell data the live map would show, directly as vector shapes. It's an
honest visual proxy, not a literal browser screenshot.
"""
from case_runner import LAT_MIN, LAT_MAX, LON_MIN, LON_MAX, GRID_N, cell_bounds

W, H = 900, 700
PAD = 40

MODE_COLOR = {"driving": "#ff453a", "walking": "#0a84ff", "stationary": "#8e8e93"}
REASON_COLOR = {"panic_outward": "#ff453a", "crush_inward": "#ff9f0a", "variance_spike": "#ffd60a"}


def to_xy(lat, lon):
    x = PAD + (lon - LON_MIN) / (LON_MAX - LON_MIN) * (W - 2 * PAD)
    y = PAD + (1 - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * (H - 2 * PAD)
    return x, y


def render_snapshot(path, devices_snapshot, active_flags, title, subtitle, highlight_ids=None):
    highlight_ids = highlight_ids or set()
    parts = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
    parts.append(f'<rect width="{W}" height="{H}" fill="#0b0b0d"/>')

    # grid
    for gi in range(GRID_N):
        for gj in range(GRID_N):
            lat_min, lat_max, lon_min, lon_max = cell_bounds(gi, gj)
            x1, y1 = to_xy(lat_max, lon_min)
            x2, y2 = to_xy(lat_min, lon_max)
            parts.append(f'<rect x="{x1:.1f}" y="{y1:.1f}" width="{x2 - x1:.1f}" height="{y2 - y1:.1f}" '
                         f'fill="none" stroke="#2c2c2e" stroke-width="1"/>')

    # flagged cells
    for flag in active_flags:
        gi, gj = flag["cell"]
        lat_min, lat_max, lon_min, lon_max = cell_bounds(gi, gj)
        x1, y1 = to_xy(lat_max, lon_min)
        x2, y2 = to_xy(lat_min, lon_max)
        color = REASON_COLOR.get(flag["reason"], "#ffd60a")
        parts.append(f'<rect x="{x1:.1f}" y="{y1:.1f}" width="{x2 - x1:.1f}" height="{y2 - y1:.1f}" '
                     f'fill="{color}" opacity="0.22" stroke="{color}" stroke-width="2" stroke-dasharray="6,4"/>')
        parts.append(f'<text x="{x1 + 6:.1f}" y="{y1 + 16:.1f}" fill="{color}" font-size="11" '
                     f'font-family="monospace">{flag["reason"]}</text>')

    # devices
    for dev in devices_snapshot:
        x, y = to_xy(dev["lat"], dev["lon"])
        color = MODE_COLOR.get(dev["mode"], "#8e8e93")
        r = 4.5 if dev["id"] in highlight_ids else 2.5
        stroke = 'stroke="#fff" stroke-width="1"' if dev["id"] in highlight_ids else ""
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}" {stroke}/>')

    parts.append(f'<text x="{PAD}" y="24" fill="#f5f5f7" font-size="18" font-family="sans-serif" '
                 f'font-weight="600">{title}</text>')
    parts.append(f'<text x="{PAD}" y="{H - 16}" fill="#8e8e93" font-size="12" font-family="monospace">{subtitle}</text>')

    legend_y = H - 90
    for i, (label, color) in enumerate([("driving", "#ff453a"), ("walking", "#0a84ff"), ("stationary", "#8e8e93")]):
        ly = legend_y + i * 18
        parts.append(f'<circle cx="{W - 160}" cy="{ly}" r="4" fill="{color}"/>')
        parts.append(f'<text x="{W - 148}" y="{ly + 4}" fill="#f5f5f7" font-size="11" font-family="monospace">{label}</text>')

    parts.append('</svg>')
    with open(path, "w") as f:
        f.write("\n".join(parts))
