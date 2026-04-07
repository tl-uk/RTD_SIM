"""
visualiser/style_config.py

Central styling configuration for RTD_SIM visualizations.

Covers:
  - Map basemap styles (Carto, MapTiler, dark/light/satellite)
  - Mode colours (RGB and hex)
  - Agent and route layer styling
  - Layer visibility defaults
  - Map view defaults
"""

from typing import Dict, List, Optional, Tuple


# ── Map basemap styles ─────────────────────────────────────────────────────────
#
# Grouped by provider.
# Carto styles:   no API key required; reliable.
# MapTiler styles: free tier requires API key (100k tile requests/month).
#                  Register at https://cloud.maptiler.com/auth/widget?mode=signup
#                  Set env var MAPTILER_API_KEY or pass key in sidebar.
#                  The 'openstreetmap' style is recommended for RTD_SIM because
#                  it renders ferry routes (OSM route=ferry relations) as blue
#                  dashed lines and shows harbours, docks, and maritime
#                  infrastructure — critical for sea-road-rail freight modelling.
#
# Key format for MapTiler:
#   "https://api.maptiler.com/maps/{style_id}/style.json?key={API_KEY}"
#
MAP_STYLES: Dict[str, Dict] = {
    # ── Carto (no API key) ─────────────────────────────────────────────────────
    "Light (Carto Positron)": {
        "url":      "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        "provider": "carto",
        "key_required": False,
        "description": "Clean light basemap. Good for agent route visibility.",
        "ferry_lanes": False,
        "emoji":    "🗺️",
    },
    "Voyager (Carto)": {
        "url":      "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
        "provider": "carto",
        "key_required": False,
        "description": "Detailed OSM-based map with waterways and parks. Shows rivers and canals.",
        "ferry_lanes": False,
        "emoji":    "🌍",
    },
    "Dark (Carto Dark Matter)": {
        "url":      "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        "provider": "carto",
        "key_required": False,
        "description": "Dark basemap. Route colours stand out well against dark background.",
        "ferry_lanes": False,
        "emoji":    "🌑",
    },
    "Light (no labels)": {
        "url":      "https://basemaps.cartocdn.com/gl/positron-nolabels-gl-style/style.json",
        "provider": "carto",
        "key_required": False,
        "description": "Clean light map without place name labels. Reduces visual clutter.",
        "ferry_lanes": False,
        "emoji":    "⬜",
    },
    "Dark (no labels)": {
        "url":      "https://basemaps.cartocdn.com/gl/dark-matter-nolabels-gl-style/style.json",
        "provider": "carto",
        "key_required": False,
        "description": "Dark map without labels. Best for emission hotspot heat maps.",
        "ferry_lanes": False,
        "emoji":    "⬛",
    },
    # ── MapTiler (free API key required) ──────────────────────────────────────
    # All MapTiler styles use the same URL pattern with a key parameter.
    # The placeholder {MAPTILER_KEY} is replaced at render time by
    # render_map() using the key from session_state or env var.
    "OpenStreetMap (MapTiler) ⭐": {
        "url":      "https://api.maptiler.com/maps/openstreetmap/style.json?key={MAPTILER_KEY}",
        "provider": "maptiler",
        "key_required": True,
        "description": (
            "Full OpenStreetMap rendering with ferry routes (blue dashed lines), "
            "harbours, docks, and shipping lanes. Recommended for freight modelling."
        ),
        "ferry_lanes": True,
        "emoji":    "⛴️",
    },
    "Streets (MapTiler)": {
        "url":      "https://api.maptiler.com/maps/streets-v2/style.json?key={MAPTILER_KEY}",
        "provider": "maptiler",
        "key_required": True,
        "description": "Detailed street map with POIs. Good general-purpose basemap.",
        "ferry_lanes": True,
        "emoji":    "🛣️",
    },
    "Topo (MapTiler)": {
        "url":      "https://api.maptiler.com/maps/topo-v2/style.json?key={MAPTILER_KEY}",
        "provider": "maptiler",
        "key_required": True,
        "description": "Topographic map with terrain contours. Useful for Highland simulations.",
        "ferry_lanes": True,
        "emoji":    "🏔️",
    },
    "Satellite Hybrid (MapTiler)": {
        "url":      "https://api.maptiler.com/maps/hybrid/style.json?key={MAPTILER_KEY}",
        "provider": "maptiler",
        "key_required": True,
        "description": "Satellite imagery with road and label overlay.",
        "ferry_lanes": False,
        "emoji":    "🛰️",
    },
    "Ocean (MapTiler)": {
        "url":      "https://api.maptiler.com/maps/ocean/style.json?key={MAPTILER_KEY}",
        "provider": "maptiler",
        "key_required": True,
        "description": (
            "Nautical chart style with depth contours, shipping lanes, and maritime "
            "features. Ideal for CalMac ferry and offshore freight routing."
        ),
        "ferry_lanes": True,
        "emoji":    "🌊",
    },
}

# Default style used when no selection is made.
DEFAULT_MAP_STYLE_NAME = "Light (Carto Positron)"
DEFAULT_MAP_STYLE_URL  = MAP_STYLES[DEFAULT_MAP_STYLE_NAME]["url"]


def get_map_style_url(
    style_name: str,
    maptiler_key: Optional[str] = None,
) -> str:
    """
    Return the GL JSON style URL for the given style name.

    Substitutes the MapTiler API key into the URL template when needed.
    Falls back to the Carto Positron style if the key is missing for a
    MapTiler style (so the map still renders, just without the premium tiles).

    Args:
        style_name:   Key from MAP_STYLES dict.
        maptiler_key: MapTiler API key string (or None).

    Returns:
        GL style URL string suitable for pdk.Deck(map_style=...).
    """
    import os

    style = MAP_STYLES.get(style_name, MAP_STYLES[DEFAULT_MAP_STYLE_NAME])

    if not style["key_required"]:
        return style["url"]

    # Resolve key: argument → env var → fallback to Carto
    key = (maptiler_key
           or os.environ.get("MAPTILER_API_KEY", "")
           or os.environ.get("MAPTILER_KEY", ""))

    if not key:
        # No key available — silently fall back to Carto Voyager (shows waterways)
        return MAP_STYLES["Voyager (Carto)"]["url"]

    return style["url"].replace("{MAPTILER_KEY}", key)


# ── Layer visibility defaults ──────────────────────────────────────────────────
#
# These control which overlay layers are shown on the map by default.
# All values can be overridden per-session in the map tab controls.
#
LAYER_DEFAULTS: Dict[str, bool] = {
    "agents":        True,   # Agent position markers
    "routes":        True,   # Agent route polylines
    "infrastructure": True,  # Charging station markers
    "rail":          False,  # OpenRailMap / spine rail network
    "gtfs_routes":   False,  # GTFS service route lines (PathLayer)
    "gtfs_stops":    False,  # GTFS stop markers (ScatterplotLayer)
    "gtfs_electric_only": False,  # Filter GTFS to electric services only
    "naptan_stops":  False,  # NaPTAN rail/ferry/tram station markers
    "ferry_routes":  False,  # Ferry route layer (future: from OSM or GTFS)
    "congestion":    False,  # Road congestion heat overlay
}

# Human-readable labels and help text for each layer toggle.
LAYER_LABELS: Dict[str, Dict] = {
    "agents": {
        "label": "Show Agents",
        "help":  "Agent positions as coloured dots (colour = transport mode).",
        "emoji": "🔵",
    },
    "routes": {
        "label": "Show Routes",
        "help":  "Agent route polylines. Rail routes show via station waypoints.",
        "emoji": "🛣️",
    },
    "infrastructure": {
        "label": "Show Chargers",
        "help":  "EV charging station markers. Red circles = high utilisation.",
        "emoji": "🔌",
    },
    "rail": {
        "label": "Rail Network",
        "help":  "OpenRailMap track geometry (or hardcoded spine when offline).",
        "emoji": "🚆",
    },
    "gtfs_routes": {
        "label": "GTFS Routes",
        "help":  "Bus, tram, and ferry service lines from the loaded GTFS feed.",
        "emoji": "🚌",
    },
    "gtfs_stops": {
        "label": "GTFS Stops",
        "help":  "Bus and tram stop positions from the loaded GTFS feed.",
        "emoji": "🚏",
    },
    "gtfs_electric_only": {
        "label": "Electric GTFS only",
        "help":  "Filter GTFS layer to show only electric/zero-emission services.",
        "emoji": "⚡",
    },
    "naptan_stops": {
        "label": "NaPTAN Stations",
        "help":  "Authoritative UK rail, metro, tram, and ferry terminal positions.",
        "emoji": "📍",
    },
    "ferry_routes": {
        "label": "Ferry Lanes",
        "help":  "Scheduled ferry route lines (requires MapTiler OSM or GTFS ferry data).",
        "emoji": "⛴️",
    },
    "congestion": {
        "label": "Congestion",
        "help":  "Road congestion heat overlay (red = high congestion).",
        "emoji": "🔴",
    },
}


# ── Mode colours ────────────────────────────────────────────────────────────────

MODE_COLORS_RGB: Dict[str, List[int]] = {
    # Personal
    "walk":             [34,  197,  94],
    "bike":             [59,  130, 246],
    "e_scooter":        [139, 195,  74],
    "cargo_bike":       [34,  197,  94],
    # Road – personal
    "car":              [239,  68,  68],
    "ev":               [168,  85, 245],
    "taxi_ev":          [192, 132, 252],
    "taxi_diesel":      [209,  99,  99],
    # Road – light commercial
    "van_electric":     [16,  185, 129],
    "van_diesel":       [107, 114, 128],
    # Road – medium freight
    "truck_electric":   [74,  222, 128],
    "truck_diesel":     [120, 113, 108],
    # Road – heavy freight
    "hgv_electric":     [52,  211, 153],
    "hgv_diesel":       [75,   85,  99],
    "hgv_hydrogen":     [96,  165, 250],
    # Public transport
    "bus":              [245, 158,  11],
    "tram":             [255, 193,   7],
    "local_train":      [33,  150, 243],
    "intercity_train":  [63,   81, 181],
    "freight_rail":     [101,  84, 192],
    # Maritime
    "ferry_diesel":     [0,   150, 136],
    "ferry_electric":   [0,   188, 212],
    # Aviation
    "flight_domestic":  [244,  67,  54],
    "flight_electric":  [233,  30,  99],
}

MODE_COLORS_HEX: Dict[str, str] = {
    "walk":             "#22c55e",
    "bike":             "#3b82f6",
    "e_scooter":        "#8bc34a",
    "cargo_bike":       "#22c55e",
    "car":              "#ef4444",
    "ev":               "#a855f7",
    "taxi_ev":          "#c084fc",
    "taxi_diesel":      "#d16363",
    "van_electric":     "#10b981",
    "van_diesel":       "#6b7280",
    "truck_electric":   "#4ade80",
    "truck_diesel":     "#78716c",
    "hgv_electric":     "#34d399",
    "hgv_diesel":       "#4b5563",
    "hgv_hydrogen":     "#60a5fa",
    "bus":              "#f59e0b",
    "tram":             "#ffc107",
    "local_train":      "#2196f3",
    "intercity_train":  "#3f51b5",
    "freight_rail":     "#6554c0",
    "ferry_diesel":     "#009688",
    "ferry_electric":   "#00bcd4",
    "flight_domestic":  "#f44336",
    "flight_electric":  "#e91e63",
}

MODE_EMOJI: Dict[str, str] = {
    "walk":            "🚶",
    "bike":            "🚲",
    "e_scooter":       "🛴",
    "cargo_bike":      "📦🚲",
    "car":             "🚗",
    "ev":              "🔋",
    "taxi_ev":         "🔋🚕",
    "taxi_diesel":     "🚕",
    "van_electric":    "🔋🚐",
    "van_diesel":      "🚐",
    "truck_electric":  "🔋🚛",
    "truck_diesel":    "🚛",
    "hgv_electric":    "🔋🚚",
    "hgv_diesel":      "🚚",
    "hgv_hydrogen":    "💧🚚",
    "bus":             "🚌",
    "tram":            "🚋",
    "local_train":     "🚆",
    "intercity_train": "🚄",
    "freight_rail":    "🚂",
    "ferry_diesel":    "⛴️",
    "ferry_electric":  "🛳️",
    "flight_domestic": "✈️",
    "flight_electric": "🛩️",
}


# ── Agent marker styling ───────────────────────────────────────────────────────

AGENT_RADIUS_PIXELS:    int   = 8
AGENT_OPACITY:          float = 0.85
ARRIVED_RADIUS_PIXELS:  int   = 10   # slightly larger ring for arrived agents
ARRIVED_RING_COLOR:     List[int] = [255, 255, 0, 120]   # yellow ring

# ── Route line styling ─────────────────────────────────────────────────────────

ROUTE_WIDTH_PIXELS:   int   = 3
ROUTE_OPACITY:        float = 0.65
RAIL_ROUTE_WIDTH:     int   = 4     # slightly thicker for rail routes
FERRY_ROUTE_WIDTH:    int   = 4
FERRY_ROUTE_DASH:     bool  = True  # dashed line for ferry routes (future)

# ── Infrastructure styling ─────────────────────────────────────────────────────

CHARGER_RADIUS_PIXELS: int = 12
CHARGER_FREE_COLOR:    List[int] = [16, 185, 129, 200]   # green  = available
CHARGER_BUSY_COLOR:    List[int] = [239, 68, 68, 200]    # red    = full
CHARGER_MID_COLOR:     List[int] = [245, 158, 11, 200]   # amber  = >50% used

# ── Rail / track styling ───────────────────────────────────────────────────────

RAIL_LINE_COLOR:       List[int] = [99, 102, 241]    # indigo
RAIL_LINE_WIDTH:       int       = 2
TRAM_LINE_COLOR:       List[int] = [251, 191, 36]    # amber
TRAM_LINE_WIDTH:       int       = 2
FERRY_LANE_COLOR:      List[int] = [14, 165, 233]    # sky blue
FERRY_LANE_WIDTH:      int       = 2

# ── NaPTAN station marker ──────────────────────────────────────────────────────

NAPTAN_RAIL_COLOR:   List[int] = [33, 150, 243, 200]   # blue
NAPTAN_FERRY_COLOR:  List[int] = [0, 188, 212, 200]    # cyan
NAPTAN_TRAM_COLOR:   List[int] = [255, 193, 7, 200]    # amber
NAPTAN_RADIUS:       int = 7

# ── Congestion heatmap ─────────────────────────────────────────────────────────

CONGESTION_MIN_WIDTH: int = 2
CONGESTION_MAX_WIDTH: int = 10


def get_congestion_color(factor: float) -> List[int]:
    """Map congestion factor (1.0–3.0) to green→yellow→red RGB."""
    normalized = min(1.0, max(0.0, (factor - 1.0) / 2.0))
    if normalized < 0.5:
        r = int(255 * normalized * 2)
        g = 255
        b = 0
    else:
        r = 255
        g = int(255 * (1 - (normalized - 0.5) * 2))
        b = 0
    return [r, g, b]


def get_congestion_width(factor: float) -> float:
    normalized = min(1.0, (factor - 1.0) / 2.0)
    return CONGESTION_MIN_WIDTH + (CONGESTION_MAX_WIDTH - CONGESTION_MIN_WIDTH) * normalized


# ── Default view state ─────────────────────────────────────────────────────────

DEFAULT_VIEW_STATE = {
    "latitude":  55.9533,
    "longitude": -3.1883,
    "zoom":      12,
    "pitch":     0,
    "bearing":   0,
}

# ── Tooltip styling ────────────────────────────────────────────────────────────

TOOLTIP_STYLE = {
    "backgroundColor": "rgba(0, 0, 0, 0.85)",
    "color":           "white",
    "fontSize":        "13px",
    "padding":         "8px 12px",
    "borderRadius":    "6px",
    "lineHeight":      "1.6",
}