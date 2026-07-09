
import os
import sys
import linecache
import re
import inspect

__all__ = ['spew', 'unspew', 'format_hub_listeners', 'format_hub_timers',
           'hub_listener_stacks', 'hub_exceptions', 'tpool_exceptions',
           'hub_prevent_multiple_readers', 'hub_timer_stacks',
           'hub_blocking_detection', 'format_asyncio_info',
           'format_threads_info']

_token_splitter = re.compile(r'\W+')


class Spew:

    def __init__(self, trace_names=None, show_values=True):
        self.trace_names = trace_names
        self.show_values = show_values

    def __call__(self, frame, event, arg):
        if event == 'line':
            lineno = frame.f_lineno
            if '__file__' in frame.f_globals:
                filename = frame.f_globals['__file__']
                if (filename.endswith('.pyc') or
                        filename.endswith('.pyo')):
                    filename = filename[:-1]
                name = frame.f_globals['__name__']
                line = linecache.getline(filename, lineno)
            else:
                name = '[unknown]'
                try:
                    src, offset = inspect.getsourcelines(frame)
                    if offset == 0:
                        offset = 1
                    line = src[lineno - offset]
                except OSError:
                    line = 'Unknown code named [%s].  VM instruction #%d' % (
                        frame.f_code.co_name, frame.f_lasti)
            if self.trace_names is None or name in self.trace_names:
                print('%s:%s: %s' % (name, lineno, line.rstrip()))
                if not self.show_values:
                    return self
                details = []
                tokens = _token_splitter.split(line)
                for tok in tokens:
                    if tok in frame.f_globals:
                        details.append('%s=%r' % (tok, frame.f_globals[tok]))
                    if tok in frame.f_locals:
                        details.append('%s=%r' % (tok, frame.f_locals[tok]))
                if details:
                    print("\t%s" % ' '.join(details))
        return self


def spew(trace_names=None, show_values=False):
    pass


def unspew():
    pass


def format_hub_listeners():
    pass


def format_asyncio_info():
    pass


def format_threads_info():
    pass


def format_hub_timers():
    pass


def hub_listener_stacks(state=False):
    pass


def hub_timer_stacks(state=False):
    pass


def hub_prevent_multiple_readers(state=True):
    pass


def hub_exceptions(state=True):
    """Toggles whether the hub prints exceptions that are raised from its
    timers.  This can be useful to see how greenthreads are terminating.
    """
    from eventlet import hubs
    hubs.get_hub().set_timer_exceptions(state)
    from eventlet import greenpool
    greenpool.DEBUG = state


def tpool_exceptions(state=False):
    pass


def hub_blocking_detection(state=False, resolution=1):
    pass
