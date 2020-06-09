import time
from math import inf

from .. import _core
from ._run import GLOBAL_RUN_CONTEXT
from .._abc import Clock
from .._util import SubclassingDeprecatedIn_v0_15_0

################################################################
# The glorious MockClock
################################################################


# Prior art:
#   https://twistedmatrix.com/documents/current/api/twisted.internet.task.Clock.html
#   https://github.com/ztellman/manifold/issues/57
class MockClock(Clock, metaclass=SubclassingDeprecatedIn_v0_15_0):
    """A user-controllable clock suitable for writing tests.

    Args:
      rate (float): the initial :attr:`rate`.
      autojump_threshold (float): the initial :attr:`autojump_threshold`.

    .. attribute:: rate

       How many seconds of clock time pass per second of real time. Default is
       0.0, i.e. the clock only advances through manuals calls to :meth:`jump`
       or when the :attr:`autojump_threshold` is triggered. You can assign to
       this attribute to change it.

    .. attribute:: autojump_threshold

       The clock keeps an eye on the run loop, and if at any point it detects
       that all tasks have been blocked for this many real seconds (i.e.,
       according to the actual clock, not this clock), then the clock
       automatically jumps ahead to the run loop's next scheduled
       timeout. Default is :data:`math.inf`, i.e., to never autojump. You can
       assign to this attribute to change it.

       Basically the idea is that if you have code or tests that use sleeps
       and timeouts, you can use this to make it run much faster, totally
       automatically. (At least, as long as those sleeps/timeouts are
       happening inside Trio; if your test involves talking to external
       service and waiting for it to timeout then obviously we can't help you
       there.)

       You should set this to the smallest value that lets you reliably avoid
       "false alarms" where some I/O is in flight (e.g. between two halves of
       a socketpair) but the threshold gets triggered and time gets advanced
       anyway. This will depend on the details of your tests and test
       environment. If you aren't doing any I/O (like in our sleeping example
       above) then just set it to zero, and the clock will jump whenever all
       tasks are blocked.

       .. warning::

          If you're using :func:`wait_all_tasks_blocked` and
          :attr:`autojump_threshold` together, then you have to be
          careful. Setting :attr:`autojump_threshold` acts like a background
          task calling::

             while True:
                 await wait_all_tasks_blocked(
                   cushion=clock.autojump_threshold, tiebreaker=float("inf"))

          This means that if you call :func:`wait_all_tasks_blocked` with a
          cushion *larger* than your autojump threshold, then your call to
          :func:`wait_all_tasks_blocked` will never return, because the
          autojump task will keep waking up before your task does, and each
          time it does it'll reset your task's timer. However, if your cushion
          and the autojump threshold are the *same*, then the autojump's
          tiebreaker will prevent them from interfering (unless you also set
          your tiebreaker to infinity for some reason. Don't do that). As an
          important special case: this means that if you set an autojump
          threshold of zero and use :func:`wait_all_tasks_blocked` with the
          default zero cushion, then everything will work fine.

          **Summary**: you should set :attr:`autojump_threshold` to be at
          least as large as the largest cushion you plan to pass to
          :func:`wait_all_tasks_blocked`.

    """

    def __init__(self, rate=0.0, autojump_threshold=inf):
        # when the real clock said 'real_base', the virtual time was
        # 'virtual_base', and since then it's advanced at 'rate' virtual
        # seconds per real second.
        self._real_base = 0.0
        self._virtual_base = 0.0
        self._rate = 0.0
        self._autojump_threshold = 0.0
        self._autojump_task = None
        self._autojump_cancel_scope = None
        # kept as an attribute so that our tests can monkeypatch it
        self._real_clock = time.perf_counter

        # use the property update logic to set initial values
        self.rate = rate
        self.autojump_threshold = autojump_threshold

    def __repr__(self):
        return "<MockClock, time={:.7f}, rate={} @ {:#x}>".format(
            self.current_time(), self._rate, id(self)
        )

    @property
    def rate(self):
        return self._rate

    @rate.setter
    def rate(self, new_rate):
        if new_rate < 0:
            raise ValueError("rate must be >= 0")
        else:
            real = self._real_clock()
            virtual = self._real_to_virtual(real)
            self._virtual_base = virtual
            self._real_base = real
            self._rate = float(new_rate)

    @property
    def autojump_threshold(self):
        return self._autojump_threshold

    @autojump_threshold.setter
    def autojump_threshold(self, new_autojump_threshold):
        self._autojump_threshold = float(new_autojump_threshold)
        self._try_resync_autojump_threshold()

    # runner.clock_autojump_threshold is an internal API that isn't easily
    # usable by custom third-party Clock objects. If you need access to this
    # functionality, let us know, and we'll figure out how to make a public
    # API. Discussion:
    #
    #     https://github.com/python-trio/trio/issues/1587
    def _try_resync_autojump_threshold(self):
        try:
            runner = GLOBAL_RUN_CONTEXT.runner
        except AttributeError:
            pass
        else:
            runner.clock_autojump_threshold = self._autojump_threshold

    # Invoked by the run loop when runner.clock_autojump_threshold is
    # exceeded.
    def _autojump(self):
        statistics = _core.current_statistics()
        jump = statistics.seconds_to_next_deadline
        if 0 < jump < inf:
            self.jump(jump)

    def _real_to_virtual(self, real):
        real_offset = real - self._real_base
        virtual_offset = self._rate * real_offset
        return self._virtual_base + virtual_offset

    def start_clock(self):
        self._try_resync_autojump_threshold()

    def current_time(self):
        return self._real_to_virtual(self._real_clock())

    def deadline_to_sleep_time(self, deadline):
        virtual_timeout = deadline - self.current_time()
        if virtual_timeout <= 0:
            return 0
        elif self._rate > 0:
            return virtual_timeout / self._rate
        else:
            return 999999999

    def jump(self, seconds):
        """Manually advance the clock by the given number of seconds.

        Args:
          seconds (float): the number of seconds to jump the clock forward.

        Raises:
          ValueError: if you try to pass a negative value for ``seconds``.

        """
        if seconds < 0:
            raise ValueError("time can't go backwards")
        self._virtual_base += seconds
