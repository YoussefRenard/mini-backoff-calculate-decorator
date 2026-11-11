# mini-backoff-calculate-decorator

Wraps a flush callback with exponential backoff, pausing emission rather than blocking the call site after repeated sink failures.

```python
import time

from mini_backoff_calculate_decorator import BackoffCalculator, FlushPaused, backoff_flush

calc = BackoffCalculator(base=0.5, factor=2.0, max_delay=30.0, jitter=True)

@backoff_flush(calc, clock=time.monotonic)
def flush(batch):
    sink.send(batch)

try:
    flush(batch)
except FlushPaused:
    pass  # emit later; the pause is still active
except Exception:
    pass  # the sink failed and a pause has just been scheduled
```

The wrapped callback returns whatever the flush callback returns, and re-raises
whatever the flush callback raises.  While a pause is active, calling the
wrapped callback raises `FlushPaused` without touching the sink.  After the
pause expires the next call attempts the sink again.

## Why this exists

A flush loop that sleeps blocks whatever thread is producing data.  If the sink
is down, the producer stalls with it.  This decorator records the next allowed
attempt time instead of sleeping, so the producer can keep running, drop or
buffer the batch, and try again later.  The trade-off is that the caller must
handle `FlushPaused`: the library deliberately does not retry on its own,
because only the caller knows whether a dropped batch is acceptable.

## Edge case to know about

`FlushPaused` is raised *before* the flush callback is invoked, so it does not
count as a new failure.  A caller that catches `Exception` broadly around the
flush will therefore see both the original sink error and the pause error.  If
that matters, catch `FlushPaused` first.

## API

- `BackoffCalculator(base=0.5, factor=2.0, max_delay=30.0, jitter=True, rng=None)`
  - `delay_for(attempt)` returns the delay in seconds before retry number
    `attempt` (1-based).  Attempts below 1 are clamped to 1.
- `backoff_flush(calculator, clock)` returns a decorator.  `clock` is a
  zero-argument callable returning monotonic seconds.
- `FlushPaused` is raised by the wrapped callback while a pause is active.
