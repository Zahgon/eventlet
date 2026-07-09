import errno
import sys
from types import FunctionType

import eventlet
from eventlet import greenio
from eventlet import patcher
from eventlet.green import select, threading, time


__patched__ = ['call', 'check_call', 'Popen']
to_patch = [('select', select), ('threading', threading), ('time', time)]

from eventlet.green import selectors
to_patch.append(('selectors', selectors))

patcher.inject('subprocess', globals(), *to_patch)
subprocess_orig = patcher.original("subprocess")
subprocess_imported = sys.modules.get('subprocess', subprocess_orig)
mswindows = sys.platform == "win32"


if getattr(subprocess_orig, 'TimeoutExpired', None) is None:
    class TimeoutExpired(Exception):

        def __init__(self, cmd, timeout, output=None):
            self.cmd = cmd
            self.timeout = timeout
            self.output = output

        def __str__(self):
            return ("Command '%s' timed out after %s seconds" %
                    (self.cmd, self.timeout))
else:
    TimeoutExpired = subprocess_imported.TimeoutExpired


class Popen(subprocess_orig.Popen):
    if not mswindows:
        def __init__(self, args, bufsize=0, *argss, **kwds):
            self.args = args
            subprocess_orig.Popen.__init__(self, args, 0, *argss, **kwds)
            for attr in "stdin", "stdout", "stderr":
                pipe = getattr(self, attr)
                if pipe is not None and type(pipe) != greenio.GreenPipe:
                    mode = getattr(pipe, 'mode', '')
                    if not mode:
                        if pipe.readable():
                            mode += 'r'
                        if pipe.writable():
                            mode += 'w'
                        if bufsize == 0:
                            bufsize = -1
                    wrapped_pipe = greenio.GreenPipe(pipe, mode, bufsize)
                    setattr(self, attr, wrapped_pipe)
        __init__.__doc__ = subprocess_orig.Popen.__init__.__doc__

    def wait(self, timeout=None, check_interval=0.01):
        if timeout is not None:
            endtime = time.time() + timeout
        try:
            while True:
                status = self.poll()
                if status is not None:
                    return status
                if timeout is not None and time.time() > endtime:
                    raise TimeoutExpired(self.args, timeout)
                eventlet.sleep(check_interval)
        except OSError as e:
            if e.errno == errno.ECHILD:
                return -1
            else:
                raise
    wait.__doc__ = subprocess_orig.Popen.wait.__doc__

    if not mswindows:
        _communicate = FunctionType(
            subprocess_orig.Popen._communicate.__code__,
            globals())
        try:
            _communicate_with_select = FunctionType(
                subprocess_orig.Popen._communicate_with_select.__code__,
                globals())
            _communicate_with_poll = FunctionType(
                subprocess_orig.Popen._communicate_with_poll.__code__,
                globals())
        except AttributeError:
            pass


def patched_function(function):
    new_function = FunctionType(function.__code__, globals())
    new_function.__kwdefaults__ = function.__kwdefaults__
    new_function.__defaults__ = function.__defaults__
    return new_function


call = patched_function(subprocess_orig.call)
check_call = patched_function(subprocess_orig.check_call)
if hasattr(subprocess_orig, 'check_output'):
    __patched__.append('check_output')
    check_output = patched_function(subprocess_orig.check_output)
del patched_function

CalledProcessError = subprocess_imported.CalledProcessError
del subprocess_imported
