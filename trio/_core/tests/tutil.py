# Utilities for testing
import socket as stdlib_socket

import pytest

import gc

# See trio/tests/conftest.py for the other half of this
slow = pytest.mark.skipif(
    not pytest.config.getoption("--run-slow", True),
    reason="use --run-slow to run slow tests",
)

try:
    with stdlib_socket.socket(
        stdlib_socket.AF_INET6, stdlib_socket.SOCK_STREAM, 0
    ) as s:
        s.bind(('::1', 0))
    have_ipv6 = True
except OSError:
    have_ipv6 = False

need_ipv6 = pytest.mark.skipif(not have_ipv6, reason="need IPv6")


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
#   [1, {2.1, 2.2}, 3] -> matches [1, 2.1, 3] or [1, 2.2, 3]
def check_sequence_matches(seq, template):
    i = 0
    for pattern in template:
        if not isinstance(pattern, set):
            pattern = {pattern}
        got = set(seq[i:i + len(pattern)])
        assert got == pattern
        i += len(got)
