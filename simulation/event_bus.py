"""Simple event bus for decoupled communication (standard library only)."""
from __future__ import annotations
from typing import Callable, Dict, List, Any
import logging

logger = logging.getLogger(__name__)

class EventBus:
    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[..., None]]] = {}

    def subscribe(self, event_name: str, handler: Callable[..., None]) -> None:
        handlers = self._subscribers.setdefault(event_name, [])
        if handler not in handlers:
            handlers.append(handler)
            logger.debug("Subscribed %s to '%s'", getattr(handler, '__name__', str(handler)), event_name)

    def unsubscribe(self, event_name: str, handler: Callable[..., None]) -> None:
        handlers = self._subscribers.get(event_name, [])
        if handler in handlers:
            handlers.remove(handler)
            logger.debug("Unsubscribed %s from '%s'", getattr(handler, '__name__', str(handler)), event_name)

    def publish(self, event_name: str, **payload: Any) -> None:
        handlers = self._subscribers.get(event_name, [])
        logger.debug("Publishing event '%s' to %d handlers with payload %s", event_name, len(handlers), payload)
        for h in list(handlers):
            try:
                h(**payload)
            except Exception:
                logger.exception("Error in handler for event '%s'", event_name)