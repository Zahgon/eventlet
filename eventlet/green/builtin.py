
builtins_orig = __builtins__

from eventlet import hubs
from eventlet.hubs import hub
from eventlet.patcher import slurp_properties
import sys

__all__ = dir(builtins_orig)
__patched__ = ['open']
slurp_properties(builtins_orig, globals(),
                 ignore=__patched__, srckeys=dir(builtins_orig))

hubs.get_hub()

__original_open = open
__opening = False


