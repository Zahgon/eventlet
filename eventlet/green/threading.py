import eventlet
from eventlet.green import thread
from eventlet.green import time
from eventlet.support import greenlets as greenlet

__patched__ = ['Lock', '_allocate_lock', '_get_main_thread_ident',
               '_make_thread_handle', '_shutdown', '_sleep',
               '_start_joinable_thread', '_start_new_thread', '_ThreadHandle',
               'currentThread', 'current_thread', 'local', 'stack_size',
               "_active", "_limbo"]

__patched__ += ['get_ident', '_set_sentinel']

__orig_threading = eventlet.patcher.original('threading')
__threadlocal = __orig_threading.local()
__patched_enumerate = None


eventlet.patcher.inject(
    'threading',
    globals(),
    ('_thread', thread),
    ('time', time))


_count = 1


class _GreenThread:

    def __init__(self, g):
        global _count
        self._g = g
        self._name = 'GreenThread-%d' % _count
        _count += 1

    def __repr__(self):
        return '<_GreenThread(%s, %r)>' % (self._name, self._g)

    def join(self, timeout=None):
        return self._g.wait()

    get_name = getName

    set_name = setName

    name = property(getName, setName)

    ident = property(lambda self: id(self._g))

    is_alive = isAlive

    daemon = property(lambda self: True)

    is_daemon = isDaemon


__threading = None


def _fixup_thread(t):
    global __threading
    if not __threading:
        __threading = __import__('threading')

    if (hasattr(__threading.Thread, 'get_name') and
            not hasattr(t, 'get_name')):
        t.get_name = t.getName
    return t


def current_thread():
    global __patched_enumerate
    g = greenlet.getcurrent()
    if not g:
        return _fixup_thread(__orig_threading.current_thread())

    try:
        active = __threadlocal.active
    except AttributeError:
        active = __threadlocal.active = {}

    g_id = id(g)
    t = active.get(g_id)
    if t is not None:
        return t

    if __patched_enumerate is None:
        __patched_enumerate = eventlet.patcher.patch_function(__import__('threading').enumerate)
    found = [th for th in __patched_enumerate() if th.ident == g_id]
    if found:
        return found[0]

    def cleanup(g):
        del active[g_id]
    try:
        g.link(cleanup)
    except AttributeError:
        t = _fixup_thread(__orig_threading.current_thread())
    else:
        t = active[g_id] = _GreenThread(g)

    return t


currentThread = current_thread
