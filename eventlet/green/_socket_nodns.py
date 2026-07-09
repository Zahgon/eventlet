__socket = __import__('socket')

__all__ = __socket.__all__
__patched__ = ['fromfd', 'socketpair', 'ssl', 'socket', 'timeout']

import eventlet.patcher
eventlet.patcher.slurp_properties(__socket, globals(), ignore=__patched__, srckeys=dir(__socket))

os = __import__('os')
import sys
from eventlet import greenio


socket = greenio.GreenSocket
_GLOBAL_DEFAULT_TIMEOUT = greenio._GLOBAL_DEFAULT_TIMEOUT
timeout = greenio.socket_timeout

try:
    __original_fromfd__ = __socket.fromfd

except AttributeError:
    pass

try:
    __original_socketpair__ = __socket.socketpair

except AttributeError:
    pass
