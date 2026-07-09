import warnings

from eventlet.green import httplib
from eventlet.zipkin import api


HDR_TRACE_ID = 'X-B3-TraceId'
HDR_SPAN_ID = 'X-B3-SpanId'
HDR_PARENT_SPAN_ID = 'X-B3-ParentSpanId'
HDR_SAMPLED = 'X-B3-Sampled'




def unpatch():
    pass


def hex_str(n):
    pass
