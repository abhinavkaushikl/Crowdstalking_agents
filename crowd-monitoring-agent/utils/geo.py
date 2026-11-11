"""Shared geo math used by multiple agents/services, kept in one place instead
of each file carrying its own copy."""
import math


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def circle_polygon(lat, lon, radius_km, n=16):
    """n points approximating a circle of radius_km around (lat, lon), used to
    build a query polygon for the OSM index lookup."""
    pts = []
    for i in range(n):
        a = (i / n) * 2 * math.pi
        d_lat = (radius_km / 111.32) * math.cos(a)
        d_lon = (radius_km / (111.32 * math.cos(math.radians(lat)) + 1e-9)) * math.sin(a)
        pts.append((lat + d_lat, lon + d_lon))
    return pts
