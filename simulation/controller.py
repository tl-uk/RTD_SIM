# simulation/controller.py
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict

from .event_bus import EventBus

logger = logging.getLogger(__name__)

@dataclass
class SimulationConfig:
    steps: int = 200
    dt_ms: int = 100  # UI cadence

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

        if self.model and not self.agents:
            state = self.model.step()
            self.bus.publish('tick', step=self._current_step)
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
                mode = state.get('mode', 'unknown')
                modal_counts[mode] = modal_counts.get(mode, 0) + 1

                # Publish per-agent update & log
                self.bus.publish('state_updated', step=self._current_step, state=state)
                self.bus.publish('log_entry', message=f"Step {self._current_step} [{state.get('agent_id','?')}]: {state}")

                # Aggregate travel stats from agent state
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