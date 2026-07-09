
import sys
import types

import stackless

caller = None
coro_args = {}
tasklet_to_greenlet = {}


def getcurrent():
    return tasklet_to_greenlet[stackless.getcurrent()]


class FirstSwitch:
    def __init__(self, gr):
        self.gr = gr

    def __call__(self, *args, **kw):
        gr = self.gr
        del gr.switch
        run, gr.run = gr.run, None
        t = stackless.tasklet(run)
        gr.t = t
        tasklet_to_greenlet[t] = gr
        t.setup(*args, **kw)
        t.run()


class greenlet:
    def __init__(self, run=None, parent=None):
        self.dead = False
        if parent is None:
            parent = getcurrent()

        self.parent = parent
        if run is not None:
            self.run = run

        self.switch = FirstSwitch(self)

    def switch(self, *args):
        global caller
        caller = stackless.getcurrent()
        coro_args[self] = args
        self.t.insert()
        stackless.schedule()
        if caller is not self.t:
            caller.remove()
        rval = coro_args[self]
        return rval

    def run(self):
        pass

    def __bool__(self):
        return self.run is None and not self.dead


class GreenletExit(Exception):
    pass


