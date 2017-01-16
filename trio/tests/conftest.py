import inspect
from functools import wraps, partial
import pytest
from .. import run, TaskCrashedError

import attr
@attr.s(slots=True)
class MockClock: # XX inherit from abc
    _mock_time = attr.ib(convert=float, default=0.0)

    # XX could also have pause/unpause functionality to start it running in
    # real time... is that useful?

    def current_time(self):
        return _mock_time

    def deadline_to_sleep_time(self, deadline):
        if deadline <= self._mock_time:
            return 0
        else:
            return 999999999

    def set_time(self, new_time):
        new_time = float(new_time)
        assert self._mock_time <= new_time
        self._mock_time = float(new_time)

    def advance(self, offset):
        self.set_time(self._mock_time + offset)

@pytest.fixture
def mock_clock():
    return MockClock()

# Useful in general, e.g. with unittest
def trio_test(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        __tracebackhide__ = True
        clock = kwargs.get("mock_clock")
        return run(partial(fn, *args, **kwargs), clock=clock)
    return wrapper

# XX hacky workaround for
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
    print(_pytest.python.is_generator)
else:
    print("""

    pytest has been fixed!  yay!

    please bump up the requirements number and remove the ugly hack in
    conftest.py

    """)

# FIXME: split off into a package (or just make part of trio's public
# interface?), with config file to enable? and I guess a mark option too; I
# guess it's useful with the class- and file-level marking machinery (where
# the raw @trio_test decorator isn't enough).
@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        pyfuncitem.obj = trio_test(pyfuncitem.obj)
