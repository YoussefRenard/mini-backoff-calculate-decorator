"""Core implementation of the backoff-calculate decorator.

The decorator wraps a flush callback so that after a sink failure the callback
is paused for a computed duration instead of blocking the caller.  Time is
injected as a monotonic clock function so tests never depend on wall-clock
time.
"""

from __future__ import annotations

import functools
import random
from typing import Callable, Optional


class FlushPaused(Exception):
    """Raised when a flush is attempted while the backoff pause is active.

    The decorator does not sleep; it raises this exception so the call site can
    decide how to proceed (drop the batch, retry later, etc.).  This keeps the
    caller responsive while still enforcing the pause.
    """


class BackoffCalculator:
    """Compute bounded exponential backoff delays with optional jitter.

    Parameters
    ----------
    base:
        Delay in seconds for the first retry.  Must be positive.
    factor:
        Multiplier applied per attempt.  Must be >= 1.0.
    max_delay:
        Upper bound on the computed delay.  Must be >= base.
    jitter:
        When true, each delay is multiplied by a random factor in [0.5, 1.0).
        Jitter is deterministic only if a seeded ``random.Random`` instance is
        supplied via ``rng``; tests do that to stay reproducible.
    rng:
        Optional ``random.Random``-compatible object.  Defaults to a private
        instance so the module-level random state is never touched.
    """

    def __init__(
        self,
        base: float = 0.5,
        factor: float = 2.0,
        max_delay: float = 30.0,
        jitter: bool = True,
        rng: Optional[random.Random] = None,
    ) -> None:
        if base <= 0:
            raise ValueError("base must be positive")
        if factor < 1.0:
            raise ValueError("factor must be >= 1.0")
        if max_delay < base:
            raise ValueError("max_delay must be >= base")
        self.base = float(base)
        self.factor = float(factor)
        self.max_delay = float(max_delay)
        self.jitter = bool(jitter)
        self._rng = rng if rng is not None else random.Random()

    def delay_for(self, attempt: int) -> float:
        """Return the delay in seconds before retry number ``attempt``.

        ``attempt`` is 1-based: attempt 1 is the first retry after the initial
        failure.  Values below 1 are treated as 1 so callers cannot accidentally
        request a zero or negative exponent.
        """
        if attempt < 1:
            attempt = 1
        raw = self.base * (self.factor ** (attempt - 1))
        if raw > self.max_delay:
            raw = self.max_delay
        if self.jitter:
            # Multiply by a factor in [0.5, 1.0) so the delay is never longer
            # than the computed bound but still spreads retries out.
            raw *= 0.5 + (self._rng.random() * 0.5)
        return raw


def backoff_flush(
    calculator: BackoffCalculator,
    clock: Callable[[], float],
) -> Callable[[Callable[..., object]], Callable[..., object]]:
    """Wrap a flush callback with exponential backoff.

    The wrapped function calls ``flush(*args, **kwargs)``.  On success the
    failure counter resets and the result is returned.  On failure the counter
    increments and the computed delay is stored; subsequent calls before
    ``clock()`` reaches the stored deadline raise :class:`FlushPaused` instead
    of invoking ``flush``.  After the deadline the callback is attempted again.

    The clock is a zero-argument callable returning a monotonic timestamp in
    seconds.  This keeps the decorator testable without sleeping.
    """
    if not callable(clock):
        raise TypeError("clock must be callable")

    def decorator(flush: Callable[..., object]) -> Callable[..., object]:
        failures = 0
        resume_at: Optional[float] = None

        @functools.wraps(flush)
        def wrapper(*args: object, **kwargs: object) -> object:
            nonlocal failures, resume_at
            now = clock()
            if resume_at is not None and now < resume_at:
                raise FlushPaused(
                    f"flush paused until {resume_at:.6f} (now {now:.6f})"
                )
            try:
                result = flush(*args, **kwargs)
            except Exception:
                failures += 1
                resume_at = now + calculator.delay_for(failures)
                raise
            failures = 0
            resume_at = None
            return result

        return wrapper

    return decorator
