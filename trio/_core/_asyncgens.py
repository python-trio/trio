from __future__ import annotations

import logging
import sys
import warnings
import weakref
from types import AsyncGeneratorType
from typing import TYPE_CHECKING, NoReturn

import attr

from .. import _core
from .._util import name_asyncgen
from . import _run

# Used to log exceptions in async generator finalizers
ASYNCGEN_LOGGER = logging.getLogger("trio.async_generator_errors")

if TYPE_CHECKING:
    from typing import Set

    _WEAK_ASYNC_GEN_SET = weakref.WeakSet[AsyncGeneratorType[object, NoReturn]]
    _ASYNC_GEN_SET = Set[AsyncGeneratorType[object, NoReturn]]
else:
    _WEAK_ASYNC_GEN_SET = weakref.WeakSet
    _ASYNC_GEN_SET = set


@attr.s(eq=False, slots=True)
class AsyncGenerators:
    # Async generators are added to this set when first iterated. Any
    # left after the main task exits will be closed before trio.run()
    # returns.  During most of the run, this is a WeakSet so GC works.
    # During shutdown, when we're finalizing all the remaining
    # asyncgens after the system nursery has been closed, it's a
    # regular set so we don't have to deal with GC firing at
    # unexpected times.
    alive: _WEAK_ASYNC_GEN_SET | _ASYNC_GEN_SET = attr.ib(factory=_WEAK_ASYNC_GEN_SET)

    # This collects async generators that get garbage collected during
    # the one-tick window between the system nursery closing and the
    # init task starting end-of-run asyncgen finalization.
    trailing_needs_finalize: _ASYNC_GEN_SET = attr.ib(factory=_ASYNC_GEN_SET)

    prev_hooks = attr.ib(init=False)

    def install_hooks(self, runner: _run.Runner) -> None:
        def firstiter(agen: AsyncGeneratorType[object, NoReturn]) -> None:
            if hasattr(_run.GLOBAL_RUN_CONTEXT, "task"):
                self.alive.add(agen)
            else:
                # An async generator first iterated outside of a Trio
                # task doesn't belong to Trio. Probably we're in guest
                # mode and the async generator belongs to our host.
                # The locals dictionary is the only good place to
                # remember this fact, at least until
                # https://bugs.python.org/issue40916 is implemented.
                agen.ag_frame.f_locals["@trio_foreign_asyncgen"] = True
                if self.prev_hooks.firstiter is not None:
                    self.prev_hooks.firstiter(agen)

        def finalize_in_trio_context(
            agen: AsyncGeneratorType[object, NoReturn], agen_name: str
        ) -> None:
            try:
                runner.spawn_system_task(
                    self._finalize_one,
                    agen,
                    agen_name,
                    name=f"close asyncgen {agen_name} (abandoned)",
                )
            except RuntimeError:
                # There is a one-tick window where the system nursery
                # is closed but the init task hasn't yet made
                # self.asyncgens a strong set to disable GC. We seem to
                # have hit it.
                self.trailing_needs_finalize.add(agen)

        def finalizer(agen: AsyncGeneratorType[object, NoReturn]) -> None:
            agen_name = name_asyncgen(agen)
            try:
                is_ours = not agen.ag_frame.f_locals.get("@trio_foreign_asyncgen")
            except AttributeError:  # pragma: no cover
                is_ours = True

            if is_ours:
                runner.entry_queue.run_sync_soon(
                    finalize_in_trio_context, agen, agen_name
                )

                # Do this last, because it might raise an exception
                # depending on the user's warnings filter. (That
                # exception will be printed to the terminal and
                # ignored, since we're running in GC context.)
                warnings.warn(
                    f"Async generator {agen_name!r} was garbage collected before it "
                    "had been exhausted. Surround its use in 'async with "
                    "aclosing(...):' to ensure that it gets cleaned up as soon as "
                    "you're done using it.",
                    ResourceWarning,
                    stacklevel=2,
                    source=agen,
                )
            else:
                # Not ours -> forward to the host loop's async generator finalizer
                if self.prev_hooks.finalizer is not None:
                    self.prev_hooks.finalizer(agen)
                else:
                    # Host has no finalizer.  Reimplement the default
                    # Python behavior with no hooks installed: throw in
                    # GeneratorExit, step once, raise RuntimeError if
                    # it doesn't exit.
                    closer = agen.aclose()
                    try:
                        # If the next thing is a yield, this will raise RuntimeError
                        # which we allow to propagate
                        closer.send(None)
                    except StopIteration:
                        pass
                    else:
                        # If the next thing is an await, we get here. Give a nicer
                        # error than the default "async generator ignored GeneratorExit"
                        raise RuntimeError(
                            f"Non-Trio async generator {agen_name!r} awaited something "
                            "during finalization; install a finalization hook to "
                            "support this, or wrap it in 'async with aclosing(...):'"
                        )

        self.prev_hooks = sys.get_asyncgen_hooks()
        sys.set_asyncgen_hooks(firstiter=firstiter, finalizer=finalizer)  # type: ignore[arg-type]  # Finalizer doesn't use AsyncGeneratorType

    async def finalize_remaining(self, runner: _run.Runner) -> None:
        # This is called from init after shutting down the system nursery.
        # The only tasks running at this point are init and
        # the run_sync_soon task, and since the system nursery is closed,
        # there's no way for user code to spawn more.
        assert _core.current_task() is runner.init_task
        assert len(runner.tasks) == 2

        # To make async generator finalization easier to reason
        # about, we'll shut down asyncgen garbage collection by turning
        # the alive WeakSet into a regular set.
        self.alive = set(self.alive)

        # Process all pending run_sync_soon callbacks, in case one of
        # them was an asyncgen finalizer that snuck in under the wire.
        runner.entry_queue.run_sync_soon(runner.reschedule, runner.init_task)
        await _core.wait_task_rescheduled(
            lambda _: _core.Abort.FAILED  # pragma: no cover
        )
        self.alive.update(self.trailing_needs_finalize)
        self.trailing_needs_finalize.clear()

        # None of the still-living tasks use async generators, so
        # every async generator must be suspended at a yield point --
        # there's no one to be doing the iteration. That's good,
        # because aclose() only works on an asyncgen that's suspended
        # at a yield point.  (If it's suspended at an event loop trap,
        # because someone is in the middle of iterating it, then you
        # get a RuntimeError on 3.8+, and a nasty surprise on earlier
        # versions due to https://bugs.python.org/issue32526.)
        #
        # However, once we start aclose() of one async generator, it
        # might start fetching the next value from another, thus
        # preventing us from closing that other (at least until
        # aclose() of the first one is complete).  This constraint
        # effectively requires us to finalize the remaining asyncgens
        # in arbitrary order, rather than doing all of them at the
        # same time. On 3.8+ we could defer any generator with
        # ag_running=True to a later batch, but that only catches
        # the case where our aclose() starts after the user's
        # asend()/etc. If our aclose() starts first, then the
        # user's asend()/etc will raise RuntimeError, since they're
        # probably not checking ag_running.
        #
        # It might be possible to allow some parallelized cleanup if
        # we can determine that a certain set of asyncgens have no
        # interdependencies, using gc.get_referents() and such.
        # But just doing one at a time will typically work well enough
        # (since each aclose() executes in a cancelled scope) and
        # is much easier to reason about.

        # It's possible that that cleanup code will itself create
        # more async generators, so we iterate repeatedly until
        # all are gone.
        while self.alive:
            batch = self.alive
            self.alive = _ASYNC_GEN_SET()
            for agen in batch:
                await self._finalize_one(agen, name_asyncgen(agen))

    def close(self) -> None:
        sys.set_asyncgen_hooks(*self.prev_hooks)

    async def _finalize_one(
        self, agen: AsyncGeneratorType[object, NoReturn], name: object
    ) -> None:
        try:
            # This shield ensures that finalize_asyncgen never exits
            # with an exception, not even a Cancelled. The inside
            # is cancelled so there's no deadlock risk.
            with _core.CancelScope(shield=True) as cancel_scope:
                cancel_scope.cancel()
                await agen.aclose()
        except BaseException:
            ASYNCGEN_LOGGER.exception(
                "Exception ignored during finalization of async generator %r -- "
                "surround your use of the generator in 'async with aclosing(...):' "
                "to raise exceptions like this in the context where they're generated",
                name,
            )
