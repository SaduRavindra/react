"""Runnable checks for the reliability core (no pytest required).

    python -m tests.test_reliability

Covers: retry backoff + error classes, circuit breaker open/close,
token bucket pacing, and the headline guarantee — checkpoint resume does
NOT re-run an already-completed (paid) step.
"""
import asyncio

from app.db import db
from app.reliability.breaker import CircuitBreaker, CircuitOpenError, TokenBucket
from app.reliability.checkpoint import run_step
from app.reliability.retry import PermanentError, TransientError, with_retry


async def test_retry_succeeds_after_transient():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("blip")
        return "ok"

    out = await with_retry(flaky, name="flaky", base_delay=0.01)
    assert out == "ok" and calls["n"] == 3, calls


async def test_retry_skips_permanent():
    calls = {"n": 0}

    async def bad():
        calls["n"] += 1
        raise PermanentError("nope")

    try:
        await with_retry(bad, name="bad", base_delay=0.01)
    except PermanentError:
        pass
    assert calls["n"] == 1, "permanent error must not retry"


async def test_breaker_opens_and_blocks():
    cb = CircuitBreaker("t", fail_threshold=2, cooldown=10)

    async def boom():
        raise TransientError("x")

    for _ in range(2):
        try:
            await cb.call(boom)
        except TransientError:
            pass
    assert cb.state == "open"
    try:
        await cb.call(boom)
        assert False, "open circuit should fail fast"
    except CircuitOpenError:
        pass


async def test_token_bucket_paces():
    tb = TokenBucket(rate=50, capacity=2)
    loop = asyncio.get_event_loop()
    start = loop.time()
    for _ in range(5):
        await tb.acquire()
    # 2 free + 3 paced at 50/s ≈ 0.06s minimum
    assert loop.time() - start >= 0.05


async def test_checkpoint_resume_skips_paid_step():
    video = await db.create_video("https://example.com/p", "youtube")
    vid = video["id"]
    calls = {"n": 0}

    async def expensive():
        calls["n"] += 1
        return {"audio_url": "x"}

    out1 = await run_step(vid, "voiceover", expensive)
    out2 = await run_step(vid, "voiceover", expensive)  # should hit checkpoint
    assert out1 == out2 and calls["n"] == 1, f"paid step re-ran: {calls}"


async def main():
    await db.connect()
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        await t()
        print(f"  ✓ {t.__name__}")
    print(f"\n{len(tests)} reliability checks passed")


if __name__ == "__main__":
    asyncio.run(main())
