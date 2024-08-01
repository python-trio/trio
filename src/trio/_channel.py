from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Iterable
from math import inf
from operator import itemgetter

from typing import (
    TYPE_CHECKING,
    Generic,
    TypeVar,
    Tuple,  # only needed for typechecking on <3.9
)

import attrs
from outcome import Error, Value

import trio

from ._abc import ReceiveChannel, ReceiveType, SendChannel, SendType
from ._core import Abort, RaiseCancelT, Task, enable_ki_protection
from ._util import NoPublicConstructor, final, generic_function

if TYPE_CHECKING:
    from types import TracebackType

    from typing_extensions import Self


T = TypeVar("T")


def _open_memory_channel(
    max_buffer_size: int | float,  # noqa: PYI041
) -> MemoryChannelPair[T]:
    """Open a channel for passing objects between tasks within a process.

    Memory channels are lightweight, cheap to allocate, and entirely
    in-memory. They don't involve any operating-system resources, or any kind
    of serialization. They just pass Python objects directly between tasks
    (with a possible stop in an internal buffer along the way).

    Channel objects can be closed by calling `~trio.abc.AsyncResource.aclose`
    or using ``async with``. They are *not* automatically closed when garbage
    collected. Closing memory channels isn't mandatory, but it is generally a
    good idea, because it helps avoid situations where tasks get stuck waiting
    on a channel when there's no-one on the other side. See
    :ref:`channel-shutdown` for details.

    Memory channel operations are all atomic with respect to
    cancellation, either `~trio.abc.ReceiveChannel.receive` will
    successfully return an object, or it will raise :exc:`Cancelled`
    while leaving the channel unchanged.

    Args:
      max_buffer_size (int or math.inf): The maximum number of items that can
        be buffered in the channel before :meth:`~trio.abc.SendChannel.send`
        blocks. Choosing a sensible value here is important to ensure that
        backpressure is communicated promptly and avoid unnecessary latency;
        see :ref:`channel-buffering` for more details. If in doubt, use 0.

    Returns:
      A named tuple ``(send_channel, receive_channel)``.  The tuple ordering is
      intended to match the image of data flowing from left → right.

    In addition to the standard channel methods, all memory channel objects
    provide a ``statistics()`` method, which returns an object with the
    following fields:

    * ``current_buffer_used``: The number of items currently stored in the
      channel buffer.
    * ``max_buffer_size``: The maximum number of items allowed in the buffer,
      as passed to :func:`open_memory_channel`.
    * ``open_send_channels``: The number of open
      :class:`MemorySendChannel` endpoints pointing to this channel.
      Initially 1, but can be increased by
      :meth:`MemorySendChannel.clone`.
    * ``open_receive_channels``: Likewise, but for open
      :class:`MemoryReceiveChannel` endpoints.
    * ``tasks_waiting_send``: The number of tasks blocked in ``send`` on this
      channel (summing over all clones).
    * ``tasks_waiting_receive``: The number of tasks blocked in ``receive`` on
      this channel (summing over all clones).

    """
    if max_buffer_size != inf and not isinstance(max_buffer_size, int):
        raise TypeError("max_buffer_size must be an integer or math.inf")
    if max_buffer_size < 0:
        raise ValueError("max_buffer_size must be >= 0")
    state: MemoryChannelState[T] = MemoryChannelState(max_buffer_size)
    return MemoryChannelPair(
        MemorySendChannel[T]._create(state),
        MemoryReceiveChannel[T]._create(state),
    )


# This workaround requires python3.9+, once older python versions are not supported
# or there's a better way of achieving type-checking on a generic factory function,
# it could replace the normal function header
if TYPE_CHECKING:
    # written as a class so that you can say open_memory_channel[int](5)
    # Need to use Tuple instead of tuple due to CI check running on 3.8
    class open_memory_channel(MemoryChannelPair[T]):
        def __new__(  # type: ignore[misc]  # "must return a subtype"
            cls, max_buffer_size: int | float  # noqa: PYI041
        ) -> MemoryChannelPair[T]:
            return _open_memory_channel(max_buffer_size)

        def __init__(self, max_buffer_size: int | float):  # noqa: PYI041
            ...

else:
    # apply the generic_function decorator to make open_memory_channel indexable
    # so it's valid to say e.g. ``open_memory_channel[bytes](5)`` at runtime
    open_memory_channel = generic_function(_open_memory_channel)


@attrs.frozen
class MemoryChannelStats:
    current_buffer_used: int
    max_buffer_size: int | float
    open_send_channels: int
    open_receive_channels: int
    tasks_waiting_send: int
    tasks_waiting_receive: int


@attrs.define
class MemoryChannelState(Generic[T]):
    max_buffer_size: int | float
    data: deque[T] = attrs.Factory(deque)
    # Counts of open endpoints using this state
    open_send_channels: int = 0
    open_receive_channels: int = 0
    # {task: value}
    send_tasks: OrderedDict[Task, T] = attrs.Factory(OrderedDict)
    # {task: None}
    receive_tasks: OrderedDict[Task, None] = attrs.Factory(OrderedDict)

    def statistics(self) -> MemoryChannelStats:
        return MemoryChannelStats(
            current_buffer_used=len(self.data),
            max_buffer_size=self.max_buffer_size,
            open_send_channels=self.open_send_channels,
            open_receive_channels=self.open_receive_channels,
            tasks_waiting_send=len(self.send_tasks),
            tasks_waiting_receive=len(self.receive_tasks),
        )


@final
@attrs.define(eq=False, repr=False, slots=False)
class MemorySendChannel(
    SendChannel[SendType],
    Generic[SendType],
    metaclass=NoPublicConstructor,
):
    _state: MemoryChannelState[SendType]
    # This is just the tasks waiting on *this* object. As compared to
    # self._state.send_tasks, which includes tasks from this object and
    # all clones.
    _tasks: set[Task] = attrs.Factory(set)

    def __attrs_post_init__(self) -> None:
        self._state.open_send_channels += 1

    def __repr__(self) -> str:
        return f"<send channel at {id(self):#x}, using buffer at {id(self._state):#x}>"

    def statistics(self) -> MemoryChannelStats:
        # XX should we also report statistics specific to this object?
        return self._state.statistics()

    @enable_ki_protection
    def send_nowait(self, value: SendType) -> None:
        """Like `~trio.abc.SendChannel.send`, but if the channel's buffer is
        full, raises `WouldBlock` instead of blocking.

        """
        if self._closed:
            raise trio.ClosedResourceError
        if self._state.open_receive_channels == 0:
            raise trio.BrokenResourceError
        if self._state.receive_tasks:
            assert not self._state.data
            task, _ = self._state.receive_tasks.popitem(last=False)
            task.custom_sleep_data._tasks.remove(task)
            trio.lowlevel.reschedule(task, Value(value))
        elif len(self._state.data) < self._state.max_buffer_size:
            self._state.data.append(value)
        else:
            raise trio.WouldBlock

    @enable_ki_protection
    async def send(self, value: SendType) -> None:
        """See `SendChannel.send <trio.abc.SendChannel.send>`.

        Memory channels allow multiple tasks to call `send` at the same time.

        """
        await trio.lowlevel.checkpoint_if_cancelled()
        try:
            self.send_nowait(value)
        except trio.WouldBlock:
            pass
        else:
            await trio.lowlevel.cancel_shielded_checkpoint()
            return

        task = trio.lowlevel.current_task()
        self._tasks.add(task)
        self._state.send_tasks[task] = value
        task.custom_sleep_data = self

        def abort_fn(_: RaiseCancelT) -> Abort:
            self._tasks.remove(task)
            del self._state.send_tasks[task]
            return trio.lowlevel.Abort.SUCCEEDED

        await trio.lowlevel.wait_task_rescheduled(abort_fn)

    # Return type must be stringified or use a TypeVar
    @enable_ki_protection
    def clone(self) -> MemorySendChannel[SendType]:
        """Clone this send channel object.

        This returns a new `MemorySendChannel` object, which acts as a
        duplicate of the original: sending on the new object does exactly the
        same thing as sending on the old object. (If you're familiar with
        `os.dup`, then this is a similar idea.)

        However, closing one of the objects does not close the other, and
        receivers don't get `EndOfChannel` until *all* clones have been
        closed.

        This is useful for communication patterns that involve multiple
        producers all sending objects to the same destination. If you give
        each producer its own clone of the `MemorySendChannel`, and then make
        sure to close each `MemorySendChannel` when it's finished, receivers
        will automatically get notified when all producers are finished. See
        :ref:`channel-mpmc` for examples.

        Raises:
          trio.ClosedResourceError: if you already closed this
              `MemorySendChannel` object.

        """
        if self._closed:
            raise trio.ClosedResourceError
        return MemorySendChannel._create(self._state)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @enable_ki_protection
    def close(self) -> None:
        """Close this send channel object synchronously.

        All channel objects have an asynchronous `~.AsyncResource.aclose` method.
        Memory channels can also be closed synchronously. This has the same
        effect on the channel and other tasks using it, but `close` is not a
        trio checkpoint. This simplifies cleaning up in cancelled tasks.

        Using ``with send_channel:`` will close the channel object on leaving
        the with block.

        """
        if self._closed:
            return
        self._closed = True
        for task in self._tasks:
            trio.lowlevel.reschedule(task, Error(trio.ClosedResourceError()))
            del self._state.send_tasks[task]
        self._tasks.clear()
        self._state.open_send_channels -= 1
        if self._state.open_send_channels == 0:
            assert not self._state.send_tasks
            for task in self._state.receive_tasks:
                task.custom_sleep_data._tasks.remove(task)
                trio.lowlevel.reschedule(task, Error(trio.EndOfChannel()))
            self._state.receive_tasks.clear()

    @enable_ki_protection
    async def aclose(self) -> None:
        self.close()
        await trio.lowlevel.checkpoint()


@final
@attrs.define(eq=False, repr=False, slots=False)
class MemoryReceiveChannel(
    ReceiveChannel[ReceiveType],
    Generic[ReceiveType],
    metaclass=NoPublicConstructor,
):
    _state: MemoryChannelState[ReceiveType]
    _closed: bool = False
    _tasks: set[trio._core._run.Task] = attrs.Factory(set)

    def __attrs_post_init__(self) -> None:
        self._state.open_receive_channels += 1

    def statistics(self) -> MemoryChannelStats:
        return self._state.statistics()

    def __repr__(self) -> str:
        return (
            f"<receive channel at {id(self):#x}, using buffer at {id(self._state):#x}>"
        )

    @enable_ki_protection
    def receive_nowait(self) -> ReceiveType:
        """Like `~trio.abc.ReceiveChannel.receive`, but if there's nothing
        ready to receive, raises `WouldBlock` instead of blocking.

        """
        if self._closed:
            raise trio.ClosedResourceError
        if self._state.send_tasks:
            task, value = self._state.send_tasks.popitem(last=False)
            task.custom_sleep_data._tasks.remove(task)
            trio.lowlevel.reschedule(task)
            self._state.data.append(value)
            # Fall through
        if self._state.data:
            return self._state.data.popleft()
        if not self._state.open_send_channels:
            raise trio.EndOfChannel
        raise trio.WouldBlock

    @enable_ki_protection
    async def receive(self) -> ReceiveType:
        """See `ReceiveChannel.receive <trio.abc.ReceiveChannel.receive>`.

        Memory channels allow multiple tasks to call `receive` at the same
        time. The first task will get the first item sent, the second task
        will get the second item sent, and so on.

        """
        await trio.lowlevel.checkpoint_if_cancelled()
        try:
            value = self.receive_nowait()
        except trio.WouldBlock:
            pass
        else:
            await trio.lowlevel.cancel_shielded_checkpoint()
            return value

        task = trio.lowlevel.current_task()
        self._tasks.add(task)
        self._state.receive_tasks[task] = None
        task.custom_sleep_data = self

        def abort_fn(_: RaiseCancelT) -> Abort:
            self._tasks.remove(task)
            del self._state.receive_tasks[task]
            return trio.lowlevel.Abort.SUCCEEDED

        # Not strictly guaranteed to return ReceiveType, but will do so unless
        # you intentionally reschedule with a bad value.
        return await trio.lowlevel.wait_task_rescheduled(abort_fn)  # type: ignore[no-any-return]

    @enable_ki_protection
    def clone(self) -> MemoryReceiveChannel[ReceiveType]:
        """Clone this receive channel object.

        This returns a new `MemoryReceiveChannel` object, which acts as a
        duplicate of the original: receiving on the new object does exactly
        the same thing as receiving on the old object.

        However, closing one of the objects does not close the other, and the
        underlying channel is not closed until all clones are closed. (If
        you're familiar with `os.dup`, then this is a similar idea.)

        This is useful for communication patterns that involve multiple
        consumers all receiving objects from the same underlying channel. See
        :ref:`channel-mpmc` for examples.

        .. warning:: The clones all share the same underlying channel.
           Whenever a clone :meth:`receive`\\s a value, it is removed from the
           channel and the other clones do *not* receive that value. If you
           want to send multiple copies of the same stream of values to
           multiple destinations, like :func:`itertools.tee`, then you need to
           find some other solution; this method does *not* do that.

        Raises:
          trio.ClosedResourceError: if you already closed this
              `MemoryReceiveChannel` object.

        """
        if self._closed:
            raise trio.ClosedResourceError
        return MemoryReceiveChannel._create(self._state)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @enable_ki_protection
    def close(self) -> None:
        """Close this receive channel object synchronously.

        All channel objects have an asynchronous `~.AsyncResource.aclose` method.
        Memory channels can also be closed synchronously. This has the same
        effect on the channel and other tasks using it, but `close` is not a
        trio checkpoint. This simplifies cleaning up in cancelled tasks.

        Using ``with receive_channel:`` will close the channel object on
        leaving the with block.

        """
        if self._closed:
            return
        self._closed = True
        for task in self._tasks:
            trio.lowlevel.reschedule(task, Error(trio.ClosedResourceError()))
            del self._state.receive_tasks[task]
        self._tasks.clear()
        self._state.open_receive_channels -= 1
        if self._state.open_receive_channels == 0:
            assert not self._state.receive_tasks
            for task in self._state.send_tasks:
                task.custom_sleep_data._tasks.remove(task)
                trio.lowlevel.reschedule(task, Error(trio.BrokenResourceError()))
            self._state.send_tasks.clear()
            self._state.data.clear()

    @enable_ki_protection
    async def aclose(self) -> None:
        self.close()
        await trio.lowlevel.checkpoint()


# We cannot use generic named tuples before Py 3.11, manually define it.
class MemoryChannelPair(
    Tuple[MemorySendChannel[T], MemoryReceiveChannel[T]],
    Generic[T],
):
    """Named tuple of send/receive memory channels."""

    __slots__ = ()
    _fields = ("send_channel", "receive_channel")

    if TYPE_CHECKING:

        @property
        def send_channel(self) -> MemorySendChannel[T]:
            """Returns the sending channel half."""
            return self[0]

        @property
        def receive_channel(self) -> MemoryReceiveChannel[T]:
            """Returns the receiving channel half."""
            return self[1]

    else:  # More efficient
        send_channel = property(itemgetter(0), doc="Returns the sending channel half.")
        receive_channel = property(
            itemgetter(1), doc="Returns the receiving channel half."
        )

    def __new__(
        cls,
        send_channel: MemorySendChannel[T],
        receive_channel: MemoryReceiveChannel[T],
    ) -> Self:
        """Create new instance of MemoryChannelPair(send_channel, receive_channel)"""
        return tuple.__new__(cls, (send_channel, receive_channel))  # type: ignore[type-var]

    @classmethod
    def _make(
        cls,
        iterable: Iterable[MemorySendChannel[T] | MemoryReceiveChannel[T]],
    ) -> Self:
        """Make a new MemoryChannelPair object from a sequence or iterable"""
        send, rec = iterable
        if isinstance(send, MemoryReceiveChannel) or isinstance(rec, MemorySendChannel):
            raise TypeError("Channel order passed incorrectly.")
        return tuple.__new__(cls, (send, rec))  # type: ignore[type-var]

    def _replace(
        self,
        *,
        send_channel: MemorySendChannel[T] | None = None,
        receive_channel: MemoryReceiveChannel[T] | None = None,
    ) -> MemoryChannelPair[T]:
        """Return a new MemoryChannelPair object replacing specified fields with new values"""
        if send_channel is None:
            send_channel = self.send_channel
        if receive_channel is None:
            receive_channel = self.receive_channel
        return tuple.__new__(
            MemoryChannelPair,
            (send_channel, receive_channel),
        )  # type: ignore[type-var]

    def __repr__(self) -> str:
        """Return a nicely formatted representation string"""
        return f"{self.__class__.__name__}(send_channel={self[0]!r}, receive_channel={self[1]!r})"

    def _asdict(
        self,
    ) -> OrderedDict[str, MemorySendChannel[T] | MemoryReceiveChannel[T]]:
        """Return a new OrderedDict which maps field names to their values."""
        return OrderedDict(zip(self._fields, self))

    def __getnewargs__(self) -> tuple[MemorySendChannel[T], MemoryReceiveChannel[T]]:
        """Return self as a plain tuple.  Used by copy and pickle."""
        return (self[0], self[1])
