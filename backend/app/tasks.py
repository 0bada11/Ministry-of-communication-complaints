"""A single background worker for model calls.

FastAPI's BackgroundTasks were the obvious home for the priority review, but
they run on the same threadpool that serves sync endpoints. Sixteen concurrent
submissions meant sixteen threads each blocked for seconds on Ollama, and
ordinary requests were left waiting for a worker — the API stalled because of
work no one was waiting for.

So model work gets one dedicated thread and a bounded queue. Ollama serialises
requests internally anyway, so a second worker would buy nothing; what this
buys is the guarantee that no amount of AI backlog can touch request handling.
"""

import logging
import queue
import threading

logger = logging.getLogger("moct")

# Bounded on purpose. If the backlog ever reaches this, the platform is taking
# complaints far faster than the model can review them; dropping the review is
# the right sacrifice, because the rule-based priority is already in place and
# the overdue sweep will still escalate anything that lingers.
MAX_QUEUED = 500

_queue: "queue.Queue[tuple | None]" = queue.Queue(maxsize=MAX_QUEUED)
_worker: threading.Thread | None = None


def _run() -> None:
    while True:
        item = _queue.get()
        try:
            if item is None:  # shutdown signal
                return
            function, args = item
            function(*args)
        except Exception:
            # A failed review must never kill the worker; the complaint simply
            # keeps the priority the rules gave it.
            logger.exception("background task failed")
        finally:
            _queue.task_done()


def start() -> None:
    global _worker
    if _worker and _worker.is_alive():
        return
    _worker = threading.Thread(target=_run, name="moct-ai-worker", daemon=True)
    _worker.start()


def stop(timeout: float = 5.0) -> None:
    if not (_worker and _worker.is_alive()):
        return
    try:
        _queue.put_nowait(None)
    except queue.Full:
        return
    _worker.join(timeout=timeout)


def submit(function, *args) -> bool:
    """Queue work for the background worker. False if the backlog is full."""
    try:
        _queue.put_nowait((function, args))
        return True
    except queue.Full:
        logger.warning("AI backlog full (%d); skipping %s", MAX_QUEUED, function.__name__)
        return False


def drain(timeout: float = 30.0) -> bool:
    """Block until the queue empties. For tests only."""
    deadline = threading.Event()
    waiter = threading.Thread(target=lambda: (_queue.join(), deadline.set()), daemon=True)
    waiter.start()
    return deadline.wait(timeout)


def pending() -> int:
    return _queue.qsize()
