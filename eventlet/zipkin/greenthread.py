from eventlet import greenthread

from eventlet.zipkin import api


__original_init__ = greenthread.GreenThread.__init__
__original_main__ = greenthread.GreenThread.main








