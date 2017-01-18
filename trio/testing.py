import threading
from functools import wraps, partial
import inspect
import attr

from . import _core

__all__ = ["busy_wait_for", "quiesce", "trio_test", "MockClock"]

async def busy_wait_for(predicate):
    while not predicate():
        await _core.yield_briefly()

_quiesce_local = threading.local()

@attr.s(slots=True, cmp=False, hash=False)
class _QuiesceChecker(_core.Instrument):
    repetitions = attr.ib(default=0)
    lot = attr.ib(default=attr.Factory(_core.ParkingLot))
    looper_task = attr.ib(default=None)

    async def _looper(self):
        try:
            while True:
                await _core.yield_briefly()
        except _core.Cancelled:
            pass

    async def spawn(self):
        self.looper_task = await _core.spawn(self._looper)
        _core.current_instruments().append(self)

    def stop(self):
        self.lot.unpark()
        self.looper_task.cancel_nowait()
        del _quiesce_local.checker
        _core.current_instruments().remove(self)

    def before_task_step(self, task):
        print(task)
        if task is self.looper_task:
            self.repetitions += 1
            if self.repetitions == 3:
                self.stop()
        else:
            self.repetitions = 0

    def after_task_step(self, task):
        pass

    def close(self):
        assert False

async def quiesce():
    if not hasattr(_quiesce_local, "checker"):
        _quiesce_local.checker = _QuiesceChecker()
        await _quiesce_local.checker.spawn()  # doesn't yield
    try:
        await _quiesce_local.checker.lot.park()
    except:
        try:
            checker = _quiesce_local.checker
        except AttributeError:
            pass
        else:
            if checker.lot.parked_count() == 0:
                checker.stop()
        raise

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
@attr.s(slots=True, cmp=False, hash=False)
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

    def advance(self, offset):
        if offset < 0:
            raise ValueError("time can't go backwards")
        self._mock_time += offset

    # async def pump(self, offsets):
    #     for offset in offsets:
    #         self.advance(offset)
    #         await _core.yield_briefly()
    #         await _core.yield_briefly()


# XX Sequencer like in volley/jongleur
# refinements:
# - ability to schedule clock advancements
# - tick over the event loop between steps, so timeouts have a chance to fire?
#   - a random number of times? until quiescent?
