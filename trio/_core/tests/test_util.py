# This file is somewhat misnamed -- it has tests for ../_util.py, but also has
# utilities for testing.

import pytest

from ... import _core

# See the test below for examples of 'template'
def check_sequence_matches(seq, template):
    i = 0
    for pattern in template:
        if not isinstance(pattern, set):
            pattern = {pattern}
        got = set(seq[i:i + len(pattern)])
        assert got == pattern
        i += len(got)

def test_check_sequence_matches():
    check_sequence_matches([1, 2, 3], [1, 2, 3])
    with pytest.raises(AssertionError):
        check_sequence_matches([1, 3, 2], [1, 2, 3])
    check_sequence_matches([1, 2, 3, 4], [1, {2, 3}, 4])
    check_sequence_matches([1, 3, 2, 4], [1, {2, 3}, 4])
    with pytest.raises(AssertionError):
        check_sequence_matches([1, 2, 4, 3], [1, {2, 3}, 4])
