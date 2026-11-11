#!/usr/bin/env python3
"""
Offline polygon -> streets + restaurants + shops lookup, no API, no AI, no internet
(after the one-time .pbf download).

Usage:
    python3 extract.py --pbf data/Frankfurt.osm.pbf --points points.txt
    python3 extract.py --pbf data/Frankfurt.osm.pbf --points points.txt --amenity restaurant,cafe,bar

By default this reports:
  - every node/way tagged shop=* (any shop type at all: supermarket, bakery, clothes, ...)
  - every node/way tagged amenity=<food/drink type> (restaurant, cafe, fast_food, bar, pub, etc.)

points.txt format (same as pasted from the map tool), one vertex per line:
    lat: 50.114692, lng: 8.664029
    lat: 50.114858, lng: 8.665819
    ...
"""
import argparse
import json
import re
import sys
import osmium
import shapely.geometry as geom

FOOD_AMENITIES = {
    "restaurant", "fast_food", "cafe", "bar", "pub", "biergarten",
    "ice_cream", "food_court", "nightclub",
}


def load_points(path):
    points = []
    pattern = re.compile(r"lat:\s*([-\d.]+)\s*,\s*lng:\s*([-\d.]+)")
    with open(path) as f:
        for line in f:
            m = pattern.search(line)
            if m:
                lat, lng = float(m.group(1)), float(m.group(2))
                points.append((lat, lng))
    if len(points) < 3:
        raise ValueError(f"Found only {len(points)} points in {path}; need at least 3 for a polygon.")
    return points


def place_category(tags, amenities):
    """Return a category label if these tags should be reported as a place, else None."""
    shop = tags.get("shop")
    if shop:
        return f"shop:{shop}"
    amenity = tags.get("amenity")
    if amenity and amenity in amenities:
        return f"amenity:{amenity}"
    return None


# ---------------------------------------------------------------------------
# Index build/query: parsing a whole city .osm.pbf (buildings, landuse, every
# node) just to answer "what's in this small polygon" is what made lookups
# take ~25s. Doing that full scan ONCE per city and keeping only named
# highways + shop/food points in a small JSON file turns every later query
# into "load this small file + shapely checks", which is sub-second.
# ---------------------------------------------------------------------------

ALL_REPORTABLE_AMENITIES = None  # sentinel: capture every amenity=* at index-build time


class IndexHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.streets = []  # [{"name": ..., "coords": [[lng, lat], ...]}, ...]
        self.places = []   # [{"name": ..., "category": ..., "lat": ..., "lng": ...}, ...]
        self.seen = set()

    def _place_category(self, tags):
        shop = tags.get("shop")
        if shop:
            return f"shop:{shop}"
        amenity = tags.get("amenity")
        if amenity:
            return f"amenity:{amenity}"
        return None

    def _add_place(self, tags, lat, lng):
        category = self._place_category(tags)
        if category is None:
            return
        name = tags.get("name", "(unnamed)")
        key = (name, category, round(lat, 5), round(lng, 5))
        if key in self.seen:
            return
        self.seen.add(key)
        self.places.append({"name": name, "category": category, "lat": lat, "lng": lng})

    def node(self, n):
        if not n.location.valid():
            return
        self._add_place(dict(n.tags), n.location.lat, n.location.lon)

    def way(self, w):
        tags = dict(w.tags)
        try:
            coords = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
        except Exception:
            return
        if not coords:
            return

        if "highway" in tags:
            name = tags.get("name")
            if name:
                self.streets.append({"name": name, "coords": [list(c) for c in coords]})
            return

        if self._place_category(tags) is not None:
            centroid = geom.Polygon(coords).centroid if len(coords) > 2 else geom.LineString(coords).centroid
            self._add_place(tags, centroid.y, centroid.x)


def build_index(pbf_path, out_path):
    handler = IndexHandler()
    handler.apply_file(pbf_path, locations=True)
    with open(out_path, "w") as f:
        json.dump({"streets": handler.streets, "places": handler.places}, f)
    return len(handler.streets), len(handler.places)


def query_index(index_path, polygon, amenities):
    with open(index_path) as f:
        idx = json.load(f)

    minx, miny, maxx, maxy = polygon.bounds
    pad = 0.002

    streets = {}
    for seg in idx["streets"]:
        coords = seg["coords"]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        if max(xs) < minx - pad or min(xs) > maxx + pad or max(ys) < miny - pad or min(ys) > maxy + pad:
            continue
        if polygon.intersects(geom.LineString(coords)):
            streets[seg["name"]] = True

    places = []
    seen = set()
    for p in idx["places"]:
        category = p["category"]
        if category.startswith("amenity:") and category.split(":", 1)[1] not in amenities:
            continue
        lat, lng = p["lat"], p["lng"]
        if lat < miny - pad or lat > maxy + pad or lng < minx - pad or lng > maxx + pad:
            continue
        if not polygon.contains(geom.Point(lng, lat)):
            continue
        key = (p["name"], category, round(lat, 5), round(lng, 5))
        if key in seen:
            continue
        seen.add(key)
        places.append((p["name"], category, lat, lng))

    return streets, places


class Handler(osmium.SimpleHandler):
    def __init__(self, polygon, amenities):
        super().__init__()
        self.polygon = polygon
        self.amenities = amenities
        self.minx, self.miny, self.maxx, self.maxy = polygon.bounds
        self.streets = {}
        self.places = []
        self.seen = set()  # dedupe (name, category, rounded-lat, rounded-lng)

    def _in_bbox(self, lat, lng, pad=0.002):
        return self.miny - pad <= lat <= self.maxy + pad and self.minx - pad <= lng <= self.maxx + pad

    def _add_place(self, tags, lat, lng):
        category = place_category(tags, self.amenities)
        if category is None:
            return
        if not self.polygon.contains(geom.Point(lng, lat)):
            return
        name = tags.get("name", "(unnamed)")
        key = (name, category, round(lat, 5), round(lng, 5))
        if key in self.seen:
            return
        self.seen.add(key)
        self.places.append((name, category, lat, lng))

    def node(self, n):
        if not n.location.valid():
            return
        lat, lng = n.location.lat, n.location.lon
        if not self._in_bbox(lat, lng):
            return
        self._add_place(dict(n.tags), lat, lng)

    def way(self, w):
        tags = dict(w.tags)
        try:
            coords = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
        except Exception:
            return
        if not coords:
            return
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        if max(xs) < self.minx - 0.002 or min(xs) > self.maxx + 0.002 \
                or max(ys) < self.miny - 0.002 or min(ys) > self.maxy + 0.002:
            return

        if "highway" in tags:
            name = tags.get("name")
            if name and self.polygon.intersects(geom.LineString(coords)):
                self.streets[name] = w.id
            return

        # shops/restaurants are sometimes mapped as building outlines (ways), not points
        if place_category(tags, self.amenities) is not None:
            centroid = geom.Polygon(coords).centroid if len(coords) > 2 else geom.LineString(coords).centroid
            self._add_place(tags, centroid.y, centroid.x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", help="Path to a regional .osm.pbf extract (full scan; slow, ~seconds-per-city)")
    ap.add_argument("--index", help="Path to a pre-built .index.json (fast; see --build-index)")
    ap.add_argument("--build-index", metavar="OUT_PATH",
                     help="One-time: scan --pbf fully and write a small streets+places index to OUT_PATH, then exit")
    ap.add_argument("--points", help="Path to a text file with 'lat: X, lng: Y' lines")
    ap.add_argument("--points-json", help='Polygon vertices as JSON, e.g. \'[[50.11,8.66],[50.12,8.67],...]\' (lat, lng)')
    ap.add_argument("--amenity", default=None,
                     help="Comma-separated amenity types to include (default: all food/drink types: "
                          + ",".join(sorted(FOOD_AMENITIES)) + "). shop=* is always included regardless of this flag.")
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of plain text")
    args = ap.parse_args()

    if args.build_index:
        if not args.pbf:
            raise SystemExit("--build-index requires --pbf")
        n_streets, n_places = build_index(args.pbf, args.build_index)
        print(f"Wrote index to {args.build_index}: {n_streets} street segments, {n_places} places")
        return

    if args.points_json:
        raw_points = [(lat, lng) for lat, lng in json.loads(args.points_json)]
        if len(raw_points) < 3:
            raise ValueError("Need at least 3 points for a polygon.")
    elif args.points:
        raw_points = load_points(args.points)
    else:
        raise SystemExit("Provide either --points or --points-json")

    polygon = geom.Polygon([(lng, lat) for lat, lng in raw_points])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)

    amenities = FOOD_AMENITIES if args.amenity is None else set(a.strip() for a in args.amenity.split(","))

    if args.index:
        streets, places = query_index(args.index, polygon, amenities)
    elif args.pbf:
        handler = Handler(polygon, amenities)
        handler.apply_file(args.pbf, locations=True)
        streets, places = handler.streets, handler.places
    else:
        raise SystemExit("Provide either --index (fast) or --pbf (slow, full scan)")

    if args.json:
        result = {
            "streets": sorted(streets.keys()) if isinstance(streets, dict) else sorted(streets),
            "places": [
                {"name": name, "category": category, "lat": lat, "lng": lng}
                for name, category, lat, lng in sorted(places, key=lambda p: p[1])
            ],
        }
        json.dump(result, sys.stdout)
        return

    street_names = streets.keys() if isinstance(streets, dict) else streets
    print("=== STREETS INSIDE POLYGON ===")
    for name in sorted(street_names):
        print(" -", name)
    print(f"\nTotal distinct streets: {len(street_names)}")

    print(f"\n=== RESTAURANTS & SHOPS INSIDE POLYGON ===")
    for name, category, lat, lng in sorted(places, key=lambda p: p[1]):
        print(f" - {name} [{category}] ({lat:.6f}, {lng:.6f})")
    print(f"\nTotal places: {len(places)}")


if __name__ == "__main__":
    main()
