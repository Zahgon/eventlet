
import email.parser
import email.message
import io
import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from eventlet.green import http, os, socket

__all__ = ["HTTPResponse", "HTTPConnection",
           "HTTPException", "NotConnected", "UnknownProtocol",
           "UnknownTransferEncoding", "UnimplementedFileMode",
           "IncompleteRead", "InvalidURL", "ImproperConnectionState",
           "CannotSendRequest", "CannotSendHeader", "ResponseNotReady",
           "BadStatusLine", "LineTooLong", "RemoteDisconnected", "error",
           "responses"]

HTTP_PORT = 80
HTTPS_PORT = 443

_UNKNOWN = 'UNKNOWN'

_CS_IDLE = 'Idle'
_CS_REQ_STARTED = 'Request-started'
_CS_REQ_SENT = 'Request-sent'


globals().update(http.HTTPStatus.__members__)

responses = {v: v.phrase for v in http.HTTPStatus.__members__.values()}

MAXAMOUNT = 1048576

_MAXLINE = 65536
_MAXHEADERS = 100



_is_legal_header_name = re.compile(rb'[^:\s][^:\r\n]*\Z').match
_is_illegal_header_value = re.compile(rb'\n(?![ \t])|\r(?![ \t\n])').search

_METHODS_EXPECTING_BODY = {'PATCH', 'POST', 'PUT'}


def _encode(data, name='data'):
    pass


class HTTPMessage(email.message.Message):

    def getallmatchingheaders(self, name):
        pass

def parse_headers(fp, _class=HTTPMessage):
    """Parses only RFC2822 headers from a file pointer.

    email Parser wants to see strings rather than bytes.
    But a TextIOWrapper around self.rfile would buffer too many bytes
    from the stream, bytes which we later need to read as bytes.
    So we read the correct bytes here, as bytes, for email Parser
    to parse.

    """
    headers = []
    while True:
        line = fp.readline(_MAXLINE + 1)
        if len(line) > _MAXLINE:
            raise LineTooLong("header line")
        headers.append(line)
        if len(headers) > _MAXHEADERS:
            raise HTTPException("got more than %d headers" % _MAXHEADERS)
        if line in (b'\r\n', b'\n', b''):
            break
    hstring = b''.join(headers).decode('iso-8859-1')
    return email.parser.Parser(_class=_class).parsestr(hstring)


class HTTPResponse(io.BufferedIOBase):



    def __init__(self, sock, debuglevel=0, method=None, url=None):
        self.fp = sock.makefile("rb")
        self.debuglevel = debuglevel
        self._method = method


        self.headers = self.msg = None

        self.version = _UNKNOWN # HTTP-Version
        self.status = _UNKNOWN  # Status-Code
        self.reason = _UNKNOWN  # Reason-Phrase

        self.chunked = _UNKNOWN         # is "chunked" being used?
        self.chunk_left = _UNKNOWN      # bytes left to read in current chunk
        self.length = _UNKNOWN          # number of bytes left in response
        self.will_close = _UNKNOWN      # conn will close at end of response

    def _read_status(self):
        line = str(self.fp.readline(_MAXLINE + 1), "iso-8859-1")
        if len(line) > _MAXLINE:
            raise LineTooLong("status line")
        if self.debuglevel > 0:
            print("reply:", repr(line))
        if not line:
            raise RemoteDisconnected("Remote end closed connection without"
                                     " response")
        try:
            version, status, reason = line.split(None, 2)
        except ValueError:
            try:
                version, status = line.split(None, 1)
                reason = ""
            except ValueError:
                version = ""
        if not version.startswith("HTTP/"):
            self._close_conn()
            raise BadStatusLine(line)

        try:
            status = int(status)
            if status < 100 or status > 999:
                raise BadStatusLine(line)
        except ValueError:
            raise BadStatusLine(line)
        return version, status, reason



    def _close_conn(self):
        fp = self.fp
        self.fp = None
        fp.close()

    def close(self):
        try:
            super().close() # set "closed" flag
        finally:
            if self.fp:
                self._close_conn()



    def flush(self):
        super().flush()
        if self.fp:
            self.fp.flush()

    def readable(self):
        """Always returns True"""
        return True


    def isclosed(self):
        pass

    def read(self, amt=None):
        if self.fp is None:
            return b""

        if self._method == "HEAD":
            self._close_conn()
            return b""

        if amt is not None:
            b = bytearray(amt)
            n = self.readinto(b)
            return memoryview(b)[:n].tobytes()
        else:

            if self.chunked:
                return self._readall_chunked()

            if self.length is None:
                s = self.fp.read()
            else:
                try:
                    s = self._safe_read(self.length)
                except IncompleteRead:
                    self._close_conn()
                    raise
                self.length = 0
            self._close_conn()        # we read everything
            return s

    def readinto(self, b):
        """Read up to len(b) bytes into bytearray b and return the number
        of bytes read.
        """

        if self.fp is None:
            return 0

        if self._method == "HEAD":
            self._close_conn()
            return 0

        if self.chunked:
            return self._readinto_chunked(b)

        if self.length is not None:
            if len(b) > self.length:
                b = memoryview(b)[0:self.length]

        n = self.fp.readinto(b)
        if not n and b:
            self._close_conn()
        elif self.length is not None:
            self.length -= n
            if not self.length:
                self._close_conn()
        return n

    def _read_next_chunk_size(self):
        line = self.fp.readline(_MAXLINE + 1)
        if len(line) > _MAXLINE:
            raise LineTooLong("chunk size")
        i = line.find(b";")
        if i >= 0:
            line = line[:i] # strip chunk-extensions
        try:
            return int(line, 16)
        except ValueError:
            self._close_conn()
            raise

    def _read_and_discard_trailer(self):
        while True:
            line = self.fp.readline(_MAXLINE + 1)
            if len(line) > _MAXLINE:
                raise LineTooLong("trailer line")
            if not line:
                break
            if line in (b'\r\n', b'\n', b''):
                break

    def _get_chunk_left(self):
        chunk_left = self.chunk_left
        if not chunk_left: # Can be 0 or None
            if chunk_left is not None:
                self._safe_read(2)  # toss the CRLF at the end of the chunk
            try:
                chunk_left = self._read_next_chunk_size()
            except ValueError:
                raise IncompleteRead(b'')
            if chunk_left == 0:
                self._read_and_discard_trailer()
                self._close_conn()
                chunk_left = None
            self.chunk_left = chunk_left
        return chunk_left

    def _readall_chunked(self):
        assert self.chunked != _UNKNOWN
        value = []
        try:
            while True:
                chunk_left = self._get_chunk_left()
                if chunk_left is None:
                    break
                value.append(self._safe_read(chunk_left))
                self.chunk_left = 0
            return b''.join(value)
        except IncompleteRead:
            raise IncompleteRead(b''.join(value))

    def _readinto_chunked(self, b):
        assert self.chunked != _UNKNOWN
        total_bytes = 0
        mvb = memoryview(b)
        try:
            while True:
                chunk_left = self._get_chunk_left()
                if chunk_left is None:
                    return total_bytes

                if len(mvb) <= chunk_left:
                    n = self._safe_readinto(mvb)
                    self.chunk_left = chunk_left - n
                    return total_bytes + n

                temp_mvb = mvb[:chunk_left]
                n = self._safe_readinto(temp_mvb)
                mvb = mvb[n:]
                total_bytes += n
                self.chunk_left = 0

        except IncompleteRead:
            raise IncompleteRead(bytes(b[0:total_bytes]))

    def _safe_read(self, amt):
        """Read the number of bytes requested, compensating for partial reads.

        Normally, we have a blocking socket, but a read() can be interrupted
        by a signal (resulting in a partial read).

        Note that we cannot distinguish between EOF and an interrupt when zero
        bytes have been read. IncompleteRead() will be raised in this
        situation.

        This function should be used when <amt> bytes "should" be present for
        reading. If the bytes are truly not available (due to EOF), then the
        IncompleteRead exception can be used to detect the problem.
        """
        s = []
        while amt > 0:
            chunk = self.fp.read(min(amt, MAXAMOUNT))
            if not chunk:
                raise IncompleteRead(b''.join(s), amt)
            s.append(chunk)
            amt -= len(chunk)
        return b"".join(s)

    def _safe_readinto(self, b):
        """Same as _safe_read, but for reading into a buffer."""
        total_bytes = 0
        mvb = memoryview(b)
        while total_bytes < len(b):
            if MAXAMOUNT < len(mvb):
                temp_mvb = mvb[0:MAXAMOUNT]
                n = self.fp.readinto(temp_mvb)
            else:
                n = self.fp.readinto(mvb)
            if not n:
                raise IncompleteRead(bytes(mvb[0:total_bytes]), len(b))
            mvb = mvb[n:]
            total_bytes += n
        return total_bytes

    def read1(self, n=-1):
        pass


    def readline(self, limit=-1):
        if self.fp is None or self._method == "HEAD":
            return b""
        if self.chunked:
            return super().readline(limit)
        if self.length is not None and (limit < 0 or limit > self.length):
            limit = self.length
        result = self.fp.readline(limit)
        if not result and limit:
            self._close_conn()
        elif self.length is not None:
            self.length -= len(result)
        return result



    def fileno(self):
        return self.fp.fileno()

    def getheader(self, name, default=None):
        pass

    def getheaders(self):
        pass


    def __iter__(self):
        return self


    def info(self):
        '''Returns an instance of the class mimetools.Message containing
        meta-information associated with the URL.

        When the method is HTTP, these headers are those returned by
        the server at the head of the retrieved HTML page (including
        Content-Length and Content-Type).

        When the method is FTP, a Content-Length header will be
        present if (as is now usual) the server passed back a file
        length in response to the FTP retrieval request. A
        Content-Type header will be present if the MIME type can be
        guessed.

        When the method is local-file, returned headers will include
        a Date representing the file's last-modified time, a
        Content-Length giving file size, and a Content-Type
        containing a guess at the file's type. See also the
        description of the mimetools module.

        '''
        return self.headers

    def geturl(self):
        pass

    def getcode(self):
        pass

class HTTPConnection:

    _http_vsn = 11
    _http_vsn_str = 'HTTP/1.1'

    response_class = HTTPResponse
    default_port = HTTP_PORT
    auto_open = 1
    debuglevel = 0

    @staticmethod
    def _is_textIO(stream):
        pass

    @staticmethod
    def _get_content_length(body, method):
        pass

    def __init__(self, host, port=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                 source_address=None):
        self.timeout = timeout
        self.source_address = source_address
        self.sock = None
        self._buffer = []
        self.__response = None
        self.__state = _CS_IDLE
        self._method = None
        self._tunnel_host = None
        self._tunnel_port = None
        self._tunnel_headers = {}

        (self.host, self.port) = self._get_hostport(host, port)

        self._create_connection = socket.create_connection

    def set_tunnel(self, host, port=None, headers=None):
        pass

    def _get_hostport(self, host, port):
        if port is None:
            i = host.rfind(':')
            j = host.rfind(']')         # ipv6 addresses have [...]
            if i > j:
                try:
                    port = int(host[i+1:])
                except ValueError:
                    if host[i+1:] == "": # http://foo.com:/ == http://foo.com/
                        port = self.default_port
                    else:
                        raise InvalidURL("nonnumeric port: '%s'" % host[i+1:])
                host = host[:i]
            else:
                port = self.default_port
            if host and host[0] == '[' and host[-1] == ']':
                host = host[1:-1]

        return (host, port)


    def _tunnel(self):
        connect_str = "CONNECT %s:%d HTTP/1.0\r\n" % (self._tunnel_host,
            self._tunnel_port)
        connect_bytes = connect_str.encode("ascii")
        self.send(connect_bytes)
        for header, value in self._tunnel_headers.items():
            header_str = "%s: %s\r\n" % (header, value)
            header_bytes = header_str.encode("latin-1")
            self.send(header_bytes)
        self.send(b'\r\n')

        response = self.response_class(self.sock, method=self._method)
        (version, code, message) = response._read_status()

        if code != http.HTTPStatus.OK:
            self.close()
            raise OSError("Tunnel connection failed: %d %s" % (code,
                                                               message.strip()))
        while True:
            line = response.fp.readline(_MAXLINE + 1)
            if len(line) > _MAXLINE:
                raise LineTooLong("header line")
            if not line:
                break
            if line in (b'\r\n', b'\n', b''):
                break

            if self.debuglevel > 0:
                print('header:', line.decode())

    def connect(self):
        """Connect to the host and port specified in __init__."""
        self.sock = self._create_connection(
            (self.host,self.port), self.timeout, self.source_address)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        if self._tunnel_host:
            self._tunnel()

    def close(self):
        """Close the connection to the HTTP server."""
        self.__state = _CS_IDLE
        try:
            sock = self.sock
            if sock:
                self.sock = None
                sock.close()   # close it manually... there may be other refs
        finally:
            response = self.__response
            if response:
                self.__response = None
                response.close()

    def send(self, data):
        """Send `data' to the server.
        ``data`` can be a string object, a bytes object, an array object, a
        file-like object that supports a .read() method, or an iterable object.
        """

        if self.sock is None:
            if self.auto_open:
                self.connect()
            else:
                raise NotConnected()

        if self.debuglevel > 0:
            print("send:", repr(data))
        blocksize = 8192
        if hasattr(data, "read") :
            if self.debuglevel > 0:
                print("sendIng a read()able")
            encode = False
            try:
                mode = data.mode
            except AttributeError:
                pass
            else:
                if "b" not in mode:
                    encode = True
                    if self.debuglevel > 0:
                        print("encoding file using iso-8859-1")
            while 1:
                datablock = data.read(blocksize)
                if not datablock:
                    break
                if encode:
                    datablock = datablock.encode("iso-8859-1")
                self.sock.sendall(datablock)
            return
        try:
            self.sock.sendall(data)
        except TypeError:
            if isinstance(data, Iterable):
                for d in data:
                    self.sock.sendall(d)
            else:
                raise TypeError("data should be a bytes-like object "
                                "or an iterable, got %r" % type(data))

    def _output(self, s):
        pass


    def _send_output(self, message_body=None, encode_chunked=False):
        pass

    def putrequest(self, method, url, skip_host=0, skip_accept_encoding=0):
        pass

    def putheader(self, header, *values):
        pass

    def endheaders(self, message_body=None, **kwds):
        pass

    def request(self, method, url, body=None, headers={}, **kwds):
        pass



    def getresponse(self):
        pass

try:
    from eventlet.green import ssl
except ImportError:
    pass
else:
    def _create_https_context(http_version):
        context = ssl._create_default_https_context()
        if http_version == 11:
            context.set_alpn_protocols(['http/1.1'])
        if context.post_handshake_auth is not None:
            context.post_handshake_auth = True
        return context

    def _populate_https_context(context, check_hostname):
        if check_hostname is not None:
            context.check_hostname = check_hostname

    class HTTPSConnection(HTTPConnection):

        default_port = HTTPS_PORT


        def __init__(self, host, port=None, key_file=None, cert_file=None,
                     timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                     source_address=None, *, context=None,
                     check_hostname=None):
            super().__init__(host, port, timeout,
                                                  source_address)
            self.key_file = key_file
            self.cert_file = cert_file
            if context is None:
                context = _create_https_context(self._http_vsn)
            _populate_https_context(context, check_hostname)
            if key_file or cert_file:
                context.load_cert_chain(cert_file, key_file)
            self._context = context
            self._check_hostname = check_hostname

        def connect(self):
            "Connect to a host on a given (SSL) port."

            super().connect()

            if self._tunnel_host:
                server_hostname = self._tunnel_host
            else:
                server_hostname = self.host

            self.sock = self._context.wrap_socket(self.sock,
                                                  server_hostname=server_hostname)
            if not self._context.check_hostname and self._check_hostname:
                try:
                    ssl.match_hostname(self.sock.getpeercert(), server_hostname)
                except Exception:
                    self.sock.shutdown(socket.SHUT_RDWR)
                    self.sock.close()
                    raise

    __all__.append("HTTPSConnection")

class HTTPException(Exception):
    pass

class NotConnected(HTTPException):
    pass

class InvalidURL(HTTPException):
    pass

class UnknownProtocol(HTTPException):
    def __init__(self, version):
        self.args = version,
        self.version = version

class UnknownTransferEncoding(HTTPException):
    pass

class UnimplementedFileMode(HTTPException):
    pass

class IncompleteRead(HTTPException):
    def __init__(self, partial, expected=None):
        self.args = partial,
        self.partial = partial
        self.expected = expected
    def __repr__(self):
        if self.expected is not None:
            e = ', %i more expected' % self.expected
        else:
            e = ''
        return '%s(%i bytes read%s)' % (self.__class__.__name__,
                                        len(self.partial), e)
    def __str__(self):
        return repr(self)

class ImproperConnectionState(HTTPException):
    pass

class CannotSendRequest(ImproperConnectionState):
    pass

class CannotSendHeader(ImproperConnectionState):
    pass

class ResponseNotReady(ImproperConnectionState):
    pass

class BadStatusLine(HTTPException):
    def __init__(self, line):
        if not line:
            line = repr(line)
        self.args = line,
        self.line = line

class LineTooLong(HTTPException):
    def __init__(self, line_type):
        HTTPException.__init__(self, "got more than %d bytes when reading %s"
                                     % (_MAXLINE, line_type))

class RemoteDisconnected(ConnectionResetError, BadStatusLine):
    def __init__(self, *pos, **kw):
        BadStatusLine.__init__(self, "")
        ConnectionResetError.__init__(self, *pos, **kw)

error = HTTPException
