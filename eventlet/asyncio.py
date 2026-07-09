import asyncio

from greenlet import GreenletExit

from .greenthread import spawn, getcurrent
from .event import Event
from .hubs import get_hub
from .hubs.asyncio import Hub as AsyncioHub

__all__ = ["spawn_for_awaitable"]


def spawn_for_awaitable(coroutine):
    """
    Take a coroutine or some other object that can be awaited
    (``asyncio.Future``, ``asyncio.Task``), and turn it into a ``GreenThread``.

    Known limitations:

    * The coroutine/future/etc.  don't run in their own
      greenlet/``GreenThread``.
    * As a result, things like ``eventlet.Lock``
      won't work correctly inside ``async`` functions, thread ids aren't
      meaningful, and so on.
    """
    if not isinstance(get_hub(), AsyncioHub):
        raise RuntimeError(
            "This API only works with eventlet's asyncio hub. "
            + "To use it, set an EVENTLET_HUB=asyncio environment variable."
        )


    return spawn(_run)
