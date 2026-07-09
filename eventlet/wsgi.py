import errno
import os
import sys
import time
import traceback
import types
import urllib.parse
import warnings

import eventlet
from eventlet import greenio
from eventlet import support
from eventlet.corolocal import local
from eventlet.green import BaseHTTPServer
from eventlet.green import socket


DEFAULT_MAX_SIMULTANEOUS_REQUESTS = 1024
DEFAULT_MAX_HTTP_VERSION = 'HTTP/1.1'
MAX_REQUEST_LINE = 8192
MAX_HEADER_LINE = 8192
MAX_TOTAL_HEADER_SIZE = 65536
MINIMUM_CHUNK_SIZE = 4096
DEFAULT_LOG_FORMAT = ('%(client_ip)s - - [%(date_time)s] "%(request_line)s"'
                      ' %(status_code)s %(body_length)s %(wall_seconds).6f')
RESPONSE_414 = b'''HTTP/1.0 414 Request URI Too Long\r\n\
Connection: close\r\n\
Content-Length: 0\r\n\r\n'''
is_accepting = True

STATE_IDLE = 'idle'
STATE_REQUEST = 'request'
STATE_CLOSE = 'close'

__all__ = ['server', 'format_date_time']

_weekdayname = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_monthname = [None,  # Dummy so we can use 1-based month numbers
              "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def format_date_time(timestamp):
    """Formats a unix timestamp into an HTTP standard string."""
    year, month, day, hh, mm, ss, wd, _y, _z = time.gmtime(timestamp)
    return "%s, %02d %3s %4d %02d:%02d:%02d GMT" % (
        _weekdayname[wd], day, _monthname[month], year, hh, mm, ss
    )


def addr_to_host_port(addr):
    host = 'unix'
    port = ''
    if isinstance(addr, tuple):
        host = addr[0]
        port = addr[1]
    return (host, port)


BAD_SOCK = {errno.EBADF, 10053}
BROKEN_SOCK = {errno.EPIPE, errno.ECONNRESET, errno.ESHUTDOWN}


class ChunkReadError(ValueError):
    pass


WSGI_LOCAL = local()


class Input:

    def __init__(self,
                 rfile,
                 content_length,
                 sock,
                 wfile=None,
                 wfile_line=None,
                 chunked_input=False):

        self.rfile = rfile
        self._sock = sock
        if content_length is not None:
            content_length = int(content_length)
        self.content_length = content_length

        self.wfile = wfile
        self.wfile_line = wfile_line

        self.position = 0
        self.chunked_input = chunked_input
        self.chunk_length = -1

        self.hundred_continue_headers = None
        self.is_hundred_continue_response_sent = False

        self.headers_sent = None

    def send_hundred_continue_response(self):
        if self.headers_sent:
            return

        towrite = []

        towrite.append(self.wfile_line)

        if self.hundred_continue_headers is not None:
            for header in self.hundred_continue_headers:
                towrite.append(('%s: %s\r\n' % header).encode())

        towrite.append(b'\r\n')

        self.wfile.writelines(towrite)
        self.wfile.flush()

        self.chunk_length = -1


    def _do_read(self, reader, length=None):
        if self.should_send_hundred_continue:
            self.send_hundred_continue_response()
            self.is_hundred_continue_response_sent = True
        if length is None or length > self.content_length - self.position:
            length = self.content_length - self.position
        if not length:
            return b''
        try:
            read = reader(length)
        except greenio.SSL.ZeroReturnError:
            read = b''
        self.position += len(read)
        return read

    def _discard_trailers(self, rfile):
        while True:
            line = rfile.readline()
            if not line or line in (b'\r\n', b'\n', b''):
                break

    def _chunked_read(self, rfile, length=None, use_readline=False):
        if self.should_send_hundred_continue:
            self.send_hundred_continue_response()
            self.is_hundred_continue_response_sent = True
        try:
            if length == 0:
                return b""

            if length and length < 0:
                length = None

            if use_readline:
                reader = self.rfile.readline
            else:
                reader = self.rfile.read

            response = []
            while self.chunk_length != 0:
                maxreadlen = self.chunk_length - self.position
                if length is not None and length < maxreadlen:
                    maxreadlen = length

                if maxreadlen > 0:
                    data = reader(maxreadlen)
                    if not data:
                        self.chunk_length = 0
                        raise OSError("unexpected end of file while parsing chunked data")

                    datalen = len(data)
                    response.append(data)

                    self.position += datalen
                    if self.chunk_length == self.position:
                        rfile.readline()

                    if length is not None:
                        length -= datalen
                        if length == 0:
                            break
                    if use_readline and data[-1:] == b"\n":
                        break
                else:
                    try:
                        self.chunk_length = int(rfile.readline().split(b";", 1)[0], 16)
                    except ValueError as err:
                        raise ChunkReadError(err)
                    self.position = 0
                    if self.chunk_length == 0:
                        self._discard_trailers(rfile)
        except greenio.SSL.ZeroReturnError:
            pass
        return b''.join(response)

    def read(self, length=None):
        if self.chunked_input:
            return self._chunked_read(self.rfile, length)
        return self._do_read(self.rfile.read, length)

    def readline(self, size=None):
        if self.chunked_input:
            return self._chunked_read(self.rfile, size, True)
        else:
            return self._do_read(self.rfile.readline, size)

    def readlines(self, hint=None):
        if self.chunked_input:
            lines = []
            for line in iter(self.readline, b''):
                lines.append(line)
                if hint and hint > 0:
                    hint -= len(line)
                    if hint <= 0:
                        break
            return lines
        else:
            return self._do_read(self.rfile.readlines, hint)

    def __iter__(self):
        return iter(self.read, b'')



    def discard(self, buffer_size=16 << 10):
        while self.read(buffer_size):
            pass


class HeaderLineTooLong(Exception):
    pass


class HeadersTooLarge(Exception):
    pass


def get_logger(log, debug):
    if callable(getattr(log, 'info', None)) \
       and callable(getattr(log, 'debug', None)):
        return log
    else:
        return LoggerFileWrapper(log or sys.stderr, debug)


class LoggerNull:
    def __init__(self):
        pass

    def error(self, msg, *args, **kwargs):
        pass

    def info(self, msg, *args, **kwargs):
        pass

    def debug(self, msg, *args, **kwargs):
        pass

    def write(self, msg, *args):
        pass


class LoggerFileWrapper(LoggerNull):
    def __init__(self, log, debug):
        self.log = log
        self._debug = debug

    def error(self, msg, *args, **kwargs):
        self.write(msg, *args)

    def info(self, msg, *args, **kwargs):
        self.write(msg, *args)

    def debug(self, msg, *args, **kwargs):
        if self._debug:
            self.write(msg, *args)

    def write(self, msg, *args):
        msg = msg + '\n'
        if args:
            msg = msg % args
        self.log.write(msg)


class FileObjectForHeaders:

    def __init__(self, fp):
        self.fp = fp
        self.total_header_size = 0

    def readline(self, size=-1):
        sz = size
        if size < 0:
            sz = MAX_HEADER_LINE
        rv = self.fp.readline(sz)
        if len(rv) >= MAX_HEADER_LINE:
            raise HeaderLineTooLong()
        self.total_header_size += len(rv)
        if self.total_header_size > MAX_TOTAL_HEADER_SIZE:
            raise HeadersTooLarge()
        return rv


class HttpProtocol(BaseHTTPServer.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    minimum_chunk_size = MINIMUM_CHUNK_SIZE
    capitalize_response_headers = True
    reject_bad_requests = True

    wbufsize = 16 << 10

    def __init__(self, conn_state, server):
        self.request = conn_state[1]
        self.client_address = conn_state[0]
        self.conn_state = conn_state
        self.server = server
        if server.minimum_chunk_size is not None:
            self.minimum_chunk_size = server.minimum_chunk_size
        self.capitalize_response_headers = server.capitalize_response_headers

        self.setup()
        try:
            self.handle()
        finally:
            self.finish()

    def setup(self):
        conn = self.connection = self.request

        if getattr(socket, 'TCP_QUICKACK', None):
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, True)
            except OSError:
                pass

        try:
            self.rfile = conn.makefile('rb', self.rbufsize)
            self.wfile = conn.makefile('wb', self.wbufsize)
        except (AttributeError, NotImplementedError):
            if hasattr(conn, 'send') and hasattr(conn, 'recv'):
                self.rfile = socket._fileobject(conn, "rb", self.rbufsize)
                self.wfile = socket._fileobject(conn, "wb", self.wbufsize)
            else:
                raise NotImplementedError(
                    '''eventlet.wsgi doesn't support sockets of type {}'''.format(type(conn)))

    def handle(self):
        self.close_connection = True

        while True:
            self.handle_one_request()
            if self.conn_state[2] == STATE_CLOSE:
                self.close_connection = 1
            else:
                self.conn_state[2] = STATE_IDLE
            if self.close_connection:
                break

    def _read_request_line(self):
        if self.rfile.closed:
            self.close_connection = 1
            return ''

        try:
            sock = self.connection
            if self.server.keepalive and not isinstance(self.server.keepalive, bool):
                sock.settimeout(self.server.keepalive)
            line = self.rfile.readline(self.server.url_length_limit)
            sock.settimeout(self.server.socket_timeout)
            return line
        except greenio.SSL.ZeroReturnError:
            pass
        except OSError as e:
            last_errno = support.get_errno(e)
            if last_errno in BROKEN_SOCK:
                self.server.log.debug('({}) connection reset by peer {!r}'.format(
                    self.server.pid,
                    self.client_address))
            elif last_errno not in BAD_SOCK:
                raise
        return ''

    def handle_one_request(self):
        if self.server.max_http_version:
            self.protocol_version = self.server.max_http_version

        self.raw_requestline = self._read_request_line()
        self.conn_state[2] = STATE_REQUEST
        if not self.raw_requestline:
            self.close_connection = 1
            return
        if len(self.raw_requestline) >= self.server.url_length_limit:
            self.wfile.write(RESPONSE_414)
            self.close_connection = 1
            return

        orig_rfile = self.rfile
        try:
            self.rfile = FileObjectForHeaders(self.rfile)
            if not self.parse_request():
                return
        except HeaderLineTooLong:
            self.wfile.write(
                b"HTTP/1.0 400 Header Line Too Long\r\n"
                b"Connection: close\r\nContent-length: 0\r\n\r\n")
            self.close_connection = 1
            return
        except HeadersTooLarge:
            self.wfile.write(
                b"HTTP/1.0 400 Headers Too Large\r\n"
                b"Connection: close\r\nContent-length: 0\r\n\r\n")
            self.close_connection = 1
            return
        finally:
            self.rfile = orig_rfile

        content_length = self.headers.get('content-length')
        transfer_encoding = self.headers.get('transfer-encoding')
        if content_length is not None:
            try:
                if int(content_length) < 0:
                    raise ValueError
            except ValueError:
                self.wfile.write(
                    b"HTTP/1.0 400 Bad Request\r\n"
                    b"Connection: close\r\nContent-length: 0\r\n\r\n")
                self.close_connection = 1
                return

            if transfer_encoding is not None:
                if self.reject_bad_requests:
                    msg = b"Content-Length and Transfer-Encoding are not allowed together\n"
                    self.wfile.write(
                        b"HTTP/1.0 400 Bad Request\r\n"
                        b"Connection: close\r\n"
                        b"Content-Length: %d\r\n"
                        b"\r\n%s" % (len(msg), msg))
                    self.close_connection = 1
                    return

        self.environ = self.get_environ()
        self.application = self.server.app
        try:
            self.server.outstanding_requests += 1
            try:
                self.handle_one_response()
            except OSError as e:
                if support.get_errno(e) not in BROKEN_SOCK:
                    raise
        finally:
            self.server.outstanding_requests -= 1

    def handle_one_response(self):
        start = time.time()
        headers_set = []
        headers_sent = []
        request_input = self.environ['eventlet.input']
        request_input.headers_sent = headers_sent

        wfile = self.wfile
        result = None
        use_chunked = [False]
        length = [0]
        status_code = [200]
        bodyless = [False]

        def write(data):
            towrite = []
            if not headers_set:
                raise AssertionError("write() before start_response()")
            elif not headers_sent:
                status, response_headers = headers_set
                headers_sent.append(1)
                header_list = [header[0].lower() for header in response_headers]
                towrite.append(('%s %s\r\n' % (self.protocol_version, status)).encode())
                for header in response_headers:
                    towrite.append(('%s: %s\r\n' % header).encode('latin-1'))

                if 'date' not in header_list:
                    towrite.append(('Date: %s\r\n' % (format_date_time(time.time()),)).encode())

                client_conn = self.headers.get('Connection', '').lower()
                send_keep_alive = False
                if self.close_connection == 0 and \
                   self.server.keepalive and (client_conn == 'keep-alive' or
                                              (self.request_version == 'HTTP/1.1' and
                                               not client_conn == 'close')):
                    send_keep_alive = (client_conn == 'keep-alive')
                    self.close_connection = 0
                else:
                    self.close_connection = 1

                if 'content-length' not in header_list:
                    if bodyless[0]:
                        pass  # client didn't expect a body anyway
                    elif self.request_version == 'HTTP/1.1':
                        use_chunked[0] = True
                        towrite.append(b'Transfer-Encoding: chunked\r\n')
                    else:
                        self.close_connection = 1

                if self.close_connection:
                    towrite.append(b'Connection: close\r\n')
                elif send_keep_alive:
                    towrite.append(b'Connection: keep-alive\r\n')
                    int_timeout = int(self.server.keepalive or 0)
                    if not isinstance(self.server.keepalive, bool) and int_timeout:
                        towrite.append(b'Keep-Alive: timeout=%d\r\n' % int_timeout)
                towrite.append(b'\r\n')

            if use_chunked[0]:
                # Write the chunked encoding
                towrite.append(("%x" % (len(data),)).encode() + b"\r\n" + data + b"\r\n")
            else:
                towrite.append(data)
            wfile.writelines(towrite)
            wfile.flush()
            length[0] = length[0] + sum(map(len, towrite))

        def start_response(status, response_headers, exc_info=None):
            status_code[0] = int(status.split(" ", 1)[0])
            if exc_info:
                try:
                    if headers_sent:
                        raise exc_info[1].with_traceback(exc_info[2])
                finally:
                    exc_info = None

            bodyless[0] = (
                status_code[0] in (204, 304)
                or self.command == "HEAD"
                or (100 <= status_code[0] < 200)
                or (self.command == "CONNECT" and 200 <= status_code[0] < 300)
            )

            if self.capitalize_response_headers:
                def cap(x):
                    return x.encode('latin1').capitalize().decode('latin1')

                response_headers = [
                    ('-'.join([cap(x) for x in key.split('-')]), value)
                    for key, value in response_headers]

            headers_set[:] = [status, response_headers]
            return write

        try:
            try:
                WSGI_LOCAL.already_handled = False
                result = self.application(self.environ, start_response)

                if headers_set and not headers_sent and hasattr(result, '__len__'):
                    if not bodyless[0] and 'Content-Length' not in [h for h, _v in headers_set[1]]:
                        headers_set[1].append(('Content-Length', str(sum(map(len, result)))))
                    if request_input.should_send_hundred_continue:
                        self.close_connection = 1

                towrite = []
                towrite_size = 0
                just_written_size = 0
                minimum_write_chunk_size = int(self.environ.get(
                    'eventlet.minimum_write_chunk_size', self.minimum_chunk_size))
                for data in result:
                    if len(data) == 0:
                        continue
                    if isinstance(data, str):
                        data = data.encode('ascii')

                    towrite.append(data)
                    towrite_size += len(data)
                    if towrite_size >= minimum_write_chunk_size:
                        write(b''.join(towrite))
                        towrite = []
                        just_written_size = towrite_size
                        towrite_size = 0
                if WSGI_LOCAL.already_handled:
                    self.close_connection = 1
                    return
                if towrite:
                    just_written_size = towrite_size
                    write(b''.join(towrite))
                if not headers_sent or (use_chunked[0] and just_written_size):
                    write(b'')
            except (Exception, eventlet.Timeout):
                self.close_connection = 1
                tb = traceback.format_exc()
                self.server.log.info(tb)
                if not headers_sent:
                    err_body = tb.encode() if self.server.debug else b''
                    start_response("500 Internal Server Error",
                                   [('Content-type', 'text/plain'),
                                    ('Content-length', len(err_body))])
                    write(err_body)
        finally:
            if hasattr(result, 'close'):
                result.close()
            if request_input.should_send_hundred_continue:
                self.close_connection = 1

            if (request_input.chunked_input or
                    request_input.position < (request_input.content_length or 0)):
                if self.close_connection == 0:
                    try:
                        request_input.discard()
                    except ChunkReadError as e:
                        self.close_connection = 1
                        self.server.log.error((
                            'chunked encoding error while discarding request body.'
                            + ' client={0} request="{1}" error="{2}"').format(
                                self.get_client_address()[0], self.requestline, e,
                        ))
                    except OSError as e:
                        self.close_connection = 1
                        self.server.log.error((
                            'I/O error while discarding request body.'
                            + ' client={0} request="{1}" error="{2}"').format(
                                self.get_client_address()[0], self.requestline, e,
                        ))
            finish = time.time()

            for hook, args, kwargs in self.environ['eventlet.posthooks']:
                hook(self.environ, *args, **kwargs)

            if self.server.log_output:
                client_host, client_port = self.get_client_address()

                self.server.log.info(self.server.log_format % {
                    'client_ip': client_host,
                    'client_port': client_port,
                    'date_time': self.log_date_time_string(),
                    'request_line': self.requestline,
                    'status_code': status_code[0],
                    'body_length': length[0],
                    'wall_seconds': finish - start,
                })

    def get_client_address(self):
        host, port = addr_to_host_port(self.client_address)

        if self.server.log_x_forwarded_for:
            forward = self.headers.get('X-Forwarded-For', '').replace(' ', '')
            if forward:
                host = forward + ',' + host
        return (host, port)

    def formalize_key_naming(self, k):
        """
        Headers containing underscores are permitted by RFC9110,
        but evenlet joining headers of different names into
        the same environment variable will dangerously confuse applications as to which is which.
        Cf.
            - Nginx: http://nginx.org/en/docs/http/ngx_http_core_module.html#underscores_in_headers
            - Django: https://www.djangoproject.com/weblog/2015/jan/13/security/
            - Gunicorn: https://github.com/benoitc/gunicorn/commit/72b8970dbf2bf3444eb2e8b12aeff1a3d5922a9a
            - Werkzeug: https://github.com/pallets/werkzeug/commit/5ee439a692dc4474e0311de2496b567eed2d02cf
            - ...
        """
        if "_" in k:
            return

        return k.replace('-', '_').upper()

    def get_environ(self):
        env = self.server.get_environ()
        env['REQUEST_METHOD'] = self.command
        env['SCRIPT_NAME'] = ''

        pq = self.path.split('?', 1)
        env['RAW_PATH_INFO'] = pq[0]
        env['PATH_INFO'] = urllib.parse.unquote(pq[0], encoding='latin1')
        if len(pq) > 1:
            env['QUERY_STRING'] = pq[1]

        ct = self.headers.get('content-type')
        if ct is None:
            try:
                ct = self.headers.type
            except AttributeError:
                ct = self.headers.get_content_type()
        env['CONTENT_TYPE'] = ct

        length = self.headers.get('content-length')
        if length:
            env['CONTENT_LENGTH'] = length
        env['SERVER_PROTOCOL'] = 'HTTP/1.0'

        sockname = self.request.getsockname()
        server_addr = addr_to_host_port(sockname)
        env['SERVER_NAME'] = server_addr[0]
        env['SERVER_PORT'] = str(server_addr[1])
        client_addr = addr_to_host_port(self.client_address)
        env['REMOTE_ADDR'] = client_addr[0]
        env['REMOTE_PORT'] = str(client_addr[1])
        env['GATEWAY_INTERFACE'] = 'CGI/1.1'

        try:
            headers = self.headers.headers
        except AttributeError:
            headers = self.headers._headers
        else:
            headers = [h.split(':', 1) for h in headers]

        env['headers_raw'] = headers_raw = tuple((k, v.strip(' \t\n\r')) for k, v in headers)
        for k, v in headers_raw:
            k = self.formalize_key_naming(k)
            if not k:
                continue

            if k in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
                continue
            envk = 'HTTP_' + k
            if envk in env:
                env[envk] += ',' + v
            else:
                env[envk] = v

        if env.get('HTTP_EXPECT', '').lower() == '100-continue':
            wfile = self.wfile
            wfile_line = b'HTTP/1.1 100 Continue\r\n'
        else:
            wfile = None
            wfile_line = None
        chunked = env.get('HTTP_TRANSFER_ENCODING', '').lower() == 'chunked'
        if not chunked and length is None:
            length = '0'
        env['wsgi.input'] = env['eventlet.input'] = Input(
            self.rfile, length, self.connection, wfile=wfile, wfile_line=wfile_line,
            chunked_input=chunked)
        env['eventlet.posthooks'] = []

        env['eventlet.set_idle'] = set_idle

        return env

    def finish(self):
        try:
            BaseHTTPServer.BaseHTTPRequestHandler.finish(self)
        except OSError as e:
            if support.get_errno(e) not in BROKEN_SOCK:
                raise
        greenio.shutdown_safe(self.connection)
        self.connection.close()

    def handle_expect_100(self):
        return True


class Server(BaseHTTPServer.HTTPServer):

    def __init__(self,
                 socket,
                 address,
                 app,
                 log=None,
                 environ=None,
                 max_http_version=None,
                 protocol=HttpProtocol,
                 minimum_chunk_size=None,
                 log_x_forwarded_for=True,
                 keepalive=True,
                 log_output=True,
                 log_format=DEFAULT_LOG_FORMAT,
                 url_length_limit=MAX_REQUEST_LINE,
                 debug=True,
                 socket_timeout=None,
                 capitalize_response_headers=True):

        self.outstanding_requests = 0
        self.socket = socket
        self.address = address
        self.log = LoggerNull()
        if log_output:
            self.log = get_logger(log, debug)
        self.app = app
        self.keepalive = keepalive
        self.environ = environ
        self.max_http_version = max_http_version
        self.protocol = protocol
        self.pid = os.getpid()
        self.minimum_chunk_size = minimum_chunk_size
        self.log_x_forwarded_for = log_x_forwarded_for
        self.log_output = log_output
        self.log_format = log_format
        self.url_length_limit = url_length_limit
        self.debug = debug
        self.socket_timeout = socket_timeout
        self.capitalize_response_headers = capitalize_response_headers

        if not self.capitalize_response_headers:
            warnings.warn("""capitalize_response_headers is disabled.
 Please, make sure you know what you are doing.
 HTTP headers names are case-insensitive per RFC standard.
 Most likely, you need to fix HTTP parsing in your client software.""",
                          DeprecationWarning, stacklevel=3)

    def get_environ(self):
        d = {
            'wsgi.errors': sys.stderr,
            'wsgi.version': (1, 0),
            'wsgi.multithread': True,
            'wsgi.multiprocess': False,
            'wsgi.run_once': False,
            'wsgi.url_scheme': 'http',
        }
        if hasattr(self.socket, 'do_handshake'):
            d['wsgi.url_scheme'] = 'https'
            d['HTTPS'] = 'on'
        if self.environ is not None:
            d.update(self.environ)
        return d


    def log_message(self, message):
        raise AttributeError('''\
eventlet.wsgi.server.log_message was deprecated and deleted.
Please use server.log.info instead.''')


try:
    import ssl
    ACCEPT_EXCEPTIONS = (socket.error, ssl.SSLError)
    ACCEPT_ERRNO = {errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN,
                    errno.ESHUTDOWN, ssl.SSL_ERROR_EOF, ssl.SSL_ERROR_SSL}
except ImportError:
    ACCEPT_EXCEPTIONS = (socket.error,)
    ACCEPT_ERRNO = {errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN,
                    errno.ESHUTDOWN}




def server(sock, site,
           log=None,
           environ=None,
           max_size=None,
           max_http_version=DEFAULT_MAX_HTTP_VERSION,
           protocol=HttpProtocol,
           server_event=None,
           minimum_chunk_size=None,
           log_x_forwarded_for=True,
           custom_pool=None,
           keepalive=True,
           log_output=True,
           log_format=DEFAULT_LOG_FORMAT,
           url_length_limit=MAX_REQUEST_LINE,
           debug=True,
           socket_timeout=None,
           capitalize_response_headers=True):
    pass
