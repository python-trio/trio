# Utilities for testing

import pytest

# See trio/tests/conftest.py for the other half of this
slow = pytest.mark.skipif(
    not pytest.config.getoption("--run-slow"),
    reason="use --run-slow to run slow tests",
)

from ... import _core

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
