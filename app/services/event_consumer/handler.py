"""Typed handler protocol and registry for Boomerang event consumers."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.events import BoomerangEvent, EventType

logger = logging.getLogger(__name__)


@runtime_checkable
class EventHandler(Protocol):
    """Protocol for event handlers participating in consumer processing."""

    @property
    def event_types(self) -> Sequence[EventType | str]:
        """Sequence of event types this handler subscribes to."""
        ...

    async def handle(self, event: BoomerangEvent, session: AsyncSession) -> None:
        """Processes a validated domain event within an active database transaction.

        Database mutations performed on `session` are committed atomically with
        the consumer idempotency record. If an error is raised, all database
        changes made during this handle execution are rolled back.
        """
        ...


class FunctionalEventHandler:
    """Wrapper adapting a callable async function into an EventHandler."""

    def __init__(
        self,
        event_types: Sequence[EventType | str],
        func: Callable[[BoomerangEvent, AsyncSession], Any],
        name: str | None = None,
    ) -> None:
        self._event_types = tuple(
            et.value if isinstance(et, EventType) else str(et) for et in event_types
        )
        self._func = func
        self.name = name or getattr(func, "__name__", "functional_handler")

    @property
    def event_types(self) -> Sequence[str]:
        return self._event_types

    async def handle(self, event: BoomerangEvent, session: AsyncSession) -> None:
        await self._func(event, session)


class HandlerRegistry:
    """Registry routing validated domain events to subscribed handlers."""

    def __init__(self) -> None:
        self._handlers_by_type: dict[str, list[EventHandler]] = {}
        self._wildcard_handlers: list[EventHandler] = []

    def register(self, handler: EventHandler) -> None:
        """Registers an event handler for its declared event types."""
        types = handler.event_types
        if "*" in types:
            if handler not in self._wildcard_handlers:
                self._wildcard_handlers.append(handler)
        for et in types:
            if et == "*":
                continue
            key = et.value if isinstance(et, EventType) else str(et)
            handlers = self._handlers_by_type.setdefault(key, [])
            if handler not in handlers:
                handlers.append(handler)
        logger.debug(
            "Registered handler %s for types %s",
            getattr(handler, "name", type(handler).__name__),
            types,
        )

    def register_func(
        self,
        event_types: Sequence[EventType | str],
        name: str | None = None,
    ) -> Callable[
        [Callable[[BoomerangEvent, AsyncSession], Any]],
        Callable[[BoomerangEvent, AsyncSession], Any],
    ]:
        """Decorator for registering an async function as an EventHandler."""

        def decorator(
            func: Callable[[BoomerangEvent, AsyncSession], Any],
        ) -> Callable[[BoomerangEvent, AsyncSession], Any]:
            handler = FunctionalEventHandler(event_types, func, name=name)
            self.register(handler)
            return func

        return decorator

    def get_handlers(self, event_type: str | EventType) -> list[EventHandler]:
        """Retrieves all registered handlers matching the given event type."""
        key = event_type.value if isinstance(event_type, EventType) else str(event_type)
        type_handlers = self._handlers_by_type.get(key, [])
        # Return combined wildcard and specific handlers without duplicates
        combined: list[EventHandler] = []
        for h in self._wildcard_handlers + type_handlers:
            if h not in combined:
                combined.append(h)
        return combined

    @property
    def supported_event_types(self) -> set[str]:
        """Returns all distinct event type strings registered."""
        return set(self._handlers_by_type.keys())
