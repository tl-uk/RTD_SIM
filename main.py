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
#   python main.py [--steps N] [--csv path/to/log.csv] [--no-ui]
#   --steps N         Number of simulation steps (default: 200)
#   --csv path/to/log.csv  Save simulation log to specified CSV file
#   --no-ui           Run in headless mode without UI   
# 

from __future__ import annotations
import argparse
import logging
from pathlib import Path

from rtd_sim.simulation.event_bus import EventBus
from rtd_sim.simulation.controller import SimulationController, SimulationConfig
from rtd_sim.simulation.data_adapter import DataAdapter
from rtd_sim.models.cognitive_abm import CognitiveAgent

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger('RTD_SIM')

def run_headless(steps: int, save_csv: Path | None, enable_mqtt: bool, enable_ws: bool) -> None:
    bus = EventBus()
    model = CognitiveAgent(seed=42)
    data = DataAdapter()
    config = SimulationConfig(steps=steps)
    ctl = SimulationController(bus, model, data, config)

    # optional Phase 1 stubs for realtime
    if enable_mqtt:
        data.realtime.enable_mqtt({'broker_url': 'mqtt://localhost', 'topic_state': 'rtd_sim/state'})
    if enable_ws:
        data.realtime.enable_ws({'host': '127.0.0.1', 'port': 8765, 'path': '/rtd'})

    bus.subscribe('state_updated', lambda step, state: data.append_log(step, state))
    ctl.run_steps(steps)
    if save_csv:
        data.save_log_csv(save_csv)

def run_ui(steps: int, enable_mqtt: bool, enable_ws: bool) -> None:
    import tkinter as tk  # stdlib GUI
    from rtd_sim.ui.main_ui import MainUI

    bus = EventBus()
    model = CognitiveAgent(seed=7)
    data = DataAdapter()
    config = SimulationConfig(steps=steps)
    ctl = SimulationController(bus, model, data, config)

    if enable_mqtt:
        data.realtime.enable_mqtt({'broker_url': 'mqtt://localhost', 'topic_state': 'rtd_sim/state'})
    if enable_ws:
        data.realtime.enable_ws({'host': '127.0.0.1', 'port': 8765, 'path': '/rtd'})

    root = tk.Tk()
    app = MainUI(root, controller=ctl, bus=bus, data_adapter=data, tick_ms=config.dt_ms)
    app.mainloop()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RTD_SIM — Phase 1 core skeleton (stdlib only)')
    parser.add_argument('--steps', type=int, default=200, help='Number of simulation steps')
    parser.add_argument('--csv', type=Path, default=None, help='Save headless run to CSV path')
    parser.add_argument('--no-ui', action='store_true', help='Run headless (no UI)')
    parser.add_argument('--enable-mqtt', action='store_true', help='Enable MQTT stub (Phase 1 no-op)')
    parser.add_argument('--enable-ws', action='store_true', help='Enable WebSocket stub (Phase 1 no-op)')
    args = parser.parse_args()

    if args.no_ui:
        run_headless(steps=args.steps, save_csv=args.csv, enable_mqtt=args.enable_mqtt, enable_ws=args.enable_ws)
    else:
        run_ui(steps=args.steps, enable_mqtt=args.enable_mqtt, enable_ws=args.enable_ws)