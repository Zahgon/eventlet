from eventlet import hubs
from eventlet.semaphore import Semaphore


class Lock(Semaphore):


    def release(self, blocking=True):
        """Modify behaviour vs :class:`Semaphore` to raise a RuntimeError
        exception if the value is greater than zero. This corrects behaviour
        to realign with :class:`threading.Lock`.
        """
        if self.counter > 0:
            raise RuntimeError("release unlocked lock")

        self.counter += 1
        if self._waiters:
            hubs.get_hub().schedule_call_global(0, self._do_acquire)
        return True

