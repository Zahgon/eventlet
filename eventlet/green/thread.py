import _thread as __thread
from eventlet.support import greenlets as greenlet
from eventlet import greenthread
from eventlet.timeout import with_timeout
from eventlet.lock import Lock
import sys


__patched__ = ['Lock', 'LockType', '_ThreadHandle', '_count',
               '_get_main_thread_ident', '_local', '_make_thread_handle',
               'allocate', 'allocate_lock', 'exit', 'get_ident',
               'interrupt_main', 'stack_size', 'start_joinable_thread',
               'start_new', 'start_new_thread']

error = __thread.error
LockType = Lock
__threadcount = 0

if hasattr(__thread, "_is_main_interpreter"):
    _is_main_interpreter = __thread._is_main_interpreter




TIMEOUT_MAX = __thread.TIMEOUT_MAX




def get_ident(gr=None):
    if gr is None:
        return id(greenlet.getcurrent())
    else:
        return id(gr)




class _ThreadHandle:
    def __init__(self, greenthread=None):
        self._greenthread = greenthread
        self._done = False




    def join(self, timeout=None):
        if not hasattr(self._greenthread, "wait"):
            return
        if timeout is not None:
            return with_timeout(timeout, self._greenthread.wait)
        return self._greenthread.wait()










start_new = start_new_thread




def allocate_lock(*a):
    return LockType(1)


allocate = allocate_lock


def exit():
    raise greenlet.GreenletExit


exit_thread = __thread.exit_thread




if hasattr(__thread, 'stack_size'):
    __original_stack_size__ = __thread.stack_size


from eventlet.corolocal import local as _local

if hasattr(__thread, 'daemon_threads_allowed'):
    daemon_threads_allowed = __thread.daemon_threads_allowed

if hasattr(__thread, '_shutdown'):
    _shutdown = __thread._shutdown
