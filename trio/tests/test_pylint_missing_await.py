"""
Test the pylint-missing-await custom checker.

This file is run through pylint separately.  The error metadata is collected
and compared to "# expect=..." annotations.

Except for test_pylint(), code in this module is not executed, only linted.
"""
import sys
import warnings

import pytest
from pylint.lint import Run


async def missing_await():
    async def async_func():
        pass

    async_func()  # expect=missing-await

    def wrapped():
        return async_func

    wrapped()()  # expect=missing-await


@pytest.mark.skipif(
    sys.version_info < (3, 5, 6), reason="strange TypeError from pylint"
)
def test_pylint(capsys):
    # Run pylint on this file with the pylint-expect-message plugin enabled
    # and compare actual vs. expected pylint messages.
    #
    # pylint output synopsis:
    #    expected_line1:expected_symbol1
    #    expected_line2:expected_symbol2
    #    ...
    #    *** delimiter message
    #    actual_line1:actual_symbol1
    #    actual_line2:actual_symbol2
    #    ...
    with warnings.catch_warnings():
        # https://github.com/PyCQA/pylint/issues/2866
        # https://github.com/PyCQA/pylint/issues/2867
        warnings.simplefilter("ignore", category=DeprecationWarning)
        Run(
            [
                '--load-plugins=trio.testing.pylint-missing-await,trio.tests.pylint-expect-message',
                '--disable=all',
                '--enable=expect-message,missing-await,not-context-manager,not-an-iterable',
                '--score=n', '--msg-template={line}:{symbol}', __file__
            ],
            do_exit=False
        )
    expected = set()  # set of (line_number, symbol)
    actual = set()
    target = expected
    for line in capsys.readouterr().out.splitlines():
        if line.startswith('*'):
            # end of expected section
            target = actual
            continue
        target.add(tuple(line.split(':')))
    assert actual == expected, 'pylint message check (ACTUAL == EXPECTED) failed'
