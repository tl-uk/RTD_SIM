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

def _make_agents(n: int) -> list:
    rng = random.Random(123)
    planner = BDIPlanner()
    agents = []
    for i in range(n):
        if i % 3 == 0:
            desires = {'eco': 0.8, 'time': 0.4, 'cost': 0.2, 'comfort': 0.3, 'risk': 0.3}
        elif i % 3 == 1:
            desires = {'eco': 0.3, 'time': 0.7, 'cost': 0.4, 'comfort': 0.5, 'risk': 0.2}
        else:
            desires = {'eco': 0.5, 'time': 0.5, 'cost': 0.5, 'comfort': 0.4, 'risk': 0.3}
        origin = (rng.uniform(0, 5), rng.uniform(0, 5))
        dest = (rng.uniform(0, 5), rng.uniform(0, 5))
        a = CognitiveAgent(seed=42 + i, agent_id=f'agent_{i+1}', desires=desires, planner=planner, origin=origin, dest=dest)
        agents.append(a)
    return agents

def run_headless(steps: int, save_csv: Path | None, enable_mqtt: bool, enable_ws: bool, agents_n: int) -> None:
    bus = EventBus()
    data = DataAdapter()
    config = SimulationConfig(steps=steps)
    env = SpatialEnvironment()
    env.load_osm_graph(None)

    agents = _make_agents(agents_n)
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

def run_ui(steps: int, enable_mqtt: bool, enable_ws: bool, agents_n: int) -> None:
    import tkinter as tk
    from ui.main_ui import MainUI

    bus = EventBus()
    data = DataAdapter()
    config = SimulationConfig(steps=steps)
    env = SpatialEnvironment()
    env.load_osm_graph(None)

    agents = _make_agents(agents_n)
    ctl = SimulationController(bus, model=None, data_adapter=data, config=config, agents=agents, environment=env)

    if enable_mqtt:
        data.realtime.enable_mqtt({'broker_url': 'mqtt://localhost', 'topic_state': 'rtd_sim/state'})
    if enable_ws:
        data.realtime.enable_ws({'host': '127.0.0.1', 'port': 8765, 'path': '/rtd'})

    root = tk.Tk()
    app = MainUI(root, controller=ctl, bus=bus, data_adapter=data, tick_ms=config.dt_ms)
    app.mainloop()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RTD_SIM — Phase 2 stubs (multi-agent, planner, spatial env)')
    parser.add_argument('--steps', type=int, default=200, help='Number of simulation steps')
    parser.add_argument('--csv', type=Path, default=None, help='Save headless run to CSV path')
    parser.add_argument('--no-ui', action='store_true', help='Run headless (no UI)')
    parser.add_argument('--enable-mqtt', action='store_true', help='Enable MQTT stub (no-op)')
    parser.add_argument('--enable-ws', action='store_true', help='Enable WebSocket stub (no-op)')
    parser.add_argument('--agents', type=int, default=5, help='Number of agents for Phase 2 test')
    args = parser.parse_args()

    if args.no_ui:
        run_headless(steps=args.steps, save_csv=args.csv, enable_mqtt=args.enable_mqtt, enable_ws=args.enable_ws, agents_n=args.agents)
    else:
        run_ui(steps=args.steps, enable_mqtt=args.enable_mqtt, enable_ws=args.enable_ws, agents_n=args.agents)