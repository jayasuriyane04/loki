import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """In-process sliding-window limiter. Single-process only; replaced by Redis in Phase 3."""

    def __init__(self, max_events: int, window_s: float) -> None:
        self.max_events = max_events
        self.window_s = window_s
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> bool:
        """Record an attempt. Returns False if the key is over its limit."""
        now = time.monotonic()
        q = self._events[key]
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.max_events:
            return False
        q.append(now)
        return True

    def reset(self, key: str) -> None:
        self._events.pop(key, None)


login_limiter = SlidingWindowLimiter(max_events=10, window_s=300)
register_limiter = SlidingWindowLimiter(max_events=5, window_s=3600)
