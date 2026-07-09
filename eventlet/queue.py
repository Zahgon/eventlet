

import collections
import heapq
import sys
import traceback
import types

from eventlet.event import Event
from eventlet.greenthread import getcurrent
from eventlet.hubs import get_hub
import queue as Stdlib_Queue
from eventlet.timeout import Timeout


__all__ = ['Queue', 'PriorityQueue', 'LifoQueue', 'LightQueue', 'Full', 'Empty']

_NONE = object()
Full = Stdlib_Queue.Full
Empty = Stdlib_Queue.Empty


class Waiter:
    __slots__ = ['greenlet']

    def __init__(self):
        self.greenlet = None

    def __repr__(self):
        if self.waiting:
            waiting = ' waiting'
        else:
            waiting = ''
        return '<%s at %s%s greenlet=%r>' % (
            type(self).__name__, hex(id(self)), waiting, self.greenlet,
        )

    def __str__(self):
        """
        >>> print(Waiter())
        <Waiter greenlet=None>
        """
        if self.waiting:
            waiting = ' waiting'
        else:
            waiting = ''
        return '<%s%s greenlet=%s>' % (type(self).__name__, waiting, self.greenlet)

    def __nonzero__(self):
        return self.greenlet is not None

    __bool__ = __nonzero__

    @property
    def waiting(self):
        return self.greenlet is not None

    def switch(self, value=None):
        """Wake up the greenlet that is calling wait() currently (if there is one).
        Can only be called from Hub's greenlet.
        """
        assert getcurrent() is get_hub(
        ).greenlet, "Can only use Waiter.switch method from the mainloop"
        if self.greenlet is not None:
            try:
                self.greenlet.switch(value)
            except Exception:
                traceback.print_exc()

    def throw(self, *throw_args):
        """Make greenlet calling wait() wake up (if there is a wait()).
        Can only be called from Hub's greenlet.
        """
        assert getcurrent() is get_hub(
        ).greenlet, "Can only use Waiter.switch method from the mainloop"
        if self.greenlet is not None:
            try:
                self.greenlet.throw(*throw_args)
            except Exception:
                traceback.print_exc()

    def wait(self):
        """Wait until switch() or throw() is called.
        """
        assert self.greenlet is None, 'This Waiter is already used by %r' % (self.greenlet, )
        self.greenlet = getcurrent()
        try:
            return get_hub().switch()
        finally:
            self.greenlet = None


class LightQueue:

    def __init__(self, maxsize=None):
        if maxsize is None or maxsize < 0:  # None is not comparable in 3.x
            self.maxsize = None
        else:
            self.maxsize = maxsize
        self.getters = set()
        self.putters = set()
        self._event_unlock = None
        self._init(maxsize)


    def _init(self, maxsize):
        self.queue = collections.deque()

    def _get(self):
        return self.queue.popleft()

    def _put(self, item):
        self.queue.append(item)

    def __repr__(self):
        return '<%s at %s %s>' % (type(self).__name__, hex(id(self)), self._format())

    def __str__(self):
        return '<%s %s>' % (type(self).__name__, self._format())

    def _format(self):
        result = 'maxsize=%r' % (self.maxsize, )
        if getattr(self, 'queue', None):
            result += ' queue=%r' % self.queue
        if self.getters:
            result += ' getters[%s]' % len(self.getters)
        if self.putters:
            result += ' putters[%s]' % len(self.putters)
        if self._event_unlock is not None:
            result += ' unlocking'
        return result

    def qsize(self):
        """Return the size of the queue."""
        return len(self.queue)

    def resize(self, size):
        pass

    def putting(self):
        """Returns the number of greenthreads that are blocked waiting to put
        items into the queue."""
        return len(self.putters)

    def getting(self):
        """Returns the number of greenthreads that are blocked waiting on an
        empty queue."""
        return len(self.getters)

    def empty(self):
        pass

    def full(self):
        pass

    def put(self, item, block=True, timeout=None):
        """Put an item into the queue.

        If optional arg *block* is true and *timeout* is ``None`` (the default),
        block if necessary until a free slot is available. If *timeout* is
        a positive number, it blocks at most *timeout* seconds and raises
        the :class:`Full` exception if no free slot was available within that time.
        Otherwise (*block* is false), put an item on the queue if a free slot
        is immediately available, else raise the :class:`Full` exception (*timeout*
        is ignored in that case).
        """
        if self.maxsize is None or self.qsize() < self.maxsize:
            self._put(item)
            if self.getters:
                self._schedule_unlock()
        elif not block and get_hub().greenlet is getcurrent():
            while self.getters:
                getter = self.getters.pop()
                if getter:
                    self._put(item)
                    item = self._get()
                    getter.switch(item)
                    return
            raise Full
        elif block:
            waiter = ItemWaiter(item, block)
            self.putters.add(waiter)
            timeout = Timeout(timeout, Full)
            try:
                if self.getters:
                    self._schedule_unlock()
                result = waiter.wait()
                assert result is waiter, "Invalid switch into Queue.put: %r" % (result, )
                if waiter.item is not _NONE:
                    self._put(item)
            finally:
                timeout.cancel()
                self.putters.discard(waiter)
        elif self.getters:
            waiter = ItemWaiter(item, block)
            self.putters.add(waiter)
            self._schedule_unlock()
            result = waiter.wait()
            assert result is waiter, "Invalid switch into Queue.put: %r" % (result, )
            if waiter.item is not _NONE:
                raise Full
        else:
            raise Full

    def put_nowait(self, item):
        pass

    def get(self, block=True, timeout=None):
        """Remove and return an item from the queue.

        If optional args *block* is true and *timeout* is ``None`` (the default),
        block if necessary until an item is available. If *timeout* is a positive number,
        it blocks at most *timeout* seconds and raises the :class:`Empty` exception
        if no item was available within that time. Otherwise (*block* is false), return
        an item if one is immediately available, else raise the :class:`Empty` exception
        (*timeout* is ignored in that case).
        """
        if self.qsize():
            if self.putters:
                self._schedule_unlock()
            return self._get()
        elif not block and get_hub().greenlet is getcurrent():
            while self.putters:
                putter = self.putters.pop()
                if putter:
                    putter.switch(putter)
                    if self.qsize():
                        return self._get()
            raise Empty
        elif block:
            waiter = Waiter()
            timeout = Timeout(timeout, Empty)
            try:
                self.getters.add(waiter)
                if self.putters:
                    self._schedule_unlock()
                try:
                    return waiter.wait()
                except:
                    self._schedule_unlock()
                    raise
            finally:
                self.getters.discard(waiter)
                timeout.cancel()
        else:
            raise Empty

    def get_nowait(self):
        pass


    def _schedule_unlock(self):
        if self._event_unlock is None:
            self._event_unlock = get_hub().schedule_call_global(0, self._unlock)

    if sys.version_info >= (3, 9):
        __class_getitem__ = classmethod(types.GenericAlias)


class ItemWaiter(Waiter):
    __slots__ = ['item', 'block']

    def __init__(self, item, block):
        Waiter.__init__(self)
        self.item = item
        self.block = block


class Queue(LightQueue):

    def __init__(self, maxsize=None):
        LightQueue.__init__(self, maxsize)
        self.unfinished_tasks = 0
        self._cond = Event()

    def _format(self):
        result = LightQueue._format(self)
        if self.unfinished_tasks:
            result += ' tasks=%s _cond=%s' % (self.unfinished_tasks, self._cond)
        return result

    def _put(self, item):
        LightQueue._put(self, item)
        self._put_bookkeeping()

    def _put_bookkeeping(self):
        self.unfinished_tasks += 1
        if self._cond.ready():
            self._cond.reset()

    def task_done(self):
        pass

    def join(self):
        '''Block until all items in the queue have been gotten and processed.

        The count of unfinished tasks goes up whenever an item is added to the queue.
        The count goes down whenever a consumer thread calls :meth:`task_done` to indicate
        that the item was retrieved and all work on it is complete. When the count of
        unfinished tasks drops to zero, :meth:`join` unblocks.
        '''
        if self.unfinished_tasks > 0:
            self._cond.wait()


class PriorityQueue(Queue):

    def _init(self, maxsize):
        self.queue = []

    def _put(self, item, heappush=heapq.heappush):
        heappush(self.queue, item)
        self._put_bookkeeping()

    def _get(self, heappop=heapq.heappop):
        return heappop(self.queue)


class LifoQueue(Queue):

    def _init(self, maxsize):
        self.queue = []

    def _put(self, item):
        self.queue.append(item)
        self._put_bookkeeping()

    def _get(self):
        return self.queue.pop()
