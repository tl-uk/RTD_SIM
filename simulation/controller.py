from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

from .event_bus import EventBus

logger = logging.getLogger(__name__)

@dataclass
class SimulationConfig:
    steps: int = 200
    dt_ms: int = 100  # recommended UI tick interval

class SimulationController:
    """Coordinates the simulation loop and mediates between ABM and UI."""

    def __init__(self, bus: EventBus, model, data_adapter: Optional[object] = None, config: Optional[SimulationConfig] = None):
        self.bus = bus
        self.model = model
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
        self.model.reset()
        self.bus.publish('sim_reset')

    def step(self) -> None:
        """Advance the simulation by one step and publish updates."""
        if not self._running:
            return
        self._current_step += 1
        state = self.model.step()
        self.bus.publish('tick', step=self._current_step)
        self.bus.publish('state_updated', step=self._current_step, state=state)
        self.bus.publish('log_entry', message=f"Step {self._current_step}: {state}")
        if self._current_step >= self.config.steps:
            self.stop()

    def run_steps(self, steps: Optional[int] = None) -> None:
        self.start()
        max_steps = steps if steps is not None else self.config.steps
        while self._running and self._current_step < max_steps:
            self.step()
