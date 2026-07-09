

import re
import string

__all__ = ["CookieError", "BaseCookie", "SimpleCookie"]

_nulljoin = ''.join
_semispacejoin = '; '.join
_spacejoin = ' '.join


class CookieError(Exception):
    pass


_LegalChars = string.ascii_letters + string.digits + "!#$%&'*+-.^_`|~:"
_UnescapedChars = _LegalChars + ' ()/<=>?@[]{}'

_Translator = {n: '\\%03o' % n
               for n in set(range(256)) - set(map(ord, _UnescapedChars))}
_Translator.update({
    ord('"'): '\\"',
    ord('\\'): '\\\\',
})

_is_legal_key = re.compile(r'[%s]+\Z' % re.escape(_LegalChars)).match

def _quote(str):
    r"""Quote a string for use in a cookie header.

    If the string does not need to be double-quoted, then just return the
    string.  Otherwise, surround the string in doublequotes and quote
    (with a \) special characters.
    """
    if str is None or _is_legal_key(str):
        return str
    else:
        return '"' + str.translate(_Translator) + '"'


_OctalPatt = re.compile(r"\\[0-3][0-7][0-7]")
_QuotePatt = re.compile(r"[\\].")

def _unquote(str):
    if str is None or len(str) < 2:
        return str
    if str[0] != '"' or str[-1] != '"':
        return str


    str = str[1:-1]

    i = 0
    n = len(str)
    res = []
    while 0 <= i < n:
        o_match = _OctalPatt.search(str, i)
        q_match = _QuotePatt.search(str, i)
        if not o_match and not q_match:              # Neither matched
            res.append(str[i:])
            break
        j = k = -1
        if o_match:
            j = o_match.start(0)
        if q_match:
            k = q_match.start(0)
        if q_match and (not o_match or k < j):     # QuotePatt matched
            res.append(str[i:k])
            res.append(str[k+1])
            i = k + 2
        else:                                      # OctalPatt matched
            res.append(str[i:j])
            res.append(chr(int(str[j+1:j+4], 8)))
            i = j + 4
    return _nulljoin(res)


_weekdayname = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

_monthname = [None,
              'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']



class Morsel(dict):
    _reserved = {
        "expires"  : "expires",
        "path"     : "Path",
        "comment"  : "Comment",
        "domain"   : "Domain",
        "max-age"  : "Max-Age",
        "secure"   : "Secure",
        "httponly" : "HttpOnly",
        "version"  : "Version",
    }

    _flags = {'secure', 'httponly'}

    def __init__(self):
        self._key = self._value = self._coded_value = None

        for key in self._reserved:
            dict.__setitem__(self, key, "")







    def __setitem__(self, K, V):
        K = K.lower()
        if not K in self._reserved:
            raise CookieError("Invalid attribute %r" % (K,))
        dict.__setitem__(self, K, V)

    def setdefault(self, key, val=None):
        key = key.lower()
        if key not in self._reserved:
            raise CookieError("Invalid attribute %r" % (key,))
        return dict.setdefault(self, key, val)

    def __eq__(self, morsel):
        if not isinstance(morsel, Morsel):
            return NotImplemented
        return (dict.__eq__(self, morsel) and
                self._value == morsel._value and
                self._key == morsel._key and
                self._coded_value == morsel._coded_value)

    __ne__ = object.__ne__

    def copy(self):
        morsel = Morsel()
        dict.update(morsel, self)
        morsel.__dict__.update(self.__dict__)
        return morsel

    def update(self, values):
        data = {}
        for key, val in dict(values).items():
            key = key.lower()
            if key not in self._reserved:
                raise CookieError("Invalid attribute %r" % (key,))
            data[key] = val
        dict.update(self, data)



    def __getstate__(self):
        return {
            'key': self._key,
            'value': self._value,
            'coded_value': self._coded_value,
        }

    def __setstate__(self, state):
        self._key = state['key']
        self._value = state['value']
        self._coded_value = state['coded_value']


    __str__ = output

    def __repr__(self):
        return '<%s: %s>' % (self.__class__.__name__, self.OutputString())





_LegalKeyChars  = r"\w\d!#%&'~_`><@,:/\$\*\+\-\.\^\|\)\(\?\}\{\="
_LegalValueChars = _LegalKeyChars + r'\[\]'
_CookiePattern = re.compile(r"""
    (?x)                           # This is a verbose pattern
    \s*                            # Optional whitespace at start of cookie
    (?P<key>                       # Start of group 'key'
    [""" + _LegalKeyChars + r"""]+?   # Any word of at least one letter
    )                              # End of group 'key'
    (                              # Optional group: there may not be a value.
    \s*=\s*                          # Equal Sign
    (?P<val>                         # Start of group 'val'
    "(?:[^\\"]|\\.)*"                  # Any doublequoted string
    |                                  # or
    \w{3},\s[\w\d\s-]{9,11}\s[\d:]{8}\sGMT  # Special case for "expires" attr
    |                                  # or
    [""" + _LegalValueChars + r"""]*      # Any word or empty string
    )                                # End of group 'val'
    )?                             # End of optional value group
    \s*                            # Any number of spaces.
    (\s+|;|$)                      # Ending either at space, semicolon, or EOS.
    """, re.ASCII)                 # May be removed if safe.


class BaseCookie(dict):

    def value_decode(self, val):
        """real_value, coded_value = value_decode(STRING)
        Called prior to setting a cookie's value from the network
        representation.  The VALUE is the value read from HTTP
        header.
        Override this function to modify the behavior of cookies.
        """
        return val, val

    def value_encode(self, val):
        """real_value, coded_value = value_encode(VALUE)
        Called prior to setting a cookie's value from the dictionary
        representation.  The VALUE is the value being assigned.
        Override this function to modify the behavior of cookies.
        """
        strval = str(val)
        return strval, strval

    def __init__(self, input=None):
        if input:
            self.load(input)

    def __set(self, key, real_value, coded_value):
        """Private method for setting a cookie's value"""
        M = self.get(key, Morsel())
        M.set(key, real_value, coded_value)
        dict.__setitem__(self, key, M)

    def __setitem__(self, key, value):
        """Dictionary style assignment."""
        if isinstance(value, Morsel):
            dict.__setitem__(self, key, value)
        else:
            rval, cval = self.value_encode(value)
            self.__set(key, rval, cval)

    def output(self, attrs=None, header="Set-Cookie:", sep="\015\012"):
        pass

    __str__ = output

    def __repr__(self):
        l = []
        items = sorted(self.items())
        for key, value in items:
            l.append('%s=%s' % (key, repr(value.value)))
        return '<%s: %s>' % (self.__class__.__name__, _spacejoin(l))

    def js_output(self, attrs=None):
        pass

    def load(self, rawdata):
        """Load cookies from a string (presumably HTTP_COOKIE) or
        from a dictionary.  Loading cookies from a dictionary 'd'
        is equivalent to calling:
            map(Cookie.__setitem__, d.keys(), d.values())
        """
        if isinstance(rawdata, str):
            self.__parse_string(rawdata)
        else:
            for key, value in rawdata.items():
                self[key] = value
        return

    def __parse_string(self, str, patt=_CookiePattern):
        i = 0                 # Our starting point
        n = len(str)          # Length of string
        parsed_items = []     # Parsed (type, key, value) triples
        morsel_seen = False   # A key=value pair was previously encountered

        TYPE_ATTRIBUTE = 1
        TYPE_KEYVALUE = 2

        while 0 <= i < n:
            match = patt.match(str, i)
            if not match:
                break

            key, value = match.group("key"), match.group("val")
            i = match.end(0)

            if key[0] == "$":
                if not morsel_seen:
                    continue
                parsed_items.append((TYPE_ATTRIBUTE, key[1:], value))
            elif key.lower() in Morsel._reserved:
                if not morsel_seen:
                    return
                if value is None:
                    if key.lower() in Morsel._flags:
                        parsed_items.append((TYPE_ATTRIBUTE, key, True))
                    else:
                        return
                else:
                    parsed_items.append((TYPE_ATTRIBUTE, key, _unquote(value)))
            elif value is not None:
                parsed_items.append((TYPE_KEYVALUE, key, self.value_decode(value)))
                morsel_seen = True
            else:
                return

        M = None         # current morsel
        for tp, key, value in parsed_items:
            if tp == TYPE_ATTRIBUTE:
                assert M is not None
                M[key] = value
            else:
                assert tp == TYPE_KEYVALUE
                rval, cval = value
                self.__set(key, rval, cval)
                M = self[key]


class SimpleCookie(BaseCookie):
    def value_decode(self, val):
        return _unquote(val), val

    def value_encode(self, val):
        strval = str(val)
        return strval, _quote(strval)
