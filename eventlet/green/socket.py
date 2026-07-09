import os
import sys

__import__('eventlet.green._socket_nodns')
__socket = sys.modules['eventlet.green._socket_nodns']

__all__ = __socket.__all__
__patched__ = __socket.__patched__ + [
    'create_connection',
    'getaddrinfo',
    'gethostbyname',
    'gethostbyname_ex',
    'getnameinfo',
]

from eventlet.patcher import slurp_properties
slurp_properties(__socket, globals(), srckeys=dir(__socket))


if os.environ.get("EVENTLET_NO_GREENDNS", '').lower() != 'yes':
    from eventlet.support import greendns
    gethostbyname = greendns.gethostbyname
    getaddrinfo = greendns.getaddrinfo
    gethostbyname_ex = greendns.gethostbyname_ex
    getnameinfo = greendns.getnameinfo
    del greendns


def create_connection(address,
                      timeout=_GLOBAL_DEFAULT_TIMEOUT,
                      source_address=None):
    pass
