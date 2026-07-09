

profile_orig = __import__('profile')
__all__ = profile_orig.__all__

from eventlet.patcher import slurp_properties
slurp_properties(profile_orig, globals(), srckeys=dir(profile_orig))

import sys
import functools

from eventlet import greenthread
from eventlet import patcher
import _thread

thread = patcher.original(_thread.__name__)  # non-monkeypatched module needed


class Profile(profile_orig.Profile):
    base = profile_orig.Profile

    def __init__(self, timer=None, bias=None):
        self.current_tasklet = greenthread.getcurrent()
        self.thread_id = thread.get_ident()
        self.base.__init__(self, timer, bias)
        self.sleeping = {}

    def __call__(self, *args):
        """make callable, allowing an instance to be the profiler"""
        self.dispatcher(*args)

    def _setup(self):
        self._has_setup = True
        self.cur = None
        self.timings = {}
        self.current_tasklet = greenthread.getcurrent()
        self.thread_id = thread.get_ident()
        self.simulate_call("profiler")

    def start(self, name="start"):
        if getattr(self, "running", False):
            return
        self._setup()
        self.simulate_call("start")
        self.running = True
        sys.setprofile(self.dispatcher)




    def trace_dispatch_return_extend_back(self, frame, t):
        pass


    def SwitchTasklet(self, t0, t1, t):
        pt, it, et, fn, frame, rcur = self.cur
        cur = (pt, it + t, et, fn, frame, rcur)

        self.sleeping[t0] = cur, self.timings
        self.current_tasklet = t1

        try:
            self.cur, self.timings = self.sleeping.pop(t1)
        except KeyError:
            self.cur, self.timings = None, {}
            self.simulate_call("profiler")
            self.simulate_call("new_tasklet")


    def Unwind(self, cur, timings):
        pass


def ContextWrap(f):
    return ContextWrapper


Profile.dispatch = dict(profile_orig.Profile.dispatch, **{
    'return': Profile.trace_dispatch_return_extend_back,
    'c_return': Profile.trace_dispatch_c_return_extend_back,
})
Profile.dispatch = {k: ContextWrap(v) for k, v in Profile.dispatch.items()}


def run(statement, filename=None, sort=-1):
    """Run statement under profiler optionally saving results in filename

    This function takes a single argument that can be passed to the
    "exec" statement, and an optional file name.  In all cases this
    routine attempts to "exec" its first argument and gather profiling
    statistics from the execution. If no file name is present, then this
    function automatically prints a simple profiling report, sorted by the
    standard name string (file/line/function-name) that is presented in
    each line.
    """
    prof = Profile()
    try:
        prof = prof.run(statement)
    except SystemExit:
        pass
    if filename is not None:
        prof.dump_stats(filename)
    else:
        return prof.print_stats(sort)


def runctx(statement, globals, locals, filename=None):
    pass
