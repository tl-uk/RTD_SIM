# main.py
# RTD_SIM — Ready-to-run skeleton for cognitive ABM (stdlib imports only)
# Copyright (c) 2024 Cognitive Scale, Inc. Licensed under the MIT license.
# See LICENSE file in the project root for details.
# 
# This file demonstrates how to set up and run a simple cognitive agent-based model
# simulation using only Python's standard library. It includes both a headless mode
# for command-line execution and a minimal Tkinter-based UI for interactive control.
# The simulation logs can be saved to a CSV file for further analysis.
# 
# Usage:
# python main.py [--no-ui] [--steps N] [--csv PATH] [--enable-mqtt] [--enable-ws] [--agents N]
# 
# UI mode (Tkinter), 8 agents
# python main.py --steps 200 --agents 8

# Headless + save CSV, 12 agents
# python main.py --no-ui --steps 300 --agents 12 --csv out_phase2.csv

# Optional flags (stubs only, no network in Phase 2)
# python main.py --enable-mqtt --enable-ws
# 
# UI mode, seed from OSM nodes in Edinburgh
# python main.py --steps 200 --agents 8 --place "Edinburgh, UK" --osm-seed
# 
# Headless, bbox + OSM seeding + CSV
# python main.py --no-ui --steps 300 --agents 12 --bbox 55.97 55.90 -3.15 -3.20 --osm-seed --csv out_phase2_osm.csv

# Note: This is a Phase 2 skeleton focusing on core logic without external dependencies.

from __future__ import annotations
import argparse
import logging
from pathlib import Path
import random

# Path guard for script execution
import sys
from pathlib import Path as _P
THIS_FILE = _P(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulation.event_bus import EventBus
from simulation.controller import SimulationController, SimulationConfig
from simulation.data_adapter import DataAdapter
from simulation.spatial_environment import SpatialEnvironment
from agent.cognitive_abm import CognitiveAgent
from agent.bdi_planner import BDIPlanner

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger('RTD_SIM')


def _make_agents(n: int, env: SpatialEnvironment, use_osm_seed: bool) -> list:
    rng = random.Random(123)
    planner = BDIPlanner()
    agents = []

    # PATCH: Edinburgh fallback bounds (lon, lat)
    EDI_LON_MIN, EDI_LON_MAX = -3.30, -3.15
    EDI_LAT_MIN, EDI_LAT_MAX = 55.90, 55.97

    def _rand_lonlat_edinburgh() -> tuple[float, float]:
        return (rng.uniform(EDI_LON_MIN, EDI_LON_MAX), rng.uniform(EDI_LAT_MIN, EDI_LAT_MAX))  # (lon, lat)

    for i in range(n):
        # Heterogeneous desires
        if i % 3 == 0:
            desires = {'eco': 0.8, 'time': 0.4, 'cost': 0.2, 'comfort': 0.3, 'risk': 0.3}
        elif i % 3 == 1:
            desires = {'eco': 0.3, 'time': 0.7, 'cost': 0.4, 'comfort': 0.5, 'risk': 0.2}
        else:
            desires = {'eco': 0.5, 'time': 0.5, 'cost': 0.5, 'comfort': 0.4, 'risk': 0.3}

        # Seeding
        if use_osm_seed and env.graph_loaded and env.osmnx_available and env.G is not None:
            pair = env.get_random_origin_dest()
            if pair is not None:
                origin, dest = pair  # (lon, lat)
            else:
                # PATCH: Edinburgh fallback if OSM seeding did not yield a pair
                origin = _rand_lonlat_edinburgh()
                dest = _rand_lonlat_edinburgh()
        else:
            # PATCH: Edinburgh fallback instead of (0..5, 0..5)
            origin = _rand_lonlat_edinburgh()
            dest = _rand_lonlat_edinburgh()

        a = CognitiveAgent(
            seed=42 + i,
            agent_id=f'agent_{i+1}',
            desires=desires,
            planner=planner,
            origin=origin,   # (lon, lat)
            dest=dest        # (lon, lat)
        )
        agents.append(a)

    return agents

def run_headless(
    steps: int,
    save_csv: Path | None,
    enable_mqtt: bool,
    enable_ws: bool,
    agents_n: int,
    place: str | None,
    bbox: list | None,
    osm_seed: bool
) -> None:
    bus = EventBus()
    data = DataAdapter()
    config = SimulationConfig(steps=steps)
    env = SpatialEnvironment(step_minutes=max(0.001, config.dt_ms / 60000.0))  # tie movement to UI cadence

    # Optional OSM routing
    if place or bbox:
        try:
            env.load_osm_graph(place=place, bbox=tuple(bbox) if bbox else None, network_type='all')
            logger.info('OSM graph loaded (place=%s bbox=%s)', place, bbox)
        except Exception:
            logger.exception('OSM graph load failed; using fallback straight-line routes')

    agents = _make_agents(agents_n, env, use_osm_seed=osm_seed)
    ctl = SimulationController(bus, model=None, data_adapter=data, config=config, agents=agents, environment=env)

    if enable_mqtt:
        data.realtime.enable_mqtt({'broker_url': 'mqtt://localhost', 'topic_state': 'rtd_sim/state'})
    if enable_ws:
        data.realtime.enable_ws({'host': '127.0.0.1', 'port': 8765, 'path': '/rtd'})

    bus.subscribe('state_updated', lambda step, state: data.append_log(step, state))
    bus.subscribe('metrics_updated', lambda metrics: data.append_log(metrics.get('step', 0), metrics))

    ctl.run_steps(steps)
    if save_csv:
        data.save_log_csv(save_csv)

def run_ui(
    steps: int,
    enable_mqtt: bool,
    enable_ws: bool,
    agents_n: int,
    place: str | None,
    bbox: list | None,
    osm_seed: bool
) -> None:
    import tkinter as tk
    from ui.main_ui import MainUI

    bus = EventBus()
    data = DataAdapter()
    config = SimulationConfig(steps=steps)
    env = SpatialEnvironment(step_minutes=max(0.001, config.dt_ms / 60000.0))

    # Optional OSM routing
    if place or bbox:
        try:
            env.load_osm_graph(place=place, bbox=tuple(bbox) if bbox else None, network_type='all')
            logger.info('OSM graph loaded (place=%s bbox=%s)', place, bbox)
        except Exception:
            logger.exception('OSM graph load failed; using fallback straight-line routes')

    agents = _make_agents(agents_n, env, use_osm_seed=osm_seed)
    ctl = SimulationController(bus, model=None, data_adapter=data, config=config, agents=agents, environment=env)

    if enable_mqtt:
        data.realtime.enable_mqtt({'broker_url': 'mqtt://localhost', 'topic_state': 'rtd_sim/state'})
    if enable_ws:
        data.realtime.enable_ws({'host': '127.0.0.1', 'port': 8765, 'path': '/rtd'})

    root = tk.Tk()
    app = MainUI(root, controller=ctl, bus=bus, data_adapter=data, tick_ms=config.dt_ms)
    app.mainloop()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RTD_SIM — Phase 2 movement + optional OSM routing')
    parser.add_argument('--steps', type=int, default=200, help='Number of simulation steps')
    parser.add_argument('--csv', type=Path, default=None, help='Save headless run to CSV path')
    parser.add_argument('--no-ui', action='store_true', help='Run headless (no UI)')
    parser.add_argument('--enable-mqtt', action='store_true', help='Enable MQTT stub (no-op)')
    parser.add_argument('--enable-ws', action='store_true', help='Enable WebSocket stub (no-op)')
    parser.add_argument('--agents', type=int, default=5, help='Number of agents for Phase 2 test')
    parser.add_argument('--place', type=str, default=None, help='OSM place name (e.g., "Edinburgh, UK")')
    parser.add_argument('--bbox', nargs=4, type=float, default=None, help='OSM bbox: north south east west')
    parser.add_argument('--osm-seed', action='store_true', help='Seed agent origins/dests from loaded OSM graph')
    args = parser.parse_args()

    if args.no_ui:
        run_headless(
            steps=args.steps, save_csv=args.csv,
            enable_mqtt=args.enable_mqtt, enable_ws=args.enable_ws,
            agents_n=args.agents, place=args.place, bbox=args.bbox,
            osm_seed=args.osm_seed
        )
    else:
        run_ui(
            steps=args.steps,
            enable_mqtt=args.enable_mqtt, enable_ws=args.enable_ws,
            agents_n=args.agents, place=args.place, bbox=args.bbox,
            osm_seed=args.osm_seed
        )