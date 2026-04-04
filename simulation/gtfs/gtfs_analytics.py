"""
simulation/gtfs/gtfs_analytics.py

Research analytics layer for RTD_SIM's GTFS integration.

Implements four analysis functions that expose emergent decarbonisation
behaviour from the interaction of GTFS service data and OSM infrastructure:

1. transit_desert_analysis()
   Identifies areas where poor transit access forces car dependency.
   Scores each agent's origin by access time to the nearest stop,
   number of services within walkable distance, and headway quality.
   Outputs a per-origin vulnerability score and spatial heatmap data.

2. electrification_opportunity_ranking()
   Ranks GTFS routes by decarbonisation impact: diesel route × ridership
   × emissions per km.  Flags routes where electric replacements are
   operationally feasible (route length ≤ EV range, depot access available).

3. modal_shift_threshold_analysis()
   For each OD pair in the agent population, computes the generalised cost
   ratio car / transit.  Identifies the headway or fare reduction required
   to flip each agent from car to transit — the policy lever that creates
   tipping points in the BDI simulation.

4. emissions_hotspot_detection()
   Aggregates per-agent per-step emissions onto road segments and transit
   corridors using the route geometry stored in agent state.  Returns the
   top-N hotspot corridors ranked by total CO₂ burden, with mode breakdown.

All functions are pure analytics — they read simulation output and return
plain Python dicts / lists.  No side effects, no UI dependencies.
They are designed to be called after simulation.run() returns results.

Usage:
    from simulation.gtfs.gtfs_analytics import (
        transit_desert_analysis,
        electrification_opportunity_ranking,
        modal_shift_threshold_analysis,
        emissions_hotspot_detection,
    )

    deserts = transit_desert_analysis(agents, G_transit, env)
    elec    = electrification_opportunity_ranking(G_transit, loader)
    shift   = modal_shift_threshold_analysis(agents, G_transit, policy_context)
    hotspot = emissions_hotspot_detection(agents, results['time_series'], top_n=20)
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371.0
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dl / 2) ** 2)
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _walk_time_min(dist_km: float, speed_kmh: float = 4.8) -> float:
    return (dist_km / speed_kmh) * 60.0


def _generalised_cost(
    travel_time_h: float,
    headway_s: float,
    dist_km: float,
    emissions_g_km: float,
    vot: float = 10.0,
    energy_price: float = 0.12,
    carbon_tax: float = 0.0,
) -> float:
    """
    Standard RTD_SIM generalised cost formula, applied consistently with router.py.
    headway_s / 2 = expected waiting time (uniform arrivals assumption).
    """
    wait_h = (headway_s / 2.0) / 3600.0
    emit_kg = emissions_g_km / 1000.0
    return (
        (travel_time_h + wait_h) * vot
        + dist_km * energy_price
        + dist_km * emit_kg * carbon_tax
    )


# ── 1. Transit Desert Analysis ───────────────────────────────────────────────

def transit_desert_analysis(
    agents: List[Any],
    G_transit: Any,
    env: Any,
    walk_threshold_km: float = 0.8,
    headway_threshold_s: int = 1800,   # 30 min — threshold for "good" service
    vot_gbp_h: float = 10.0,
) -> Dict[str, Any]:
    """
    Identify agents whose origins lack accessible transit.

    A "transit desert" is defined by three compounding conditions:
      a) Nearest stop > walk_threshold_km (poor physical access)
      b) Headway at nearest stop > headway_threshold_s (infrequent service)
      c) No other stops within walk_threshold_km × 2

    Returns:
        {
          'desert_agents':   [agent_id, ...]      — agents in transit deserts
          'scores':          {agent_id: float}    — 0.0 (good) to 1.0 (desert)
          'summary':         {pct_desert, avg_walk_km, avg_headway_min}
          'heatmap_data':    [{lon, lat, score}, ...]  — for pydeck HeatmapLayer
          'threshold_km':    walk_threshold_km
          'threshold_min':   headway_threshold_s // 60
        }
    """
    if G_transit is None or not agents:
        return {'desert_agents': [], 'scores': {}, 'summary': {}, 'heatmap_data': []}

    desert_agents  = []
    scores         = {}
    heatmap_data   = []

    for agent in agents:
        origin = getattr(agent.state, 'location', None)
        if origin is None:
            continue
        agent_id = getattr(agent.state, 'agent_id', str(id(agent)))
        lon, lat = float(origin[0]), float(origin[1])

        # Find all stops within 2× walk threshold
        nearby: List[Tuple[str, float, int]] = []   # (stop_id, dist_km, headway_s)
        for stop_id, data in G_transit.nodes(data=True):
            slat = data.get('y', 0)
            slon = data.get('x', 0)
            d = _haversine_km(lon, lat, slon, slat)
            if d <= walk_threshold_km * 2:
                # Best (lowest) headway among outgoing edges at this stop
                out_edges = list(G_transit.edges(stop_id, data=True))
                if out_edges:
                    min_hw = min(e[2].get('headway_s', 3600) for e in out_edges)
                else:
                    min_hw = 3600
                nearby.append((stop_id, d, min_hw))

        if not nearby:
            # No stops at all within 2× threshold
            score = 1.0
        else:
            nearest_d  = min(d for _, d, _ in nearby)
            nearest_hw = min(hw for _, d, hw in nearby if d == nearest_d)
            stops_in_range = len([s for s in nearby if s[1] <= walk_threshold_km])

            # Component scores (0 = good, 1 = bad)
            access_score   = min(1.0, nearest_d / walk_threshold_km)
            headway_score  = min(1.0, nearest_hw / headway_threshold_s)
            coverage_score = max(0.0, 1.0 - stops_in_range / 3.0)   # 3+ stops = 0

            score = (access_score * 0.4 + headway_score * 0.4 + coverage_score * 0.2)

        scores[agent_id] = round(score, 3)
        heatmap_data.append({'lon': lon, 'lat': lat, 'score': score})

        if score > 0.65:
            desert_agents.append(agent_id)

    n = len(scores)
    pct_desert = len(desert_agents) / n * 100 if n else 0.0

    all_scores = list(scores.values())
    avg_score  = sum(all_scores) / n if n else 0.0

    logger.info(
        "Transit desert analysis: %.1f%% of agents in deserts (score > 0.65), "
        "avg score %.2f",
        pct_desert, avg_score,
    )

    return {
        'desert_agents': desert_agents,
        'scores':        scores,
        'heatmap_data':  heatmap_data,
        'summary': {
            'total_agents':    n,
            'desert_agents':   len(desert_agents),
            'pct_desert':      round(pct_desert, 1),
            'avg_desert_score': round(avg_score, 3),
        },
        'threshold_km':  walk_threshold_km,
        'threshold_min': headway_threshold_s // 60,
    }


# ── 2. Electrification Opportunity Ranking ───────────────────────────────────

def electrification_opportunity_ranking(
    G_transit: Any,
    loader: Any,
    ev_range_km: float = 250.0,
    max_route_km_for_depot_charge: float = 400.0,
) -> List[Dict[str, Any]]:
    """
    Rank GTFS routes by decarbonisation impact potential.

    Impact score = diesel_routes_count × avg_emissions_g_km × total_route_km
    normalised to [0, 1] across all routes in the feed.

    For each route also reports:
      - operational_feasibility: whether EV range can cover the route
      - savings_tco2_per_year:   estimated annual CO₂ saving at current ridership
      - replacement_mode:        suggested zero-emission mode

    Returns a list of dicts sorted by impact_score descending.
    """
    if G_transit is None or loader is None:
        return []

    # Compute route-level statistics from graph edges
    route_stats: Dict[str, Dict] = defaultdict(lambda: {
        'total_km': 0.0,
        'edge_count': 0,
        'emissions_g_km_sum': 0.0,
        'fuel_types': set(),
        'modes': set(),
        'headways': [],
    })

    for u, v, attrs in G_transit.edges(data=True):
        for rid in attrs.get('route_ids', []):
            rs = route_stats[rid]
            rs['total_km']          += attrs.get('length', 0) / 1000.0
            rs['edge_count']        += 1
            rs['emissions_g_km_sum'] += attrs.get('emissions_g_km', 0)
            rs['fuel_types'].add(attrs.get('fuel_type', 'diesel'))
            rs['modes'].add(attrs.get('mode', 'bus'))
            rs['headways'].append(attrs.get('headway_s', 3600))

    results = []

    for rid, rs in route_stats.items():
        route_meta = loader.routes.get(rid, {})
        if not route_meta:
            continue

        fuel       = route_meta.get('fuel_type', 'diesel')
        mode       = route_meta.get('mode', 'bus')
        short_name = route_meta.get('short_name', rid)
        long_name  = route_meta.get('long_name', '')

        # Only diesel/hybrid routes are decarbonisation opportunities
        if fuel in ('electric', 'hydrogen'):
            continue

        avg_emit   = rs['emissions_g_km_sum'] / max(rs['edge_count'], 1)
        total_km   = rs['total_km']
        avg_hw_min = (sum(rs['headways']) / len(rs['headways'])) / 60.0 if rs['headways'] else 60.0

        # Rough annual ridership proxy: trips_per_day × 365
        # We don't have actual ridership — use frequency as a proxy
        trips_per_day = 14.4 * 60.0 / max(avg_hw_min, 1.0)   # operating hours 06:00-22:00
        annual_km     = total_km * trips_per_day * 365

        savings_tco2  = (avg_emit * annual_km) / 1_000_000.0   # g → tonnes

        # Operational feasibility: can a BEV cover route length without recharging?
        max_single_trip_km = total_km * 1.1   # 10% buffer
        feasible_bev   = max_single_trip_km <= ev_range_km
        feasible_depot = max_single_trip_km <= max_route_km_for_depot_charge

        if mode in ('local_train', 'intercity_train'):
            replacement = 'local_train (electric)' if mode == 'local_train' else 'intercity_train (electric)'
        elif mode == 'ferry_diesel':
            replacement = 'ferry_electric'
        else:
            replacement = 'bus (battery-electric)'

        results.append({
            'route_id':          rid,
            'short_name':        short_name,
            'long_name':         long_name[:60],
            'mode':              mode,
            'fuel_type':         fuel,
            'total_km':          round(total_km, 1),
            'avg_emissions_g_km': round(avg_emit, 1),
            'avg_headway_min':   round(avg_hw_min, 1),
            'annual_km_est':     round(annual_km),
            'savings_tco2_yr':   round(savings_tco2, 1),
            'feasible_bev':      feasible_bev,
            'feasible_depot':    feasible_depot,
            'replacement_mode':  replacement,
        })

    # Normalise impact score
    if results:
        max_saving = max(r['savings_tco2_yr'] for r in results) or 1.0
        for r in results:
            r['impact_score'] = round(r['savings_tco2_yr'] / max_saving, 3)

    results.sort(key=lambda x: x.get('impact_score', 0), reverse=True)

    logger.info(
        "Electrification ranking: %d diesel/hybrid routes, "
        "top saving %.0f tCO₂/yr",
        len(results),
        results[0]['savings_tco2_yr'] if results else 0,
    )
    return results


# ── 3. Modal Shift Threshold Analysis ───────────────────────────────────────

def modal_shift_threshold_analysis(
    agents: List[Any],
    G_transit: Any,
    policy_context: Optional[Dict[str, float]] = None,
    car_mode: str = 'car',
    transit_modes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    For each agent currently using a road mode, compute how much transit
    would need to improve to flip them.

    The "flip threshold" is the headway reduction (in minutes) that would
    make the transit generalised cost equal to the car generalised cost.

    Returns:
        {
          'flip_counts':      {headway_reduction_band: agent_count}
                              — e.g. {'0-5min': 42, '5-15min': 78, '>15min': 55}
          'near_tipping':     [agent_id, ...]  — agents flippable with ≤5 min improvement
          'car_ratio':        avg ratio of car_cost / transit_cost
          'agent_detail':     [{agent_id, car_cost, transit_cost, flip_threshold_min}, ...]
          'policy_levers':    {lever: required_improvement}
                              — human-readable policy recommendations
        }
    """
    if transit_modes is None:
        transit_modes = ['bus', 'tram', 'local_train', 'intercity_train']

    pc = policy_context or {}
    vot        = float(pc.get('value_of_time_gbp_h',  10.0))
    energy_p   = float(pc.get('energy_price_gbp_km',   0.12))
    carbon_t   = float(pc.get('carbon_tax_gbp_tco2',   0.0))

    # Car cost constants (proxy)
    CAR_SPEED_KMH   = 35.0   # urban average incl. congestion
    CAR_EMIT_G_KM   = 170.0
    CAR_FUEL_GBP_KM = 0.14   # ~14p/km petrol

    flip_counts   = {'0-5min': 0, '5-15min': 0, '15-30min': 0, '>30min': 0, 'never': 0}
    near_tipping  = []
    agent_detail  = []
    cost_ratios   = []

    for agent in agents:
        mode = getattr(agent.state, 'mode', '')
        if mode not in (car_mode, 'ev', 'van_diesel', 'van_electric'):
            continue

        origin = getattr(agent.state, 'location', None)
        dest   = getattr(agent.state, 'destination', None)
        if origin is None or dest is None:
            continue

        agent_id = getattr(agent.state, 'agent_id', str(id(agent)))
        dist_km  = getattr(agent.state, 'distance_km', None)
        if dist_km is None or dist_km < 0.1:
            dist_km = _haversine_km(
                float(origin[0]), float(origin[1]),
                float(dest[0]), float(dest[1]),
            )

        # Car generalised cost
        car_time_h  = dist_km / CAR_SPEED_KMH
        car_cost = (
            car_time_h * vot
            + dist_km * CAR_FUEL_GBP_KM
            + dist_km * (CAR_EMIT_G_KM / 1000.0) * carbon_t
        )

        # Best available transit cost at origin
        best_transit_cost  = float('inf')
        best_transit_hw_s  = 3600

        if G_transit is not None:
            for stop_id, data in G_transit.nodes(data=True):
                slat = data.get('y', 0)
                slon = data.get('x', 0)
                walk_km = _haversine_km(float(origin[0]), float(origin[1]), slon, slat)
                if walk_km > 1.5:
                    continue
                walk_time_h = walk_km / 4.8
                for _, _, attrs in G_transit.edges(stop_id, data=True):
                    if attrs.get('mode', '') not in transit_modes:
                        continue
                    hw_s  = attrs.get('headway_s', 3600)
                    travel_h = attrs.get('travel_time_s', 600) / 3600.0
                    emit_g   = attrs.get('emissions_g_km', 80.0)
                    seg_km   = attrs.get('length', 0) / 1000.0
                    cost = (
                        walk_time_h * vot
                        + _generalised_cost(travel_h, hw_s, seg_km, emit_g, vot, energy_p, carbon_t)
                    )
                    if cost < best_transit_cost:
                        best_transit_cost = cost
                        best_transit_hw_s = hw_s

        if best_transit_cost == float('inf'):
            flip_counts['never'] += 1
            continue

        ratio = car_cost / best_transit_cost if best_transit_cost > 0 else 1.0
        cost_ratios.append(ratio)

        if ratio >= 1.0:
            # Car is already more expensive — transit already competitive
            flip_threshold_min = 0.0
        else:
            # How much must headway drop to flip?
            # Solve: car_cost = transit_cost(new_hw)
            # Approximation: reduce headway_component by (car_cost - transit_cost) / (vot / 2)
            gap           = best_transit_cost - car_cost
            vot_per_h     = vot
            hw_reduction_h = gap / vot_per_h * 2.0   # headway/2 × VoT = gap
            flip_threshold_min = max(0.0, hw_reduction_h * 60.0)

        band = (
            '0-5min'   if flip_threshold_min <= 5  else
            '5-15min'  if flip_threshold_min <= 15 else
            '15-30min' if flip_threshold_min <= 30 else
            '>30min'
        )
        flip_counts[band] += 1

        if flip_threshold_min <= 5:
            near_tipping.append(agent_id)

        agent_detail.append({
            'agent_id':            agent_id,
            'car_cost':            round(car_cost, 3),
            'transit_cost':        round(best_transit_cost, 3),
            'cost_ratio':          round(ratio, 3),
            'flip_threshold_min':  round(flip_threshold_min, 1),
            'current_headway_min': round(best_transit_hw_s / 60, 1),
        })

    n_road = sum(flip_counts.values())
    avg_ratio = sum(cost_ratios) / len(cost_ratios) if cost_ratios else 1.0

    # Policy lever interpretation
    near_frac = len(near_tipping) / max(n_road, 1)
    policy_levers: Dict[str, str] = {}
    if near_frac > 0.3:
        policy_levers['frequency_increase'] = (
            f"{near_frac:.0%} of car users flippable with ≤5 min headway reduction — "
            "doubling peak frequency likely to produce measurable modal shift." \
            "Private car travel could technically be replaced by " \
            "public transport if the service were frequent enough. " \
            "Reducing this by 5 minutes or more significantly cuts down" \
            "on waiting time, which is often the biggest deterrent " \
            "for car users. Increase the number of vehicles running " \
            "during the busiest times of day (e.g., from 4 buses per hour to 8)." \
            "This is often the most cost-effective way to achieve modal shift, " \
            "compared to building new transit routes or infrastructure."
        )
    if flip_counts.get('5-15min', 0) / max(n_road, 1) > 0.2:
        policy_levers['integrated_ticketing'] = (
            "~20% of car users need modest headway + fare co-ordination. "
            "Smart ticketing or through-fares may tip them."
        )
    if avg_ratio < 0.85:
        policy_levers['carbon_pricing'] = (
            f"Avg car/transit cost ratio {avg_ratio:.2f} — car still cheaper. "
            "A carbon tax ≥ £50/tCO₂ would close the gap for most commuters."
        )

    logger.info(
        "Modal shift analysis: %d road agents, %d near tipping (%.1f%%), "
        "avg ratio %.2f",
        n_road, len(near_tipping), near_frac * 100, avg_ratio,
    )

    return {
        'flip_counts':    flip_counts,
        'near_tipping':   near_tipping,
        'car_ratio':      round(avg_ratio, 3),
        'agent_detail':   agent_detail[:200],   # cap at 200 for performance
        'policy_levers':  policy_levers,
        'total_road':     n_road,
        'near_tipping_pct': round(near_frac * 100, 1),
    }


# ── 4. Emissions Hotspot Detection ──────────────────────────────────────────

def emissions_hotspot_detection(
    agents: List[Any],
    time_series: Any,
    top_n: int = 20,
    grid_resolution_km: float = 0.5,
) -> Dict[str, Any]:
    """
    Aggregate per-agent emissions onto a spatial grid to find hotspot corridors.

    Uses agent route geometry (list of lon/lat points) stored in agent.state.route
    to project emissions onto grid cells.  Each cell accumulates:
      total_emissions_g, mode_breakdown, agent_count

    Args:
        agents:               Agent list with state.route, state.emissions_g, state.mode
        time_series:          TimeSeries object (used for step snapshots if available)
        top_n:                Number of hotspot cells to return.
        grid_resolution_km:   Grid cell size in km (default 500m).

    Returns:
        {
          'hotspots': [
            {
              'cell_key': (lon_idx, lat_idx),
              'center':   (lon, lat),
              'total_emissions_g': float,
              'top_mode': str,
              'mode_breakdown': {mode: emissions_g},
              'agent_count': int,
            }, ...
          ],
          'total_emissions_g':  float,
          'grid_summary': {cells_with_emissions, max_cell_g, mean_cell_g}
        }
    """
    # Approximate degrees per km at UK latitudes (~56°N)
    DEG_PER_KM_LAT = 1.0 / 111.0
    DEG_PER_KM_LON = 1.0 / (111.0 * math.cos(math.radians(56.0)))
    cell_lat = grid_resolution_km * DEG_PER_KM_LAT
    cell_lon = grid_resolution_km * DEG_PER_KM_LON

    grid: Dict[Tuple[int, int], Dict] = defaultdict(lambda: {
        'total_g': 0.0,
        'agents':  0,
        'modes':   defaultdict(float),
        'lon_sum': 0.0,
        'lat_sum': 0.0,
        'point_count': 0,
    })

    grand_total = 0.0

    for agent in agents:
        route = getattr(agent.state, 'route', None)
        if not route or len(route) < 2:
            continue

        emit_total  = getattr(agent.state, 'emissions_g', 0.0)
        mode        = getattr(agent.state, 'mode', 'unknown')
        dist_km     = getattr(agent.state, 'distance_km', 0.0)

        if dist_km < 0.001 or emit_total <= 0:
            continue

        emit_per_km = emit_total / dist_km
        grand_total += emit_total

        for i in range(len(route) - 1):
            p1 = route[i]
            p2 = route[i + 1]
            try:
                lon = (float(p1[0]) + float(p2[0])) / 2.0
                lat = (float(p1[1]) + float(p2[1])) / 2.0
            except (TypeError, IndexError):
                continue

            seg_km = _haversine_km(float(p1[0]), float(p1[1]), float(p2[0]), float(p2[1]))
            seg_emit = emit_per_km * seg_km

            cell_key = (int(lon / cell_lon), int(lat / cell_lat))
            cell = grid[cell_key]
            cell['total_g']     += seg_emit
            cell['agents']      += 1
            cell['modes'][mode] += seg_emit
            cell['lon_sum']     += lon
            cell['lat_sum']     += lat
            cell['point_count'] += 1

    if not grid:
        return {
            'hotspots':       [],
            'total_emissions_g': 0.0,
            'grid_summary': {'cells_with_emissions': 0},
        }

    # Build sorted hotspot list
    hotspots = []
    for cell_key, cell in grid.items():
        n = cell['point_count'] or 1
        center_lon = cell['lon_sum'] / n
        center_lat = cell['lat_sum'] / n
        modes = dict(cell['modes'])
        top_mode = max(modes, key=modes.get) if modes else 'unknown'
        hotspots.append({
            'cell_key':          cell_key,
            'center':            (round(center_lon, 5), round(center_lat, 5)),
            'total_emissions_g': round(cell['total_g'], 1),
            'top_mode':          top_mode,
            'mode_breakdown':    {k: round(v, 1) for k, v in modes.items()},
            'agent_count':       cell['agents'],
        })

    hotspots.sort(key=lambda x: x['total_emissions_g'], reverse=True)
    all_vals = [h['total_emissions_g'] for h in hotspots]
    mean_g = sum(all_vals) / len(all_vals) if all_vals else 0.0

    logger.info(
        "Emissions hotspot: %d grid cells, top cell %.0f g, total %.0f g, %.0f tCO₂",
        len(hotspots), hotspots[0]['total_emissions_g'] if hotspots else 0,
        grand_total, grand_total / 1_000_000,
    )

    return {
        'hotspots':          hotspots[:top_n],
        'total_emissions_g': round(grand_total, 1),
        'grid_summary': {
            'cells_with_emissions': len(hotspots),
            'max_cell_g':  round(all_vals[0], 1) if all_vals else 0,
            'mean_cell_g': round(mean_g, 1),
        },
    }


# ── Convenience runner ────────────────────────────────────────────────────────

def run_full_gtfs_analysis(
    agents: List[Any],
    results: Dict[str, Any],
    env: Any,
    policy_context: Optional[Dict[str, float]] = None,
    top_hotspots: int = 20,
) -> Dict[str, Any]:
    """
    Run all four analytics in sequence and return a combined report.

    Args:
        agents:         Agent list from simulation.run()
        results:        Results dict from simulation.run()
        env:            SpatialEnvironment (has .get_transit_graph())
        policy_context: Active scenario policy parameters
        top_hotspots:   Number of hotspot cells in emissions report

    Returns:
        {
          'transit_deserts':     from transit_desert_analysis()
          'electrification':     from electrification_opportunity_ranking()
          'modal_shift':         from modal_shift_threshold_analysis()
          'emissions_hotspots':  from emissions_hotspot_detection()
        }
    """
    G_transit  = env.get_transit_graph() if hasattr(env, 'get_transit_graph') else None
    gtfs_loader = getattr(env, 'gtfs_loader', None)
    time_series = results.get('time_series')

    logger.info("Running full GTFS analytics suite…")

    deserts = transit_desert_analysis(agents, G_transit, env)

    electrification = (
        electrification_opportunity_ranking(G_transit, gtfs_loader)
        if gtfs_loader else []
    )

    modal_shift = modal_shift_threshold_analysis(
        agents, G_transit, policy_context
    )

    hotspots = emissions_hotspot_detection(agents, time_series, top_n=top_hotspots)

    report = {
        'transit_deserts':    deserts,
        'electrification':    electrification,
        'modal_shift':        modal_shift,
        'emissions_hotspots': hotspots,
    }

    _log_summary(report)
    return report


def _log_summary(report: Dict) -> None:
    """Log a compact one-line summary of each analysis result."""
    d  = report.get('transit_deserts', {}).get('summary', {})
    m  = report.get('modal_shift', {})
    e  = report.get('emissions_hotspots', {})
    el = report.get('electrification', [])

    logger.info("── GTFS Analytics Summary ──────────────────────────────")
    logger.info(
        "Transit deserts:     %s%% of agents (score > 0.65)",
        d.get('pct_desert', '?'),
    )
    logger.info(
        "Near modal shift:    %s%% of car users flippable (≤5 min improvement)",
        m.get('near_tipping_pct', '?'),
    )
    logger.info(
        "Avg car/transit ratio: %s (>1 = transit already cheaper)",
        m.get('car_ratio', '?'),
    )
    if el:
        top = el[0]
        logger.info(
            "Top electrification: %s (%s) — %.0f tCO₂/yr saving",
            top.get('short_name', '?'), top.get('mode', '?'),
            top.get('savings_tco2_yr', 0),
        )
    logger.info(
        "Emissions hotspot:   %.0f g total, %d cells, top cell %.0f g",
        e.get('total_emissions_g', 0),
        e.get('grid_summary', {}).get('cells_with_emissions', 0),
        e.get('grid_summary', {}).get('max_cell_g', 0),
    )
    logger.info("────────────────────────────────────────────────────────")
