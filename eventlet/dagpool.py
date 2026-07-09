
from eventlet.event import Event
from eventlet import greenthread
import collections


_MISSING = object()


class Collision(Exception):
    pass


class PropagateError(Exception):
    def __init__(self, key, exc):
        msg = "PropagateError({}): {}: {}" \
              .format(key, exc.__class__.__name__, exc)
        super().__init__(msg)
        self.msg = msg
        self.args = (key, exc)
        self.key = key
        self.exc = exc

    def __str__(self):
        return self.msg


class DAGPool:

    _Coro = collections.namedtuple("_Coro", ("greenthread", "pending"))

    def __init__(self, preload={}):
        """
        DAGPool can be prepopulated with an initial dict or iterable of (key,
        value) pairs. These (key, value) pairs are of course immediately
        available for any greenthread that depends on any of those keys.
        """
        try:
            iteritems = preload.items()
        except AttributeError:
            iteritems = preload

        self.values = dict(iteritems)

        self.coros = {}

        self.event = Event()

    def waitall(self):
        """
        waitall() blocks the calling greenthread until there is a value for
        every DAGPool greenthread launched by :meth:`spawn`. It returns a dict
        containing all :class:`preload data <DAGPool>`, all data from
        :meth:`post` and all values returned by spawned greenthreads.

        See also :meth:`wait`.
        """
        return self.wait()

    def wait(self, keys=_MISSING):
        """
        *keys* is an optional iterable of keys. If you omit the argument, it
        waits for all the keys from :class:`preload data <DAGPool>`, from
        :meth:`post` calls and from :meth:`spawn` calls: in other words, all
        the keys of which this DAGPool is aware.

        wait() blocks the calling greenthread until all of the relevant keys
        have values. wait() returns a dict whose keys are the relevant keys,
        and whose values come from the *preload* data, from values returned by
        DAGPool greenthreads or from :meth:`post` calls.

        If a DAGPool greenthread terminates with an exception, wait() will
        raise :class:`PropagateError` wrapping that exception. If more than
        one greenthread terminates with an exception, it is indeterminate
        which one wait() will raise.

        If an external greenthread posts a :class:`PropagateError` instance,
        wait() will raise that PropagateError. If more than one greenthread
        posts PropagateError, it is indeterminate which one wait() will raise.

        See also :meth:`wait_each_success`, :meth:`wait_each_exception`.
        """
        return dict(self.wait_each(keys))

    def wait_each(self, keys=_MISSING):
        """
        *keys* is an optional iterable of keys. If you omit the argument, it
        waits for all the keys from :class:`preload data <DAGPool>`, from
        :meth:`post` calls and from :meth:`spawn` calls: in other words, all
        the keys of which this DAGPool is aware.

        wait_each() is a generator producing (key, value) pairs as a value
        becomes available for each requested key. wait_each() blocks the
        calling greenthread until the next value becomes available. If the
        DAGPool was prepopulated with values for any of the relevant keys, of
        course those can be delivered immediately without waiting.

        Delivery order is intentionally decoupled from the initial sequence of
        keys: each value is delivered as soon as it becomes available. If
        multiple keys are available at the same time, wait_each() delivers
        each of the ready ones in arbitrary order before blocking again.

        The DAGPool does not distinguish between a value returned by one of
        its own greenthreads and one provided by a :meth:`post` call or *preload* data.

        The wait_each() generator terminates (raises StopIteration) when all
        specified keys have been delivered. Thus, typical usage might be:

        ::

            for key, value in dagpool.wait_each(keys):
                # process this ready key and value
            # continue processing now that we've gotten values for all keys

        By implication, if you pass wait_each() an empty iterable of keys, it
        returns immediately without yielding anything.

        If the value to be delivered is a :class:`PropagateError` exception object, the
        generator raises that PropagateError instead of yielding it.

        See also :meth:`wait_each_success`, :meth:`wait_each_exception`.
        """
        return self._wait_each(self._get_keyset_for_wait_each(keys))

    def wait_each_success(self, keys=_MISSING):
        pass

    def wait_each_exception(self, keys=_MISSING):
        pass

    def _get_keyset_for_wait_each(self, keys):
        """
        wait_each(), wait_each_success() and wait_each_exception() promise
        that if you pass an iterable of keys, the method will wait for results
        from those keys -- but if you omit the keys argument, the method will
        wait for results from all known keys. This helper implements that
        distinction, returning a set() of the relevant keys.
        """
        if keys is not _MISSING:
            return set(keys)
        else:
            return set(self.coros.keys()) | set(self.values.keys())

    def _wait_each(self, pending):
        """
        When _wait_each() encounters a value of PropagateError, it raises it.

        In all other respects, _wait_each() behaves like _wait_each_raw().
        """
        for key, value in self._wait_each_raw(pending):
            yield key, self._value_or_raise(value)

    @staticmethod
    def _value_or_raise(value):
        if isinstance(value, PropagateError):
            raise value
        return value

    def _wait_each_raw(self, pending):
        """
        pending is a set() of keys for which we intend to wait. THIS SET WILL
        BE DESTRUCTIVELY MODIFIED: as each key acquires a value, that key will
        be removed from the passed 'pending' set.

        _wait_each_raw() does not treat a PropagateError instance specially:
        it will be yielded to the caller like any other value.

        In all other respects, _wait_each_raw() behaves like wait_each().
        """
        while True:
            for key in pending.copy():
                value = self.values.get(key, _MISSING)
                if value is not _MISSING:
                    pending.remove(key)
                    yield (key, value)

            if not pending:
                break

            self.event.wait()

    def spawn(self, key, depends, function, *args, **kwds):
        """
        Launch the passed *function(key, results, ...)* as a greenthread,
        passing it:

        - the specified *key*
        - an iterable of (key, value) pairs
        - whatever other positional args or keywords you specify.

        Iterating over the *results* iterable behaves like calling
        :meth:`wait_each(depends) <DAGPool.wait_each>`.

        Returning from *function()* behaves like
        :meth:`post(key, return_value) <DAGPool.post>`.

        If *function()* terminates with an exception, that exception is wrapped
        in :class:`PropagateError` with the greenthread's *key* and (effectively) posted
        as the value for that key. Attempting to retrieve that value will
        raise that PropagateError.

        Thus, if the greenthread with key 'a' terminates with an exception,
        and greenthread 'b' depends on 'a', when greenthread 'b' attempts to
        iterate through its *results* argument, it will encounter
        PropagateError. So by default, an uncaught exception will propagate
        through all the downstream dependencies.

        If you pass :meth:`spawn` a key already passed to spawn() or :meth:`post`, spawn()
        raises :class:`Collision`.
        """
        if key in self.coros or key in self.values:
            raise Collision(key)

        pending = set(depends)
        newcoro = greenthread.spawn(self._wrapper, function, key,
                                    self._wait_each(pending),
                                    *args, **kwds)
        self.coros[key] = self._Coro(newcoro, pending)

    def _wrapper(self, function, key, results, *args, **kwds):
        pass

    def spawn_many(self, depends, function, *args, **kwds):
        pass

    def kill(self, key):
        """
        Kill the greenthread that was spawned with the specified *key*.

        If no such greenthread was spawned, raise KeyError.
        """
        self.coros[key].greenthread.kill()
        del self.coros[key]

    def post(self, key, value, replace=False):
        pass

    def __getitem__(self, key):
        """
        __getitem__(key) (aka dagpool[key]) blocks until *key* has a value,
        then delivers that value.
        """
        for _, value in self.wait_each((key,)):
            return value

    def get(self, key, default=None):
        """
        get() returns the value for *key*. If *key* does not yet have a value,
        get() returns *default*.
        """
        return self._value_or_raise(self.values.get(key, default))

    def keys(self):
        """
        Return a snapshot tuple of keys for which we currently have values.
        """
        return tuple(self.values.keys())

    def items(self):
        """
        Return a snapshot tuple of currently-available (key, value) pairs.
        """
        return tuple((key, self._value_or_raise(value))
                     for key, value in self.values.items())

    def running(self):
        """
        Return number of running DAGPool greenthreads. This includes
        greenthreads blocked while iterating through their *results* iterable,
        that is, greenthreads waiting on values from other keys.
        """
        return len(self.coros)

    def running_keys(self):
        pass

    def waiting(self):
        """
        Return number of waiting DAGPool greenthreads, that is, greenthreads
        still waiting on values from other keys. This explicitly does *not*
        include external greenthreads waiting on :meth:`wait`,
        :meth:`waitall`, :meth:`wait_each`.
        """
        return len(self.waiting_for())

    def waiting_for(self, key=_MISSING):
        """
        waiting_for(key) returns a set() of the keys for which the DAGPool
        greenthread spawned with that *key* is still waiting. If you pass a
        *key* for which no greenthread was spawned, waiting_for() raises
        KeyError.

        waiting_for() without argument returns a dict. Its keys are the keys
        of DAGPool greenthreads still waiting on one or more values. In the
        returned dict, the value of each such key is the set of other keys for
        which that greenthread is still waiting.

        This method allows diagnosing a "hung" DAGPool. If certain
        greenthreads are making no progress, it's possible that they are
        waiting on keys for which there is no greenthread and no :meth:`post` data.
        """
        available = set(self.values.keys())

        if key is not _MISSING:
            coro = self.coros.get(key, _MISSING)
            if coro is _MISSING:
                self.values[key]
                return set()
            else:
                return coro.pending - available


        return {key: pending
                for key, pending in ((key, (coro.pending - available))
                                     for key, coro in self.coros.items())
                if pending}
