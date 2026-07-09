
import atexit
try:
    import _imp as imp
except ImportError:
    import imp
import os
import sys
import traceback

import eventlet
from eventlet import event, greenio, greenthread, patcher, timeout

__all__ = ['execute', 'Proxy', 'killall', 'set_num_threads']


EXC_CLASSES = (Exception, timeout.Timeout)
SYS_EXCS = (GeneratorExit, KeyboardInterrupt, SystemExit)

QUIET = True

socket = patcher.original('socket')
threading = patcher.original('threading')
Queue_module = patcher.original('queue')

Empty = Queue_module.Empty
Queue = Queue_module.Queue

_bytetosend = b' '
_coro = None
_nthreads = int(os.environ.get('EVENTLET_THREADPOOL_SIZE', 20))
_reqq = _rspq = None
_rsock = _wsock = None
_setup_already = False
_threads = []






def execute(meth, *args, **kwargs):
    """
    Execute *meth* in a Python thread, blocking the current coroutine/
    greenthread until the method completes.

    The primary use case for this is to wrap an object or module that is not
    amenable to monkeypatching or any of the other tricks that Eventlet uses
    to achieve cooperative yielding.  With tpool, you can force such objects to
    cooperate with green threads by sticking them in native threads, at the cost
    of some overhead.
    """
    setup()
    my_thread = threading.current_thread()
    if my_thread in _threads or imp.lock_held() or _nthreads == 0:
        return meth(*args, **kwargs)

    e = event.Event()
    _reqq.put((e, meth, args, kwargs))

    rv = e.wait()
    if isinstance(rv, tuple) \
            and len(rv) == 3 \
            and isinstance(rv[1], EXC_CLASSES):
        (c, e, tb) = rv
        if not QUIET:
            traceback.print_exception(c, e, tb)
            traceback.print_stack()
        raise e.with_traceback(tb)
    return rv


def proxy_call(autowrap, f, *args, **kwargs):
    """
    Call a function *f* and returns the value.  If the type of the return value
    is in the *autowrap* collection, then it is wrapped in a :class:`Proxy`
    object before return.

    Normally *f* will be called in the threadpool with :func:`execute`; if the
    keyword argument "nonblocking" is set to ``True``, it will simply be
    executed directly.  This is useful if you have an object which has methods
    that don't need to be called in a separate thread, but which return objects
    that should be Proxy wrapped.
    """
    if kwargs.pop('nonblocking', False):
        rv = f(*args, **kwargs)
    else:
        rv = execute(f, *args, **kwargs)
    if isinstance(rv, autowrap):
        return Proxy(rv, autowrap)
    else:
        return rv


class Proxy:

    def __init__(self, obj, autowrap=(), autowrap_names=()):
        self._obj = obj
        self._autowrap = autowrap
        self._autowrap_names = autowrap_names

    def __getattr__(self, attr_name):
        f = getattr(self._obj, attr_name)
        if not hasattr(f, '__call__'):
            if isinstance(f, self._autowrap) or attr_name in self._autowrap_names:
                return Proxy(f, self._autowrap)
            return f

        return doit

    def __getitem__(self, key):
        return proxy_call(self._autowrap, self._obj.__getitem__, key)

    def __setitem__(self, key, value):
        return proxy_call(self._autowrap, self._obj.__setitem__, key, value)

    def __deepcopy__(self, memo=None):
        return proxy_call(self._autowrap, self._obj.__deepcopy__, memo)

    def __copy__(self, memo=None):
        return proxy_call(self._autowrap, self._obj.__copy__, memo)

    def __call__(self, *a, **kw):
        if '__call__' in self._autowrap_names:
            return Proxy(proxy_call(self._autowrap, self._obj, *a, **kw))
        else:
            return proxy_call(self._autowrap, self._obj, *a, **kw)

    def __enter__(self):
        return proxy_call(self._autowrap, self._obj.__enter__)

    def __exit__(self, *exc):
        return proxy_call(self._autowrap, self._obj.__exit__, *exc)

    def __eq__(self, rhs):
        return self._obj == rhs

    def __hash__(self):
        return self._obj.__hash__()

    def __repr__(self):
        return self._obj.__repr__()

    def __str__(self):
        return self._obj.__str__()

    def __len__(self):
        return len(self._obj)

    def __nonzero__(self):
        return bool(self._obj)
    __bool__ = __nonzero__

    def __iter__(self):
        it = iter(self._obj)
        if it == self._obj:
            return self
        else:
            return Proxy(it)

    __next__ = next


def setup():
    global _rsock, _wsock, _coro, _setup_already, _rspq, _reqq
    if _setup_already:
        return
    else:
        _setup_already = True

    assert _nthreads >= 0, "Can't specify negative number of threads"
    if _nthreads == 0:
        import warnings
        warnings.warn("Zero threads in tpool.  All tpool.execute calls will\
            execute in main thread.  Check the value of the environment \
            variable EVENTLET_THREADPOOL_SIZE.", RuntimeWarning)
    _reqq = Queue(maxsize=-1)
    _rspq = Queue(maxsize=-1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(1)
    csock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    csock.connect(sock.getsockname())
    csock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
    _wsock, _addr = sock.accept()
    _wsock.settimeout(None)
    _wsock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
    sock.close()
    _rsock = greenio.GreenSocket(csock)
    _rsock.settimeout(None)

    for i in range(_nthreads):
        t = threading.Thread(target=tworker,
                             name="tpool_thread_%s" % i)
        t.daemon = True
        t.start()
        _threads.append(t)

    _coro = greenthread.spawn_n(tpool_trampoline)
    eventlet.sleep(0)




