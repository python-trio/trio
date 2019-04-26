from collections import defaultdict

from async_generator import async_generator, yield_, asynccontextmanager

from .. import _core
from .. import _util
from .. import Event

if False:
    from typing import DefaultDict, Set

__all__ = ["Sequencer", "LabeledSequencer"]

class Sequencer:
    """A convenience class for forcing code in different tasks to run in an
    explicit linear order.

    Instances of this class implement a ``__call__`` method which returns an
    async context manager. The idea is that you pass a sequence number to
    ``__call__`` to say where this block of code should go in the linear
    sequence. Block 0 starts immediately, and then block N doesn't start until
    block N-1 has finished.

    Example:
      An extremely elaborate way to print the numbers 0-5, in order::

         async def worker1(seq):
             async with seq(0):
                 print(0)
             async with seq(4):
                 print(4)

         async def worker2(seq):
             async with seq(2):
                 print(2)
             async with seq(5):
                 print(5)

         async def worker3(seq):
             async with seq(1):
                 print(1)
             async with seq(3):
                 print(3)

         async def main():
            seq = trio.testing.Sequencer()
            async with trio.open_nursery() as nursery:
                nursery.start_soon(worker1, seq)
                nursery.start_soon(worker2, seq)
                nursery.start_soon(worker3, seq)

    """

    def __init__(self):
        self._sequence_points: DefaultDict[int, Event] = defaultdict(Event)
        self._claimed: Set[int] = set()
        self._broken = False

    @asynccontextmanager
    @async_generator
    async def __call__(self, position: int):
        if position in self._claimed:
            raise RuntimeError(
                "Attempted to re-use sequence point {}".format(position)
            )
        if self._broken:
            raise RuntimeError("sequence broken!")
        self._claimed.add(position)
        if position != 0:
            try:
                await self._sequence_points[position].wait()
            except _core.Cancelled:
                self._broken = True
                for event in self._sequence_points.values():
                    event.set()
                raise RuntimeError(
                    "Sequencer wait cancelled -- sequence broken"
                )
            else:
                if self._broken:
                    raise RuntimeError("sequence broken!")
        try:
            await yield_()
        finally:
            self._sequence_points[position + 1].set()

class LabeledSequencer(Sequencer):

    """The labeled version of :class:`Sequencer`

    It allows you to specify ahead of time what position the sequencer should
    wait for, making the insertion of new positions much easier. Using the same
    example as above::

         async def worker1(seq):
             async with seq("worker 1 first"):
                 print(0)
             async with seq("worker 1 second"):
                 print(4)

         async def worker2(seq):
             async with seq("worker 2 first"):
                 print(2)
             async with seq("worker 2 second"):
                 print(5)

         async def worker3(seq):
             async with seq("worker 3 first"):
                 print(1)
             async with seq("worker 3 second"):
                 print(3)

         async def main():
             seq = trio.testing.LabeledSequencer(
                 "worker 1 first",
                 "worker 3 first",
                 "worker 2 first",
                 "worker 3 second",
                 "worker 1 second",
                 "worker 2 second"
             )
             async with trio.open_nursery() as nursery:
                 nursery.start_soon(worker1, seq)
                 nursery.start_soon(worker2, seq)
                 nursery.start_soon(worker3, seq)

    """

    def __init__(self, *labels: str):
        super().__init__()
        self._labels = labels

    @asynccontextmanager
    @async_generator
    async def __call__(self, label: str):
        try:
            pos = self._labels.index(label)
        except ValueError:
            raise ValueError("Label {!r} is unknown".format(label)) from None

        async with super().__call__(pos):
            await yield_()
