
__all__ = ['Cookie', 'CookieJar', 'CookiePolicy', 'DefaultCookiePolicy',
           'FileCookieJar', 'LWPCookieJar', 'LoadError', 'MozillaCookieJar']

import copy
import datetime
import re
import time
import urllib.parse
from calendar import timegm

from eventlet.green import threading as _threading, time
from eventlet.green.http import client as http_client  # only for the default HTTP port

debug = False   # set to True to enable debugging via the logging module
logger = None



DEFAULT_HTTP_PORT = str(http_client.HTTP_PORT)
MISSING_FILENAME_TEXT = ("a filename was not supplied (nor was the CookieJar "
                         "instance initialised with one)")

def _warn_unhandled_exception():
    import io, warnings, traceback
    f = io.StringIO()
    traceback.print_exc(None, f)
    msg = f.getvalue()
    warnings.warn("http.cookiejar bug!\n%s" % msg, stacklevel=2)



EPOCH_YEAR = 1970
def _timegm(tt):
    year, month, mday, hour, min, sec = tt[:6]
    if ((year >= EPOCH_YEAR) and (1 <= month <= 12) and (1 <= mday <= 31) and
        (0 <= hour <= 24) and (0 <= min <= 59) and (0 <= sec <= 61)):
        return timegm(tt)
    else:
        return None

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_LOWER = []
for month in MONTHS: MONTHS_LOWER.append(month.lower())

def time2isoz(t=None):
    """Return a string representing time in seconds since epoch, t.

    If the function is called without an argument, it will use the current
    time.

    The format of the returned string is like "YYYY-MM-DD hh:mm:ssZ",
    representing Universal Time (UTC, aka GMT).  An example of this format is:

    1994-11-24 08:49:37Z

    """
    if t is None:
        dt = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    else:
        dt = datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc
            ).replace(tzinfo=None)
    return "%04d-%02d-%02d %02d:%02d:%02dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)

def time2netscape(t=None):
    pass


UTC_ZONES = {"GMT": None, "UTC": None, "UT": None, "Z": None}

TIMEZONE_RE = re.compile(r"^([-+])?(\d\d?):?(\d\d)?$", re.ASCII)
def offset_from_tz_string(tz):
    offset = None
    if tz in UTC_ZONES:
        offset = 0
    else:
        m = TIMEZONE_RE.search(tz)
        if m:
            offset = 3600 * int(m.group(2))
            if m.group(3):
                offset = offset + 60 * int(m.group(3))
            if m.group(1) == '-':
                offset = -offset
    return offset

def _str2time(day, mon, yr, hr, min, sec, tz):
    yr = int(yr)
    if yr > datetime.MAXYEAR:
        return None

    try:
        mon = MONTHS_LOWER.index(mon.lower())+1
    except ValueError:
        try:
            imon = int(mon)
        except ValueError:
            return None
        if 1 <= imon <= 12:
            mon = imon
        else:
            return None

    if hr is None: hr = 0
    if min is None: min = 0
    if sec is None: sec = 0

    day = int(day)
    hr = int(hr)
    min = int(min)
    sec = int(sec)

    if yr < 1000:
        cur_yr = time.localtime(time.time())[0]
        m = cur_yr % 100
        tmp = yr
        yr = yr + cur_yr - m
        m = m - tmp
        if abs(m) > 50:
            if m > 0: yr = yr + 100
            else: yr = yr - 100

    t = _timegm((yr, mon, day, hr, min, sec, tz))

    if t is not None:
        if tz is None:
            tz = "UTC"
        tz = tz.upper()
        offset = offset_from_tz_string(tz)
        if offset is None:
            return None
        t = t - offset

    return t

STRICT_DATE_RE = re.compile(
    r"^[SMTWF][a-z][a-z], (\d\d) ([JFMASOND][a-z][a-z]) "
    r"(\d\d\d\d) (\d\d):(\d\d):(\d\d) GMT$", re.ASCII)
WEEKDAY_RE = re.compile(
    r"^(?:Sun|Mon|Tue|Wed|Thu|Fri|Sat)[a-z]*,?\s*", re.I | re.ASCII)
LOOSE_HTTP_DATE_RE = re.compile(
    r"""^
    (\d\d?)            # day
       (?:\s+|[-\/])
    (\w+)              # month
        (?:\s+|[-\/])
    (\d+)              # year
    (?:
          (?:\s+|:)    # separator before clock
       (\d\d?):(\d\d)  # hour:min
       (?::(\d\d))?    # optional seconds
    )?                 # optional clock
       \s*
    ([-+]?\d{2,4}|(?![APap][Mm]\b)[A-Za-z]+)? # timezone
       \s*
    (?:\(\w+\))?       # ASCII representation of timezone in parens.
       \s*$""", re.X | re.ASCII)
def http2time(text):
    pass

ISO_DATE_RE = re.compile(
    r"""^
    (\d{4})              # year
       [-\/]?
    (\d\d?)              # numerical month
       [-\/]?
    (\d\d?)              # day
   (?:
         (?:\s+|[-:Tt])  # separator before clock
      (\d\d?):?(\d\d)    # hour:min
      (?::?(\d\d(?:\.\d*)?))?  # optional seconds (and fractional)
   )?                    # optional clock
      \s*
   ([-+]?\d\d?:?(:?\d\d)?
    |Z|z)?               # timezone  (Z is "zero meridian", i.e. GMT)
      \s*$""", re.X | re. ASCII)
def iso2time(text):
    """
    As for http2time, but parses the ISO 8601 formats:

    1994-02-03 14:15:29 -0100    -- ISO 8601 format
    1994-02-03 14:15:29          -- zone is optional
    1994-02-03                   -- only date
    1994-02-03T14:15:29          -- Use T as separator
    19940203T141529Z             -- ISO 8601 compact format
    19940203                     -- only date

    """
    text = text.lstrip()

    day, mon, yr, hr, min, sec, tz = [None]*7

    m = ISO_DATE_RE.search(text)
    if m is not None:
        yr, mon, day, hr, min, sec, tz, _ = m.groups()
    else:
        return None  # bad format

    return _str2time(day, mon, yr, hr, min, sec, tz)



def unmatched(match):
    """Return unmatched part of re.Match object."""
    start, end = match.span(0)
    return match.string[:start]+match.string[end:]

HEADER_TOKEN_RE =        re.compile(r"^\s*([^=\s;,]+)")
HEADER_QUOTED_VALUE_RE = re.compile(r"^\s*=\s*\"([^\"\\]*(?:\\.[^\"\\]*)*)\"")
HEADER_VALUE_RE =        re.compile(r"^\s*=\s*([^\s;,]*)")
HEADER_ESCAPE_RE = re.compile(r"\\(.)")
def split_header_words(header_values):
    r"""Parse header values into a list of lists containing key,value pairs.

    The function knows how to deal with ",", ";" and "=" as well as quoted
    values after "=".  A list of space separated tokens are parsed as if they
    were separated by ";".

    If the header_values passed as argument contains multiple values, then they
    are treated as if they were a single value separated by comma ",".

    This means that this function is useful for parsing header fields that
    follow this syntax (BNF as from the HTTP/1.1 specification, but we relax
    the requirement for tokens).

      headers           = #header
      header            = (token | parameter) *( [";"] (token | parameter))

      token             = 1*<any CHAR except CTLs or separators>
      separators        = "(" | ")" | "<" | ">" | "@"
                        | "," | ";" | ":" | "\" | <">
                        | "/" | "[" | "]" | "?" | "="
                        | "{" | "}" | SP | HT

      quoted-string     = ( <"> *(qdtext | quoted-pair ) <"> )
      qdtext            = <any TEXT except <">>
      quoted-pair       = "\" CHAR

      parameter         = attribute "=" value
      attribute         = token
      value             = token | quoted-string

    Each header is represented by a list of key/value pairs.  The value for a
    simple token (not part of a parameter) is None.  Syntactically incorrect
    headers will not necessarily be parsed as you would want.

    This is easier to describe with some examples:

    >>> split_header_words(['foo="bar"; port="80,81"; discard, bar=baz'])
    [[('foo', 'bar'), ('port', '80,81'), ('discard', None)], [('bar', 'baz')]]
    >>> split_header_words(['text/html; charset="iso-8859-1"'])
    [[('text/html', None), ('charset', 'iso-8859-1')]]
    >>> split_header_words([r'Basic realm="\"foo\bar\""'])
    [[('Basic', None), ('realm', '"foobar"')]]

    """
    assert not isinstance(header_values, str)
    result = []
    for text in header_values:
        orig_text = text
        pairs = []
        while text:
            m = HEADER_TOKEN_RE.search(text)
            if m:
                text = unmatched(m)
                name = m.group(1)
                m = HEADER_QUOTED_VALUE_RE.search(text)
                if m:  # quoted value
                    text = unmatched(m)
                    value = m.group(1)
                    value = HEADER_ESCAPE_RE.sub(r"\1", value)
                else:
                    m = HEADER_VALUE_RE.search(text)
                    if m:  # unquoted value
                        text = unmatched(m)
                        value = m.group(1)
                        value = value.rstrip()
                    else:
                        value = None
                pairs.append((name, value))
            elif text.lstrip().startswith(","):
                text = text.lstrip()[1:]
                if pairs: result.append(pairs)
                pairs = []
            else:
                non_junk, nr_junk_chars = re.subn(r"^[=\s;]*", "", text)
                assert nr_junk_chars > 0, (
                    "split_header_words bug: '%s', '%s', %s" %
                    (orig_text, text, pairs))
                text = non_junk
        if pairs: result.append(pairs)
    return result

HEADER_JOIN_ESCAPE_RE = re.compile(r"([\"\\])")
def join_header_words(lists):
    """Do the inverse (almost) of the conversion done by split_header_words.

    Takes a list of lists of (key, value) pairs and produces a single header
    value.  Attribute values are quoted if needed.

    >>> join_header_words([[("text/plain", None), ("charset", "iso-8859-1")]])
    'text/plain; charset="iso-8859-1"'
    >>> join_header_words([[("text/plain", None)], [("charset", "iso-8859-1")]])
    'text/plain, charset="iso-8859-1"'

    """
    headers = []
    for pairs in lists:
        attr = []
        for k, v in pairs:
            if v is not None:
                if not re.search(r"^\w+$", v):
                    v = HEADER_JOIN_ESCAPE_RE.sub(r"\\\1", v)  # escape " and \
                    v = '"%s"' % v
                k = "%s=%s" % (k, v)
            attr.append(k)
        if attr: headers.append("; ".join(attr))
    return ", ".join(headers)


def parse_ns_headers(ns_headers):
    pass


IPV4_RE = re.compile(r"\.\d+$", re.ASCII)
def is_HDN(text):
    pass

def domain_match(A, B):
    pass

def liberal_is_HDN(text):
    pass

def user_domain_match(A, B):
    pass

cut_port_re = re.compile(r":\d+$", re.ASCII)
def request_host(request):
    pass

def eff_request_host(request):
    pass

def request_path(request):
    pass


HTTP_PATH_SAFE = "%/;:@&=+$,!~*'()"
ESCAPED_CHAR_RE = re.compile(r"%([0-9a-fA-F][0-9a-fA-F])")
def escape_path(path):
    pass

def reach(h):
    pass

def is_third_party(request):
    pass


class Cookie:

    def __init__(self, version, name, value,
                 port, port_specified,
                 domain, domain_specified, domain_initial_dot,
                 path, path_specified,
                 secure,
                 expires,
                 discard,
                 comment,
                 comment_url,
                 rest,
                 rfc2109=False,
                 ):

        if version is not None: version = int(version)
        if expires is not None: expires = int(float(expires))
        if port is None and port_specified is True:
            raise ValueError("if port is None, port_specified must be false")

        self.version = version
        self.name = name
        self.value = value
        self.port = port
        self.port_specified = port_specified
        self.domain = domain.lower()
        self.domain_specified = domain_specified
        self.domain_initial_dot = domain_initial_dot
        self.path = path
        self.path_specified = path_specified
        self.secure = secure
        self.expires = expires
        self.discard = discard
        self.comment = comment
        self.comment_url = comment_url
        self.rfc2109 = rfc2109

        self._rest = copy.copy(rest)


    def is_expired(self, now=None):
        if now is None: now = time.time()
        if (self.expires is not None) and (self.expires <= now):
            return True
        return False

    def __str__(self):
        if self.port is None: p = ""
        else: p = ":"+self.port
        limit = self.domain + p + self.path
        if self.value is not None:
            namevalue = "%s=%s" % (self.name, self.value)
        else:
            namevalue = self.name
        return "<Cookie %s for %s>" % (namevalue, limit)

    def __repr__(self):
        args = []
        for name in ("version", "name", "value",
                     "port", "port_specified",
                     "domain", "domain_specified", "domain_initial_dot",
                     "path", "path_specified",
                     "secure", "expires", "discard", "comment", "comment_url",
                     ):
            attr = getattr(self, name)
            args.append("%s=%s" % (name, repr(attr)))
        args.append("rest=%s" % repr(self._rest))
        args.append("rfc2109=%s" % repr(self.rfc2109))
        return "%s(%s)" % (self.__class__.__name__, ", ".join(args))


class CookiePolicy:
    def set_ok(self, cookie, request):
        """Return true if (and only if) cookie should be accepted from server.

        Currently, pre-expired cookies never get this far -- the CookieJar
        class deletes such cookies itself.

        """
        raise NotImplementedError()

    def return_ok(self, cookie, request):
        """Return true if (and only if) cookie should be returned to server."""
        raise NotImplementedError()

    def domain_return_ok(self, domain, request):
        pass

    def path_return_ok(self, path, request):
        pass


class DefaultCookiePolicy(CookiePolicy):

    DomainStrictNoDots = 1
    DomainStrictNonDomain = 2
    DomainRFC2965Match = 4

    DomainLiberal = 0
    DomainStrict = DomainStrictNoDots|DomainStrictNonDomain

    def __init__(self,
                 blocked_domains=None, allowed_domains=None,
                 netscape=True, rfc2965=False,
                 rfc2109_as_netscape=None,
                 hide_cookie2=False,
                 strict_domain=False,
                 strict_rfc2965_unverifiable=True,
                 strict_ns_unverifiable=False,
                 strict_ns_domain=DomainLiberal,
                 strict_ns_set_initial_dollar=False,
                 strict_ns_set_path=False,
                 ):
        """Constructor arguments should be passed as keyword arguments only."""
        self.netscape = netscape
        self.rfc2965 = rfc2965
        self.rfc2109_as_netscape = rfc2109_as_netscape
        self.hide_cookie2 = hide_cookie2
        self.strict_domain = strict_domain
        self.strict_rfc2965_unverifiable = strict_rfc2965_unverifiable
        self.strict_ns_unverifiable = strict_ns_unverifiable
        self.strict_ns_domain = strict_ns_domain
        self.strict_ns_set_initial_dollar = strict_ns_set_initial_dollar
        self.strict_ns_set_path = strict_ns_set_path

        if blocked_domains is not None:
            self._blocked_domains = tuple(blocked_domains)
        else:
            self._blocked_domains = ()

        if allowed_domains is not None:
            allowed_domains = tuple(allowed_domains)
        self._allowed_domains = allowed_domains

    def blocked_domains(self):
        pass
    def set_blocked_domains(self, blocked_domains):
        pass


    def allowed_domains(self):
        pass
    def set_allowed_domains(self, allowed_domains):
        pass


    def set_ok(self, cookie, request):
        pass







    def return_ok(self, cookie, request):
        pass











def deepvalues(mapping):
    pass


class Absent: pass

class CookieJar:

    non_word_re = re.compile(r"\W")
    quote_re = re.compile(r"([\"\\])")
    strict_domain_re = re.compile(r"\.?[^.]*")
    domain_re = re.compile(r"[^.]*")
    dots_re = re.compile(r"^\.+")

    magic_re = re.compile(r"^\#LWP-Cookies-(\d+\.\d+)", re.ASCII)

    def __init__(self, policy=None):
        if policy is None:
            policy = DefaultCookiePolicy()
        self._policy = policy

        self._cookies_lock = _threading.RLock()
        self._cookies = {}



    def _cookies_for_request(self, request):
        pass

    def _cookie_attrs(self, cookies):
        pass

    def add_cookie_header(self, request):
        pass

    def _normalized_cookie_tuples(self, attrs_set):
        pass




    def make_cookies(self, response, request):
        pass

    def set_cookie_if_ok(self, cookie, request):
        pass

    def set_cookie(self, cookie):
        """Set a cookie, without checking whether or not it should be set."""
        c = self._cookies
        self._cookies_lock.acquire()
        try:
            if cookie.domain not in c: c[cookie.domain] = {}
            c2 = c[cookie.domain]
            if cookie.path not in c2: c2[cookie.path] = {}
            c3 = c2[cookie.path]
            c3[cookie.name] = cookie
        finally:
            self._cookies_lock.release()

    def extract_cookies(self, response, request):
        pass

    def clear(self, domain=None, path=None, name=None):
        """Clear some cookies.

        Invoking this method without arguments will clear all cookies.  If
        given a single argument, only cookies belonging to that domain will be
        removed.  If given two arguments, cookies belonging to the specified
        path within that domain are removed.  If given three arguments, then
        the cookie with the specified name, path and domain is removed.

        Raises KeyError if no matching cookie exists.

        """
        if name is not None:
            if (domain is None) or (path is None):
                raise ValueError(
                    "domain and path must be given to remove a cookie by name")
            del self._cookies[domain][path][name]
        elif path is not None:
            if domain is None:
                raise ValueError(
                    "domain must be given to remove cookies by path")
            del self._cookies[domain][path]
        elif domain is not None:
            del self._cookies[domain]
        else:
            self._cookies = {}

    def clear_session_cookies(self):
        pass

    def clear_expired_cookies(self):
        pass

    def __iter__(self):
        return deepvalues(self._cookies)

    def __len__(self):
        """Return number of contained cookies."""
        i = 0
        for cookie in self: i = i + 1
        return i

    def __repr__(self):
        r = []
        for cookie in self: r.append(repr(cookie))
        return "<%s[%s]>" % (self.__class__.__name__, ", ".join(r))

    def __str__(self):
        r = []
        for cookie in self: r.append(str(cookie))
        return "<%s[%s]>" % (self.__class__.__name__, ", ".join(r))


class LoadError(OSError): pass

class FileCookieJar(CookieJar):

    def __init__(self, filename=None, delayload=False, policy=None):
        """
        Cookies are NOT loaded from the named file until either the .load() or
        .revert() method is called.

        """
        CookieJar.__init__(self, policy)
        if filename is not None:
            try:
                filename+""
            except:
                raise ValueError("filename must be string-like")
        self.filename = filename
        self.delayload = bool(delayload)

    def save(self, filename=None, ignore_discard=False, ignore_expires=False):
        """Save cookies to a file."""
        raise NotImplementedError()

    def load(self, filename=None, ignore_discard=False, ignore_expires=False):
        """Load cookies from a file."""
        if filename is None:
            if self.filename is not None: filename = self.filename
            else: raise ValueError(MISSING_FILENAME_TEXT)

        with open(filename) as f:
            self._really_load(f, filename, ignore_discard, ignore_expires)

    def revert(self, filename=None,
               ignore_discard=False, ignore_expires=False):
        pass


def lwp_cookie_str(cookie):
    """Return string representation of Cookie in the LWP cookie file format.

    Actually, the format is extended a bit -- see module docstring.

    """
    h = [(cookie.name, cookie.value),
         ("path", cookie.path),
         ("domain", cookie.domain)]
    if cookie.port is not None: h.append(("port", cookie.port))
    if cookie.path_specified: h.append(("path_spec", None))
    if cookie.port_specified: h.append(("port_spec", None))
    if cookie.domain_initial_dot: h.append(("domain_dot", None))
    if cookie.secure: h.append(("secure", None))
    if cookie.expires: h.append(("expires",
                               time2isoz(float(cookie.expires))))
    if cookie.discard: h.append(("discard", None))
    if cookie.comment: h.append(("comment", cookie.comment))
    if cookie.comment_url: h.append(("commenturl", cookie.comment_url))

    keys = sorted(cookie._rest.keys())
    for k in keys:
        h.append((k, str(cookie._rest[k])))

    h.append(("version", str(cookie.version)))

    return join_header_words([h])

class LWPCookieJar(FileCookieJar):

    def as_lwp_str(self, ignore_discard=True, ignore_expires=True):
        """Return cookies as a string of "\\n"-separated "Set-Cookie3" headers.

        ignore_discard and ignore_expires: see docstring for FileCookieJar.save

        """
        now = time.time()
        r = []
        for cookie in self:
            if not ignore_discard and cookie.discard:
                continue
            if not ignore_expires and cookie.is_expired(now):
                continue
            r.append("Set-Cookie3: %s" % lwp_cookie_str(cookie))
        return "\n".join(r+[""])

    def save(self, filename=None, ignore_discard=False, ignore_expires=False):
        if filename is None:
            if self.filename is not None: filename = self.filename
            else: raise ValueError(MISSING_FILENAME_TEXT)

        with open(filename, "w") as f:
            f.write("#LWP-Cookies-2.0\n")
            f.write(self.as_lwp_str(ignore_discard, ignore_expires))

    def _really_load(self, f, filename, ignore_discard, ignore_expires):
        magic = f.readline()
        if not self.magic_re.search(magic):
            msg = ("%r does not look like a Set-Cookie3 (LWP) format "
                   "file" % filename)
            raise LoadError(msg)

        now = time.time()

        header = "Set-Cookie3:"
        boolean_attrs = ("port_spec", "path_spec", "domain_dot",
                         "secure", "discard")
        value_attrs = ("version",
                       "port", "path", "domain",
                       "expires",
                       "comment", "commenturl")

        try:
            while 1:
                line = f.readline()
                if line == "": break
                if not line.startswith(header):
                    continue
                line = line[len(header):].strip()

                for data in split_header_words([line]):
                    name, value = data[0]
                    standard = {}
                    rest = {}
                    for k in boolean_attrs:
                        standard[k] = False
                    for k, v in data[1:]:
                        if k is not None:
                            lc = k.lower()
                        else:
                            lc = None
                        if (lc in value_attrs) or (lc in boolean_attrs):
                            k = lc
                        if k in boolean_attrs:
                            if v is None: v = True
                            standard[k] = v
                        elif k in value_attrs:
                            standard[k] = v
                        else:
                            rest[k] = v

                    h = standard.get
                    expires = h("expires")
                    discard = h("discard")
                    if expires is not None:
                        expires = iso2time(expires)
                    if expires is None:
                        discard = True
                    domain = h("domain")
                    domain_specified = domain.startswith(".")
                    c = Cookie(h("version"), name, value,
                               h("port"), h("port_spec"),
                               domain, domain_specified, h("domain_dot"),
                               h("path"), h("path_spec"),
                               h("secure"),
                               expires,
                               discard,
                               h("comment"),
                               h("commenturl"),
                               rest)
                    if not ignore_discard and c.discard:
                        continue
                    if not ignore_expires and c.is_expired(now):
                        continue
                    self.set_cookie(c)
        except OSError:
            raise
        except Exception:
            _warn_unhandled_exception()
            raise LoadError("invalid Set-Cookie3 format file %r: %r" %
                            (filename, line))


class MozillaCookieJar(FileCookieJar):
    magic_re = re.compile("#( Netscape)? HTTP Cookie File")
    header = """\
# Netscape HTTP Cookie File
# http://curl.haxx.se/rfc/cookie_spec.html
# This is a generated file!  Do not edit.

"""

    def _really_load(self, f, filename, ignore_discard, ignore_expires):
        now = time.time()

        magic = f.readline()
        if not self.magic_re.search(magic):
            raise LoadError(
                "%r does not look like a Netscape format cookies file" %
                filename)

        try:
            while 1:
                line = f.readline()
                if line == "": break

                if line.endswith("\n"): line = line[:-1]

                if (line.strip().startswith(("#", "$")) or
                    line.strip() == ""):
                    continue

                domain, domain_specified, path, secure, expires, name, value = \
                        line.split("\t")
                secure = (secure == "TRUE")
                domain_specified = (domain_specified == "TRUE")
                if name == "":
                    name = value
                    value = None

                initial_dot = domain.startswith(".")
                assert domain_specified == initial_dot

                discard = False
                if expires == "":
                    expires = None
                    discard = True

                c = Cookie(0, name, value,
                           None, False,
                           domain, domain_specified, initial_dot,
                           path, False,
                           secure,
                           expires,
                           discard,
                           None,
                           None,
                           {})
                if not ignore_discard and c.discard:
                    continue
                if not ignore_expires and c.is_expired(now):
                    continue
                self.set_cookie(c)

        except OSError:
            raise
        except Exception:
            _warn_unhandled_exception()
            raise LoadError("invalid Netscape format cookies file %r: %r" %
                            (filename, line))

    def save(self, filename=None, ignore_discard=False, ignore_expires=False):
        if filename is None:
            if self.filename is not None: filename = self.filename
            else: raise ValueError(MISSING_FILENAME_TEXT)

        with open(filename, "w") as f:
            f.write(self.header)
            now = time.time()
            for cookie in self:
                if not ignore_discard and cookie.discard:
                    continue
                if not ignore_expires and cookie.is_expired(now):
                    continue
                if cookie.secure: secure = "TRUE"
                else: secure = "FALSE"
                if cookie.domain.startswith("."): initial_dot = "TRUE"
                else: initial_dot = "FALSE"
                if cookie.expires is not None:
                    expires = str(cookie.expires)
                else:
                    expires = ""
                if cookie.value is None:
                    name = ""
                    value = cookie.name
                else:
                    name = cookie.name
                    value = cookie.value
                f.write(
                    "\t".join([cookie.domain, initial_dot, cookie.path,
                               secure, expires, name, value])+
                    "\n")
