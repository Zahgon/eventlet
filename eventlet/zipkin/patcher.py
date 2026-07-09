from eventlet.zipkin import http
from eventlet.zipkin import wsgi
from eventlet.zipkin import greenthread
from eventlet.zipkin import log
from eventlet.zipkin import api
from eventlet.zipkin.client import ZipkinClient


def enable_trace_patch(host='127.0.0.1', port=9410,
                       trace_app_log=False, sampling_rate=1.0):
    pass


