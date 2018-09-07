# PyCharm tries to statically trio's attributes, so that it can offer
# completions. (Other IDEs probably do similar things.)
#
# _core's exports use all sorts of wacky runtime tricks to set up their
# exports, and then they get divided between trio, trio.hazmat, and
# trio.testing. In an attempt to make this easier to understand for static
# analysis, this file lists all the _core symbols that are re-exported at the
# top-level (trio.whatever), with a simple static __all__. This turns out to
# be important -- PyCharm at least gives up on analyzing __all__ entirely if
# it sees __all__ += <opaque variable>, see:
#     https://github.com/python-trio/trio/issues/314#issuecomment-327824200
#
# trio/hazmat.py and trio/testing/__init__.py have similar tricks, and we have
# a test to make sure that every _core export does get re-exported in one of
# these places or another.
__all__ = [
    "TrioInternalError", "RunFinishedError", "WouldBlock", "Cancelled",
    "ResourceBusyError", "ClosedResourceError", "MultiError", "run",
    "open_nursery", "open_cancel_scope", "current_effective_deadline",
    "TASK_STATUS_IGNORED", "current_time", "open_signal_receiver"
]

from . import _core
globals().update({sym: getattr(_core, sym) for sym in __all__})
