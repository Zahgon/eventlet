import traceback

import eventlet
from eventlet import queue
from eventlet.support import greenlets as greenlet

__all__ = ['GreenPool', 'GreenPile']

DEBUG = True


class GreenPool:

    def __init__(self, size=1000):
        try:
            size = int(size)
        except ValueError as e:
            msg = 'GreenPool() expect size :: int, actual: {} {}'.format(type(size), str(e))
            raise TypeError(msg)
        if size < 0:
            msg = 'GreenPool() expect size >= 0, actual: {}'.format(repr(size))
            raise ValueError(msg)
        self.size = size
        self.coroutines_running = set()
        self.sem = eventlet.Semaphore(size)
        self.no_coros_running = eventlet.Event()

    def resize(self, new_size):
        pass

    def running(self):
        """ Returns the number of greenthreads that are currently executing
        functions in the GreenPool."""
        return len(self.coroutines_running)

    def free(self):
        pass

    def spawn(self, function, *args, **kwargs):
        """Run the *function* with its arguments in its own green thread.
        Returns the :class:`GreenThread <eventlet.GreenThread>`
        object that is running the function, which can be used to retrieve the
        results.

        If the pool is currently at capacity, ``spawn`` will block until one of
        the running greenthreads completes its task and frees up a slot.

        This function is reentrant; *function* can call ``spawn`` on the same
        pool without risk of deadlocking the whole thing.
        """
        current = eventlet.getcurrent()
        if self.sem.locked() and current in self.coroutines_running:
            gt = eventlet.greenthread.GreenThread(current)
            gt.main(function, args, kwargs)
            return gt
        else:
            self.sem.acquire()
            gt = eventlet.spawn(function, *args, **kwargs)
            if not self.coroutines_running:
                self.no_coros_running = eventlet.Event()
            self.coroutines_running.add(gt)
            gt.link(self._spawn_done)
        return gt

    def _spawn_n_impl(self, func, args, kwargs, coro):
        try:
            try:
                func(*args, **kwargs)
            except (KeyboardInterrupt, SystemExit, greenlet.GreenletExit):
                raise
            except:
                if DEBUG:
                    traceback.print_exc()
        finally:
            if coro is not None:
                coro = eventlet.getcurrent()
                self._spawn_done(coro)

    def spawn_n(self, function, *args, **kwargs):
        """Create a greenthread to run the *function*, the same as
        :meth:`spawn`.  The difference is that :meth:`spawn_n` returns
        None; the results of *function* are not retrievable.
        """
        current = eventlet.getcurrent()
        if self.sem.locked() and current in self.coroutines_running:
            self._spawn_n_impl(function, args, kwargs, None)
        else:
            self.sem.acquire()
            g = eventlet.spawn_n(
                self._spawn_n_impl,
                function, args, kwargs, True)
            if not self.coroutines_running:
                self.no_coros_running = eventlet.Event()
            self.coroutines_running.add(g)

    def waitall(self):
        """Waits until all greenthreads in the pool are finished working."""
        assert eventlet.getcurrent() not in self.coroutines_running, \
            "Calling waitall() from within one of the " \
            "GreenPool's greenthreads will never terminate."
        if self.running():
            self.no_coros_running.wait()

    def _spawn_done(self, coro):
        self.sem.release()
        if coro is not None:
            self.coroutines_running.remove(coro)
        if self.sem.balance == self.size:
            self.no_coros_running.send(None)

    def waiting(self):
        """Return the number of greenthreads waiting to spawn.
        """
        if self.sem.balance < 0:
            return -self.sem.balance
        else:
            return 0


    def starmap(self, function, iterable):
        pass

    def imap(self, function, *iterables):
        pass


class GreenPile:

    def __init__(self, size_or_pool=1000):
        if isinstance(size_or_pool, GreenPool):
            self.pool = size_or_pool
        else:
            self.pool = GreenPool(size_or_pool)
        self.waiters = queue.LightQueue()
        self.counter = 0

    def spawn(self, func, *args, **kw):
        """Runs *func* in its own green thread, with the result available by
        iterating over the GreenPile object."""
        self.counter += 1
        try:
            gt = self.pool.spawn(func, *args, **kw)
            self.waiters.put(gt)
        except:
            self.counter -= 1
            raise

    def __iter__(self):
        return self

    def next(self):
        pass
    __next__ = next



class GreenMap(GreenPile):
    def __init__(self, size_or_pool):
        super().__init__(size_or_pool)
        self.waiters = queue.LightQueue(maxsize=self.pool.size)


    __next__ = next
