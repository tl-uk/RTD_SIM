"""
simulation/spatial/coordinate_utils.py

Coordinate utilities for spatial calculations.

Pure functions for:
- Distance calculations (Haversine formula)
- Coordinate validation
- Route distance computation
"""

from __future__ import annotations
import math
from typing import List, Tuple


def is_valid_lonlat(coord) -> bool:
    """
    Check if coordinates are valid (lon, lat) format.

    Robust to dict-type abstract route nodes (returns False for non-2-tuples
    so segment_distance_km falls back to Euclidean rather than crashing).

    Args:
        coord: Expected Tuple of (longitude, latitude); tolerates dicts/other types.

    Returns:
        True if valid (lon, lat) pair, False otherwise.
    """
    try:
        if isinstance(coord, dict):
            return False
        if len(coord) != 2:
            return False
        lon = float(coord[0])
        lat = float(coord[1])
        return (-180.0 <= lon <= 180.0) and (-90.0 <= lat <= 90.0)
    except (TypeError, ValueError, AttributeError):
        return False


def _extract_coord(pt) -> tuple:
    """
    Extract a (lon, lat) 2-tuple from a route point.

    Handles three formats:
      - Normal (lon, lat) tuples / lists       → direct use
      - Abstract route dicts {'pos': (lon,lat)}→ use 'pos' field
      - OSMnx integer node IDs                 → returns None (caller skips)
    """
    if isinstance(pt, dict):
        pos = pt.get('pos')
        if pos is not None and len(pos) == 2:
            return (float(pos[0]), float(pos[1]))
        return None
    try:
        if len(pt) == 2:
            return (float(pt[0]), float(pt[1]))
    except (TypeError, ValueError):
        pass
    return None


def haversine_km(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    """
    Calculate great-circle distance between two points using Haversine formula.
    
    Args:
        coord1: (longitude, latitude) of first point
        coord2: (longitude, latitude) of second point
    
    Returns:
        Distance in kilometers
    """
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    
    # Earth's radius in km
    R = 6371.0
    
    # Convert to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    # Haversine formula
    a = (math.sin(delta_phi / 2) ** 2 + 
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    
    return R * c


def haversine_m(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    """
    Calculate great-circle distance in meters.
    
    Args:
        coord1: (longitude, latitude) of first point
        coord2: (longitude, latitude) of second point
    
    Returns:
        Distance in meters
    """
    return haversine_km(coord1, coord2) * 1000.0


def euclidean_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    """
    Calculate Euclidean distance (for small local distances).
    
    Args:
        coord1: (x, y) coordinates
        coord2: (x, y) coordinates
    
    Returns:
        Euclidean distance
    """
    return math.hypot(coord2[0] - coord1[0], coord2[1] - coord1[1])


def segment_distance_km(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    """
    Calculate distance between two points, using appropriate method.
    
    Uses Haversine for valid (lon, lat) coordinates, Euclidean otherwise.
    
    Args:
        coord1: First coordinate
        coord2: Second coordinate
    
    Returns:
        Distance in kilometers
    """
    if is_valid_lonlat(coord1) and is_valid_lonlat(coord2):
        return haversine_km(coord1, coord2)
    else:
        return euclidean_distance(coord1, coord2)


def route_distance_km(route: List[Tuple[float, float]]) -> float:
    """
    Calculate total distance along a route.
    
    Args:
        route: List of (lon, lat) coordinates
    
    Returns:
        Total distance in kilometers
    """
    if len(route) < 2:
        return 0.0
    
    total = 0.0
    for i in range(len(route) - 1):
        total += segment_distance_km(route[i], route[i + 1])
    
    return total


def densify_route(route: List[Tuple[float, float]], step_meters: float = 20.0) -> List[Tuple[float, float]]:
    """
    Add intermediate points along route segments for smoother visualization.
    
    Args:
        route: Original route coordinates
        step_meters: Maximum distance between points in meters
    
    Returns:
        Densified route with additional intermediate points
    """
    if len(route) < 2:
        return route
    
    densified = [route[0]]
    
    for i in range(len(route) - 1):
        start, end = route[i], route[i + 1]
        segment_length = haversine_m(start, end)
        
        if segment_length <= step_meters:
            densified.append(end)
            continue
        
        # Add intermediate points
        num_steps = int(segment_length // step_meters)
        lon1, lat1 = start
        lon2, lat2 = end
        
        for k in range(1, num_steps + 1):
            fraction = min(1.0, (k * step_meters) / segment_length)
            intermediate = (
                lon1 + (lon2 - lon1) * fraction,
                lat1 + (lat2 - lat1) * fraction
            )
            densified.append(intermediate)
        
        # Always add the end point
        if densified[-1] != end:
            densified.append(end)
    
    return densified


def interpolate_along_segment(
    start: Tuple[float, float],
    end: Tuple[float, float],
    distance_km: float
) -> Tuple[float, float]:
    """
    Find point at specified distance along line segment.
    
    Args:
        start: Starting coordinate
        end: Ending coordinate
        distance_km: Distance from start in kilometers
    
    Returns:
        Interpolated coordinate
    """
    segment_length = segment_distance_km(start, end)
    
    if segment_length == 0:
        return start
    
    fraction = min(1.0, distance_km / segment_length)
    
    lon1, lat1 = start
    lon2, lat2 = end
    
    return (
        lon1 + (lon2 - lon1) * fraction,
        lat1 + (lat2 - lat1) * fraction
    )


def bounds_from_coords(coords: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """
    Calculate bounding box from list of coordinates.
    
    Args:
        coords: List of (lon, lat) coordinates
    
    Returns:
        Tuple of (min_lon, min_lat, max_lon, max_lat)
    """
    if not coords:
        return (0.0, 0.0, 0.0, 0.0)
    
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    
    return (min(lons), min(lats), max(lons), max(lats))


def point_in_bbox(
    coord: Tuple[float, float],
    bbox: Tuple[float, float, float, float]
) -> bool:
    """
    Check if point is inside bounding box.
    
    Args:
        coord: (lon, lat) coordinate
        bbox: (min_lon, min_lat, max_lon, max_lat)
    
    Returns:
        True if point is inside bbox
    """
    lon, lat = coord
    min_lon, min_lat, max_lon, max_lat = bbox
    
    return (min_lon <= lon <= max_lon) and (min_lat <= lat <= max_lat)