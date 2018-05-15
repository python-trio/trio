"""
Utilities for tracing and testing concurrent executions.

This module exposes three functions: trace(), pause(), pausing(). Together,
they can be used to force one task to pause from another task, which can be
used for things like testing correct handling of cancellations and potential
race conditions.

Usage
-----
Suppose that we have two tasks, A and B, and we want to run some code in Task B
while Task A is paused at a known location. We can achieve that goal using
tools provided by this module by writing something like::

async def task_A():
    do_stuff()
    await trace('known location')
    do_more_stuff()

async def task_B():
    async with pausing('known location'):
        do_stuff_while_task_A_is_paused()
"""
from trio import Event
from async_generator import asynccontextmanager


class TracepointRegistry:

    def __init__(self):
        self._registry = {}

    def _clear(self):
        self._registry.clear()

    async def trace(self, key):
        """
        Trace a location.

        The default behavior of this function is to do nothing. Other functions
        in this module register functions that temporarily change what happens
        during a tracepoint (e.g., forcing the call to trace() to block for
        some period of time).
        """
        await self._registry.get(key, noop)()

    async def pause(self, key):
        """Force another task to pause during a call to :func:`trace`.
        """
        if key in self._registry:
            raise ValueError("Already tracing {!r}.".format(key))

        traced = Event()
        unpaused = Event()

        async def on_trace():
            traced.set()
            await unpaused.wait()
            del self._registry[key]

        self._registry[key] = on_trace
        try:
            # Wait until someone comes calls `trace(key)`.
            await traced.wait()
        except:  # noqa
            # If we get cancelled, clean up the events so that the blocked
            # coroutine gets unblocked.
            traced.set()
            unpaused.set()
            raise

        return unpaused.set

    @asynccontextmanager
    async def pausing(self, key):
        """Context manager for pauses.
        """
        unpause = await self.pause(key)
        try:
            yield
        finally:
            unpause()


async def noop():
    return


_global_registry = TracepointRegistry()
trace = _global_registry.trace
pause = _global_registry.pause
pausing = _global_registry.pausing
