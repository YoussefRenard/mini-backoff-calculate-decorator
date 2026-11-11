import random
import unittest

from mini_backoff_calculate_decorator import (
    BackoffCalculator,
    FlushPaused,
    backoff_flush,
)


class FakeClock:
    """Deterministic monotonic clock for tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class BackoffCalculatorTests(unittest.TestCase):
    def test_delay_grows_exponentially_without_jitter(self) -> None:
        calc = BackoffCalculator(base=0.5, factor=2.0, max_delay=30.0, jitter=False)
        self.assertAlmostEqual(calc.delay_for(1), 0.5)
        self.assertAlmostEqual(calc.delay_for(2), 1.0)
        self.assertAlmostEqual(calc.delay_for(3), 2.0)
        self.assertAlmostEqual(calc.delay_for(4), 4.0)

    def test_delay_is_capped_at_max_delay(self) -> None:
        calc = BackoffCalculator(base=1.0, factor=10.0, max_delay=5.0, jitter=False)
        self.assertAlmostEqual(calc.delay_for(1), 1.0)
        self.assertAlmostEqual(calc.delay_for(2), 5.0)
        self.assertAlmostEqual(calc.delay_for(9), 5.0)

    def test_attempt_below_one_is_clamped(self) -> None:
        calc = BackoffCalculator(base=0.25, factor=2.0, max_delay=10.0, jitter=False)
        self.assertAlmostEqual(calc.delay_for(0), 0.25)
        self.assertAlmostEqual(calc.delay_for(-5), 0.25)

    def test_jitter_stays_within_half_and_full_delay(self) -> None:
        rng = random.Random(1234)
        calc = BackoffCalculator(base=2.0, factor=1.0, max_delay=10.0, jitter=True, rng=rng)
        for _ in range(50):
            delay = calc.delay_for(1)
            self.assertGreaterEqual(delay, 1.0)
            self.assertLess(delay, 2.0)

    def test_invalid_parameters_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BackoffCalculator(base=0.0)
        with self.assertRaises(ValueError):
            BackoffCalculator(factor=0.5)
        with self.assertRaises(ValueError):
            BackoffCalculator(base=2.0, max_delay=1.0)


class BackoffFlushTests(unittest.TestCase):
    def test_successful_flush_returns_result_and_resets_state(self) -> None:
        clock = FakeClock()
        calls = []

        @backoff_flush(BackoffCalculator(jitter=False), clock)
        def flush(value: int) -> str:
            calls.append(value)
            return f"ok:{value}"

        self.assertEqual(flush(7), "ok:7")
        self.assertEqual(calls, [7])

    def test_failure_sets_pause_and_raises_original_error(self) -> None:
        clock = FakeClock()
        calc = BackoffCalculator(base=1.0, factor=2.0, max_delay=10.0, jitter=False)

        @backoff_flush(calc, clock)
        def flush() -> None:
            raise RuntimeError("sink down")

        with self.assertRaises(RuntimeError):
            flush()
        with self.assertRaises(FlushPaused):
            flush()

    def test_pause_expires_after_computed_delay(self) -> None:
        clock = FakeClock()
        calc = BackoffCalculator(base=1.0, factor=2.0, max_delay=10.0, jitter=False)
        attempts = []

        @backoff_flush(calc, clock)
        def flush() -> str:
            attempts.append(clock.now)
            if len(attempts) == 1:
                raise RuntimeError("first failure")
            return "recovered"

        with self.assertRaises(RuntimeError):
            flush()
        with self.assertRaises(FlushPaused):
            flush()
        clock.advance(0.5)
        with self.assertRaises(FlushPaused):
            flush()
        clock.advance(0.5)
        self.assertEqual(flush(), "recovered")
        self.assertEqual(len(attempts), 2)

    def test_second_failure_uses_next_delay(self) -> None:
        clock = FakeClock()
        calc = BackoffCalculator(base=1.0, factor=3.0, max_delay=10.0, jitter=False)
        attempts = []

        @backoff_flush(calc, clock)
        def flush() -> None:
            attempts.append(clock.now)
            raise RuntimeError("still down")

        with self.assertRaises(RuntimeError):
            flush()
        clock.advance(1.0)
        with self.assertRaises(RuntimeError):
            flush()
        # Delay for attempt 2 is base * factor = 3.0 seconds.
        with self.assertRaises(FlushPaused):
            flush()
        clock.advance(3.0)
        with self.assertRaises(RuntimeError):
            flush()
        self.assertEqual(len(attempts), 3)

    def test_success_after_recovery_clears_pause(self) -> None:
        clock = FakeClock()
        calc = BackoffCalculator(base=1.0, factor=2.0, max_delay=10.0, jitter=False)
        fail = {"on": True}

        @backoff_flush(calc, clock)
        def flush() -> str:
            if fail["on"]:
                raise RuntimeError("down")
            return "ok"

        with self.assertRaises(RuntimeError):
            flush()
        clock.advance(1.0)
        fail["on"] = False
        self.assertEqual(flush(), "ok")
        # A subsequent failure starts the delay schedule from the beginning.
        fail["on"] = True
        with self.assertRaises(RuntimeError):
            flush()
        with self.assertRaises(FlushPaused):
            flush()

    def test_flush_paused_is_not_swallowed_as_flush_failure(self) -> None:
        clock = FakeClock()
        calc = BackoffCalculator(base=1.0, factor=2.0, max_delay=10.0, jitter=False)

        @backoff_flush(calc, clock)
        def flush() -> None:
            raise RuntimeError("down")

        with self.assertRaises(RuntimeError):
            flush()
        with self.assertRaises(FlushPaused):
            flush()
        # Still paused: the pause exception must not have incremented failures.
        clock.advance(0.5)
        with self.assertRaises(FlushPaused):
            flush()

    def test_clock_must_be_callable(self) -> None:
        with self.assertRaises(TypeError):
            backoff_flush(BackoffCalculator(), 123)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
