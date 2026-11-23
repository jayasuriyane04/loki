"""Built-in observability: per-turn traces with spans, system events, and the metrics behind the Analytics page.

Nothing here stores message content: traces hold timings, counts, model/tool names and status only.
"""

from app.observability.trace import (
    Trace,
    current_trace,
    event,
    record_event,
    sink,
    span,
    traced,
)

__all__ = ["Trace", "current_trace", "event", "record_event", "sink", "span", "traced"]
