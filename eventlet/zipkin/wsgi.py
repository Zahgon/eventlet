import random

from eventlet import wsgi
from eventlet.zipkin import api
from eventlet.zipkin._thrift.zipkinCore.constants import \
    SERVER_RECV, SERVER_SEND
from eventlet.zipkin.http import \
    HDR_TRACE_ID, HDR_SPAN_ID, HDR_PARENT_SPAN_ID, HDR_SAMPLED


_sampler = None
__original_handle_one_response__ = wsgi.HttpProtocol.handle_one_response




class Sampler:
    def __init__(self, sampling_rate):
        self.sampling_rate = sampling_rate









