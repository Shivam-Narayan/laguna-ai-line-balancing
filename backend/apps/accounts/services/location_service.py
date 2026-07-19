from math import atan2, cos, radians, sin, sqrt
from typing import Tuple

EARTH_RADIUS_METERS = 6371000

# Geofence definition
GEOFENCE = {
    "radius": 5000  # 5 km radius
}


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the distance in meters between two GPS coordinates."""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return EARTH_RADIUS_METERS * c


def verify_geofence(user, current_lat, current_lon) -> Tuple[bool, str, int]:
    """Verifies if a user is within the allowed geofence radius of their assigned location."""
    try:
        current_lat = float(current_lat)
        current_lon = float(current_lon)
    except (TypeError, ValueError):
        return False, "Required Latitude and Longitude must be valid numbers.", 400

    user_lat = user.latitude
    user_lon = user.longitude

    if not user_lat or not user_lon:
        return (
            False,
            "User Latitude and Longitude values are empty in the database.",
            404,
        )

    distance = haversine_distance(
        current_lat, current_lon, float(user_lat), float(user_lon)
    )

    if distance <= GEOFENCE["radius"]:
        return True, "You are within the geofence.", 200

    return (
        False,
        "You are outside the geofence. Please be within the access range to continue.",
        403,
    )
