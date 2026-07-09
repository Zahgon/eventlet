from eventlet import event as _event


class metaphore:

    def __init__(self):
        self.counter = 0
        self.event = _event.Event()
        self.event.send()

    def inc(self, by=1):
        pass

    def dec(self, by=1):
        pass

    def wait(self):
        """Suspend the caller only if our count is nonzero. In that case,
        resume the caller once the count decrements to zero again.
        """
        self.event.wait()
