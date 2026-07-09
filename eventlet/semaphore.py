import collections

import eventlet
from eventlet import hubs


class Semaphore:


    def __init__(self, value=1):
        try:
            value = int(value)
        except ValueError as e:
            msg = 'Semaphore() expect value :: int, actual: {} {}'.format(type(value), str(e))
            raise TypeError(msg)
        if value < 0:
            msg = 'Semaphore() expect value >= 0, actual: {}'.format(repr(value))
            raise ValueError(msg)
        self.counter = value
        self._waiters = collections.deque()

    def __repr__(self):
        params = (self.__class__.__name__, hex(id(self)),
                  self.counter, len(self._waiters))
        return '<%s at %s c=%s _w[%s]>' % params

    def __str__(self):
        params = (self.__class__.__name__, self.counter, len(self._waiters))
        return '<%s c=%s _w[%s]>' % params

    def locked(self):
        """Returns true if a call to acquire would block.
        """
        return self.counter <= 0

    def bounded(self):
        """Returns False; for consistency with
        :class:`~eventlet.semaphore.CappedSemaphore`.
        """
        return False

    def acquire(self, blocking=True, timeout=None):
        """Acquire a semaphore.

        When invoked without arguments: if the internal counter is larger than
        zero on entry, decrement it by one and return immediately. If it is zero
        on entry, block, waiting until some other thread has called release() to
        make it larger than zero. This is done with proper interlocking so that
        if multiple acquire() calls are blocked, release() will wake exactly one
        of them up. The implementation may pick one at random, so the order in
        which blocked threads are awakened should not be relied on. There is no
        return value in this case.

        When invoked with blocking set to true, do the same thing as when called
        without arguments, and return true.

        When invoked with blocking set to false, do not block. If a call without
        an argument would block, return false immediately; otherwise, do the
        same thing as when called without arguments, and return true.

        Timeout value must be strictly positive.
        """
        if timeout == -1:
            timeout = None
        if timeout is not None and timeout < 0:
            raise ValueError("timeout value must be strictly positive")
        if not blocking:
            if timeout is not None:
                raise ValueError("can't specify timeout for non-blocking acquire")
            timeout = 0
        if not blocking and self.locked():
            return False

        current_thread = eventlet.getcurrent()

        if self.counter <= 0 or self._waiters:
            if current_thread not in self._waiters:
                self._waiters.append(current_thread)
            try:
                if timeout is not None:
                    ok = False
                    with eventlet.Timeout(timeout, False):
                        while self.counter <= 0:
                            hubs.get_hub().switch()
                        ok = True
                    if not ok:
                        return False
                else:
                    while True:
                        hubs.get_hub().switch()
                        if self.counter > 0:
                            break
            finally:
                try:
                    self._waiters.remove(current_thread)
                except ValueError:
                    pass

        self.counter -= 1
        return True

    def __enter__(self):
        self.acquire()

    def release(self, blocking=True):
        """Release a semaphore, incrementing the internal counter by one. When
        it was zero on entry and another thread is waiting for it to become
        larger than zero again, wake up that thread.

        The *blocking* argument is for consistency with CappedSemaphore and is
        ignored
        """
        self.counter += 1
        if self._waiters:
            hubs.get_hub().schedule_call_global(0, self._do_acquire)
        return True


    def __exit__(self, typ, val, tb):
        self.release()

    @property
    def balance(self):
        pass


class BoundedSemaphore(Semaphore):


    def __init__(self, value=1):
        super().__init__(value)
        self.original_counter = value

    def release(self, blocking=True):
        """Release a semaphore, incrementing the internal counter by one. If
        the counter would exceed the initial value, raises ValueError.  When
        it was zero on entry and another thread is waiting for it to become
        larger than zero again, wake up that thread.

        The *blocking* argument is for consistency with :class:`CappedSemaphore`
        and is ignored
        """
        if self.counter >= self.original_counter:
            raise ValueError("Semaphore released too many times")
        return super().release(blocking)


class CappedSemaphore:


    def __init__(self, count, limit):
        if count < 0:
            raise ValueError("CappedSemaphore must be initialized with a "
                             "positive number, got %s" % count)
        if count > limit:
            raise ValueError("'count' cannot be more than 'limit'")
        self.lower_bound = Semaphore(count)
        self.upper_bound = Semaphore(limit - count)

    def __repr__(self):
        params = (self.__class__.__name__, hex(id(self)),
                  self.balance, self.lower_bound, self.upper_bound)
        return '<%s at %s b=%s l=%s u=%s>' % params

    def __str__(self):
        params = (self.__class__.__name__, self.balance,
                  self.lower_bound, self.upper_bound)
        return '<%s b=%s l=%s u=%s>' % params

    def locked(self):
        """Returns true if a call to acquire would block.
        """
        return self.lower_bound.locked()

    def bounded(self):
        """Returns true if a call to release would block.
        """
        return self.upper_bound.locked()

    def acquire(self, blocking=True):
        """Acquire a semaphore.

        When invoked without arguments: if the internal counter is larger than
        zero on entry, decrement it by one and return immediately. If it is zero
        on entry, block, waiting until some other thread has called release() to
        make it larger than zero. This is done with proper interlocking so that
        if multiple acquire() calls are blocked, release() will wake exactly one
        of them up. The implementation may pick one at random, so the order in
        which blocked threads are awakened should not be relied on. There is no
        return value in this case.

        When invoked with blocking set to true, do the same thing as when called
        without arguments, and return true.

        When invoked with blocking set to false, do not block. If a call without
        an argument would block, return false immediately; otherwise, do the
        same thing as when called without arguments, and return true.
        """
        if not blocking and self.locked():
            return False
        self.upper_bound.release()
        try:
            return self.lower_bound.acquire()
        except:
            self.upper_bound.counter -= 1
            raise

    def __enter__(self):
        self.acquire()

    def release(self, blocking=True):
        """Release a semaphore.  In this class, this behaves very much like
        an :meth:`acquire` but in the opposite direction.

        Imagine the docs of :meth:`acquire` here, but with every direction
        reversed.  When calling this method, it will block if the internal
        counter is greater than or equal to *limit*.
        """
        if not blocking and self.bounded():
            return False
        self.lower_bound.release()
        try:
            return self.upper_bound.acquire()
        except:
            self.lower_bound.counter -= 1
            raise

    def __exit__(self, typ, val, tb):
        self.release()

    @property
    def balance(self):
        pass
