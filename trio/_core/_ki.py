import contextlib
import contextvars
import enum
import signal
import sys
import weakref
from contextlib import contextmanager
from functools import partial

import async_generator
import outcome

from .._util import is_main_thread

if False:
    from typing import Any, TypeVar, Callable
    F = TypeVar('F', bound=Callable[..., Any])

__all__ = [
    "enable_ki_protection",
    "disable_ki_protection",
    "ki_allowed_if_safe",
    "ki_forbidden",
    "currently_ki_protected",
]

# In ordinary single-threaded Python code, when you hit control-C, it raises
# an exception and automatically does all the regular unwinding stuff.
#
# In Trio code, we would like hitting control-C to raise an exception and
# automatically do all the regular unwinding stuff. In particular, we would
# like to maintain our invariant that all tasks always run to completion (one
# way or another), by unwinding all of them.
#
# But it's basically impossible to write the core task running code in such a
# way that it can maintain this invariant in the face of KeyboardInterrupt
# exceptions arising at arbitrary bytecode positions. Similarly, if a
# KeyboardInterrupt happened at the wrong moment inside pretty much any of our
# inter-task synchronization or I/O primitives, then the system state could
# get corrupted and prevent our being able to clean up properly.
#
# So, we need a way to defer KeyboardInterrupt processing from these critical
# sections.
#
# Things that don't work:
#
# - Listen for SIGINT and process it in a system task: works fine for
#   well-behaved programs that regularly pass through the event loop, but if
#   user-code goes into an infinite loop then it can't be interrupted. Which
#   is unfortunate, since dealing with infinite loops is what
#   KeyboardInterrupt is for!
#
# - Use pthread_sigmask to disable signal delivery during critical section:
#   (a) windows has no pthread_sigmask, (b) python threads start with all
#   signals unblocked, so if there are any threads around they'll receive the
#   signal and then tell the main thread to run the handler, even if the main
#   thread has that signal blocked.
#
# - Install a signal handler which checks a global variable to decide whether
#   to raise the exception immediately (if we're in a non-critical section),
#   or to schedule it on the event loop (if we're in a critical section). The
#   problem here is that it's impossible to transition safely out of user code:
#
#     with keyboard_interrupt_enabled:
#         msg = coro.send(value)
#
#   If this raises a KeyboardInterrupt, it might be because the coroutine got
#   interrupted and has unwound... or it might be the KeyboardInterrupt
#   arrived just *after* 'send' returned, so the coroutine is still running
#   but we just lost the message it sent. (And worse, in our actual task
#   runner, the send is hidden inside a utility function etc.)
#
# Solution:
#
# Mark *stack frames* as being interrupt-safe or interrupt-unsafe, and
# from the signal handler check which kind of frame we're currently in
# when deciding whether to raise or schedule the exception.
#
# Stack frames don't have much associated metadata, so this "marking"
# is a bit tricky to implement. A given function definition is either
# interrupt-safe or not, based on how it's written and what invariants
# it needs to uphold, so we track the most basic interrupt-safety
# information in a dictionary keyed by code object. (The code object
# is accessible when traversing the stack, while the function object
# itself is not.) Once we know we're in an interrupt-safe context from
# the perspective of Trio's guts, we can use a context variable to
# implement the policy decision of which tasks want to be interrupted
# and which don't. (Using *only* a contextvar runs into the problems
# described in the last bullet above, at least on Python versions that
# don't have a C contextvars module.)
#
# (Historical note: Previously we used a fake local variable to track the
# protection state, i.e., an entry in f_locals with a uniqued name. This
# did great at allowing us to accurately answer "is it OK to raise
# KeyboardInterrupt right now?", but had some unfortunate side effects.
# In particular, it incurred runtime overhead at each protection
# boundary, introduced extra stack frames in tracebacks, and meant
# that a @enable_ki_protection'd async function would not look like an
# async function to tools like inspect.iscoroutinefunction().)
#
# There are still some cases where this can fail, like if someone hits
# control-C while the process is in the event loop, and then it immediately
# enters an infinite loop in user code. In this case the user has to hit
# control-C a second time. And of course if the user code is written so that
# it doesn't actually exit after a task crashes and everything gets cancelled,
# then there's not much to be done. (Hitting control-C repeatedly might help,
# but in general the solution is to kill the process some other way, just like
# for any Python program that's written to catch and ignore
# KeyboardInterrupt.)
#
# Terminology: We say a function is "KI safe" (KI for
# KeyboardInterrupt) if it is OK to deliver arbitrary
# KeyboardInterrupts there, and "KI unsafe" if KeyboardInterrupts may
# only be delivered at Trio checkpoints. The user decision of whether
# they want KIs in a particular context is called "KI allowed" or "KI
# forbidden". A KeyboardInterrupt will be delivered directly from the
# signal handler if the context is both KI-allowed and KI-safe, and
# scheduled for later delivery if not.


class KISafetyNote(enum.Enum):
    """Information about the interrupt-safety of a stack frame."""

    # It is safe to deliver KIs at arbitrary points in this frame and its
    # transitive callees, except for those callees that are marked unsafe.
    SAFE = 1

    # It is not safe to deliver KIs at arbitrary points in this frame or
    # its transitive callees, except for those callees that are marked safe.
    UNSAFE = 2

    # It is not safe to deliver KIs at arbitrary points in this frame,
    # but the determination doesn't affect callees (except those
    # marked transparent): callees inherit the KI safety or unsafety
    # of this frame's parent. (This is used to mark the internals of
    # common helpers like Context.run(), @contextmanager, and so on
    # as KI-unsafe, while still potentially allowing KI in the various
    # user-provided functions that they might execute.)
    UNSAFE_AS_LEAF = 3

    # Pretend this frame doesn't exist at all when determining KI
    # safety.  For example, if the innermost frame has note
    # TRANSPARENT, and the second-innermost is UNSAFE_IF_LEAF, then
    # the context is considered KI-unsafe.
    TRANSPARENT = 4


# Maps a code object to a KI safety note about all frames that use it.
# Frames whose code objects are not in this dictionary inherit the KI
# safety state of their caller.
ki_safety_note = weakref.WeakKeyDictionary()


@async_generator.async_generator
async def example_oldstyle_asyncgen():
    pass


def _ki_safety_decorator(note: KISafetyNote, name: str) -> "Callable[[F], F]":
    def decorator(fn):
        if hasattr(fn, "__wrapped__"):
            # We don't want to add some common wrapper to our KI notes
            # dictionary; if we did, we would be applying the KI
            # safety change to every function that uses that wrapper,
            # since the safety notes are per code object.
            if fn.__code__ is example_oldstyle_asyncgen.__code__:
                # Special support for @async_generator, which required that
                # the KI safety decorator go on top under the previous
                # approach.
                decorator(fn.__wrapped__)
                return fn

            raise RuntimeError(
                f"@{decorator.__name__} must be at the bottom of the decorator "
                f"stack (closest to the function definition) since it only "
                f"applies to the function itself, not any wrappers added by "
                f"other decorators."
            )

        if fn.__code__.co_name != fn.__name__:
            raise RuntimeError(
                f"{fn.__name__}'s code object is named {fn.__code__.co_name} "
                f"which looks like it might be some common helper from a "
                f"decorator or similar. Make sure @{decorator.__name__} is "
                f"at the bottom of the decorator stack (closest to the "
                f"function definition). Otherwise you're affecting the "
                f"KeyboardInterrupt safety status of the common helper, "
                f"not the function you wrote."
            )

        ki_safety_note[fn.__code__] = note
        return fn

    decorator.__name__ = decorator.__qualname__ = name
    return decorator


enable_ki_protection = _ki_safety_decorator(
    KISafetyNote.UNSAFE, "enable_ki_protection"
)
disable_ki_protection = _ki_safety_decorator(
    KISafetyNote.SAFE, "disable_ki_protection"
)
mark_ki_unsafe_as_leaf = _ki_safety_decorator(
    KISafetyNote.UNSAFE_AS_LEAF, "mark_ki_unsafe_as_leaf"
)
mark_ki_safety_transparent = _ki_safety_decorator(
    KISafetyNote.TRANSPARENT, "mark_ki_safety_transparent"
)


def setup_default_protections():
    # Protect a handful of functions we don't control.
    if sys.version_info < (3, 7):
        # The pure-Python contextvars backport -- we want Context.run() to be
        # KI protected, but the function it calls to not be
        mark_ki_unsafe_as_leaf(contextvars.Context.run)
        enable_ki_protection(contextvars._get_context)
        enable_ki_protection(contextvars._set_context)

    # Protect outcome capture, but not the function whose result is being
    # captured
    mark_ki_unsafe_as_leaf(outcome.capture)
    mark_ki_unsafe_as_leaf(outcome.acapture)

    # Protect the machinery of @contextmanager and @asynccontextmanager that
    # isn't part of the user-supplied function
    @contextlib.contextmanager
    def sync_cm():
        yield

    mark_ki_unsafe_as_leaf(type(sync_cm()).__enter__)
    mark_ki_unsafe_as_leaf(type(sync_cm()).__exit__)

    async def agen():
        yield

    acm_makers = [async_generator.asynccontextmanager]
    if sys.version_info >= (3, 7):
        acm_makers.append(contextlib.asynccontextmanager)
    for maker in acm_makers:
        mark_ki_unsafe_as_leaf(type(maker(agen)()).__aenter__)
        mark_ki_unsafe_as_leaf(type(maker(agen)()).__aexit__)


setup_default_protections()

# This is a contextvar used to track whether the current task is allowed to be
# interrupted by KeyboardInterrupt at all. False is used for system tasks,
# which by default don't receive KI regardless of the KI protection status.
# True means defer to the KI protection status implied by the call stack.
# If the contextvar is not set, we assume we're not in any Trio task (e.g.
# we're in run() or the IO manager or something) and so do not allow KI.
ki_allowed_cvar = contextvars.ContextVar("trio_ki_allowed")


# NB: according to the signal.signal docs, 'frame' can be None on entry to
# this function:
def is_ki_safe(frame):
    leaf = True
    while frame is not None:
        if frame.f_code.co_name == "__del__":
            return False
        note = ki_safety_note.get(frame.f_code)
        if note is not None:
            if note == KISafetyNote.SAFE:
                return True
            elif note == KISafetyNote.UNSAFE:
                return False
            elif note == KISafetyNote.UNSAFE_AS_LEAF:
                if leaf:
                    return False
            elif note == KISafetyNote.TRANSPARENT:
                frame = frame.f_back
                continue
            else:
                raise RuntimeError(
                    f"Internal error: invalid KI protection note {note!r} "
                    f"for code object {frame.f_code!r}"
                )
        frame = frame.f_back
        leaf = False
    return True


@mark_ki_safety_transparent
def currently_ki_protected():
    r"""Check whether the calling code has :exc:`KeyboardInterrupt` protection
    enabled.

    It's surprisingly easy to think that one's :exc:`KeyboardInterrupt`
    protection is enabled when it isn't, or vice-versa. This function tells
    you what Trio thinks of the matter, which makes it useful for ``assert``\s
    and unit tests.

    Returns:
      bool: True if protection is enabled, and False otherwise.

    """
    return not (is_ki_safe(sys._getframe()) and ki_allowed_cvar.get(True))


@contextmanager
def ki_allowed_context(allowed):
    token = ki_allowed_cvar.set(allowed)
    try:
        yield
    finally:
        ki_allowed_cvar.reset(token)


ki_allowed_if_safe = partial(ki_allowed_context, True)
ki_forbidden = partial(ki_allowed_context, False)


@contextmanager
def ki_manager(deliver_cb, restrict_keyboard_interrupt_to_checkpoints):
    if (
        not is_main_thread()
        or signal.getsignal(signal.SIGINT) != signal.default_int_handler
    ):
        yield
        return

    def handler(signum, frame):
        assert signum == signal.SIGINT

        ki_allowed = (
            ki_allowed_cvar.get(True)
            and not restrict_keyboard_interrupt_to_checkpoints
        )
        if is_ki_safe(frame) and ki_allowed:
            raise KeyboardInterrupt
        else:
            deliver_cb()

    signal.signal(signal.SIGINT, handler)
    try:
        # This ensures that KIs delivered outside of any task context will
        # be deferred. That covers run(), run_impl(), handle_io(), etc.
        with ki_forbidden():
            yield
    finally:
        if signal.getsignal(signal.SIGINT) is handler:
            signal.signal(signal.SIGINT, signal.default_int_handler)
