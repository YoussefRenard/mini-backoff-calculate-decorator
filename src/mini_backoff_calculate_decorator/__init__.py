"""Public API for mini-backoff-calculate-decorator.

Exports:
    BackoffCalculator: computes sleep durations for a sequence of attempts.
    backoff_flush: decorator that wraps a flush callback with backoff.
    FlushPaused: raised by the wrapped callback when backoff is active.
"""

from .core import BackoffCalculator, FlushPaused, backoff_flush

__all__ = ["BackoffCalculator", "FlushPaused", "backoff_flush"]
