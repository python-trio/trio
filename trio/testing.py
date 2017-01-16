from functools import wraps, partial
import inspect
import attr

from . import _core, sleep_until

# Use:
#
#    @trio_test
#    async def test_whatever():
#        await ...
#
# Also: if a pytest fixture is passed in that subclasses the Clock abc, then
# that clock is passed to trio.run().
def trio_test(fn):
    @wraps(fn)
    def wrapper(**kwargs):
        __tracebackhide__ = True
        clocks = [c for c in kwargs.values() if isinstance(c, _core.Clock)]
        if not clocks:
            clock = None
        elif len(clocks) == 1:
            clock = clocks[0]
        else:
            raise ValueError("too many clocks spoil the broth!")
        return _core.run(partial(fn, **kwargs), clock=clock)
    return wrapper

# Prior art:
#   https://twistedmatrix.com/documents/current/api/twisted.internet.task.Clock.html
#   https://github.com/ztellman/manifold/issues/57
@attr.s(slots=True)
class MockClock(_core.Clock):
    _mock_time = attr.ib(convert=float, default=0.0)

    # XX could also have pause/unpause functionality to start it running in
    # real time... is that useful?

    def current_time(self):
        return self._mock_time

    def deadline_to_sleep_time(self, deadline):
        if deadline <= self._mock_time:
            return 0
        else:
            return 999999999

    async def advance(self, offset):
        if offset < 0:
            raise ValueError("time can't go backwards")
        self._mock_time += offset
        # Sleep until the next time we process timeouts...
        await sleep_until(self._mock_time)
        # ...and then one tick more, to let other tasks respond to those
        # timeouts. (Tasks with the same wakeup time are scheduled in
        # non-deterministic order, so otherwise we might be scheduled again
        # before some other tasks that were also waiting for this time.)
        await _core.yield_briefly()
        # XX not entirely sure if this is the best interface... maybe pump
        # should guarantee processing inbetween advances, while this should be
        # lower-level and leave yield management to the user?

    async def pump(self, offsets):
        for offset in offsets:
            await self.advance(offset)
