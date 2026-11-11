#!/usr/bin/env python3
"""
Stage 1 -- Context Agent. Deliberately NOT an LLM call: every piece of data
here is a pure fetch from logic that already exists and is already correct
(reverse-geocode, nearby vendors+streets via the real OSM index, nearby
devices). No judgment for an LLM to add here, so it stays cheap, fast, and
needs zero API keys -- only Stage 2 (synthesis/search) actually needs Groq.

Ported from the original Node implementation (map-app/lib/geocode.js +
map-app/lib/tools.js), now native Python so it can import extract.py's
query_index() directly instead of shelling out to a subprocess.
"""
import importlib.util
import json
import os
from datetime import datetime, timezone

import requests
import shapely.geometry as geom

from utils.config_loader import get as config_get
from utils.geo import circle_polygon, haversine_km

AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_ROOT = os.path.dirname(AGENTS_DIR)          # .../crowd-monitoring-agent
PROJECT_ROOT = os.path.dirname(AGENT_ROOT)        # .../Location Intelligence Agen
OSM_DIR = os.path.join(PROJECT_ROOT, "osm-extract")
LIVE_POSITIONS_PATH = os.path.join(PROJECT_ROOT, "simulation", "live_positions.json")
REGIONS_PATH = os.path.join(OSM_DIR, "regions.json")

DEFAULT_RADIUS_KM = config_get("context.default_radius_km", 2)
MAX_RADIUS_KM = config_get("context.max_radius_km", 2)
VENDOR_LIMIT = config_get("context.vendor_limit", 20)
STREET_LIMIT = config_get("context.street_limit", 30)
SUBSCRIBER_LIMIT = config_get("context.subscriber_limit", 15)

# "osm-extract" has a hyphen, so it can't be a normal importable package name --
# load extract.py directly by file path instead (same technique already used
# by the real-data backtest script).
_spec = importlib.util.spec_from_file_location("osm_extract_module", os.path.join(OSM_DIR, "extract.py"))
osm_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(osm_extract)

with open(REGIONS_PATH) as f:
    REGIONS = json.load(f)


def find_region_for_point(lat, lon):
    for name, region in REGIONS.items():
        b = region["bbox"]
        if b["minLat"] <= lat <= b["maxLat"] and b["minLng"] <= lon <= b["maxLng"]:
            return name, region
    return None, None


def reverse_geocode(lat, lon):
    user_agent = os.environ.get("APP_USER_AGENT") or "crowd-monitoring-agent/0.1 (local dev)"
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=jsonv2&zoom=16&addressdetails=1"
    try:
        res = requests.get(url, headers={"User-Agent": user_agent}, timeout=10)
        res.raise_for_status()
        data = res.json()
        address = data.get("address", {})
        locality = (
            address.get("suburb") or address.get("neighbourhood") or address.get("quarter")
            or address.get("city_district") or address.get("city") or address.get("town")
            or address.get("village") or address.get("state") or address.get("country")
            or data.get("display_name")
        )
        city = address.get("city") or address.get("town") or address.get("village") or address.get("state") or ""
        return {"locality": locality, "city": city, "displayName": data.get("display_name")}
    except Exception as e:
        return {"error": str(e), "locality": None, "city": None, "displayName": None}


def get_nearby_vendors_and_streets(lat, lon, radius_km):
    region_name, region = find_region_for_point(lat, lon)
    if not region:
        return {"error": "No OSM data covers this location", "vendors": [], "streets": []}
    index_path = os.path.join(OSM_DIR, region["index"])
    points = circle_polygon(lat, lon, radius_km)
    polygon = geom.Polygon([(lng, lt) for lt, lng in points])
    try:
        streets, places = osm_extract.query_index(index_path, polygon, osm_extract.FOOD_AMENITIES)
        vendors = [{"name": n, "category": c, "lat": la, "lng": lo} for n, c, la, lo in places]
        street_names = sorted(streets.keys())
        return {
            "vendor_count": len(vendors), "vendors": vendors[:VENDOR_LIMIT],
            "street_count": len(street_names), "streets": street_names[:STREET_LIMIT]
        }
    except Exception as e:
        return {"error": str(e), "vendors": [], "streets": []}


def get_affected_subscribers(lat, lon, radius_km):
    try:
        with open(LIVE_POSITIONS_PATH) as f:
            snapshot = json.load(f)
    except Exception:
        return {"error": "live positions not available", "subscriber_count": 0, "subscribers": []}
    nearby = []
    for d in snapshot.get("devices", []):
        dist_m = round(haversine_km(lat, lon, d["latitude"], d["longitude"]) * 1000)
        if dist_m <= radius_km * 1000:
            nearby.append({"id": d["subscriber_id"], "distance_m": dist_m})
    nearby.sort(key=lambda x: x["distance_m"])
    return {"subscriber_count": len(nearby), "subscribers": nearby[:SUBSCRIBER_LIMIT]}


def resolve_location(flag):
    if flag.get("hotspot"):
        h = flag["hotspot"]
        return h["lat"], h["lon"], min(h["radius_km"], MAX_RADIUS_KM)
    # variance_spike and any other hotspot-less flag: fall back to the cell
    # center, same as app.js does client-side for flags without a hotspot.
    cc = flag["cell_center"]
    return cc[0], cc[1], DEFAULT_RADIUS_KM


def build_context(flag):
    lat, lon, radius_km = resolve_location(flag)
    area = reverse_geocode(lat, lon)
    vendors = get_nearby_vendors_and_streets(lat, lon, radius_km)
    affected_subscribers = get_affected_subscribers(lat, lon, radius_km)
    return {
        "flag": flag,
        "location": {"lat": lat, "lon": lon, "radius_km": radius_km},
        "area": area,
        "vendors": vendors,
        "affected_subscribers": affected_subscribers,
        "gathered_at": datetime.now(timezone.utc).isoformat()
    }
