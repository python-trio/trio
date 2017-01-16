# XX this does not belong here -- b/c it's here, these things only apply to
# the tests in trio/_core/tests, not in trio/tests. For now there's some
# copy-paste...
#
# this stuff should become a proper pytest plugin

import inspect
import pytest

from ..testing import trio_test, MockClock

@pytest.fixture
def mock_clock():
    return MockClock()

# FIXME: split off into a package (or just make part of trio's public
# interface?), with config file to enable? and I guess a mark option too; I
# guess it's useful with the class- and file-level marking machinery (where
# the raw @trio_test decorator isn't enough).
@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        pyfuncitem.obj = trio_test(pyfuncitem.obj)

# XX monkeypatched workaround for
#   https://github.com/pytest-dev/pytest/issues/2129
# hopefully becomes unnecessary soon...
import _pytest.compat
async def _probe():
    # need an await in the body to trigger the bug.
    await something
if _pytest.compat.is_generator(_probe):
    def fixed_is_generator(func):
        # pytest master seems to think they need a "and not
        # iscoroutinefunction" here, but I'm not sure why.
        return (inspect.isgeneratorfunction(func)
                and not inspect.iscoroutinefunction(func))
    _pytest.compat.is_generator = fixed_is_generator
    import _pytest.python
    _pytest.python.is_generator = fixed_is_generator
else:
    print("""

    pytest has been fixed!  yay!

    please bump up the requirements number and remove the ugly hack in
    conftest.py

    """)

