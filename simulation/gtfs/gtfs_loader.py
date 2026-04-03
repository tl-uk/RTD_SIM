"""
simulation/gtfs/gtfs_loader.py

Parses GTFS static feeds (zip or directory) into plain Python dicts.

Handles all 7 core files:
  stops.txt         → stop_id, name, lat, lon, wheelchair
  routes.txt        → route_id, agency_id, short_name, long_name, route_type, fuel_type
  trips.txt         → trip_id, route_id, service_id, shape_id, direction_id
  stop_times.txt    → trip_id, stop_id, stop_sequence, arrival_time, departure_time
  shapes.txt        → shape_id → ordered (lon, lat) coordinate list
  calendar.txt      → service_id → weekday bitmask + date range
  calendar_dates.txt → service_id exceptions (additions / removals)

After parsing, GTFSLoader.compute_headways() aggregates stop_times into
per-(route, stop) average headways in seconds — the key input to the
generalised cost formula in router.py.

Fuel type inference:
  GTFS has no mandatory electric/diesel field, but we can infer it from:
  1. route_type extended codes (11=trolleybus, 109=suburban rail, etc.)
  2. route_desc keywords ("electric", "diesel", "hydrogen", "hybrid")
  3. route_color (many agencies colour electric routes distinctly)
  4. A user-supplied overrides dict fed in at construction

Design principles:
  - Pure stdlib only (csv, zipfile, os, re, datetime) — no pandas dependency
  - Lazy parsing: files read on first access, cached thereafter
  - Tolerant: missing optional files are silently skipped, not fatal
  - Timezone-agnostic: times stored as total seconds past midnight (int)
    so 25:30:00 (next-day trip) stores as 91800 without datetime objects
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

logger = logging.getLogger(__name__)

# ── GTFS route_type → RTD_SIM mode mapping ───────────────────────────────────
# https://gtfs.org/documentation/schedule/reference/#routestxt
_ROUTE_TYPE_TO_MODE: Dict[int, str] = {
    0:   'tram',             # Tram / Streetcar / Light Rail
    1:   'local_train',      # Metro / Subway
    2:   'intercity_train',  # Rail (intercity treated as primary)
    3:   'bus',              # Bus
    4:   'ferry_diesel',     # Ferry (assume diesel until tagged electric)
    5:   'tram',             # Cable Car
    6:   'tram',             # Gondola / Suspended Cable Car
    7:   'tram',             # Funicular
    11:  'tram',             # Trolleybus (electric, reclassified below)
    12:  'local_train',      # Monorail
    # Extended route types
    100: 'intercity_train',  # Railway Service
    101: 'intercity_train',  # High Speed Rail
    102: 'intercity_train',  # Long Distance Rail
    103: 'local_train',      # Inter-Regional Rail
    104: 'local_train',      # Car Transport Rail
    105: 'local_train',      # Sleeper Rail
    106: 'local_train',      # Regional Rail
    107: 'local_train',      # Tourist Railway
    108: 'local_train',      # Rail Shuttle
    109: 'local_train',      # Suburban Railway
    110: 'local_train',      # Replacement Rail
    200: 'bus',              # Coach
    201: 'bus', 202: 'bus',  # International / National Coach
    400: 'tram',             # Urban Railway
    401: 'local_train',      # Metro Service
    402: 'local_train',      # Underground Service
    403: 'local_train',      # Urban Railway Service
    404: 'tram',             # All Urban Railway
    405: 'local_train',      # Monorail
    700: 'bus',              # Bus Service
    701: 'bus', 702: 'bus',  # Regional / Express Bus
    703: 'bus', 704: 'bus', 705: 'bus',
    706: 'bus', 707: 'bus', 708: 'bus',
    709: 'bus', 710: 'bus', 711: 'bus',
    712: 'bus', 713: 'bus', 714: 'bus',
    715: 'bus', 716: 'bus',
    717: 'bus',              # Share Taxi
    800: 'tram',             # Trolleybus Service (electric)
    900: 'tram',             # Tram Service
    901: 'tram', 902: 'tram', 903: 'tram',
    904: 'tram', 905: 'tram', 906: 'tram',
    1000: 'ferry_diesel',    # Water Transport Service
    1001: 'ferry_diesel', 1002: 'ferry_diesel',
    1003: 'ferry_diesel', 1004: 'ferry_diesel',
    1005: 'ferry_diesel', 1006: 'ferry_diesel',
    1007: 'ferry_diesel', 1008: 'ferry_diesel',
    1009: 'ferry_diesel', 1010: 'ferry_diesel',
    1011: 'ferry_diesel', 1012: 'ferry_diesel',
    1100: 'flight_domestic', # Air Service
}

# Route types that are inherently electric (no fuel inference needed)
_ELECTRIC_ROUTE_TYPES: Set[int] = {
    0, 1, 5, 6, 7, 11, 12,
    400, 401, 402, 403, 404, 405,
    800, 900, 901, 902, 903, 904, 905, 906,
}

# Keywords in route_desc / route_long_name that signal fuel type
_FUEL_KEYWORDS: Dict[str, str] = {
    'electric': 'electric',
    'battery': 'electric',
    'bev': 'electric',
    'zero.emission': 'electric',
    'zero emission': 'electric',
    'zev': 'electric',
    'trolley': 'electric',
    'hydrogen': 'hydrogen',
    'fuel.cell': 'hydrogen',
    'fcev': 'hydrogen',
    'diesel': 'diesel',
    'petrol': 'diesel',
    'hybrid': 'hybrid',
}


def _parse_time_s(time_str: str) -> int:
    """
    Parse GTFS time string (HH:MM:SS, including >24h next-day trips)
    to total seconds past midnight.

    Returns -1 on parse failure.
    """
    try:
        parts = time_str.strip().split(':')
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except Exception:
        return -1


class GTFSLoader:
    """
    Parses a GTFS static feed (zip or directory) into Python dicts.

    Usage:
        loader = GTFSLoader('/path/to/gtfs.zip')
        loader.load()
        stops   = loader.stops           # {stop_id: {...}}
        routes  = loader.routes          # {route_id: {...}}
        shapes  = loader.shapes          # {shape_id: [(lon, lat), ...]}
        headways = loader.compute_headways()  # {(route_id, stop_id): avg_headway_s}
    """

    def __init__(
        self,
        feed_path: str | Path,
        fuel_overrides: Optional[Dict[str, str]] = None,
        service_date: Optional[str] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,  # (west, south, east, north)
    ):
        self.feed_path    = Path(feed_path)
        self.fuel_overrides = fuel_overrides or {}
        self.service_date   = service_date
        self.bbox = bbox

        # Parsed data (populated by load())
        self.stops:      Dict[str, Dict[str, Any]] = {}
        self.routes:     Dict[str, Dict[str, Any]] = {}
        self.trips:      Dict[str, Dict[str, Any]] = {}
        self.stop_times: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.shapes:     Dict[str, List[Tuple[float, float]]] = {}
        
        # Track valid IDs for cascading filter
        self._active_services: Optional[Set[str]] = None
        self._valid_trips: Set[str] = set()
        self._valid_routes: Set[str] = set()
        self._valid_shapes: Set[str] = set()

        self._loaded = False

    # ── Loading ───────────────────────────────────────────────────────────────

    def load(self) -> 'GTFSLoader':
        if self._loaded:
            return self
        logger.info("Loading GTFS feed: %s", self.feed_path)
        self._parse_all()
        self._loaded = True
        return self

    def _yield_csv_rows(self, name: str):
        """Generator that yields rows one by one to prevent MemoryErrors."""
        if self.feed_path.suffix.lower() == '.zip':
            try:
                zf = zipfile.ZipFile(self.feed_path)
                match = next((n for n in zf.namelist() if n.endswith(f'/{name}') or n == name), None)
                if match is None: return
                with zf.open(match) as f:
                    wrapper = io.TextIOWrapper(f, encoding='utf-8-sig')
                    for row in csv.DictReader(wrapper):
                        yield row
                zf.close()
            except KeyError: return
        else:
            path = self.feed_path / name
            if not path.exists(): return
            with open(path, encoding='utf-8-sig') as f:
                for row in csv.DictReader(f):
                    yield row

    def _parse_all(self) -> None:
        self._parse_calendar()
        self._parse_calendar_dates()
        self._parse_stops()
        self._parse_stop_times()  # MUST run before trips to filter valid trips
        self._parse_trips()       # MUST run before routes/shapes to filter valid routes
        self._parse_routes()
        self._parse_shapes()

    # ── Individual file parsers ───────────────────────────────────────────────

    def _parse_calendar(self) -> None:
        if self.service_date is None: return
        self._active_services = set()
        try:
            y, m, d = int(self.service_date[:4]), int(self.service_date[4:6]), int(self.service_date[6:])
            from datetime import date
            target = date(y, m, d)
            day_col = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'][target.weekday()]
        except Exception:
            self._active_services = None
            return

        for row in self._yield_csv_rows('calendar.txt'):
            try:
                start, end = row.get('start_date', '19700101'), row.get('end_date', '20991231')
                from datetime import date as _date
                s = _date(int(start[:4]), int(start[4:6]), int(start[6:]))
                e = _date(int(end[:4]), int(end[4:6]), int(end[6:]))
                if s <= target <= e and row.get(day_col, '0') == '1':
                    self._active_services.add(row['service_id'])
            except Exception: continue

    def _parse_calendar_dates(self) -> None:
        if self.service_date is None or self._active_services is None: return
        for row in self._yield_csv_rows('calendar_dates.txt'):
            if row.get('date', '') != self.service_date: continue
            sid, exc = row.get('service_id', ''), row.get('exception_type', '')
            if exc == '1': self._active_services.add(sid)
            elif exc == '2': self._active_services.discard(sid)

    def _parse_stops(self) -> None:
        count = 0
        for row in self._yield_csv_rows('stops.txt'):
            sid = row.get('stop_id', '').strip()
            if not sid: continue
            try:
                lat, lon = float(row.get('stop_lat', 0) or 0), float(row.get('stop_lon', 0) or 0)
            except ValueError: continue
            if lat == 0.0 and lon == 0.0: continue
            
            # SPATIAL FILTER: Skip stops outside the map
            if self.bbox:
                west, south, east, north = self.bbox
                if not (west <= lon <= east and south <= lat <= north):
                    continue

            self.stops[sid] = {
                'name': row.get('stop_name', '').strip(),
                'lat': lat, 'lon': lon,
                'code': row.get('stop_code', '').strip(),
                'wheelchair': row.get('wheelchair_boarding', '0') == '1',
                'location_type': int(row.get('location_type', '0') or '0'),
                'parent_station': row.get('parent_station', '').strip(),
            }
            count += 1
        logger.info(f"GTFS: Filtered to {count} stops within map region.")

    def _parse_stop_times(self) -> None:
        count = 0
        for row in self._yield_csv_rows('stop_times.txt'):
            sid = row.get('stop_id', '').strip()
            
            # CASCADING FILTER: If stop isn't in our map, discard!
            if sid not in self.stops: continue
                
            tid = row.get('trip_id', '').strip()
            self._valid_trips.add(tid) # Save trip ID for the next cascade
            
            dep_str = row.get('departure_time', '') or row.get('arrival_time', '')
            arr_str = row.get('arrival_time', '') or dep_str
            dep_s, arr_s = _parse_time_s(dep_str), _parse_time_s(arr_str)
            if dep_s < 0: continue
            
            try: seq = int(row.get('stop_sequence', '0') or '0')
            except ValueError: seq = 0

            self.stop_times[tid].append({
                'stop_id': sid, 'stop_sequence': seq,
                'arrival_s': arr_s, 'departure_s': dep_s,
                'pickup_type': int(row.get('pickup_type', '0') or '0'),
                'dropoff_type': int(row.get('drop_off_type', '0') or '0'),
            })
            count += 1

        for tid in self.stop_times:
            self.stop_times[tid].sort(key=lambda x: x['stop_sequence'])
        logger.info(f"GTFS: Parsed {count} stop_times (dropped millions outside region).")

    def _parse_trips(self) -> None:
        for row in self._yield_csv_rows('trips.txt'):
            tid = row.get('trip_id', '').strip()
            
            # CASCADING FILTER: Only keep trips serving our stops
            if tid not in self._valid_trips: continue
                
            sid = row.get('service_id', '').strip()
            if self._active_services is not None and sid not in self._active_services: continue
                
            route_id, shape_id = row.get('route_id', '').strip(), row.get('shape_id', '').strip()
            self._valid_routes.add(route_id)
            if shape_id: self._valid_shapes.add(shape_id)
                
            self.trips[tid] = {
                'route_id': route_id, 'service_id': sid, 'shape_id': shape_id,
                'direction_id': int(row.get('direction_id', '0') or '0'),
                'headsign': row.get('trip_headsign', '').strip(),
            }

    def _infer_fuel_type(self, route_id: str, route_type: int, desc: str, color: str) -> str:
        if route_id in self.fuel_overrides: return self.fuel_overrides[route_id]
        if route_type in _ELECTRIC_ROUTE_TYPES: return 'electric'
        combined = (desc + ' ' + color).lower()
        for kw, fuel in _FUEL_KEYWORDS.items():
            if re.search(kw, combined): return fuel
        if route_type in (2, 100, 101, 102, 103, 106, 109): return 'electric'
        return 'diesel'

    def _parse_routes(self) -> None:
        for row in self._yield_csv_rows('routes.txt'):
            rid = row.get('route_id', '').strip()
            
            # CASCADING FILTER: Only keep routes serving our map
            if rid not in self._valid_routes: continue
                
            try: rtype = int(row.get('route_type', '3') or '3')
            except ValueError: rtype = 3

            desc, lname, color = row.get('route_desc', ''), row.get('route_long_name', ''), row.get('route_color', '')
            fuel = self._infer_fuel_type(rid, rtype, desc + ' ' + lname, color)
            mode = _ROUTE_TYPE_TO_MODE.get(rtype, 'bus')

            if mode == 'ferry_diesel' and fuel == 'electric': mode = 'ferry_electric'

            self.routes[rid] = {
                'agency_id': row.get('agency_id', '').strip(),
                'short_name': row.get('route_short_name', '').strip(),
                'long_name': lname.strip(),
                'route_type': rtype, 'mode': mode, 'fuel_type': fuel,
                'color': '#' + color if color else '#888888',
            }

    def _parse_shapes(self) -> None:
        raw: Dict[str, List[Tuple[int, float, float]]] = defaultdict(list)
        for row in self._yield_csv_rows('shapes.txt'):
            shape_id = row.get('shape_id', '').strip()
            
            # CASCADING FILTER: Only keep shapes serving our map
            if shape_id not in self._valid_shapes: continue
                
            try:
                seq, lat, lon = int(row.get('shape_pt_sequence', '0') or '0'), float(row.get('shape_pt_lat', 0) or 0), float(row.get('shape_pt_lon', 0) or 0)
            except (ValueError, TypeError): continue
            raw[shape_id].append((seq, lon, lat))

        for shape_id, pts in raw.items():
            pts.sort(key=lambda x: x[0])
            self.shapes[shape_id] = [(lon, lat) for _, lon, lat in pts]

    # ── Headway computation ───────────────────────────────────────────────────

    def compute_headways(
        self,
        time_window: Optional[Tuple[int, int]] = None,
    ) -> Dict[Tuple[str, str], int]:
        """
        Compute average headway (seconds) per (route_id, stop_id) pair.

        Uses departures within `time_window` (start_s, end_s).
        Defaults to the AM peak: 07:00–09:30 (25200–34200 seconds).

        Returns:
            {(route_id, stop_id): avg_headway_seconds}

        A value of 3600 (1 hour) is used as the default for routes with
        only one trip in the window — it penalises infrequent services
        in the BDI generalised cost without making them infinite.
        """
        if not self._loaded:
            self.load()

        if time_window is None:
            time_window = (25200, 34200)   # 07:00–09:30 default
        t_start, t_end = time_window

        # Collect departure times: {(route_id, stop_id): [dep_s, ...]}
        dep_times: Dict[Tuple[str, str], List[int]] = defaultdict(list)

        for trip_id, stops in self.stop_times.items():
            trip = self.trips.get(trip_id, {})
            route_id = trip.get('route_id', '')
            if not route_id:
                continue
            for st in stops:
                dep_s = st['departure_s']
                if t_start <= dep_s <= t_end:
                    dep_times[(route_id, st['stop_id'])].append(dep_s)

        headways: Dict[Tuple[str, str], int] = {}
        for key, times in dep_times.items():
            if len(times) < 2:
                headways[key] = 3600   # sparse service — 1 hour penalty
                continue
            times.sort()
            gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
            headways[key] = int(sum(gaps) / len(gaps))

        logger.debug("Computed headways for %d (route, stop) pairs", len(headways))
        return headways

    # ── Shape lookup ──────────────────────────────────────────────────────────

    def get_shape_for_trip(self, trip_id: str) -> List[Tuple[float, float]]:
        """Return the (lon, lat) shape coords for a trip_id, or None."""
        trip = self.trips.get(trip_id, {})
        shape_id = trip.get('shape_id', '')
        return self.shapes.get(shape_id, [])
    
    def get_route_for_stop_pair(
        self,
        stop_id_from: str,
        stop_id_to: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Find the first route that serves both stops consecutively.

        Returns the route dict or None.  Used by the GTFS router to look
        up fuel_type and mode when building pydeck layers.
        """
        for trip_id, stops in self.stop_times.items():
            ids = [s['stop_id'] for s in stops]
            try:
                i = ids.index(stop_id_from)
                if i + 1 < len(ids) and ids[i + 1] == stop_id_to:
                    trip = self.trips.get(trip_id, {})
                    return self.routes.get(trip.get('route_id', ''))
            except ValueError:
                continue
        return None

    # ── Stats ─────────────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Return a compact summary for logging."""
        modes: Dict[str, int] = defaultdict(int)
        fuels: Dict[str, int] = defaultdict(int)
        for r in self.routes.values():
            modes[r['mode']] += 1
            fuels[r['fuel_type']] += 1
        return {
            'stops':  len(self.stops),
            'routes': len(self.routes),
            'trips':  len(self.trips),
            'shapes': len(self.shapes),
            'modes':  dict(modes),
            'fuels':  dict(fuels),
        }