import os
import sys
import time
import struct
import socket
import random

from eventlet.green import threading
from eventlet.zipkin._thrift.zipkinCore import ttypes
from eventlet.zipkin._thrift.zipkinCore.constants import SERVER_SEND


client = None
_tls = threading.local()  # thread local storage


def put_annotation(msg, endpoint=None):
    pass


def put_key_value(key, value, endpoint=None):
    pass


def is_tracing():
    pass


def is_sample():
    pass








def _uniq_id():
    pass






class TraceData:

    END_ANNOTATION = SERVER_SEND

    def __init__(self, name, trace_id, span_id, parent_id, sampled, endpoint):
        """
        :param name: RPC name (String)
        :param trace_id: int
        :param span_id: int
        :param parent_id: int or None
        :param sampled: lets the downstream servers know
                    if I should record trace data for the request (bool)
        :param endpoint: zipkin._thrift.zipkinCore.ttypes.EndPoint
        """
        self.name = name
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_id = parent_id
        self.sampled = sampled
        self.endpoint = endpoint
        self.annotations = []
        self.bannotations = []
        self._done = False



    def flush(self):
        span = ZipkinDataBuilder.build_span(name=self.name,
                                            trace_id=self.trace_id,
                                            span_id=self.span_id,
                                            parent_id=self.parent_id,
                                            annotations=self.annotations,
                                            bannotations=self.bannotations)
        client.send_to_collector(span)
        self.annotations = []
        self.bannotations = []
        self._done = True


class ZipkinDataBuilder:
    @staticmethod
    def build_span(name, trace_id, span_id, parent_id,
                   annotations, bannotations):
        return ttypes.Span(
            name=name,
            trace_id=trace_id,
            id=span_id,
            parent_id=parent_id,
            annotations=annotations,
            binary_annotations=bannotations
        )





