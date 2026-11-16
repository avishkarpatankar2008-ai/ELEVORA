"""Bounded execution of CPU/IO-heavy work (PDF/DOCX parsing, audio decoding).

Parsing an upload or decoding audio is synchronous and can be slow. Running it
directly in a request handler blocks the event loop for every other user, and
nothing limits how many run at once. :func:`run_bounded` fixes both:

* the work runs in a worker thread, so the loop stays responsive;
* at most ``max_concurrent_processing`` jobs hold a slot at once; callers wait at
  most ``processing_queue_timeout_seconds`` for one, then get
  :class:`ProcessingBusyError` (-> 503) instead of an unbounded queue;
* each job has a hard wall-clock timeout (-> :class:`ProcessingTimeoutError`).

A thread cannot be killed, so on timeout the slot stays occupied until the
thread actually finishes. Concurrency stays bounded even while a runaway job is
being abandoned. The inputs are size-limited as well, which bounds how long such
a job can run in practice.
"""

import asyncio
import weakref
from typing import Callable, TypeVar

from app.config import get_settings

T = TypeVar("T")


def _release_when_done(future: "asyncio.Future", sem: asyncio.Semaphore) -> None:
    def _done(f: "asyncio.Future") -> None:
        if not f.cancelled():
            f.exception()  # mark retrieved: an abandoned job's error is not our concern
        sem.release()

    future.add_done_callback(_done)


class ProcessingBusyError(Exception):
    """No processing slot became free in time."""


class ProcessingTimeoutError(Exception):
    """The job exceeded its time limit."""


_semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _semaphores.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(get_settings().max_concurrent_processing)
        _semaphores[loop] = sem
    return sem


async def run_bounded(func: Callable[..., T], *args, timeout: float, **kwargs) -> T:
    settings = get_settings()
    sem = _semaphore()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=settings.processing_queue_timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise ProcessingBusyError("All processing slots are busy.") from exc

    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, lambda: func(*args, **kwargs))
    try:
        # shield: a timeout must not cancel the (uncancellable) thread future.
        result = await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError as exc:
        _release_when_done(future, sem)
        raise ProcessingTimeoutError("Processing timed out.") from exc
    except BaseException:
        # Cancellation or an error from the job itself.
        if future.done():
            sem.release()
        else:
            _release_when_done(future, sem)
        raise
    sem.release()
    return result
