"""Haversine great-circle distance in meters; location accuracy remains approximate."""
from math import atan2, cos, radians, sin, sqrt


def meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a, b = radians(lat1), radians(lat2)
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    hav = sin(dlat / 2) ** 2 + cos(a) * cos(b) * sin(dlon / 2) ** 2
    return 6371000 * 2 * atan2(sqrt(hav), sqrt(1 - hav))
