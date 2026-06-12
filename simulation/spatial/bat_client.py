"""
simulation/spatial/bat_client.py

Buses & Trains API client for RTD_SIM.
https://busesandtrains.co.uk/

PURPOSE
───────
Provides the live data tier for RTD_SIM's transport layer.  In static mode
(ABM baseline), the transit graph is built from GTFS and this module is never
called.  In live mode (digital twin), this module is called per simulation
step to inject real departure times, vehicle positions, and service disruptions
into the running simulation.

The Buses & Trains API (BAT) covers:
  • 530,000+ stops across England, Wales, and Scotland (bus, rail, tram)
  • Live departure times from 400,000+ bus stops
  • National Rail arrivals & departures
  • Live vehicle positions (bus GPS, train service data)
  • Multi-modal OTP routing (bus, rail, walking, cycling)

All data is keyed by NaPTAN ATCO code, which aligns with RTD_SIM's
NaPTAN stop registry — no ID translation is needed.

API BASE
────────
  https://api.busesandtrains.co.uk/v1/

AUTH
────
  Bearer token in Authorization header.
  BAT_API_KEY is read from .env (set by dotenv at startup).
  Alternatively: ?key=BAT_API_KEY as a query param (less preferred).

RATE LIMITS
───────────
  Free tier:  300 requests / day.
  Paid tiers: published at https://busesandtrains.co.uk/pricing

  RTD_SIM only calls BAT for stops that are ACTIVE in the current simulation
  step (agents boarding or waiting).  For a 100-agent simulation this is
  typically 5–20 stops per step — well within the free tier even at 100 steps.

  Per-request rate-limit headers are read and respected:
    X-RateLimit-Remaining — requests left in current window
    X-RateLimit-Reset     — epoch seconds when window resets
  When remaining == 0, all further calls are suppressed until reset.

ENDPOINTS USED
──────────────
  GET /v1/stops               — stop search by name or NaPTAN ATCO code
  GET /v1/stops/{atco}/departures  — live departures from one stop
  GET /v1/vehicles            — live vehicle positions (bbox query)
  GET /v1/route               — OTP multi-modal route (validation only)

INTEGRATION
───────────
Called from transport_loader._apply_live_data() when
config.data_mode == 'live'.

    from simulation.spatial.bat_client import BATClient
    bat = BATClient()                       # reads BAT_API_KEY from env
    departures = bat.get_departures(atco_code)
    vehicles   = bat.get_vehicles(bbox)

Data mode flag in SimulationConfig:
    config.data_mode = 'static'   # default — GTFS only, BAT not called
    config.data_mode = 'live'     # BAT called each step for active stops
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib import error as _urllib_error
from urllib import parse as _urllib_parse
from urllib import request as _urllib_request

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_BAT_BASE       = "https://api.busesandtrains.co.uk/v1"
_DEFAULT_TIMEOUT = 10          # seconds per request
_MAX_RETRIES     = 3
_RETRY_BACKOFF   = 2.0         # seconds; doubles on each retry
_MIN_REMAINING   = 5           # suppress calls when rate-limit remaining <= this


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class BATStop:
    """
    One transit stop as returned by the BAT /stops endpoint.

    atco_code is the NaPTAN ATCO code — the same identifier used throughout
    RTD_SIM's NaPTAN registry and transit_stop_loader.TransitStop.naptan_atco.
    """
    atco_code:   str
    name:        str
    lon:         float
    lat:         float
    mode:        str            # 'bus' | 'rail' | 'tram' | 'ferry'
    locality:    str = ""
    indicator:   str = ""       # e.g. "Stop A", "Platform 3"


@dataclass
class BATDeparture:
    """
    One live departure from a stop.

    aimed_departure is the scheduled time (ISO 8601 string).
    expected_departure is the real-time prediction (may equal aimed if no RTI).
    delay_seconds is the computed difference; None if expected is unavailable.
    """
    service:             str            # route number / service name
    destination:         str
    aimed_departure:     str            # ISO 8601, e.g. "2026-06-11T09:42:00"
    expected_departure:  Optional[str]  # None if no real-time data
    operator:            str = ""
    vehicle_id:          str = ""
    delay_seconds:       Optional[int] = None
    cancelled:           bool = False


@dataclass
class BATVehicle:
    """
    One live vehicle position from the BAT /vehicles endpoint.

    operator_ref and vehicle_ref together uniquely identify the vehicle.
    """
    vehicle_ref:    str
    operator_ref:   str
    service:        str
    destination:    str
    lon:            float
    lat:            float
    bearing:        Optional[float] = None   # degrees, 0=N
    recorded_at:    str = ""                 # ISO 8601
    delay_seconds:  Optional[int] = None


@dataclass
class BATRoute:
    """
    One multi-modal journey plan returned by BAT's OTP routing endpoint.

    Used for cross-validation: compare RTD_SIM modelled journey time against
    the OTP-computed time for the same OD pair.
    """
    duration_seconds:  int
    legs:              List[Dict] = field(default_factory=list)
    walk_distance_m:   float = 0.0
    transfers:         int = 0


# ── Client ─────────────────────────────────────────────────────────────────────

class BATClient:
    """
    Thin wrapper around the Buses & Trains REST API.

    Handles authentication, rate-limit tracking, retry with backoff,
    and response parsing.  Stateless between simulation steps — a single
    instance is created at environment setup and reused across all steps.

    Usage:
        bat = BATClient()                      # reads BAT_API_KEY from env
        deps = bat.get_departures("6200125020")
        vehs = bat.get_vehicles(bbox=(55.73, -3.59, 56.18, -2.79))
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.getenv("BAT_API_KEY", "").strip()
        if not self._api_key:
            logger.warning(
                "BATClient: BAT_API_KEY not set — live data tier disabled. "
                "Add BAT_API_KEY to .env to enable real-time departures."
            )
        # Rate-limit state (updated from response headers each call)
        self._rate_limit_remaining: Optional[int] = None
        self._rate_limit_reset:     Optional[float] = None   # epoch seconds

    # ── Public methods ─────────────────────────────────────────────────────────

    def available(self) -> bool:
        """Return True if the API key is set and the rate limit is not exhausted."""
        if not self._api_key:
            return False
        if (self._rate_limit_remaining is not None
                and self._rate_limit_remaining <= _MIN_REMAINING):
            now = time.time()
            reset = self._rate_limit_reset or 0.0
            if now < reset:
                logger.debug(
                    "BATClient: rate limit exhausted — %d requests left, "
                    "resets in %.0fs",
                    self._rate_limit_remaining, reset - now,
                )
                return False
        return True

    def search_stops(
        self,
        query: str,
        limit: int = 10,
    ) -> List[BATStop]:
        """
        Search stops by name or ATCO code.

        Args:
            query: Free-text name (e.g. "Edinburgh Waverley") or ATCO code.
            limit: Maximum results to return.

        Returns:
            List of BATStop objects, empty on failure.
        """
        params = {"q": query, "limit": str(limit)}
        raw = self._get("/stops", params)
        if raw is None:
            return []
        return [self._parse_stop(s) for s in raw.get("stops", []) if s]

    def get_stop(self, atco_code: str) -> Optional[BATStop]:
        """
        Fetch a single stop by NaPTAN ATCO code.

        Args:
            atco_code: NaPTAN ATCO code (e.g. '6200125020').

        Returns:
            BATStop or None if not found.
        """
        raw = self._get(f"/stops/{_urllib_parse.quote(atco_code, safe='')}")
        if raw is None:
            return None
        return self._parse_stop(raw)

    def get_departures(
        self,
        atco_code: str,
        limit: int = 10,
    ) -> List[BATDeparture]:
        """
        Fetch live departures from a stop.

        Args:
            atco_code: NaPTAN ATCO code of the stop.
            limit:     Maximum departures to return.

        Returns:
            List of BATDeparture objects sorted by aimed_departure.
            Empty list on failure or if stop not found.

        Digital twin usage:
            Called once per active stop per simulation step.  The
            delay_seconds value on each departure is added to the
            agent's waiting time in the BDI plan executor.

            Example:
                deps = bat.get_departures("6200125020", limit=5)
                next_bus = deps[0] if deps else None
                if next_bus and next_bus.delay_seconds:
                    agent.wait(next_bus.delay_seconds)
        """
        params = {"limit": str(limit)}
        raw = self._get(
            f"/stops/{_urllib_parse.quote(atco_code, safe='')}/departures",
            params,
        )
        if raw is None:
            return []
        deps = []
        for d in raw.get("departures", []):
            try:
                deps.append(self._parse_departure(d))
            except Exception as exc:
                logger.debug("BATClient: departure parse error: %s — %s", exc, d)
        return sorted(deps, key=lambda d: d.aimed_departure)

    def get_vehicles(
        self,
        bbox: Tuple[float, float, float, float],
    ) -> List[BATVehicle]:
        """
        Fetch live vehicle positions within a bounding box.

        Args:
            bbox: (south, west, north, east) in WGS84 decimal degrees.
                  Follows RTD_SIM's (south, west, north, east) convention.
                  Note: BAT may use a different bbox param order — this
                  method normalises to whatever BAT expects.

        Returns:
            List of BATVehicle objects.  Empty on failure.

        Digital twin usage:
            Called once per simulation step.  The returned vehicle positions
            form the "real fleet" layer on the visualisation map, alongside
            the simulated agent positions.  Spatial overlap between the two
            distributions is the primary digital twin validation metric.
        """
        south, west, north, east = bbox
        params = {
            "south": str(south),
            "west":  str(west),
            "north": str(north),
            "east":  str(east),
        }
        raw = self._get("/vehicles", params)
        if raw is None:
            return []
        vehicles = []
        for v in raw.get("vehicles", []):
            try:
                vehicles.append(self._parse_vehicle(v))
            except Exception as exc:
                logger.debug("BATClient: vehicle parse error: %s — %s", exc, v)
        return vehicles

    def get_route(
        self,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        depart_at: Optional[str] = None,
    ) -> Optional[BATRoute]:
        """
        Request a multi-modal OTP journey plan for cross-validation.

        This is NOT used for agent routing — RTD_SIM's own router handles
        that.  This is called at the END of a simulation step to compare
        the modelled journey time for a completed trip against what OTP
        would have produced.  Divergence > 20% flags a potential routing
        bug or timetable gap.

        Args:
            origin:    (lon, lat) of journey start.
            dest:      (lon, lat) of journey end.
            depart_at: ISO 8601 datetime string. Defaults to now.

        Returns:
            BATRoute with duration and leg breakdown, or None on failure.
        """
        params: Dict[str, str] = {
            "from_lon": str(origin[0]),
            "from_lat": str(origin[1]),
            "to_lon":   str(dest[0]),
            "to_lat":   str(dest[1]),
        }
        if depart_at:
            params["depart_at"] = depart_at

        raw = self._get("/route", params)
        if raw is None:
            return None
        try:
            return BATRoute(
                duration_seconds = int(raw.get("duration", 0)),
                legs             = raw.get("legs", []),
                walk_distance_m  = float(raw.get("walk_distance", 0)),
                transfers        = int(raw.get("transfers", 0)),
            )
        except Exception as exc:
            logger.debug("BATClient: route parse error: %s", exc)
            return None

    # ── Batch helpers (rate-limit-aware) ───────────────────────────────────────

    def get_departures_batch(
        self,
        atco_codes: List[str],
        limit_per_stop: int = 5,
    ) -> Dict[str, List[BATDeparture]]:
        """
        Fetch departures for multiple stops, respecting the rate limit.

        Stops are processed in order.  If the rate limit is exhausted mid-
        batch, remaining stops are returned as empty lists and a warning is
        logged.  The caller should handle empty lists gracefully (fall back
        to scheduled GTFS headways).

        Args:
            atco_codes:     List of NaPTAN ATCO codes.
            limit_per_stop: Max departures per stop.

        Returns:
            Dict mapping atco_code → List[BATDeparture].
        """
        result: Dict[str, List[BATDeparture]] = {}
        for atco in atco_codes:
            if not self.available():
                logger.warning(
                    "BATClient: rate limit reached after %d/%d stops "
                    "— remaining stops use GTFS scheduled times",
                    len(result), len(atco_codes),
                )
                for remaining in atco_codes[len(result):]:
                    result[remaining] = []
                break
            result[atco] = self.get_departures(atco, limit=limit_per_stop)
        return result

    # ── Internal HTTP ──────────────────────────────────────────────────────────

    def _get(
        self,
        path: str,
        params: Optional[Dict[str, str]] = None,
    ) -> Optional[dict]:
        """
        Make a GET request to the BAT API.

        Handles authentication, retry with exponential backoff for 429/503,
        rate-limit header parsing, and JSON decoding.

        Returns parsed JSON dict on success, None on any failure.
        """
        if not self._api_key:
            return None

        url = _BAT_BASE + path
        if params:
            url = url + "?" + _urllib_parse.urlencode(params)

        delay = _RETRY_BACKOFF
        for attempt in range(_MAX_RETRIES):
            try:
                req = _urllib_request.Request(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Accept":        "application/json",
                        "User-Agent":    "RTD_SIM/1.0 (research; decarbonisation)",
                    },
                )
                with _urllib_request.urlopen(req, timeout=_DEFAULT_TIMEOUT) as resp:
                    # Parse rate-limit headers
                    self._update_rate_limit(resp.headers)
                    body = resp.read()
                    return json.loads(body)

            except _urllib_error.HTTPError as exc:
                self._update_rate_limit(exc.headers)
                if exc.code == 429:
                    # Rate limited — read Retry-After if present
                    retry_after = float(
                        exc.headers.get("Retry-After", delay)
                    )
                    logger.warning(
                        "BATClient: 429 rate-limited (attempt %d/%d) "
                        "— waiting %.0fs",
                        attempt + 1, _MAX_RETRIES, retry_after,
                    )
                    time.sleep(retry_after)
                    delay *= 2
                    continue
                elif exc.code in (500, 502, 503, 504) and attempt < _MAX_RETRIES - 1:
                    logger.debug(
                        "BATClient: HTTP %d on %s (attempt %d/%d) — retrying",
                        exc.code, path, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue
                elif exc.code == 404:
                    logger.debug("BATClient: 404 for %s", path)
                    return None
                elif exc.code == 401:
                    logger.error(
                        "BATClient: 401 Unauthorized — check BAT_API_KEY in .env"
                    )
                    return None
                else:
                    logger.warning("BATClient: HTTP %d for %s", exc.code, path)
                    return None

            except Exception as exc:
                msg = str(exc).lower()
                if ("timed out" in msg or "timeout" in msg) and attempt < _MAX_RETRIES - 1:
                    logger.debug(
                        "BATClient: timeout on %s (attempt %d/%d) — retrying",
                        path, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue
                logger.warning("BATClient: request failed for %s: %s", path, exc)
                return None

        logger.warning("BATClient: gave up after %d retries for %s", _MAX_RETRIES, path)
        return None

    def _update_rate_limit(self, headers) -> None:
        """Parse X-RateLimit-* headers and update internal state."""
        if headers is None:
            return
        try:
            remaining = headers.get("X-RateLimit-Remaining")
            if remaining is not None:
                self._rate_limit_remaining = int(remaining)
        except (ValueError, TypeError):
            pass
        try:
            reset = headers.get("X-RateLimit-Reset")
            if reset is not None:
                self._rate_limit_reset = float(reset)
        except (ValueError, TypeError):
            pass

    # ── Parsers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_stop(raw: dict) -> BATStop:
        return BATStop(
            atco_code = str(raw.get("atco_code", raw.get("id", ""))),
            name      = raw.get("name", ""),
            lon       = float(raw.get("longitude", raw.get("lon", 0.0))),
            lat       = float(raw.get("latitude",  raw.get("lat", 0.0))),
            mode      = raw.get("mode", raw.get("type", "bus")),
            locality  = raw.get("locality", raw.get("town", "")),
            indicator = raw.get("indicator", raw.get("platform", "")),
        )

    @staticmethod
    def _parse_departure(raw: dict) -> BATDeparture:
        aimed    = raw.get("aimed_departure",    raw.get("aimed",    ""))
        expected = raw.get("expected_departure", raw.get("expected", None))
        delay: Optional[int] = None
        if aimed and expected and aimed != expected:
            try:
                from datetime import datetime
                fmt = "%Y-%m-%dT%H:%M:%S"
                a = datetime.fromisoformat(aimed[:19])
                e = datetime.fromisoformat(expected[:19])
                delay = int((e - a).total_seconds())
            except Exception:
                pass
        return BATDeparture(
            service            = str(raw.get("service", raw.get("line", ""))),
            destination        = raw.get("destination", raw.get("direction", "")),
            aimed_departure    = aimed,
            expected_departure = expected,
            operator           = raw.get("operator", raw.get("operator_name", "")),
            vehicle_id         = str(raw.get("vehicle_id", raw.get("vehicle", ""))),
            delay_seconds      = delay,
            cancelled          = bool(raw.get("cancelled", False)),
        )

    @staticmethod
    def _parse_vehicle(raw: dict) -> BATVehicle:
        return BATVehicle(
            vehicle_ref   = str(raw.get("vehicle_ref",  raw.get("vehicle_id", ""))),
            operator_ref  = raw.get("operator_ref",  raw.get("operator", "")),
            service       = raw.get("service",       raw.get("line", "")),
            destination   = raw.get("destination",   ""),
            lon           = float(raw.get("longitude", raw.get("lon", 0.0))),
            lat           = float(raw.get("latitude",  raw.get("lat", 0.0))),
            bearing       = _opt_float(raw.get("bearing")),
            recorded_at   = raw.get("recorded_at", raw.get("timestamp", "")),
            delay_seconds = _opt_int(raw.get("delay_seconds", raw.get("delay"))),
        )


# ── Module-level singleton ─────────────────────────────────────────────────────

_CLIENT: Optional[BATClient] = None


def get_client() -> BATClient:
    """
    Return the module-level BATClient singleton.

    Creates it on first call.  Reads BAT_API_KEY from environment.
    Safe to call multiple times — always returns the same instance.
    """
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = BATClient()
    return _CLIENT


# ── Convenience functions ──────────────────────────────────────────────────────

def get_live_delays(
    atco_codes: List[str],
    limit_per_stop: int = 5,
) -> Dict[str, Optional[int]]:
    """
    Return the next-departure delay in seconds for each ATCO code.

    Convenience wrapper for the most common digital twin use case:
    given a list of active stops, return how many seconds each next
    service is delayed (0 = on time, negative = early, None = no RTI).

    Args:
        atco_codes:     Active NaPTAN ATCO codes this simulation step.
        limit_per_stop: Departures to fetch per stop (first is used).

    Returns:
        Dict mapping atco_code → delay_seconds (or None).

    Example (in simulation loop):
        from simulation.spatial.bat_client import get_live_delays
        delays = get_live_delays(active_stop_atcos)
        for agent in boarding_agents:
            d = delays.get(agent.board_stop_atco)
            if d and d > 0:
                agent.add_wait(d)
    """
    client = get_client()
    if not client.available():
        return {a: None for a in atco_codes}

    batch = client.get_departures_batch(atco_codes, limit_per_stop=limit_per_stop)
    result: Dict[str, Optional[int]] = {}
    for atco, deps in batch.items():
        if deps:
            # Use the first non-cancelled departure
            for dep in deps:
                if not dep.cancelled:
                    result[atco] = dep.delay_seconds
                    break
            else:
                result[atco] = None
        else:
            result[atco] = None
    return result


def get_live_vehicles(
    bbox: Tuple[float, float, float, float],
) -> List[BATVehicle]:
    """
    Return live vehicle positions within bbox for the visualisation layer.

    Args:
        bbox: (south, west, north, east) in WGS84.

    Returns:
        List of BATVehicle.  Empty if BAT unavailable or rate-limited.
    """
    client = get_client()
    if not client.available():
        return []
    return client.get_vehicles(bbox)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _opt_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _opt_int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None