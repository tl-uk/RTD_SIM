"""
simulation/spatial/transit_stop_loader.py

City-agnostic transit stop discovery via OSM/Overpass.

REPLACES rail_spine.py's hardcoded TRAM_STOPS / STATIONS dicts.

The hardcoded spine worked only for Edinburgh and a handful of UK
corridors.  This module fetches transit stop positions for ANY bbox the
user selects, caches results to disk, and exposes the same snap/route
helpers that rail_spine provided — making the simulation portable to
any city without a single hardcoded coordinate.

Architecture (with / without GTFS)
────────────────────────────────────
  With GTFS loaded:
      _compute_gtfs_route() snaps to stops from the transit graph
      (already authoritative — this module is not called).
      This module is used by the VISUALISATION layer to draw stop markers.

  Without GTFS:
      router._transit_fallback() calls route_via_stops() from this module.
      Stop positions come from Overpass (Tier 1) or disk cache (Tier 2).
      Route geometry comes from the OSMnx track graph (rail/tram/bus) or
      straight-line interpolation between stops (Tier 3).
      The hardcoded spine (Tier 4) is NOT used — if Overpass fails AND
      the cache is empty, the agent logs a warning and skips the mode.

OSM stop tags queried
──────────────────────
  railway=station            — national rail stations
  railway=halt               — unstaffed request stops
  railway=tram_stop          — tram/light rail stops
  railway=subway_entrance    — metro/subway station entrances
  public_transport=stop_position — precise stop position (all modes)
  amenity=bus_station        — bus interchange hubs
  highway=bus_stop           — individual bus stops
  amenity=ferry_terminal     — foot/vehicle ferry terminals

One-way / contraflow awareness
────────────────────────────────
OSM directionality is respected by the OSMnx graphs already loaded by
graph_manager.py.  Stop snapping and route_via_stops() use the track
graph's edge directions, so stops on the wrong side of a one-way street
are not incorrectly connected.

Cache
──────
  ~/.rtd_sim_cache/transport/<city_tag>_stops_<mode_family>.json  (24 h TTL)
  Same root as ferry_network.py and rail_network.py caches.

Public API
──────────
  load_transit_stops(bbox, mode_families) -> Dict[str, List[TransitStop]]
  nearest_stop(stops, point, max_km) -> Optional[TransitStop]
  route_via_stops(origin, dest, mode_family, G_track, stops, interpolate_km)
      -> List[Tuple[float, float]]
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib import error as _urllib_error
from urllib import parse as _urllib_parse
from urllib import request as _urllib_request

logger = logging.getLogger(__name__)

# ── Cache ──────────────────────────────────────────────────────────────────────
CACHE_ROOT = Path.home() / ".rtd_sim_cache" / "transport"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)
CACHE_TTL_H = 24.0
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# In-memory session cache — avoids disk reads on every snap call.
# Key: (city_tag, mode_family) → List[TransitStop]
_SESSION_CACHE: Dict[Tuple[str, str], List["TransitStop"]] = {}


def _cache_stale(path: Path, ttl_h: float = CACHE_TTL_H) -> bool:
    if not path.exists():
        return True
    return (time.time() - path.stat().st_mtime) / 3600 > ttl_h


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class TransitStop:
    """
    One transit stop, agnostic of city and mode.

    Attributes:
        stop_id:      Unique string ID (OSM node ID or NaPTAN ATCO code)
        name:         Human-readable stop name (e.g. "Haymarket")
        lon:          Longitude (x)
        lat:          Latitude (y)
        mode_family:  'rail' | 'tram' | 'subway' | 'bus' | 'ferry'
        osm_id:       Raw OSM node ID as string (may differ from stop_id if
                      NaPTAN is used as stop_id)
        naptan_atco:  NaPTAN ATCO code if available ('' otherwise)
        railway_tag:  Raw OSM railway= tag value (e.g. 'station', 'tram_stop')
    """
    stop_id:     str
    name:        str
    lon:         float
    lat:         float
    mode_family: str
    osm_id:      str = ""
    naptan_atco: str = ""
    railway_tag: str = ""


def _haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Great-circle distance in km between (lon, lat) pairs."""
    lon1, lat1 = a
    lon2, lat2 = b
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dp / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(x), math.sqrt(1 - x))


# ── Overpass query helper ──────────────────────────────────────────────────────

def _overpass_post(query: str, timeout_s: int = 35) -> Optional[dict]:
    """
    POST to Overpass with exponential backoff.
    Mirrors the pattern in ferry_network._overpass_post() — see that module
    for the full rationale (406 fix, form-field encoding, User-Agent).
    """
    import random as _rand
    body = _urllib_parse.urlencode({"data": query}).encode("utf-8")
    max_retries, initial_delay = 3, 2.0

    for attempt in range(max_retries):
        try:
            req = _urllib_request.Request(
                _OVERPASS_URL,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "RTD_SIM_TransitStopLoader/1.0",
                },
            )
            with _urllib_request.urlopen(req, timeout=timeout_s + 5) as resp:
                return json.loads(resp.read())

        except _urllib_error.HTTPError as http_err:
            code = http_err.code
            if code in (429, 504) and attempt < max_retries - 1:
                wait = initial_delay * (2 ** attempt) * (1 + 0.2 * (_rand.random() - 0.5))
                logger.warning(
                    "Overpass HTTP %d (attempt %d/%d) — retrying in %.1fs",
                    code, attempt + 1, max_retries, wait,
                )
                time.sleep(wait)
                continue
            logger.warning("Overpass HTTP %d: %s", code, http_err.reason)
            return None
        except Exception as exc:
            msg = str(exc).lower()
            if ("timed out" in msg or "timeout" in msg) and attempt < max_retries - 1:
                wait = initial_delay * (2 ** attempt)
                logger.warning(
                    "Overpass timeout (attempt %d/%d) — retrying in %.1fs",
                    attempt + 1, max_retries, wait,
                )
                time.sleep(wait)
                continue
            logger.warning("Overpass POST failed: %s", exc)
            return None
    return None


# ── OSM tag → mode_family mapping ─────────────────────────────────────────────

# Maps OSM railway= tag values to RTD_SIM mode families.
_RAILWAY_TAG_TO_MODE: Dict[str, str] = {
    "station":         "rail",
    "halt":            "rail",
    "tram_stop":       "tram",
    "subway_entrance": "subway",
    "light_rail":      "tram",    # DLR / Metrolink etc.
    "monorail":        "tram",
}

# Maps mode_family to the Overpass filter tags to query.
# Each entry: (tag_key, tag_values, extra_filter)
# Designed so a single AreaQuery per mode_family fetches all relevant stop types.
_MODE_OVERPASS_FILTERS: Dict[str, str] = {
    "rail": (
        'node["railway"~"^(station|halt)$"]'
    ),
    "tram": (
        'node["railway"~"^(tram_stop|light_rail)$"];'
        'node["public_transport"="stop_position"]["tram"="yes"]'
    ),
    "subway": (
        'node["railway"="subway_entrance"];'
        'node["public_transport"="stop_position"]["subway"="yes"]'
    ),
    "bus": (
        'node["highway"="bus_stop"];'
        'node["amenity"="bus_station"];'
        'node["public_transport"="stop_position"]["bus"="yes"]'
    ),
    "ferry": (
        'node["amenity"="ferry_terminal"];'
        'node["public_transport"="stop_position"]["ferry"="yes"]'
    ),
}


# ── Overpass fetch ─────────────────────────────────────────────────────────────

def _fetch_stops_overpass(
    south: float,
    west: float,
    north: float,
    east: float,
    mode_family: str,
    timeout_s: int = 30,
) -> List[TransitStop]:
    """
    Fetch transit stops for one mode_family within the bbox from Overpass.

    Returns a list of TransitStop objects, or [] on any failure.
    """
    filters = _MODE_OVERPASS_FILTERS.get(mode_family)
    if not filters:
        logger.warning("transit_stop_loader: unknown mode_family '%s'", mode_family)
        return []

    # Build individual filter lines with bbox suffix
    filter_lines = "".join(
        f"\n  {f.strip()}({south},{west},{north},{east});"
        for f in filters.split(";")
        if f.strip()
    )
    query = (
        f"[out:json][timeout:{timeout_s}];\n"
        f"(\n{filter_lines}\n);\n"
        "out body;"
    )

    raw = _overpass_post(query, timeout_s=timeout_s)
    if not raw:
        return []

    stops: List[TransitStop] = []
    for el in raw.get("elements", []):
        if el.get("type") != "node":
            continue
        lon = el.get("lon")
        lat = el.get("lat")
        if lon is None or lat is None:
            continue

        tags        = el.get("tags", {})
        name        = tags.get("name", tags.get("ref", ""))
        railway_tag = tags.get("railway", "")
        osm_id      = str(el.get("id", ""))
        naptan      = tags.get("naptan:AtcoCode", tags.get("ref:naptan", ""))

        # Determine mode_family from tags (may be more specific than requested)
        resolved_mode = _RAILWAY_TAG_TO_MODE.get(railway_tag, mode_family)

        stops.append(TransitStop(
            stop_id     = naptan or osm_id,
            name        = name,
            lon         = float(lon),
            lat         = float(lat),
            mode_family = resolved_mode,
            osm_id      = osm_id,
            naptan_atco = naptan,
            railway_tag = railway_tag,
        ))

    logger.info(
        "transit_stop_loader: Overpass returned %d %s stops (bbox %.3f,%.3f→%.3f,%.3f)",
        len(stops), mode_family, south, west, north, east,
    )
    return stops


# ── Disk cache helpers ─────────────────────────────────────────────────────────

def _city_tag(south: float, west: float, north: float, east: float) -> str:
    """Stable short string to use as a cache key for a bbox."""
    return f"{south:.2f}_{west:.2f}_{north:.2f}_{east:.2f}".replace("-", "m")


def _cache_path(city_tag: str, mode_family: str) -> Path:
    return CACHE_ROOT / f"{city_tag}_stops_{mode_family}.json"


def _load_from_disk(path: Path) -> Optional[List[TransitStop]]:
    try:
        data = json.loads(path.read_text())
        return [TransitStop(**s) for s in data]
    except Exception as exc:
        logger.debug("transit_stop_loader: disk cache read failed: %s", exc)
        return None


def _save_to_disk(stops: List[TransitStop], path: Path) -> None:
    try:
        path.write_text(json.dumps([asdict(s) for s in stops], indent=2))
    except Exception as exc:
        logger.debug("transit_stop_loader: disk cache write failed: %s", exc)


# ── Public API ─────────────────────────────────────────────────────────────────

def load_transit_stops(
    bbox: Tuple[float, float, float, float],
    mode_families: Optional[List[str]] = None,
    force_refresh: bool = False,
) -> Dict[str, List[TransitStop]]:
    """
    Load transit stops for all requested mode families within bbox.

    Priority:
        1. In-memory session cache (zero cost)
        2. Disk cache (~/.rtd_sim_cache, 24 h TTL)
        3. Overpass live fetch
        4. Empty list + warning (never raises)

    Args:
        bbox:           (north, south, east, west) — RTD_SIM internal convention.
        mode_families:  Subset of ['rail','tram','subway','bus','ferry'].
                        Defaults to all five.
        force_refresh:  Bypass cache and re-fetch from Overpass.

    Returns:
        Dict mapping mode_family → List[TransitStop].
        Missing or failed families map to [].
    """
    north, south, east, west = bbox
    if mode_families is None:
        mode_families = list(_MODE_OVERPASS_FILTERS.keys())

    tag = _city_tag(south, west, north, east)
    result: Dict[str, List[TransitStop]] = {}

    for mf in mode_families:
        session_key = (tag, mf)

        # ── Tier 1: in-memory ────────────────────────────────────────────────
        if not force_refresh and session_key in _SESSION_CACHE:
            result[mf] = _SESSION_CACHE[session_key]
            continue

        # ── Tier 2: disk cache ───────────────────────────────────────────────
        cpath = _cache_path(tag, mf)
        if not force_refresh and not _cache_stale(cpath):
            stops = _load_from_disk(cpath)
            if stops is not None:
                _SESSION_CACHE[session_key] = stops
                result[mf] = stops
                logger.debug(
                    "transit_stop_loader: %d %s stops from disk cache", len(stops), mf
                )
                continue

        # ── Tier 3: Overpass fetch ───────────────────────────────────────────
        stops = _fetch_stops_overpass(south, west, north, east, mf)
        if stops:
            _SESSION_CACHE[session_key] = stops
            _save_to_disk(stops, cpath)
            result[mf] = stops
            continue

        # ── Tier 4: empty — log and continue ────────────────────────────────
        logger.warning(
            "transit_stop_loader: no %s stops available "
            "(Overpass failed and no cache). Agents using %s will skip this mode.",
            mf, mf,
        )
        result[mf] = []

    return result


def nearest_stop(
    stops: List[TransitStop],
    point: Tuple[float, float],
    max_km: float = 2.0,
    exclude_id: Optional[str] = None,
) -> Optional[TransitStop]:
    """
    Return the nearest TransitStop within max_km of point.

    Args:
        stops:      List returned by load_transit_stops()[mode_family].
        point:      (lon, lat) agent position.
        max_km:     Search radius in km.
        exclude_id: Skip the stop with this stop_id (used for same-stop resolution).

    Returns:
        Nearest TransitStop or None.
    """
    best_dist = max_km
    best_stop = None
    for s in stops:
        if exclude_id and s.stop_id == exclude_id:
            continue
        d = _haversine_km(point, (s.lon, s.lat))
        if d < best_dist:
            best_dist = d
            best_stop = s
    return best_stop


def route_via_stops(
    origin: Tuple[float, float],
    dest: Tuple[float, float],
    mode_family: str,
    stops: List[TransitStop],
    G_track=None,
    max_access_km: float = 2.0,
    interpolate_km: float = 0.05,
) -> List[Tuple[float, float]]:
    """
    Build a route as a list of (lon, lat) waypoints via transit stops.

    Replaces route_via_tram_stops() and route_via_stations() from rail_spine.py
    with a city-agnostic, graph-aware implementation.

    Strategy:
        1. Snap origin to nearest stop within max_access_km.
        2. Snap dest   to nearest stop within max_access_km (≠ origin stop).
        3. If G_track supplied: route on track graph (nx.shortest_path) to get
           all intermediate stops in sequence.
        4. If G_track is None or routing fails: collect all stops that lie
           between the snapped stops along the track corridor and sort by
           distance along the origin→dest vector (approximation sufficient
           for straight-line interpolation).
        5. Interpolate straight-line segments at interpolate_km intervals
           between consecutive waypoints.

    Args:
        origin:         Agent origin (lon, lat).
        dest:           Agent destination (lon, lat).
        mode_family:    'rail' | 'tram' | 'subway' | 'bus' | 'ferry'.
        stops:          Stops for this mode, from load_transit_stops().
        G_track:        OSMnx MultiDiGraph for the track network (may be None).
        max_access_km:  Maximum walk distance to snap to a stop.
        interpolate_km: Spacing for intermediate waypoints (km).

    Returns:
        List of (lon, lat) tuples.  Empty list means mode is not viable for
        this OD pair (caller should fall through to next tier).
    """
    # ── Stop snapping ─────────────────────────────────────────────────────────
    origin_stop = nearest_stop(stops, origin, max_km=max_access_km)
    if origin_stop is None:
        logger.debug(
            "route_via_stops(%s): no %s stop within %.1f km of origin %s",
            mode_family, mode_family, max_access_km, origin,
        )
        return []

    dest_stop = nearest_stop(
        stops, dest, max_km=max_access_km, exclude_id=origin_stop.stop_id
    )
    if dest_stop is None:
        logger.debug(
            "route_via_stops(%s): no %s stop within %.1f km of dest %s",
            mode_family, mode_family, max_access_km, dest,
        )
        return []

    board_coord  = (origin_stop.lon, origin_stop.lat)
    alight_coord = (dest_stop.lon,   dest_stop.lat)

    # ── Track-graph routing ───────────────────────────────────────────────────
    track_waypoints: List[Tuple[float, float]] = []

    if G_track is not None:
        try:
            import networkx as nx
            import osmnx as ox

            o_node = ox.distance.nearest_nodes(G_track, origin_stop.lon, origin_stop.lat)
            d_node = ox.distance.nearest_nodes(G_track, dest_stop.lon,   dest_stop.lat)

            if o_node != d_node:
                path_nodes = nx.shortest_path(G_track, o_node, d_node, weight="length")
                for i in range(len(path_nodes) - 1):
                    u, v = path_nodes[i], path_nodes[i + 1]
                    edge_data = G_track.get_edge_data(u, v, default={})
                    # Multi-edge: pick first key
                    if isinstance(edge_data, dict) and 0 in edge_data:
                        edge_data = edge_data[0]
                    geom = edge_data.get("geometry") if isinstance(edge_data, dict) else None
                    if geom and hasattr(geom, "coords"):
                        pts = [(float(c[0]), float(c[1])) for c in geom.coords]
                        track_waypoints.extend(pts[1:] if track_waypoints else pts)
                    else:
                        # No geometry — use node coords
                        n_data = G_track.nodes[v]
                        pt = (float(n_data.get("x", 0)), float(n_data.get("y", 0)))
                        track_waypoints.append(pt)

        except Exception as exc:
            logger.debug("route_via_stops: track graph routing failed: %s", exc)
            track_waypoints = []

    # ── Fallback: intermediate stops sorted along the OD vector ──────────────
    if not track_waypoints:
        # Project all stops onto the origin→dest vector and collect those
        # that lie between the two snapped endpoints.
        ox_f, oy_f = origin_stop.lon, origin_stop.lat
        dx = dest_stop.lon - ox_f
        dy = dest_stop.lat - oy_f
        length_sq = dx * dx + dy * dy

        between: List[Tuple[float, Tuple[float, float]]] = []
        if length_sq > 1e-12:
            for s in stops:
                if s.stop_id in (origin_stop.stop_id, dest_stop.stop_id):
                    continue
                # Scalar projection onto OD segment
                t = ((s.lon - ox_f) * dx + (s.lat - oy_f) * dy) / length_sq
                if 0.0 < t < 1.0:
                    # Perpendicular distance
                    px = ox_f + t * dx - s.lon
                    py = oy_f + t * dy - s.lat
                    perp = math.sqrt(px * px + py * py)
                    # Accept stops within ~500 m perpendicular offset
                    # (0.005° ≈ 500 m at UK latitudes)
                    if perp < 0.005:
                        between.append((t, (s.lon, s.lat)))

        between.sort(key=lambda x: x[0])
        track_waypoints = [board_coord] + [c for _, c in between] + [alight_coord]

    if not track_waypoints:
        track_waypoints = [board_coord, alight_coord]

    # ── Interpolate at fine resolution for smooth animation ───────────────────
    interpolated: List[Tuple[float, float]] = []
    all_pts = [origin] + track_waypoints + [dest]
    for i in range(len(all_pts) - 1):
        a, b = all_pts[i], all_pts[i + 1]
        seg_km = _haversine_km(a, b)
        if seg_km < 1e-6:
            continue
        n_steps = max(1, int(seg_km / interpolate_km))
        if not interpolated:
            interpolated.append(a)
        for step in range(1, n_steps + 1):
            t = step / n_steps
            interpolated.append((
                a[0] + t * (b[0] - a[0]),
                a[1] + t * (b[1] - a[1]),
            ))

    if len(interpolated) < 2:
        return [origin, dest]

    logger.debug(
        "route_via_stops(%s): %d waypoints → %d interpolated pts",
        mode_family, len(track_waypoints), len(interpolated),
    )
    return interpolated


# ── Contraflow / one-way fetch ─────────────────────────────────────────────────

def fetch_contraflow_cycling(
    south: float,
    west: float,
    north: float,
    east: float,
    timeout_s: int = 25,
) -> List[Dict]:
    """
    Fetch contraflow cycling infrastructure from Overpass.

    Covers:
      oneway:bicycle=no          — modern tag: cyclists can go both ways on a one-way road
      cycleway:left:oneway=-1    — contraflow lane on left side
      cycleway:right:oneway=-1   — contraflow lane on right side
      cycleway~opposite          — legacy catch-all tag (deprecated but common)

    Returns a list of dicts:
        {'name': str, 'coords': [(lon,lat), ...], 'tag': str}
    One dict per OSM way.  Empty list on failure.
    """
    query = (
        f"[out:json][timeout:{timeout_s}];\n"
        "(\n"
        f'  way["oneway:bicycle"="no"]({south},{west},{north},{east});\n'
        f'  way["cycleway:left:oneway"="-1"]({south},{west},{north},{east});\n'
        f'  way["cycleway:right:oneway"="-1"]({south},{west},{north},{east});\n'
        f'  way["cycleway"~"opposite"]({south},{west},{north},{east});\n'
        ");\n"
        "out body geom;"
    )
    raw = _overpass_post(query, timeout_s=timeout_s)
    if not raw:
        return []

    result = []
    for el in raw.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry", [])
        coords = []
        for pt in geom:
            try:
                coords.append((float(pt["lon"]), float(pt["lat"])))
            except (KeyError, TypeError):
                continue
        if len(coords) < 2:
            continue
        tags = el.get("tags", {})
        # Determine the most descriptive tag present
        if tags.get("oneway:bicycle") == "no":
            tag_desc = "oneway:bicycle=no"
        elif tags.get("cycleway:left:oneway") == "-1":
            tag_desc = "cycleway:left:oneway=-1"
        elif tags.get("cycleway:right:oneway") == "-1":
            tag_desc = "cycleway:right:oneway=-1"
        else:
            tag_desc = "cycleway=opposite"

        result.append({
            "name":   tags.get("name", ""),
            "coords": coords,
            "tag":    tag_desc,
        })

    logger.info(
        "transit_stop_loader: %d contraflow cycle segments (bbox %.3f,%.3f→%.3f,%.3f)",
        len(result), south, west, north, east,
    )
    return result


def fetch_contraflow_bus(
    south: float,
    west: float,
    north: float,
    east: float,
    timeout_s: int = 25,
) -> List[Dict]:
    """
    Fetch contraflow bus lanes from Overpass.

    Tags:
      oneway:bus=no              — buses can go against one-way traffic
      busway~(opposite|lane)     — contraflow bus lane way
      bus:backward=yes           — bus allowed in reverse direction

    Returns the same dict format as fetch_contraflow_cycling().
    """
    query = (
        f"[out:json][timeout:{timeout_s}];\n"
        "(\n"
        f'  way["oneway:bus"="no"]({south},{west},{north},{east});\n'
        f'  way["busway"~"opposite"]({south},{west},{north},{east});\n'
        f'  way["bus:backward"="yes"]({south},{west},{north},{east});\n'
        ");\n"
        "out body geom;"
    )
    raw = _overpass_post(query, timeout_s=timeout_s)
    if not raw:
        return []

    result = []
    for el in raw.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry", [])
        coords = []
        for pt in geom:
            try:
                coords.append((float(pt["lon"]), float(pt["lat"])))
            except (KeyError, TypeError):
                continue
        if len(coords) < 2:
            continue
        tags = el.get("tags", {})
        tag_desc = (
            "oneway:bus=no"       if tags.get("oneway:bus") == "no"    else
            "busway=opposite"     if "opposite" in tags.get("busway", "") else
            "bus:backward=yes"
        )
        result.append({
            "name":   tags.get("name", ""),
            "coords": coords,
            "tag":    tag_desc,
        })

    logger.info(
        "transit_stop_loader: %d contraflow bus segments", len(result)
    )
    return result