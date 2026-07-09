__zmq__ = __import__('zmq')
import eventlet.hubs
from eventlet.patcher import slurp_properties
from eventlet.support import greenlets as greenlet

__patched__ = ['Context', 'Socket']
slurp_properties(__zmq__, globals(), ignore=__patched__)

from collections import deque

try:
    if not hasattr(__zmq__, 'XREQ'):
        XREQ = DEALER
    if not hasattr(__zmq__, 'XREP'):
        XREP = ROUTER
except NameError:
    pass


class LockReleaseError(Exception):
    pass


class _QueueLock:

    def __init__(self):
        self._waiters = deque()
        self._count = 0
        self._holder = None
        self._hub = eventlet.hubs.get_hub()

    def __nonzero__(self):
        return bool(self._count)

    __bool__ = __nonzero__

    def __enter__(self):
        self.acquire()

    def __exit__(self, type, value, traceback):
        self.release()

    def acquire(self):
        current = greenlet.getcurrent()
        if (self._waiters or self._count > 0) and self._holder is not current:
            self._waiters.append(current)
            self._hub.switch()
            w = self._waiters.popleft()

            assert w is current, 'Waiting threads woken out of order'
            assert self._count == 0, 'After waking a thread, the lock must be unacquired'

        self._holder = current
        self._count += 1

    def release(self):
        if self._count <= 0:
            raise LockReleaseError("Cannot release unacquired lock")

        self._count -= 1
        if self._count == 0:
            self._holder = None
            if self._waiters:
                self._hub.schedule_call_global(0, self._waiters[0].switch)


class _BlockedThread:

    def __init__(self):
        self._blocked_thread = None
        self._wakeupper = None
        self._hub = eventlet.hubs.get_hub()

    def __nonzero__(self):
        return self._blocked_thread is not None

    __bool__ = __nonzero__

    def block(self, deadline=None):
        if self._blocked_thread is not None:
            raise Exception("Cannot block more than one thread on one BlockedThread")
        self._blocked_thread = greenlet.getcurrent()

        if deadline is not None:
            self._hub.schedule_call_local(deadline - self._hub.clock(), self.wake)

        try:
            self._hub.switch()
        finally:
            self._blocked_thread = None
            if self._wakeupper is not None:
                self._wakeupper.cancel()
                self._wakeupper = None

    def wake(self):
        """Schedules the blocked thread to be awoken and return
        True. If wake has already been called or if there is no
        blocked thread, then this call has no effect and returns
        False."""
        if self._blocked_thread is not None and self._wakeupper is None:
            self._wakeupper = self._hub.schedule_call_global(0, self._blocked_thread.switch)
            return True
        return False


class Context(__zmq__.Context):

    def socket(self, socket_type):
        """Overridden method to ensure that the green version of socket is used

        Behaves the same as :meth:`zmq.Context.socket`, but ensures
        that a :class:`Socket` with all of its send and recv methods set to be
        non-blocking is returned
        """
        if self.closed:
            raise ZMQError(ENOTSUP)
        return Socket(self, socket_type)


def _wraps(source_fn):
    """A decorator that copies the __name__ and __doc__ from the given
    function
    """
    return wrapper



_Socket = __zmq__.Socket
_Socket_recv = _Socket.recv
_Socket_send = _Socket.send
_Socket_send_multipart = _Socket.send_multipart
_Socket_recv_multipart = _Socket.recv_multipart
_Socket_send_string = _Socket.send_string
_Socket_recv_string = _Socket.recv_string
_Socket_send_pyobj = _Socket.send_pyobj
_Socket_recv_pyobj = _Socket.recv_pyobj
_Socket_send_json = _Socket.send_json
_Socket_recv_json = _Socket.recv_json
_Socket_getsockopt = _Socket.getsockopt


class Socket(_Socket):

    def __init__(self, context, socket_type):
        super().__init__(context, socket_type)

        self.__dict__['_eventlet_send_event'] = _BlockedThread()
        self.__dict__['_eventlet_recv_event'] = _BlockedThread()
        self.__dict__['_eventlet_send_lock'] = _QueueLock()
        self.__dict__['_eventlet_recv_lock'] = _QueueLock()

        def event(fd):
            send_wake = self._eventlet_send_event.wake()
            recv_wake = self._eventlet_recv_event.wake()
            if not send_wake and not recv_wake:
                _Socket_getsockopt(self, EVENTS)

        hub = eventlet.hubs.get_hub()
        self.__dict__['_eventlet_listener'] = hub.add(hub.READ,
                                                      self.getsockopt(FD),
                                                      event,
                                                      lambda _: None,
                                                      lambda: None)
        self.__dict__['_eventlet_clock'] = hub.clock

    @_wraps(_Socket.close)
    def close(self, linger=None):
        super().close(linger)
        if self._eventlet_listener is not None:
            eventlet.hubs.get_hub().remove(self._eventlet_listener)
            self.__dict__['_eventlet_listener'] = None
            self._eventlet_send_event.wake()
            self._eventlet_recv_event.wake()

    @_wraps(_Socket.getsockopt)
    def getsockopt(self, option):
        result = _Socket_getsockopt(self, option)
        if option == EVENTS:
            if (result & POLLOUT):
                self._eventlet_send_event.wake()
            if (result & POLLIN):
                self._eventlet_recv_event.wake()
        return result

    @_wraps(_Socket.send)
    def send(self, msg, flags=0, copy=True, track=False):
        """A send method that's safe to use when multiple greenthreads
        are calling send, send_multipart, recv and recv_multipart on
        the same socket.
        """
        if flags & NOBLOCK:
            result = _Socket_send(self, msg, flags, copy, track)
            self._eventlet_send_event.wake()
            self._eventlet_recv_event.wake()
            return result

        flags |= NOBLOCK
        with self._eventlet_send_lock:
            while True:
                try:
                    return _Socket_send(self, msg, flags, copy, track)
                except ZMQError as e:
                    if e.errno == EAGAIN:
                        self._eventlet_send_event.block()
                    else:
                        raise
                finally:
                    self._eventlet_recv_event.wake()

    @_wraps(_Socket.send_multipart)
    def send_multipart(self, msg_parts, flags=0, copy=True, track=False):
        pass

    @_wraps(_Socket.send_string)
    def send_string(self, u, flags=0, copy=True, encoding='utf-8'):
        pass

    @_wraps(_Socket.send_pyobj)
    def send_pyobj(self, obj, flags=0, protocol=2):
        pass

    @_wraps(_Socket.send_json)
    def send_json(self, obj, flags=0, **kwargs):
        pass

    @_wraps(_Socket.recv)
    def recv(self, flags=0, copy=True, track=False):
        """A recv method that's safe to use when multiple greenthreads
        are calling send, send_multipart, recv and recv_multipart on
        the same socket.
        """
        if flags & NOBLOCK:
            msg = _Socket_recv(self, flags, copy, track)
            self._eventlet_send_event.wake()
            self._eventlet_recv_event.wake()
            return msg

        deadline = None
        if hasattr(__zmq__, 'RCVTIMEO'):
            sock_timeout = self.getsockopt(__zmq__.RCVTIMEO)
            if sock_timeout == -1:
                pass
            elif sock_timeout > 0:
                deadline = self._eventlet_clock() + sock_timeout / 1000.0
            else:
                raise ValueError(sock_timeout)

        flags |= NOBLOCK
        with self._eventlet_recv_lock:
            while True:
                try:
                    return _Socket_recv(self, flags, copy, track)
                except ZMQError as e:
                    if e.errno == EAGAIN:
                        if deadline is not None and self._eventlet_clock() > deadline:
                            e.is_timeout = True
                            raise

                        self._eventlet_recv_event.block(deadline=deadline)
                    else:
                        raise
                finally:
                    self._eventlet_send_event.wake()

    @_wraps(_Socket.recv_multipart)
    def recv_multipart(self, flags=0, copy=True, track=False):
        pass

    @_wraps(_Socket.recv_string)
    def recv_string(self, flags=0, encoding='utf-8'):
        pass

    @_wraps(_Socket.recv_json)
    def recv_json(self, flags=0, **kwargs):
        pass

    @_wraps(_Socket.recv_pyobj)
    def recv_pyobj(self, flags=0):
        pass
