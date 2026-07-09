import collections
from contextlib import contextmanager

from eventlet import queue


__all__ = ['Pool', 'TokenPool']


class Pool:

    def __init__(self, min_size=0, max_size=4, order_as_stack=False, create=None):
        """*order_as_stack* governs the ordering of the items in the free pool.
        If ``False`` (the default), the free items collection (of items that
        were created and were put back in the pool) acts as a round-robin,
        giving each item approximately equal utilization.  If ``True``, the
        free pool acts as a FILO stack, which preferentially re-uses items that
        have most recently been used.
        """
        self.min_size = min_size
        self.max_size = max_size
        self.order_as_stack = order_as_stack
        self.current_size = 0
        self.channel = queue.LightQueue(0)
        self.free_items = collections.deque()
        if create is not None:
            self.create = create

        for x in range(min_size):
            self.current_size += 1
            self.free_items.append(self.create())

    def get(self):
        """Return an item from the pool, when one is available.  This may
        cause the calling greenthread to block.
        """
        if self.free_items:
            return self.free_items.popleft()
        self.current_size += 1
        if self.current_size <= self.max_size:
            try:
                created = self.create()
            except:
                self.current_size -= 1
                raise
            return created
        self.current_size -= 1  # did not create
        return self.channel.get()

    @contextmanager
    def item(self):
        pass

    def put(self, item):
        """Put an item back into the pool, when done.  This may
        cause the putting greenthread to block.
        """
        if self.current_size > self.max_size:
            self.current_size -= 1
            return

        if self.waiting():
            try:
                self.channel.put(item, block=False)
                return
            except queue.Full:
                pass

        if self.order_as_stack:
            self.free_items.appendleft(item)
        else:
            self.free_items.append(item)

    def resize(self, new_size):
        pass

    def free(self):
        pass

    def waiting(self):
        """Return the number of routines waiting for a pool item.
        """
        return max(0, self.channel.getting() - self.channel.putting())

    def create(self):
        """Generate a new pool item.  In order for the pool to
        function, either this method must be overriden in a subclass
        or the pool must be constructed with the `create` argument.
        It accepts no arguments and returns a single instance of
        whatever thing the pool is supposed to contain.

        In general, :meth:`create` is called whenever the pool exceeds its
        previous high-water mark of concurrently-checked-out-items.  In other
        words, in a new pool with *min_size* of 0, the very first call
        to :meth:`get` will result in a call to :meth:`create`.  If the first
        caller calls :meth:`put` before some other caller calls :meth:`get`,
        then the first item will be returned, and :meth:`create` will not be
        called a second time.
        """
        raise NotImplementedError("Implement in subclass")


class Token:
    pass


class TokenPool(Pool):

    def create(self):
        return Token()
