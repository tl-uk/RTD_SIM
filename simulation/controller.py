"""
simulation/controller.py

This module defines the SimulationController class, which coordinates the simulation 
loop for multi-agent simulations. It mediates between the environment, agent-based model 
(ABM), and user interface (UI) by managing the simulation state, publishing events, and 
handling agent interactions. 

The controller supports starting, stopping, resetting, and stepping through the simulation, 
while also collecting and broadcasting metrics for visualization and analysis. The design 
allows for both single-agent and multi-agent modes, with flexibility to integrate various 
models and data adapters as needed.

The SimulationController is designed to be agnostic to the specific implementations of
the environment and agents, allowing for a wide range of simulation scenarios and configurations.

"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict

from events.event_bus import EventBus

logger = logging.getLogger(__name__)

# =========================
# DATA CLASSES
# =========================
@dataclass
class SimulationConfig:
    steps: int = 200
    dt_ms: int = 100  # UI cadence

# ==========================
# SIMULATION CONTROLLER
# ==========================
# The SimulationController serves as the central coordinator for the simulation, managing the
# simulation loop, agent interactions, and communication between the environment, ABM, 
# and UI. It provides methods to start, stop, reset, and step through the simulation, 
# while also collecting and broadcasting metrics for visualization and analysis. 
# The controller is designed to be flexible, supporting both single-agent and multi-agent 
# modes, and can integrate with various models and data adapters as needed. It uses an
# event-driven architecture to facilitate communication and decouple components, allowing for
# a wide range of simulation scenarios and configurations.
class SimulationController:
    """Coordinates the simulation loop (multi-agent) and mediates between environment, ABM, and UI."""

    def __init__(self, bus: EventBus, model, data_adapter: Optional[object] = None,
                 config: Optional[SimulationConfig] = None, agents: Optional[List[object]] = None,
                 environment: Optional[object] = None):
        self.bus = bus
        self.model = model  # single-agent backward compatibility
        self.agents = agents or []
        self.environment = environment
        self.data_adapter = data_adapter
        self.config = config or SimulationConfig()
        self._running = False
        self._current_step = 0

    @property
    def current_step(self) -> int:
        return self._current_step

    def start(self) -> None:
        if self._running:
            return
        logger.info("Simulation started")
        self._running = True
        self.bus.publish('sim_started')

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        logger.info("Simulation stopped at step %d", self._current_step)
        self.bus.publish('sim_stopped', step=self._current_step)

    def reset(self) -> None:
        logger.info("Simulation reset")
        self._running = False
        self._current_step = 0
        if self.model:
            self.model.reset()
        for a in self.agents:
            try:
                a.reset()
            except Exception:
                logger.exception("Agent reset failed")
        self.bus.publish('sim_reset')

    def step(self) -> None:
        if not self._running:
            return
        self._current_step += 1

        # Publish tick for multi-agent mode too
        self.bus.publish('tick', step=self._current_step)

        if self.model and not self.agents:
            state = self.model.step()
            self.bus.publish('state_updated', step=self._current_step, state=state)
            self.bus.publish('log_entry', message=f"Step {self._current_step}: {state}")
            if hasattr(self.data_adapter, 'realtime') and self.data_adapter.realtime:
                try:
                    self.data_adapter.realtime.broadcast_state(step=self._current_step, state=state)
                except Exception:
                    logger.exception("Realtime broadcast failed at step %d", self._current_step)
        else:
            modal_counts: Dict[str, int] = {}
            total_emissions_g = 0.0
            total_distance_km = 0.0
            arrivals = 0
            sum_travel_time_arrived = 0.0

            for a in self.agents:
                try:
                    state = a.step(env=self.environment)
                except TypeError:
                    state = a.step()

                # Include the route for visualization (stringified later by pandas)
                try:
                    rt = getattr(a.state, 'route', None)
                    if rt:
                        state['route'] = rt
                except Exception:
                    pass
                
                # Count modal share for metrics and visualization
                mode = state.get('mode', 'unknown')
                modal_counts[mode] = modal_counts.get(mode, 0) + 1

                self.bus.publish('state_updated', step=self._current_step, state=state)
                self.bus.publish('log_entry', message=f"Step {self._current_step} [{state.get('agent_id','?')}]: {state}")

                try:
                    total_emissions_g += float(state.get('emissions_g', 0.0))
                    total_distance_km += float(state.get('distance_km', 0.0))
                    if bool(state.get('arrived', False)):
                        arrivals += 1
                        sum_travel_time_arrived += float(state.get('travel_time_min', 0.0))
                except Exception:
                    pass

            metrics = {
                'step': self._current_step,
                'modal_share': modal_counts,
                'emissions_total_g': round(total_emissions_g, 2),
                'distance_total_km': round(total_distance_km, 3),
                'arrivals_count': arrivals,
                'mean_travel_time_min_arrived': round(sum_travel_time_arrived / arrivals, 2) if arrivals > 0 else None,
            }
            self.bus.publish('metrics_updated', metrics=metrics)
            if hasattr(self.data_adapter, 'realtime') and self.data_adapter.realtime:
                try:
                    self.data_adapter.realtime.broadcast_state(step=self._current_step, state=metrics)
                except Exception:
                    logger.exception("Realtime broadcast (metrics) failed at step %d", self._current_step)

        if self._current_step >= self.config.steps:
            self.stop()

    def run_steps(self, steps: Optional[int] = None) -> None:
        self.start()
        max_steps = steps if steps is not None else self.config.steps
        while self._running and self._current_step < max_steps:
            self.step()
