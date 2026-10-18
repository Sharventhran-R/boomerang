"""Event Consumer Foundation package for Boomerang."""

from app.services.event_consumer.consumer import (
    ConsumerMetrics,
    ConsumerProcessingResult,
    ErrorCategory,
    EventConsumer,
    PartitionOffsetTracker,
    calculate_consumer_backoff,
)
from app.services.event_consumer.handler import (
    EventHandler,
    FunctionalEventHandler,
    HandlerRegistry,
)

__all__ = [
    "ConsumerMetrics",
    "ConsumerProcessingResult",
    "ErrorCategory",
    "EventConsumer",
    "EventHandler",
    "FunctionalEventHandler",
    "HandlerRegistry",
    "PartitionOffsetTracker",
    "calculate_consumer_backoff",
]
