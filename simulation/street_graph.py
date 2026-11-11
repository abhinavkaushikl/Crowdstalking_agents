"""
Builds a walkable road graph from the pre-extracted OSM street index
(osm-extract/data/<City>.index.json) so simulated devices move ALONG real
streets and turn only at real intersections, instead of a free-space random
walk that ignores the road network entirely.

Nodes are the polyline vertices of `highway=*` ways; two ways sharing an OSM
node produce the same (lon, lat) float pair in both street entries (extract.py
reads raw node locations, no reprojection), so snapping coordinates to a fixed
decimal precision correctly merges them into one graph node = one real
intersection (or dead end).
"""
import json
import math
import random

NODE_PRECISION = 7  # ~1cm; safe merge tolerance for shared OSM node coordinates


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


def _node_key(lon, lat):
    return (round(lon, NODE_PRECISION), round(lat, NODE_PRECISION))


class StreetGraph:
    def __init__(self, adj, node_pos, edges, edge_weights):
        self.adj = adj                  # node_key -> list[node_key]
        self.node_pos = node_pos        # node_key -> (lon, lat)
        self.edges = edges              # list[(node_key, node_key)]
        self.edge_weights = edge_weights  # list[float] (edge length km), parallel to edges
        # Precomputed once so each placement is an O(log n) bisect instead of
        # random.choices() re-summing ~150k weights per call - matters once
        # you're placing thousands of devices at startup.
        total = 0.0
        cum = []
        for w in edge_weights:
            total += w
            cum.append(total)
        self._cum_weights = cum

    def edge_length_km(self, a, b):
        lon1, lat1 = self.node_pos[a]
        lon2, lat2 = self.node_pos[b]
        return haversine_km(lat1, lon1, lat2, lon2)

    def random_point(self):
        """A uniformly-likely random point on the road network, weighted by
        edge length so long streets don't get under-sampled."""
        a, b = random.choices(self.edges, cum_weights=self._cum_weights, k=1)[0]
        frac = random.random()
        lon1, lat1 = self.node_pos[a]
        lon2, lat2 = self.node_pos[b]
        lat = lat1 + (lat2 - lat1) * frac
        lon = lon1 + (lon2 - lon1) * frac
        return a, b, frac, lat, lon

    def random_point_near(self, center_lat, center_lon, radius_km, max_attempts=400):
        """A random point on the road network within ~radius_km of a center
        (for cluster/venue spawns). Falls back to the nearest edge found if
        none land inside the radius after max_attempts (sparse road coverage)."""
        best = None
        best_dist = float("inf")
        for _ in range(max_attempts):
            a, b, frac, lat, lon = self.random_point()
            d = haversine_km(lat, lon, center_lat, center_lon)
            if d <= radius_km:
                return a, b, frac, lat, lon
            if d < best_dist:
                best_dist, best = d, (a, b, frac, lat, lon)
        return best

    def choose_next_node(self, node, prev, current_heading, bias=None, contain=None):
        """Pick the next node to walk toward from `node`.

        bias: optional (target_lat, target_lon, want_toward) - devices caught
        in an incident prefer the neighbor edge whose direction most closely
        matches heading toward (want_toward=True) or away from (False) the
        target, instead of a free-space heading override.

        contain: optional (center_lat, center_lon, radius_km) - heavily
        downweights (not forbids) neighbors that would leave the radius, for
        cluster/venue devices that should mostly stay put.
        """
        nbrs = self.adj.get(node, [])
        options = [n for n in nbrs if n != prev] if prev is not None else list(nbrs)
        if not options:
            options = list(nbrs)
        if not options:
            return None

        lon0, lat0 = self.node_pos[node]
        if bias is not None:
            target_lat, target_lon, want_toward = bias
            desired = bearing_deg(lat0, lon0, target_lat, target_lon)
            if not want_toward:
                desired = (desired + 180) % 360
        else:
            desired = current_heading

        weights = []
        for n in options:
            lon1, lat1 = self.node_pos[n]
            b = bearing_deg(lat0, lon0, lat1, lon1)
            diff = abs((b - desired + 180) % 360 - 180)
            w = math.exp(-diff / 45.0) + 0.05
            if contain is not None:
                clat, clon, radius_km = contain
                if haversine_km(lat1, lon1, clat, clon) > radius_km:
                    w *= 0.05
            weights.append(w)
        return random.choices(options, weights=weights, k=1)[0]


def load_street_graph(index_path, bbox, pad_deg=0.01):
    lat_min, lat_max, lon_min, lon_max = bbox
    with open(index_path) as f:
        idx = json.load(f)

    adj = {}
    node_pos = {}
    edges = []
    edge_weights = []

    for street in idx["streets"]:
        coords = street["coords"]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        if (max(xs) < lon_min - pad_deg or min(xs) > lon_max + pad_deg
                or max(ys) < lat_min - pad_deg or min(ys) > lat_max + pad_deg):
            continue
        for (lon_a, lat_a), (lon_b, lat_b) in zip(coords, coords[1:]):
            ka, kb = _node_key(lon_a, lat_a), _node_key(lon_b, lat_b)
            if ka == kb:
                continue
            node_pos.setdefault(ka, (lon_a, lat_a))
            node_pos.setdefault(kb, (lon_b, lat_b))
            adj.setdefault(ka, [])
            adj.setdefault(kb, [])
            if kb not in adj[ka]:
                adj[ka].append(kb)
                adj[kb].append(ka)
                length_km = haversine_km(lat_a, lon_a, lat_b, lon_b)
                edges.append((ka, kb))
                edge_weights.append(max(length_km, 1e-6))

    if not edges:
        raise ValueError(f"No street edges found in {index_path} within the given bbox")

    return StreetGraph(adj, node_pos, edges, edge_weights)
