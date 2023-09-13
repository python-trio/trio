from __future__ import annotations

import contextvars
import functools
import inspect
import queue as stdlib_queue
import threading
from collections.abc import Awaitable, Callable
from itertools import count
from typing import TypeVar

import attr
import outcome
from sniffio import current_async_library_cvar

import trio
from trio._core._traps import RaiseCancelT

from ._core import (
    RunVar,
    TrioToken,
    disable_ki_protection,
    enable_ki_protection,
    start_thread_soon,
)
from ._sync import CapacityLimiter
from ._util import coroutine_or_error

RetT = TypeVar("RetT")
Ret2T = TypeVar("Ret2T")


class _TokenLocal(threading.local):
    """Global due to Threading API, thread local storage for trio token."""

    token: TrioToken


TOKEN_LOCAL = _TokenLocal()

_limiter_local: RunVar[CapacityLimiter] = RunVar("limiter")
# I pulled this number out of the air; it isn't based on anything. Probably we
# should make some kind of measurements to pick a good value.
DEFAULT_LIMIT = 40
_thread_counter = count()


def current_default_thread_limiter() -> CapacityLimiter:
    """Get the default `~trio.CapacityLimiter` used by
    `trio.to_thread.run_sync`.

    The most common reason to call this would be if you want to modify its
    :attr:`~trio.CapacityLimiter.total_tokens` attribute.

    """
    try:
        limiter = _limiter_local.get()
    except LookupError:
        limiter = CapacityLimiter(DEFAULT_LIMIT)
        _limiter_local.set(limiter)
    return limiter


# Eventually we might build this into a full-fledged deadlock-detection
# system; see https://github.com/python-trio/trio/issues/182
# But for now we just need an object to stand in for the thread, so we can
# keep track of who's holding the CapacityLimiter's token.
@attr.s(frozen=True, eq=False, hash=False)
class ThreadPlaceholder:
    name: str = attr.ib()


@enable_ki_protection  # Decorator used on function with Coroutine[Any, Any, RetT]
async def to_thread_run_sync(  # type: ignore[misc]
    sync_fn: Callable[..., RetT],
    *args: object,
    thread_name: str | None = None,
    cancellable: bool = False,
    limiter: CapacityLimiter | None = None,
) -> RetT:
    """Convert a blocking operation into an async operation using a thread.

    These two lines are equivalent::

        sync_fn(*args)
        await trio.to_thread.run_sync(sync_fn, *args)

    except that if ``sync_fn`` takes a long time, then the first line will
    block the Trio loop while it runs, while the second line allows other Trio
    tasks to continue working while ``sync_fn`` runs. This is accomplished by
    pushing the call to ``sync_fn(*args)`` off into a worker thread.

    From inside the worker thread, you can get back into Trio using the
    functions in `trio.from_thread`.

    Args:
      sync_fn: An arbitrary synchronous callable.
      *args: Positional arguments to pass to sync_fn. If you need keyword
          arguments, use :func:`functools.partial`.
      cancellable (bool): Whether to allow cancellation of this operation. See
          discussion below.
      thread_name (str): Optional string to set the name of the thread.
          Will always set `threading.Thread.name`, but only set the os name
          if pthread.h is available (i.e. most POSIX installations).
          pthread names are limited to 15 characters, and can be read from
          ``/proc/<PID>/task/<SPID>/comm`` or with ``ps -eT``, among others.
          Defaults to ``{sync_fn.__name__|None} from {trio.lowlevel.current_task().name}``.
      limiter (None, or CapacityLimiter-like object):
          An object used to limit the number of simultaneous threads. Most
          commonly this will be a `~trio.CapacityLimiter`, but it could be
          anything providing compatible
          :meth:`~trio.CapacityLimiter.acquire_on_behalf_of` and
          :meth:`~trio.CapacityLimiter.release_on_behalf_of` methods. This
          function will call ``acquire_on_behalf_of`` before starting the
          thread, and ``release_on_behalf_of`` after the thread has finished.

          If None (the default), uses the default `~trio.CapacityLimiter`, as
          returned by :func:`current_default_thread_limiter`.

    **Cancellation handling**: Cancellation is a tricky issue here, because
    neither Python nor the operating systems it runs on provide any general
    mechanism for cancelling an arbitrary synchronous function running in a
    thread. This function will always check for cancellation on entry, before
    starting the thread. But once the thread is running, there are two ways it
    can handle being cancelled:

    * If ``cancellable=False``, the function ignores the cancellation and
      keeps going, just like if we had called ``sync_fn`` synchronously. This
      is the default behavior.

    * If ``cancellable=True``, then this function immediately raises
      `~trio.Cancelled`. In this case **the thread keeps running in
      background** – we just abandon it to do whatever it's going to do, and
      silently discard any return value or errors that it raises. Only use
      this if you know that the operation is safe and side-effect free. (For
      example: :func:`trio.socket.getaddrinfo` uses a thread with
      ``cancellable=True``, because it doesn't really affect anything if a
      stray hostname lookup keeps running in the background.)

      The ``limiter`` is only released after the thread has *actually*
      finished – which in the case of cancellation may be some time after this
      function has returned. If :func:`trio.run` finishes before the thread
      does, then the limiter release method will never be called at all.

    .. warning::

       You should not use this function to call long-running CPU-bound
       functions! In addition to the usual GIL-related reasons why using
       threads for CPU-bound work is not very effective in Python, there is an
       additional problem: on CPython, `CPU-bound threads tend to "starve out"
       IO-bound threads <https://bugs.python.org/issue7946>`__, so using
       threads for CPU-bound work is likely to adversely affect the main
       thread running Trio. If you need to do this, you're better off using a
       worker process, or perhaps PyPy (which still has a GIL, but may do a
       better job of fairly allocating CPU time between threads).

    Returns:
      Whatever ``sync_fn(*args)`` returns.

    Raises:
      Exception: Whatever ``sync_fn(*args)`` raises.

    """
    await trio.lowlevel.checkpoint_if_cancelled()
    cancellable = bool(cancellable)  # raise early if cancellable.__bool__ raises
    if limiter is None:
        limiter = current_default_thread_limiter()

    # Holds a reference to the task that's blocked in this function waiting
    # for the result – or None if this function was cancelled and we should
    # discard the result.
    task_register: list[trio.lowlevel.Task | None] = [trio.lowlevel.current_task()]
    name = f"trio.to_thread.run_sync-{next(_thread_counter)}"
    placeholder = ThreadPlaceholder(name)

    # This function gets scheduled into the Trio run loop to deliver the
    # thread's result.
    def report_back_in_trio_thread_fn(result: outcome.Outcome[RetT]) -> None:
        def do_release_then_return_result() -> RetT:
            # release_on_behalf_of is an arbitrary user-defined method, so it
            # might raise an error. If it does, we want that error to
            # replace the regular return value, and if the regular return was
            # already an exception then we want them to chain.
            try:
                return result.unwrap()  # type: ignore[no-any-return]  # Until outcome is typed
            finally:
                limiter.release_on_behalf_of(placeholder)

        result = outcome.capture(do_release_then_return_result)
        if task_register[0] is not None:
            trio.lowlevel.reschedule(task_register[0], result)

    current_trio_token = trio.lowlevel.current_trio_token()

    if thread_name is None:
        thread_name = f"{getattr(sync_fn, '__name__', None)} from {trio.lowlevel.current_task().name}"

    def worker_fn() -> RetT:
        # Trio doesn't use current_async_library_cvar, but if someone
        # else set it, it would now shine through since
        # snifio.thread_local isn't set in the new thread. Make sure
        # the new thread sees that it's not running in async context.
        current_async_library_cvar.set(None)

        TOKEN_LOCAL.token = current_trio_token
        try:
            ret = sync_fn(*args)

            if inspect.iscoroutine(ret):
                # Manually close coroutine to avoid RuntimeWarnings
                ret.close()
                raise TypeError(
                    "Trio expected a sync function, but {!r} appears to be "
                    "asynchronous".format(getattr(sync_fn, "__qualname__", sync_fn))
                )

            return ret
        finally:
            del TOKEN_LOCAL.token

    context = contextvars.copy_context()
    # Partial confuses type checkers, coerce to a callable.
    contextvars_aware_worker_fn: Callable[[], RetT] = functools.partial(context.run, worker_fn)  # type: ignore[assignment]

    def deliver_worker_fn_result(result: outcome.Outcome[RetT]) -> None:
        try:
            current_trio_token.run_sync_soon(report_back_in_trio_thread_fn, result)
        except trio.RunFinishedError:
            # The entire run finished, so the task we're trying to contact is
            # certainly long gone -- it must have been cancelled and abandoned
            # us.
            pass

    await limiter.acquire_on_behalf_of(placeholder)
    try:
        start_thread_soon(
            contextvars_aware_worker_fn, deliver_worker_fn_result, thread_name
        )
    except:
        limiter.release_on_behalf_of(placeholder)
        raise

    def abort(_: RaiseCancelT) -> trio.lowlevel.Abort:
        if cancellable:
            task_register[0] = None
            return trio.lowlevel.Abort.SUCCEEDED
        else:
            return trio.lowlevel.Abort.FAILED

    # wait_task_rescheduled return value cannot be typed
    return await trio.lowlevel.wait_task_rescheduled(abort)  # type: ignore[no-any-return]


# We use two typevars here, because cb can transform from one to the other any way it likes.
def _run_fn_as_system_task(
    cb: Callable[
        [
            stdlib_queue.SimpleQueue[outcome.Outcome[Ret2T]],
            Callable[..., RetT],
            tuple[object, ...],
        ],
        object,
    ],
    fn: Callable[..., RetT],
    *args: object,
    context: contextvars.Context,
    trio_token: TrioToken | None = None,
    # Outcome isn't typed, so Ret2T is used only in the return type.
) -> Ret2T:  # type: ignore[type-var]
    """Helper function for from_thread.run and from_thread.run_sync.

    Since this internally uses TrioToken.run_sync_soon, all warnings about
    raised exceptions canceling all tasks should be noted.
    """

    if trio_token is not None and not isinstance(trio_token, TrioToken):
        raise RuntimeError("Passed kwarg trio_token is not of type TrioToken")

    if trio_token is None:
        try:
            trio_token = TOKEN_LOCAL.token
        except AttributeError:
            raise RuntimeError(
                "this thread wasn't created by Trio, pass kwarg trio_token=..."
            )

    # Avoid deadlock by making sure we're not called from Trio thread
    try:
        trio.lowlevel.current_task()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("this is a blocking function; call it from a thread")

    q: stdlib_queue.SimpleQueue[outcome.Outcome[Ret2T]] = stdlib_queue.SimpleQueue()
    trio_token.run_sync_soon(context.run, cb, q, fn, args)
    return q.get().unwrap()  # type: ignore[no-any-return]  # Until outcome is typed


def from_thread_run(
    afn: Callable[..., Awaitable[RetT]],
    *args: object,
    trio_token: TrioToken | None = None,
) -> RetT:
    """Run the given async function in the parent Trio thread, blocking until it
    is complete.

    Returns:
      Whatever ``afn(*args)`` returns.

    Returns or raises whatever the given function returns or raises. It
    can also raise exceptions of its own:

    Raises:
        RunFinishedError: if the corresponding call to :func:`trio.run` has
            already completed, or if the run has started its final cleanup phase
            and can no longer spawn new system tasks.
        Cancelled: if the corresponding call to :func:`trio.run` completes
            while ``afn(*args)`` is running, then ``afn`` is likely to raise
            :exc:`trio.Cancelled`, and this will propagate out into
        RuntimeError: if you try calling this from inside the Trio thread,
            which would otherwise cause a deadlock.
        AttributeError: if no ``trio_token`` was provided, and we can't infer
            one from context.
        TypeError: if ``afn`` is not an asynchronous function.

    **Locating a Trio Token**: There are two ways to specify which
    `trio.run` loop to reenter:

        - Spawn this thread from `trio.to_thread.run_sync`. Trio will
          automatically capture the relevant Trio token and use it when you
          want to re-enter Trio.
        - Pass a keyword argument, ``trio_token`` specifying a specific
          `trio.run` loop to re-enter. This is useful in case you have a
          "foreign" thread, spawned using some other framework, and still want
          to enter Trio.
    """

    def callback(
        q: stdlib_queue.SimpleQueue[outcome.Outcome[RetT]],
        afn: Callable[..., Awaitable[RetT]],
        args: tuple[object, ...],
    ) -> None:
        @disable_ki_protection
        async def unprotected_afn() -> RetT:
            coro = coroutine_or_error(afn, *args)
            return await coro

        async def await_in_trio_thread_task() -> None:
            q.put_nowait(await outcome.acapture(unprotected_afn))

        context = contextvars.copy_context()
        try:
            trio.lowlevel.spawn_system_task(
                await_in_trio_thread_task, name=afn, context=context
            )
        except RuntimeError:  # system nursery is closed
            q.put_nowait(
                outcome.Error(trio.RunFinishedError("system nursery is closed"))
            )

    context = contextvars.copy_context()
    return _run_fn_as_system_task(
        callback,
        afn,
        *args,
        context=context,
        trio_token=trio_token,
    )


def from_thread_run_sync(
    fn: Callable[..., RetT],
    *args: tuple[object, ...],
    trio_token: TrioToken | None = None,
) -> RetT:
    """Run the given sync function in the parent Trio thread, blocking until it
    is complete.

    Returns:
      Whatever ``fn(*args)`` returns.

    Returns or raises whatever the given function returns or raises. It
    can also raise exceptions of its own:

    Raises:
        RunFinishedError: if the corresponding call to `trio.run` has
            already completed.
        RuntimeError: if you try calling this from inside the Trio thread,
            which would otherwise cause a deadlock.
        AttributeError: if no ``trio_token`` was provided, and we can't infer
            one from context.
        TypeError: if ``fn`` is an async function.

    **Locating a Trio Token**: There are two ways to specify which
    `trio.run` loop to reenter:

        - Spawn this thread from `trio.to_thread.run_sync`. Trio will
          automatically capture the relevant Trio token and use it when you
          want to re-enter Trio.
        - Pass a keyword argument, ``trio_token`` specifying a specific
          `trio.run` loop to re-enter. This is useful in case you have a
          "foreign" thread, spawned using some other framework, and still want
          to enter Trio.
    """

    def callback(
        q: stdlib_queue.SimpleQueue[outcome.Outcome[RetT]],
        fn: Callable[..., RetT],
        args: tuple[object, ...],
    ) -> None:
        @disable_ki_protection
        def unprotected_fn() -> RetT:
            ret = fn(*args)

            if inspect.iscoroutine(ret):
                # Manually close coroutine to avoid RuntimeWarnings
                ret.close()
                raise TypeError(
                    "Trio expected a sync function, but {!r} appears to be "
                    "asynchronous".format(getattr(fn, "__qualname__", fn))
                )

            return ret

        res = outcome.capture(unprotected_fn)
        q.put_nowait(res)

    context = contextvars.copy_context()

    return _run_fn_as_system_task(
        callback,
        fn,
        *args,
        context=context,
        trio_token=trio_token,
    )
