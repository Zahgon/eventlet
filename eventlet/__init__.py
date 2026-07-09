import os
import sys
import warnings


from eventlet import convenience
from eventlet import event
from eventlet import greenpool
from eventlet import greenthread
from eventlet import patcher
from eventlet import queue
from eventlet import semaphore
from eventlet import support
from eventlet import timeout
try:
    from eventlet._version import __version__
except ImportError:
    __version__ = "0.0.0"
import greenlet

try:
    import monotonic
    del monotonic
except ImportError:
    pass

connect = convenience.connect
listen = convenience.listen
serve = convenience.serve
StopServe = convenience.StopServe
wrap_ssl = convenience.wrap_ssl

Event = event.Event

GreenPool = greenpool.GreenPool
GreenPile = greenpool.GreenPile

sleep = greenthread.sleep
spawn = greenthread.spawn
spawn_n = greenthread.spawn_n
spawn_after = greenthread.spawn_after
kill = greenthread.kill

import_patched = patcher.import_patched
monkey_patch = patcher.monkey_patch

Queue = queue.Queue

Semaphore = semaphore.Semaphore
CappedSemaphore = semaphore.CappedSemaphore
BoundedSemaphore = semaphore.BoundedSemaphore

Timeout = timeout.Timeout
with_timeout = timeout.with_timeout
wrap_is_timeout = timeout.wrap_is_timeout
is_timeout = timeout.is_timeout

getcurrent = greenlet.greenlet.getcurrent

TimeoutError, exc_after, call_after_global = (
    support.wrap_deprecated(old, new)(fun) for old, new, fun in (
        ('TimeoutError', 'Timeout', Timeout),
        ('exc_after', 'greenthread.exc_after', greenthread.exc_after),
        ('call_after_global', 'greenthread.call_after_global', greenthread.call_after_global),
    ))


if hasattr(os, "register_at_fork"):
    os.register_at_fork(before=_warn_on_fork)


_DEPRECATED = \
"""
Eventlet is deprecated. It is currently being maintained in bugfix mode, and
we strongly recommend against using it for new projects.

If you are already using Eventlet, we recommend migrating to a different
framework.  For more detail see
https://eventlet.readthedocs.io/en/latest/asyncio/migration.html
"""

class EventletDeprecationWarning(Warning):
    pass

if os.environ.get("EVENTLET_TESTS") is None:
    warnings.warn(_DEPRECATED, EventletDeprecationWarning, stacklevel=2)
