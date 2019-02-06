# Utilities for testing
import socket as stdlib_socket

import pytest

import gc

# See trio/tests/conftest.py for the other half of this
from trio.tests.conftest import RUN_SLOW
slow = pytest.mark.skipif(
    not RUN_SLOW,
    reason="use --run-slow to run slow tests",
)

try:
    s = stdlib_socket.socket(
        stdlib_socket.AF_INET6, stdlib_socket.SOCK_STREAM, 0
    )
except OSError:  # pragma: no cover
    # Some systems don't even support creating an IPv6 socket, let alone
    # binding it. (ex: Linux with 'ipv6.disable=1' in the kernel command line)
    # We don't have any of those in our CI, and there's nothing that gets
    # tested _only_ if can_create_ipv6 = False, so we'll just no-cover this.
    can_create_ipv6 = False
    can_bind_ipv6 = False
else:
    can_create_ipv6 = True
    with s:
        try:
            s.bind(('::1', 0))
        except OSError:
            can_bind_ipv6 = False
        else:
            can_bind_ipv6 = True

creates_ipv6 = pytest.mark.skipif(not can_create_ipv6, reason="need IPv6")
binds_ipv6 = pytest.mark.skipif(not can_bind_ipv6, reason="need IPv6")


def gc_collect_harder():
    # In the test suite we sometimes want to call gc.collect() to make sure
    # that any objects with noisy __del__ methods (e.g. unawaited coroutines)
    # get collected before we continue, so their noise doesn't leak into
    # unrelated tests.
    #
    # On PyPy, coroutine objects (for example) can survive at least 1 round of
    # garbage collection, because executing their __del__ method to print the
    # warning can cause them to be resurrected. So we call collect a few times
    # to make sure.
    for _ in range(4):
        gc.collect()


# template is like:
#   [1, {2.1, 2.2}, 3] -> matches [1, 2.1, 2.2, 3] or [1, 2.2, 2.1, 3]
def check_sequence_matches(seq, template):
    i = 0
    for pattern in template:
        if not isinstance(pattern, set):
            pattern = {pattern}
        got = set(seq[i:i + len(pattern)])
        assert got == pattern
        i += len(got)
