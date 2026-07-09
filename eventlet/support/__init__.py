import inspect
import functools
import sys
import warnings

from eventlet.support import greenlets


_MISSING = object()


def get_errno(exc):
    """ Get the error code out of socket.error objects.
    socket.error in <2.5 does not have errno attribute
    socket.error in 3.x does not allow indexing access
    e.args[0] works for all.
    There are cases when args[0] is not errno.
    i.e. http://bugs.python.org/issue6471
    Maybe there are cases when errno is set, but it is not the first argument?
    """

    try:
        if exc.errno is not None:
            return exc.errno
    except AttributeError:
        pass
    try:
        return exc.args[0]
    except IndexError:
        return None


if sys.version_info[0] < 3:
    def bytes_to_str(b, encoding='ascii'):
        return b
else:
    def bytes_to_str(b, encoding='ascii'):
        return b.decode(encoding)

PY33 = sys.version_info[:2] == (3, 3)


def wrap_deprecated(old, new):
    def _resolve(s):
        return 'eventlet.'+s if '.' not in s else s
    msg = '''\
{old} is deprecated and will be removed in next version. Use {new} instead.
Autoupgrade: fgrep -rl '{old}' . |xargs -t sed --in-place='' -e 's/{old}/{new}/'
'''.format(old=_resolve(old), new=_resolve(new))

    return wrapper
