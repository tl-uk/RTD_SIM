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
            total_emissions = 0.0
            for a in self.agents:
                try:
                    state = a.step(env=self.environment)
                except TypeError:
                    state = a.step()
                mode = state.get('mode', 'unknown')
                modal_counts[mode] = modal_counts.get(mode, 0) + 1
                self.bus.publish('state_updated', step=self._current_step, state=state)
                self.bus.publish('log_entry', message=f"Step {self._current_step} [{state.get('agent_id','?')}]: {state}")
                if self.environment is not None:
                    try:
                        route = getattr(a.state, 'route', None)
                        if route:
                            total_emissions += self.environment.estimate_emissions(route, mode)
                    except Exception:
                        pass
            metrics = {
                'step': self._current_step,
                'modal_share': modal_counts,
                'emissions_total_g': round(total_emissions, 2),
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