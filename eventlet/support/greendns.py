
import re
import struct
import sys

import eventlet
from eventlet import patcher
from eventlet.green import _socket_nodns
from eventlet.green import os
from eventlet.green import time
from eventlet.green import select
from eventlet.green import ssl


def import_patched(module_name):
    modules = {
        'select': select,
        'time': time,
        'os': os,
        'socket': _socket_nodns,
        'ssl': ssl,
    }
    return patcher.import_patched(module_name, **modules)


dns = import_patched('dns')

dns.rdtypes = import_patched('dns.rdtypes')
dns.rdtypes.__all__.extend(['dnskeybase', 'dsbase', 'txtbase'])
for pkg in dns.rdtypes.__all__:
    setattr(dns.rdtypes, pkg, import_patched('dns.rdtypes.' + pkg))
for pkg in dns.rdtypes.IN.__all__:
    setattr(dns.rdtypes.IN, pkg, import_patched('dns.rdtypes.IN.' + pkg))
for pkg in dns.rdtypes.ANY.__all__:
    setattr(dns.rdtypes.ANY, pkg, import_patched('dns.rdtypes.ANY.' + pkg))

for pkg in dns.__all__:
    if pkg == 'rdtypes':
        continue
    setattr(dns, pkg, import_patched('dns.' + pkg))
del import_patched


socket = _socket_nodns

DNS_QUERY_TIMEOUT = 10.0
HOSTS_TTL = 10.0

EAI_EAGAIN_ERROR = socket.gaierror(socket.EAI_AGAIN, 'Lookup timed out')
EAI_NONAME_ERROR = socket.gaierror(socket.EAI_NONAME, 'Name or service not known')
EAI_NODATA_ERROR = EAI_NONAME_ERROR
if (os.environ.get('EVENTLET_DEPRECATED_EAI_NODATA', '').lower() in ('1', 'y', 'yes')
        and hasattr(socket, 'EAI_NODATA')):
    EAI_NODATA_ERROR = socket.gaierror(socket.EAI_NODATA, 'No address associated with hostname')


def _raise_new_error(error_instance):
    raise error_instance.__class__(*error_instance.args)


def is_ipv4_addr(host):
    """Return True if host is a valid IPv4 address"""
    if not isinstance(host, str):
        return False
    try:
        dns.ipv4.inet_aton(host)
    except dns.exception.SyntaxError:
        return False
    else:
        return True


def is_ipv6_addr(host):
    """Return True if host is a valid IPv6 address"""
    if not isinstance(host, str):
        return False
    host = host.split('%', 1)[0]
    try:
        dns.ipv6.inet_aton(host)
    except dns.exception.SyntaxError:
        return False
    else:
        return True


def is_ip_addr(host):
    """Return True if host is a valid IPv4 or IPv6 address"""
    return is_ipv4_addr(host) or is_ipv6_addr(host)


if hasattr(dns.query, '_compute_expiration'):
    pass
else:
    pass


class HostsAnswer(dns.resolver.Answer):

    def __init__(self, qname, rdtype, rdclass, rrset, raise_on_no_answer=True):
        """Create a new answer

        :qname: A dns.name.Name instance of the query name
        :rdtype: The rdatatype of the query
        :rdclass: The rdataclass of the query
        :rrset: The dns.rrset.RRset with the response, must have ttl attribute
        :raise_on_no_answer: Whether to raise dns.resolver.NoAnswer if no
           answer.
        """
        self.response = None
        self.qname = qname
        self.rdtype = rdtype
        self.rdclass = rdclass
        self.canonical_name = qname
        if not rrset and raise_on_no_answer:
            raise dns.resolver.NoAnswer()
        self.rrset = rrset
        self.expiration = (time.time() +
                           rrset.ttl if hasattr(rrset, 'ttl') else 0)


class HostsResolver:

    LINES_RE = re.compile(r"""
        \s*  # Leading space
        ([^\r\n#]*?)  # The actual match, non-greedy so as not to include trailing space
        \s*  # Trailing space
        (?:[#][^\r\n]+)?  # Comments
        (?:$|[\r\n]+)  # EOF or newline
    """, re.VERBOSE)

    def __init__(self, fname=None, interval=HOSTS_TTL):
        self._v4 = {}           # name -> ipv4
        self._v6 = {}           # name -> ipv6
        self._aliases = {}      # name -> canonical_name
        self.interval = interval
        self.fname = fname
        if fname is None:
            if os.name == 'posix':
                self.fname = '/etc/hosts'
            elif os.name == 'nt':
                self.fname = os.path.expandvars(
                    r'%SystemRoot%\system32\drivers\etc\hosts')
        self._last_load = 0
        if self.fname:
            self._load()

    def _readlines(self):
        """Read the contents of the hosts file

        Return list of lines, comment lines and empty lines are
        excluded.

        Note that this performs disk I/O so can be blocking.
        """
        try:
            with open(self.fname, 'rb') as fp:
                fdata = fp.read()
        except OSError:
            return []

        udata = fdata.decode(errors='ignore')

        return filter(None, self.LINES_RE.findall(udata))

    def _load(self):
        """Load hosts file

        This will unconditionally (re)load the data from the hosts
        file.
        """
        lines = self._readlines()
        self._v4.clear()
        self._v6.clear()
        self._aliases.clear()
        for line in lines:
            parts = line.split()
            if len(parts) < 2:
                continue
            ip = parts.pop(0)
            if is_ipv4_addr(ip):
                ipmap = self._v4
            elif is_ipv6_addr(ip):
                if ip.startswith('fe80'):
                    continue
                ipmap = self._v6
            else:
                continue
            cname = parts.pop(0).lower()
            ipmap[cname] = ip
            for alias in parts:
                alias = alias.lower()
                ipmap[alias] = ip
                self._aliases[alias] = cname
        self._last_load = time.time()

    def query(self, qname, rdtype=dns.rdatatype.A, rdclass=dns.rdataclass.IN,
              tcp=False, source=None, raise_on_no_answer=True):
        """Query the hosts file

        The known rdtypes are dns.rdatatype.A, dns.rdatatype.AAAA and
        dns.rdatatype.CNAME.

        The ``rdclass`` parameter must be dns.rdataclass.IN while the
        ``tcp`` and ``source`` parameters are ignored.

        Return a HostAnswer instance or raise a dns.resolver.NoAnswer
        exception.
        """
        now = time.time()
        if self._last_load + self.interval < now:
            self._load()
        rdclass = dns.rdataclass.IN
        if isinstance(qname, str):
            name = qname
            qname = dns.name.from_text(qname)
        elif isinstance(qname, bytes):
            name = qname.decode("ascii")
            qname = dns.name.from_text(qname)
        else:
            name = str(qname)
        name = name.lower()
        rrset = dns.rrset.RRset(qname, rdclass, rdtype)
        rrset.ttl = self._last_load + self.interval - now
        if rdclass == dns.rdataclass.IN and rdtype == dns.rdatatype.A:
            addr = self._v4.get(name)
            if not addr and qname.is_absolute():
                addr = self._v4.get(name[:-1])
            if addr:
                rrset.add(dns.rdtypes.IN.A.A(rdclass, rdtype, addr))
        elif rdclass == dns.rdataclass.IN and rdtype == dns.rdatatype.AAAA:
            addr = self._v6.get(name)
            if not addr and qname.is_absolute():
                addr = self._v6.get(name[:-1])
            if addr:
                rrset.add(dns.rdtypes.IN.AAAA.AAAA(rdclass, rdtype, addr))
        elif rdclass == dns.rdataclass.IN and rdtype == dns.rdatatype.CNAME:
            cname = self._aliases.get(name)
            if not cname and qname.is_absolute():
                cname = self._aliases.get(name[:-1])
            if cname:
                rrset.add(dns.rdtypes.ANY.CNAME.CNAME(
                    rdclass, rdtype, dns.name.from_text(cname)))
        return HostsAnswer(qname, rdtype, rdclass, rrset, raise_on_no_answer)

    def getaliases(self, hostname):
        pass


class ResolverProxy:

    def __init__(self, hosts_resolver=None, filename='/etc/resolv.conf'):
        """Initialise the resolver proxy

        :param hosts_resolver: An instance of HostsResolver to use.

        :param filename: The filename containing the resolver
           configuration.  The default value is correct for both UNIX
           and Windows, on Windows it will result in the configuration
           being read from the Windows registry.
        """
        self._hosts = hosts_resolver
        self._filename = filename
        self._cached_resolver = None

    pass

    pass

    def clear(self):
        self._resolver = dns.resolver.Resolver(filename=self._filename)
        self._resolver.cache = dns.resolver.LRUCache()

    def query(self, qname, rdtype=dns.rdatatype.A, rdclass=dns.rdataclass.IN,
              tcp=False, source=None, raise_on_no_answer=True,
              _hosts_rdtypes=(dns.rdatatype.A, dns.rdatatype.AAAA),
              use_network=True):
        """Query the resolver, using /etc/hosts if enabled.

        Behavior:
        1. if hosts is enabled and contains answer, return it now
        2. query nameservers for qname if use_network is True
        3. if qname did not contain dots, pretend it was top-level domain,
           query "foobar." and append to previous result
        """
        result = [None, None, 0]

        if qname is None:
            qname = '0.0.0.0'
        if isinstance(qname, str) or isinstance(qname, bytes):
            qname = dns.name.from_text(qname, None)

        def step(fun, *args, **kwargs):
            try:
                a = fun(*args, **kwargs)
            except Exception as e:
                result[1] = e
                return False
            if a.rrset is not None and len(a.rrset):
                if result[0] is None:
                    result[0] = a
                else:
                    result[0].rrset.union_update(a.rrset)
                result[2] += len(a.rrset)
            return True

        def end():
            if result[0] is not None:
                if raise_on_no_answer and result[2] == 0:
                    raise dns.resolver.NoAnswer
                return result[0]
            if result[1] is not None:
                if raise_on_no_answer or not isinstance(result[1], dns.resolver.NoAnswer):
                    raise result[1]
            raise dns.resolver.NXDOMAIN(qnames=(qname,))

        if (self._hosts and (rdclass == dns.rdataclass.IN) and (rdtype in _hosts_rdtypes)):
            if step(self._hosts.query, qname, rdtype, raise_on_no_answer=False):
                if (result[0] is not None) or (result[1] is not None) or (not use_network):
                    return end()

        step(self._resolver.query, qname, rdtype, rdclass, tcp, source, raise_on_no_answer=False)

        if len(qname) == 1:
            step(self._resolver.query, qname.concatenate(dns.name.root),
                 rdtype, rdclass, tcp, source, raise_on_no_answer=False)

        return end()

    def getaliases(self, hostname):
        pass


resolver = ResolverProxy(hosts_resolver=HostsResolver())


def resolve(name, family=socket.AF_INET, raises=True, _proxy=None,
            use_network=True):
    """Resolve a name for a given family using the global resolver proxy.

    This method is called by the global getaddrinfo() function. If use_network
    is False, only resolution via hosts file will be performed.

    Return a dns.resolver.Answer instance.  If there is no answer it's
    rrset will be emtpy.
    """
    if family == socket.AF_INET:
        rdtype = dns.rdatatype.A
    elif family == socket.AF_INET6:
        rdtype = dns.rdatatype.AAAA
    else:
        raise socket.gaierror(socket.EAI_FAMILY,
                              'Address family not supported')

    if _proxy is None:
        _proxy = resolver
    try:
        try:
            return _proxy.query(name, rdtype, raise_on_no_answer=raises,
                                use_network=use_network)
        except dns.resolver.NXDOMAIN:
            if not raises:
                return HostsAnswer(dns.name.Name(name),
                                   rdtype, dns.rdataclass.IN, None, False)
            raise
    except dns.exception.Timeout:
        _raise_new_error(EAI_EAGAIN_ERROR)
    except dns.exception.DNSException:
        _raise_new_error(EAI_NODATA_ERROR)


def resolve_cname(host):
    """Return the canonical name of a hostname"""
    try:
        ans = resolver.query(host, dns.rdatatype.CNAME)
    except dns.resolver.NoAnswer:
        return host
    except dns.exception.Timeout:
        _raise_new_error(EAI_EAGAIN_ERROR)
    except dns.exception.DNSException:
        _raise_new_error(EAI_NODATA_ERROR)
    else:
        return str(ans[0].target)


def getaliases(host):
    pass


def _getaddrinfo_lookup(host, family, flags):
    """Resolve a hostname to a list of addresses

    Helper function for getaddrinfo.
    """
    if flags & socket.AI_NUMERICHOST:
        _raise_new_error(EAI_NONAME_ERROR)
    addrs = []
    if family == socket.AF_UNSPEC:
        err = None
        for use_network in [False, True]:
            for qfamily in [socket.AF_INET6, socket.AF_INET]:
                try:
                    answer = resolve(host, qfamily, False, use_network=use_network)
                except socket.gaierror as e:
                    if e.errno not in (socket.EAI_AGAIN, EAI_NONAME_ERROR.errno, EAI_NODATA_ERROR.errno):
                        raise
                    err = e
                else:
                    if answer.rrset:
                        addrs.extend(rr.address for rr in answer.rrset)
            if addrs:
                break
        if err is not None and not addrs:
            raise err
    elif family == socket.AF_INET6 and flags & socket.AI_V4MAPPED:
        answer = resolve(host, socket.AF_INET6, False)
        if answer.rrset:
            addrs = [rr.address for rr in answer.rrset]
        if not addrs or flags & socket.AI_ALL:
            answer = resolve(host, socket.AF_INET, False)
            if answer.rrset:
                addrs = ['::ffff:' + rr.address for rr in answer.rrset]
    else:
        answer = resolve(host, family, False)
        if answer.rrset:
            addrs = [rr.address for rr in answer.rrset]
    return str(answer.qname), addrs


def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """Replacement for Python's socket.getaddrinfo

    This does the A and AAAA lookups asynchronously after which it
    calls the OS' getaddrinfo(3) using the AI_NUMERICHOST flag.  This
    flag ensures getaddrinfo(3) does not use the network itself and
    allows us to respect all the other arguments like the native OS.
    """
    if isinstance(host, str):
        host = host.encode('idna').decode('ascii')
    elif isinstance(host, bytes):
        host = host.decode("ascii")
    if host is not None and not is_ip_addr(host):
        qname, addrs = _getaddrinfo_lookup(host, family, flags)
    else:
        qname = host
        addrs = [host]
    aiflags = (flags | socket.AI_NUMERICHOST) & (0xffff ^ socket.AI_CANONNAME)
    res = []
    err = None
    for addr in addrs:
        try:
            ai = socket.getaddrinfo(addr, port, family,
                                    type, proto, aiflags)
        except OSError as e:
            if flags & socket.AI_ADDRCONFIG:
                err = e
                continue
            raise
        res.extend(ai)
    if not res:
        if err:
            raise err
        raise socket.gaierror(socket.EAI_NONAME, 'No address found')
    if flags & socket.AI_CANONNAME:
        if not is_ip_addr(qname):
            qname = resolve_cname(qname).encode('ascii').decode('idna')
        ai = res[0]
        res[0] = (ai[0], ai[1], ai[2], qname, ai[4])
    return res


def gethostbyname(hostname):
    """Replacement for Python's socket.gethostbyname"""
    if is_ipv4_addr(hostname):
        return hostname
    rrset = resolve(hostname)
    return rrset[0].address


def gethostbyname_ex(hostname):
    pass


def getnameinfo(sockaddr, flags):
    """Replacement for Python's socket.getnameinfo.

    Currently only supports IPv4.
    """
    try:
        host, port = sockaddr
    except (ValueError, TypeError):
        if not isinstance(sockaddr, tuple):
            del sockaddr  # to pass a stdlib test that is
            raise TypeError('getnameinfo() argument 1 must be a tuple')
        else:
            _raise_new_error(EAI_NONAME_ERROR)

    if (flags & socket.NI_NAMEREQD) and (flags & socket.NI_NUMERICHOST):
        _raise_new_error(EAI_NONAME_ERROR)

    if is_ipv4_addr(host):
        try:
            rrset = resolver.query(
                dns.reversename.from_address(host), dns.rdatatype.PTR)
            if len(rrset) > 1:
                raise OSError('sockaddr resolved to multiple addresses')
            host = rrset[0].target.to_text(omit_final_dot=True)
        except dns.exception.Timeout:
            if flags & socket.NI_NAMEREQD:
                _raise_new_error(EAI_EAGAIN_ERROR)
        except dns.exception.DNSException:
            if flags & socket.NI_NAMEREQD:
                _raise_new_error(EAI_NONAME_ERROR)
    else:
        try:
            rrset = resolver.query(host)
            if len(rrset) > 1:
                raise OSError('sockaddr resolved to multiple addresses')
            if flags & socket.NI_NUMERICHOST:
                host = rrset[0].address
        except dns.exception.Timeout:
            _raise_new_error(EAI_EAGAIN_ERROR)
        except dns.exception.DNSException:
            raise socket.gaierror(
                (socket.EAI_NODATA, 'No address associated with hostname'))

        if not (flags & socket.NI_NUMERICSERV):
            proto = (flags & socket.NI_DGRAM) and 'udp' or 'tcp'
            port = socket.getservbyport(port, proto)

    return (host, port)


def _net_read(sock, count, expiration):
    pass


def _net_write(sock, data, expiration):
    pass


try:
    dns.message.from_wire("", raise_on_truncation=True)
except dns.message.ShortHeader:
    _handle_raise_on_truncation = True
except TypeError:
    _handle_raise_on_truncation = False


def udp(q, where, timeout=DNS_QUERY_TIMEOUT, port=53,
        af=None, source=None, source_port=0, ignore_unexpected=False,
        one_rr_per_rrset=False, ignore_trailing=False,
        raise_on_truncation=False, sock=None, ignore_errors=False):
    pass


def tcp(q, where, timeout=DNS_QUERY_TIMEOUT, port=53,
        af=None, source=None, source_port=0,
        one_rr_per_rrset=False, ignore_trailing=False, sock=None):
    pass


def reset():
    resolver.clear()


dns.query.tcp = tcp
dns.query.udp = udp
