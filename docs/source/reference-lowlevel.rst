=========================================================
 Introspecting and extending Trio with ``trio.lowlevel``
=========================================================

.. module:: trio.lowlevel

:mod:`trio.lowlevel` contains low-level APIs for introspecting and
extending Trio. If you're writing ordinary, everyday code, then you
can ignore this module completely. But sometimes you need something a
bit lower level. Here are some examples of situations where you should
reach for :mod:`trio.lowlevel`:

* You want to implement a new :ref:`synchronization primitive
  <synchronization>` that Trio doesn't (yet) provide, like a
  reader-writer lock.
* You want to extract low-level metrics to monitor the health of your
  application.
* You want to use a low-level operating system interface that Trio
  doesn't (yet) provide its own wrappers for, like watching a
  filesystem directory for changes.
* You want to implement an interface for calling between Trio and
  another event loop within the same process.
* You're writing a debugger and want to visualize Trio's task tree.
* You need to interoperate with a C library whose API exposes raw file
  descriptors.

You don't need to be scared of :mod:`trio.lowlevel`, as long as you
take proper precautions. These are real public APIs, with strictly
defined and carefully documented semantics. They're the same tools we
use to implement all the nice high-level APIs in the :mod:`trio`
namespace. But, be careful. Some of those strict semantics have `nasty
big pointy teeth
<https://en.wikipedia.org/wiki/Rabbit_of_Caerbannog>`__. If you make a
mistake, Trio may not be able to handle it gracefully; conventions and
guarantees that are followed strictly in the rest of Trio do not
always apply. When you use this module, it's your job to think about
how you're going to handle the tricky cases so you can expose a
friendly Trio-style API to your users.


Debugging and instrumentation
=============================

Trio tries hard to provide useful hooks for debugging and
instrumentation. Some are documented above (the nursery introspection
attributes, :meth:`trio.Lock.statistics`, etc.). Here are some more.


Global statistics
-----------------

.. autofunction:: current_statistics


The current clock
-----------------

.. autofunction:: current_clock


.. _instrumentation:

Instrument API
--------------

The instrument API provides a standard way to add custom
instrumentation to the run loop. Want to make a histogram of
scheduling latencies, log a stack trace of any task that blocks the
run loop for >50 ms, or measure what percentage of your process's
running time is spent waiting for I/O? This is the place.

The general idea is that at any given moment, :func:`trio.run`
maintains a set of "instruments", which are objects that implement the
:class:`trio.abc.Instrument` interface. When an interesting event
happens, it loops over these instruments and notifies them by calling
an appropriate method. The tutorial has :ref:`a simple example of
using this for tracing <tutorial-instrument-example>`.

Since this hooks into Trio at a rather low level, you do have to be
careful. The callbacks are run synchronously, and in many cases if
they error out then there isn't any plausible way to propagate this
exception (for instance, we might be deep in the guts of the exception
propagation machinery...). Therefore our `current strategy
<https://github.com/python-trio/trio/issues/47>`__ for handling
exceptions raised by instruments is to (a) log an exception to the
``"trio.abc.Instrument"`` logger, which by default prints a stack
trace to standard error and (b) disable the offending instrument.

You can register an initial list of instruments by passing them to
:func:`trio.run`. :func:`add_instrument` and
:func:`remove_instrument` let you add and remove instruments at
runtime.

.. autofunction:: add_instrument

.. autofunction:: remove_instrument

And here's the interface to implement if you want to build your own
:class:`~trio.abc.Instrument`:

.. autoclass:: trio.abc.Instrument
   :members:

The tutorial has a :ref:`fully-worked example
<tutorial-instrument-example>` of defining a custom instrument to log
Trio's internal scheduling decisions.


Low-level I/O primitives
========================

Different environments expose different low-level APIs for performing
async I/O. :mod:`trio.lowlevel` exposes these APIs in a relatively
direct way, so as to allow maximum power and flexibility for higher
level code. However, this means that the exact API provided may vary
depending on what system Trio is running on.


Universally available API
-------------------------

All environments provide the following functions:

.. function:: wait_readable(obj)
   :async:

   Block until the kernel reports that the given object is readable.

   On Unix systems, ``obj`` must either be an integer file descriptor,
   or else an object with a ``.fileno()`` method which returns an
   integer file descriptor. Any kind of file descriptor can be passed,
   though the exact semantics will depend on your kernel. For example,
   this probably won't do anything useful for on-disk files.

   On Windows systems, ``obj`` must either be an integer ``SOCKET``
   handle, or else an object with a ``.fileno()`` method which returns
   an integer ``SOCKET`` handle. File descriptors aren't supported,
   and neither are handles that refer to anything besides a
   ``SOCKET``.

   :raises trio.BusyResourceError:
       if another task is already waiting for the given socket to
       become readable.
   :raises trio.ClosedResourceError:
       if another task calls :func:`notify_closing` while this
       function is still working.

.. function:: wait_writable(obj)
   :async:

   Block until the kernel reports that the given object is writable.

   See `wait_readable` for the definition of ``obj``.

   :raises trio.BusyResourceError:
       if another task is already waiting for the given socket to
       become writable.
   :raises trio.ClosedResourceError:
       if another task calls :func:`notify_closing` while this
       function is still working.


.. function:: notify_closing(obj)

   Call this before closing a file descriptor (on Unix) or socket (on
   Windows). This will cause any `wait_readable` or `wait_writable`
   calls on the given object to immediately wake up and raise
   `~trio.ClosedResourceError`.

   This doesn't actually close the object – you still have to do that
   yourself afterwards. Also, you want to be careful to make sure no
   new tasks start waiting on the object in between when you call this
   and when it's actually closed. So to close something properly, you
   usually want to do these steps in order:

   1. Explicitly mark the object as closed, so that any new attempts
      to use it will abort before they start.
   2. Call `notify_closing` to wake up any already-existing users.
   3. Actually close the object.

   It's also possible to do them in a different order if that's more
   convenient, *but only if* you make sure not to have any checkpoints in
   between the steps. This way they all happen in a single atomic
   step, so other tasks won't be able to tell what order they happened
   in anyway.


Unix-specific API
-----------------

`FdStream` supports wrapping Unix files (such as a pipe or TTY) as
a stream.

If you have two different file descriptors for sending and receiving,
and want to bundle them together into a single bidirectional
`~trio.abc.Stream`, then use `trio.StapledStream`::

    bidirectional_stream = trio.StapledStream(
        trio.lowlevel.FdStream(write_fd),
        trio.lowlevel.FdStream(read_fd)
    )

.. autoclass:: FdStream
   :show-inheritance:
   :members:


Kqueue-specific API
-------------------

TODO: these are implemented, but are currently more of a sketch than
anything real. See `#26
<https://github.com/python-trio/trio/issues/26>`__.

.. function:: current_kqueue()

.. function:: wait_kevent(ident, filter, abort_func)
   :async:

.. function:: monitor_kevent(ident, filter)
   :with: queue


Windows-specific API
--------------------

.. function:: WaitForSingleObject(handle)
    :async:

    Async and cancellable variant of `WaitForSingleObject
    <https://msdn.microsoft.com/en-us/library/windows/desktop/ms687032(v=vs.85).aspx>`__.
    Windows only.

    :arg handle:
        A Win32 object handle, as a Python integer.
    :raises OSError:
        If the handle is invalid, e.g. when it is already closed.


TODO: these are implemented, but are currently more of a sketch than
anything real. See `#26
<https://github.com/python-trio/trio/issues/26>`__ and `#52
<https://github.com/python-trio/trio/issues/52>`__.

.. function:: register_with_iocp(handle)

.. function:: wait_overlapped(handle, lpOverlapped)
   :async:

.. function:: current_iocp()

.. function:: monitor_completion_key()
   :with: queue


Global state: system tasks and run-local variables
==================================================

.. autoclass:: RunVar

.. autofunction:: spawn_system_task


Trio tokens
===========

.. autoclass:: TrioToken()
   :members:

.. autofunction:: current_trio_token


Spawning threads
================

.. autofunction:: start_thread_soon


Safer KeyboardInterrupt handling
================================

Trio's handling of control-C is designed to balance usability and
safety. On the one hand, there are sensitive regions (like the core
scheduling loop) where it's simply impossible to handle arbitrary
:exc:`KeyboardInterrupt` exceptions while maintaining our core
correctness invariants. On the other, if the user accidentally writes
an infinite loop, we do want to be able to break out of that. Our
solution is to install a default signal handler which checks whether
it's safe to raise :exc:`KeyboardInterrupt` at the place where the
signal is received. If so, then we do; otherwise, we schedule a
:exc:`KeyboardInterrupt` to be delivered to the main task at the next
available opportunity (similar to how :exc:`~trio.Cancelled` is
delivered).

So that's great, but – how do we know whether we're in one of the
sensitive parts of the program or not?

This is determined on a function-by-function basis. By default:

- The top-level function in regular user tasks is unprotected.
- The top-level function in system tasks is protected.
- If a function doesn't specify otherwise, then it inherits the
  protection state of its caller.

This means you only need to override the defaults at places where you
transition from protected code to unprotected code or vice-versa.

These transitions are accomplished using two function decorators:

.. function:: disable_ki_protection()
   :decorator:

   Decorator that marks the given regular function, generator
   function, async function, or async generator function as
   unprotected against :exc:`KeyboardInterrupt`, i.e., the code inside
   this function *can* be rudely interrupted by
   :exc:`KeyboardInterrupt` at any moment.

   If you have multiple decorators on the same function, then this
   should be at the bottom of the stack (closest to the actual
   function).

   An example of where you'd use this is in implementing something
   like :func:`trio.from_thread.run`, which uses
   :meth:`TrioToken.run_sync_soon` to get into the Trio
   thread. :meth:`~TrioToken.run_sync_soon` callbacks are run with
   :exc:`KeyboardInterrupt` protection enabled, and
   :func:`trio.from_thread.run` takes advantage of this to safely set up
   the machinery for sending a response back to the original thread, but
   then uses :func:`disable_ki_protection` when entering the
   user-provided function.

.. function:: enable_ki_protection()
   :decorator:

   Decorator that marks the given regular function, generator
   function, async function, or async generator function as protected
   against :exc:`KeyboardInterrupt`, i.e., the code inside this
   function *won't* be rudely interrupted by
   :exc:`KeyboardInterrupt`. (Though if it contains any
   :ref:`checkpoints <checkpoints>`, then it can still receive
   :exc:`KeyboardInterrupt` at those. This is considered a polite
   interruption.)

   .. warning::

      Be very careful to only use this decorator on functions that you
      know will either exit in bounded time, or else pass through a
      checkpoint regularly. (Of course all of your functions should
      have this property, but if you mess it up here then you won't
      even be able to use control-C to escape!)

   If you have multiple decorators on the same function, then this
   should be at the bottom of the stack (closest to the actual
   function).

   An example of where you'd use this is on the ``__exit__``
   implementation for something like a :class:`~trio.Lock`, where a
   poorly-timed :exc:`KeyboardInterrupt` could leave the lock in an
   inconsistent state and cause a deadlock.

.. autofunction:: currently_ki_protected


Sleeping and waking
===================

Wait queue abstraction
----------------------

.. autoclass:: ParkingLot
   :members:
   :undoc-members:


Low-level checkpoint functions
------------------------------

.. autofunction:: checkpoint

The next two functions are used *together* to make up a checkpoint:

.. autofunction:: checkpoint_if_cancelled
.. autofunction:: cancel_shielded_checkpoint

These are commonly used in cases where you have an operation that
might-or-might-not block, and you want to implement Trio's standard
checkpoint semantics. Example::

   async def operation_that_maybe_blocks():
       await checkpoint_if_cancelled()
       try:
           ret = attempt_operation()
       except BlockingIOError:
           # need to block and then retry, which we do below
           pass
       else:
           # operation succeeded, finish the checkpoint then return
           await cancel_shielded_checkpoint()
           return ret
       while True:
           await wait_for_operation_to_be_ready()
           try:
               return attempt_operation()
           except BlockingIOError:
               pass

This logic is a bit convoluted, but accomplishes all of the following:

* Every successful execution path passes through a checkpoint (assuming that
  ``wait_for_operation_to_be_ready`` is an unconditional checkpoint)

* Our :ref:`cancellation semantics <cancellable-primitives>` say that
  :exc:`~trio.Cancelled` should only be raised if the operation didn't
  happen. Using :func:`cancel_shielded_checkpoint` on the early-exit
  branch accomplishes this.

* On the path where we do end up blocking, we don't pass through any
  schedule points before that, which avoids some unnecessary work.

* Avoids implicitly chaining the :exc:`BlockingIOError` with any
  errors raised by ``attempt_operation`` or
  ``wait_for_operation_to_be_ready``, by keeping the ``while True:``
  loop outside of the ``except BlockingIOError:`` block.

These functions can also be useful in other situations. For example,
when :func:`trio.to_thread.run_sync` schedules some work to run in a
worker thread, it blocks until the work is finished (so it's a
schedule point), but by default it doesn't allow cancellation. So to
make sure that the call always acts as a checkpoint, it calls
:func:`checkpoint_if_cancelled` before starting the thread.


Low-level blocking
------------------

.. autofunction:: wait_task_rescheduled
.. autoclass:: Abort
.. autofunction:: reschedule

Here's an example lock class implemented using
:func:`wait_task_rescheduled` directly. This implementation has a
number of flaws, including lack of fairness, O(n) cancellation,
missing error checking, failure to insert a checkpoint on the
non-blocking path, etc. If you really want to implement your own lock,
then you should study the implementation of :class:`trio.Lock` and use
:class:`ParkingLot`, which handles some of these issues for you. But
this does serve to illustrate the basic structure of the
:func:`wait_task_rescheduled` API::

   class NotVeryGoodLock:
       def __init__(self):
           self._blocked_tasks = collections.deque()
           self._held = False

       async def acquire(self):
           while self._held:
               task = trio.current_task()
               self._blocked_tasks.append(task)
               def abort_fn(_):
                   self._blocked_tasks.remove(task)
                   return trio.lowlevel.Abort.SUCCEEDED
               await trio.lowlevel.wait_task_rescheduled(abort_fn)
           self._held = True

       def release(self):
           self._held = False
           if self._blocked_tasks:
               woken_task = self._blocked_tasks.popleft()
               trio.lowlevel.reschedule(woken_task)


Task API
========

.. autofunction:: current_root_task()

.. autofunction:: current_task()

.. class:: Task()

   A :class:`Task` object represents a concurrent "thread" of
   execution. It has no public constructor; Trio internally creates a
   :class:`Task` object for each call to ``nursery.start(...)`` or
   ``nursery.start_soon(...)``.

   Its public members are mostly useful for introspection and
   debugging:

   .. attribute:: name

      String containing this :class:`Task`\'s name. Usually the name
      of the function this :class:`Task` is running, but can be
      overridden by passing ``name=`` to ``start`` or ``start_soon``.

   .. attribute:: coro

      This task's coroutine object. Example usage: extracting a stack
      trace::

          import traceback

          def walk_coro_stack(coro):
              while coro is not None:
                  if hasattr(coro, "cr_frame"):
                      # A real coroutine
                      yield coro.cr_frame, coro.cr_frame.f_lineno
                      coro = coro.cr_await
                  else:
                      # A generator decorated with @types.coroutine
                      yield coro.gi_frame, coro.gi_frame.f_lineno
                      coro = coro.gi_yieldfrom

          def print_stack_for_task(task):
              ss = traceback.StackSummary.extract(walk_coro_stack(task.coro))
              print("".join(ss.format()))

   .. attribute:: context

      This task's :class:`contextvars.Context` object.

   .. autoattribute:: parent_nursery

   .. autoattribute:: eventual_parent_nursery

   .. autoattribute:: child_nurseries

   .. attribute:: custom_sleep_data

      Trio doesn't assign this variable any meaning, except that it
      sets it to ``None`` whenever a task is rescheduled. It can be
      used to share data between the different tasks involved in
      putting a task to sleep and then waking it up again. (See
      :func:`wait_task_rescheduled` for details.)


.. _guest-mode:

Using "guest mode" to run Trio on top of other event loops
==========================================================

What is "guest mode"?
---------------------

An event loop acts as a central coordinator to manage all the IO
happening in your program. Normally, that means that your application
has to pick one event loop, and use it for everything. But what if you
like Trio, but also need to use a framework like `Qt
<https://en.wikipedia.org/wiki/Qt_(software)>`__ or `PyGame
<https://www.pygame.org/>`__ that has its own event loop? Then you
need some way to run both event loops at once.

It is possible to combine event loops, but the standard approaches all
have significant downsides:

- **Polling:** this is where you use a `busy-loop
  <https://en.wikipedia.org/wiki/Busy_waiting>`__ to manually check
  for IO on both event loops many times per second. This adds latency,
  and wastes CPU time and electricity.

- **Pluggable IO backends:** this is where you reimplement one of the
  event loop APIs on top of the other, so you effectively end up with
  just one event loop. This requires a significant amount of work for
  each pair of event loops you want to integrate, and different
  backends inevitably end up with inconsistent behavior, forcing users
  to program against the least-common-denominator. And if the two
  event loops expose different feature sets, it may not even be
  possible to implement one in terms of the other.

- **Running the two event loops in separate threads:** This works, but
  most event loop APIs aren't thread-safe, so in this approach you
  need to keep careful track of which code runs on which event loop,
  and remember to use explicit inter-thread messaging whenever you
  interact with the other loop – or else risk obscure race conditions
  and data corruption.

That's why Trio offers a fourth option: **guest mode**. Guest mode
lets you execute `trio.run` on top of some other "host" event loop,
like Qt. Its advantages are:

- Efficiency: guest mode is event-driven instead of using a busy-loop,
  so it has low latency and doesn't waste electricity.

- No need to think about threads: your Trio code runs in the same
  thread as the host event loop, so you can freely call sync Trio APIs
  from the host, and call sync host APIs from Trio. For example, if
  you're making a GUI app with Qt as the host loop, then making a
  `cancel button <https://doc.qt.io/qt-5/qpushbutton.html>`__ and
  connecting it to a `trio.CancelScope` is as easy as writing::

      # Trio code can create Qt objects without any special ceremony...
      my_cancel_button = QPushButton("Cancel")
      # ...and Qt can call back to Trio just as easily
      my_cancel_button.clicked.connect(my_cancel_scope.cancel)

  (For async APIs, it's not that simple, but you can use sync APIs to
  build explicit bridges between the two worlds, e.g. by passing async
  functions and their results back and forth through queues.)

- Consistent behavior: guest mode uses the same code as regular Trio:
  the same scheduler, same IO code, same everything. So you get the
  full feature set and everything acts the way you expect.

- Simple integration and broad compatibility: pretty much every event
  loop offers some threadsafe "schedule a callback" operation, and
  that's all you need to use it as a host loop.


Really? How is that possible?
-----------------------------

.. note::

   You can use guest mode without reading this section. It's included
   for those who enjoy understanding how things work.

All event loops have the same basic structure. They loop through two
operations, over and over:

1. Wait for the operating system to notify them that something
   interesting has happened, like data arriving on a socket or a
   timeout passing. They do this by invoking a platform-specific
   ``sleep_until_something_happens()`` system call – ``select``,
   ``epoll``, ``kqueue``, ``GetQueuedCompletionEvents``, etc.

2. Run all the user tasks that care about whatever happened, then go
   back to step 1.

The problem here is step 1. Two different event loops on the same
thread can take turns running user tasks in step 2, but when they're
idle and nothing is happening, they can't both invoke their own
``sleep_until_something_happens()`` function at the same time.

The "polling" and "pluggable backend" strategies solve this by hacking
the loops so both step 1s can run at the same time in the same thread.
Keeping everything in one thread is great for step 2, but the step 1
hacks create problems.

The "separate threads" strategy solves this by moving both steps into
separate threads. This makes step 1 work, but the downside is that now
the user tasks in step 2 are running separate threads as well, so
users are forced to deal with inter-thread coordination.

The idea behind guest mode is to combine the best parts of each
approach: we move Trio's step 1 into a separate worker thread, while
keeping Trio's step 2 in the main host thread. This way, when the
application is idle, both event loops do their
``sleep_until_something_happens()`` at the same time in their own
threads. But when the app wakes up and your code is actually running,
it all happens in a single thread. The threading trickiness is all
handled transparently inside Trio.

Concretely, we unroll Trio's internal event loop into a chain of
callbacks, and as each callback finishes, it schedules the next
callback onto the host loop or a worker thread as appropriate. So the
only thing the host loop has to provide is a way to schedule a
callback onto the main thread from a worker thread.

Coordinating between Trio and the host loop does add some overhead.
The main cost is switching in and out of the background thread, since
this requires cross-thread messaging. This is cheap (on the order of a
few microseconds, assuming your host loop is implemented efficiently),
but it's not free.

But, there's a nice optimization we can make: we only *need* the
thread when our ``sleep_until_something_happens()`` call actually
sleeps, that is, when the Trio part of your program is idle and has
nothing to do. So before we switch into the worker thread, we
double-check whether we're idle, and if not, then we skip the worker
thread and jump directly to step 2. This means that your app only pays
the extra thread-switching penalty at moments when it would otherwise
be sleeping, so it should have minimal effect on your app's overall
performance.

The total overhead will depend on your host loop, your platform, your
application, etc. But we expect that in most cases, apps running in
guest mode should only be 5-10% slower than the same code using
`trio.run`. If you find that's not true for your app, then please let
us know and we'll see if we can fix it!


.. _guest-run-implementation:

Implementing guest mode for your favorite event loop
----------------------------------------------------

Let's walk through what you need to do to integrate Trio's guest mode
with your favorite event loop. Treat this section like a checklist.

**Getting started:** The first step is to get something basic working.
Here's a minimal example of running Trio on top of asyncio, that you
can use as a model::

    import asyncio, trio

    # A tiny Trio program
    async def trio_main():
        for i in range(5):
            print(f"Hello from Trio!")
            # This is inside Trio, so we have to use Trio APIs
            await trio.sleep(1)
        return "trio done!"

    # The code to run it as a guest inside asyncio
    async def asyncio_main():
        asyncio_loop = asyncio.get_running_loop()

        def run_sync_soon_threadsafe(fn):
            asyncio_loop.call_soon_threadsafe(fn)

        def done_callback(trio_main_outcome):
            print(f"Trio program ended with: {trio_main_outcome}")

        # This is where the magic happens:
        trio.lowlevel.start_guest_run(
            trio_main,
            run_sync_soon_threadsafe=run_sync_soon_threadsafe,
            done_callback=done_callback,
        )

        # Let the host loop run for a while to give trio_main time to
        # finish. (WARNING: This is a hack. See below for better
        # approaches.)
        #
        # This function is in asyncio, so we have to use asyncio APIs.
        await asyncio.sleep(10)

    asyncio.run(asyncio_main())

You can see we're using asyncio-specific APIs to start up a loop, and
then we call `trio.lowlevel.start_guest_run`. This function is very
similar to `trio.run`, and takes all the same arguments. But it has
two differences:

First, instead of blocking until ``trio_main`` has finished, it
schedules ``trio_main`` to start running on top of the host loop, and
then returns immediately. So ``trio_main`` is running in the
background – that's why we have to sleep and give it time to finish.

And second, it requires two extra keyword arguments:
``run_sync_soon_threadsafe``, and ``done_callback``.

For ``run_sync_soon_threadsafe``, we need a function that takes a
synchronous callback, and schedules it to run on your host loop. And
this function needs to be "threadsafe" in the sense that you can
safely call it from any thread. So you need to figure out how to write
a function that does that using your host loop's API. For asyncio,
this is easy because `~asyncio.loop.call_soon_threadsafe` does exactly
what we need; for your loop, it might be more or less complicated.

For ``done_callback``, you pass in a function that Trio will
automatically invoke when the Trio run finishes, so you know it's done
and what happened. For this basic starting version, we just print the
result; in the next section we'll discuss better alternatives.

At this stage you should be able to run a simple Trio program inside
your host loop. Now we'll turn that prototype into something solid.


**Loop lifetimes:** One of the trickiest things in most event loops is
shutting down correctly. And having two event loops makes this even
harder!

If you can, we recommend following this pattern:

- Start up your host loop
- Immediately call `start_guest_run` to start Trio
- When Trio finishes and your ``done_callback`` is invoked, shut down
  the host loop
- Make sure that nothing else shuts down your host loop

This way, your two event loops have the same lifetime, and your
program automatically exits when your Trio function finishes.

Here's how we'd extend our asyncio example to implement this pattern:

.. code-block:: python3
   :emphasize-lines: 8-11,19-22

   # Improved version, that shuts down properly after Trio finishes
   async def asyncio_main():
       asyncio_loop = asyncio.get_running_loop()

       def run_sync_soon_threadsafe(fn):
           asyncio_loop.call_soon_threadsafe(fn)

       # Revised 'done' callback: set a Future
       done_fut = asyncio.Future()
       def done_callback(trio_main_outcome):
           done_fut.set_result(trio_main_outcome)

       trio.lowlevel.start_guest_run(
           trio_main,
           run_sync_soon_threadsafe=run_sync_soon_threadsafe,
           done_callback=done_callback,
       )

       # Wait for the guest run to finish
       trio_main_outcome = await done_fut
       # Pass through the return value or exception from the guest run
       return trio_main_outcome.unwrap()

And then you can encapsulate all this machinery in a utility function
that exposes a `trio.run`-like API, but runs both loops together::

   def trio_run_with_asyncio(trio_main, *args, **trio_run_kwargs):
       async def asyncio_main():
           # same as above
           ...

       return asyncio.run(asyncio_main())

Technically, it is possible to use other patterns. But there are some
important limitations you have to respect:

- **You must let the Trio program run to completion.** Many event
  loops let you stop the event loop at any point, and any pending
  callbacks/tasks/etc. just... don't run. Trio follows a more
  structured system, where you can cancel things, but the code always
  runs to completion, so ``finally`` blocks run, resources are cleaned
  up, etc. If you stop your host loop early, before the
  ``done_callback`` is invoked, then that cuts off the Trio run in the
  middle without a chance to clean up. This can leave your code in an
  inconsistent state, and will definitely leave Trio's internals in an
  inconsistent state, which will cause errors if you try to use Trio
  again in that thread.

  Some programs need to be able to quit at any time, for example in
  response to a GUI window being closed or a user selecting a "Quit"
  from a menu. In these cases, we recommend wrapping your whole
  program in a `trio.CancelScope`, and cancelling it when you want to
  quit.

- Each host loop can only have one `start_guest_run` at a time. If you
  try to start a second one, you'll get an error. If you need to run
  multiple Trio functions at the same time, then start up a single
  Trio run, open a nursery, and then start your functions as child
  tasks in that nursery.

- Unless you or your host loop register a handler for `signal.SIGINT`
  before starting Trio (this is not common), then Trio will take over
  delivery of `KeyboardInterrupt`\s. And since Trio can't tell which
  host code is safe to interrupt, it will only deliver
  `KeyboardInterrupt` into the Trio part of your code. This is fine if
  your program is set up to exit when the Trio part exits, because the
  `KeyboardInterrupt` will propagate out of Trio and then trigger the
  shutdown of your host loop, which is just what you want.

Given these constraints, we think the simplest approach is to always
start and stop the two loops together.

**Signal management:** `"Signals"
<https://en.wikipedia.org/wiki/Signal_(IPC)>`__ are a low-level
inter-process communication primitive. When you hit control-C to kill
a program, that uses a signal. Signal handling in Python has `a lot of
moving parts
<https://vorpus.org/blog/control-c-handling-in-python-and-trio/>`__.
One of those parts is `signal.set_wakeup_fd`, which event loops use to
make sure that they wake up when a signal arrives so they can respond
to it. (If you've ever had an event loop ignore you when you hit
control-C, it was probably because they weren't using
`signal.set_wakeup_fd` correctly.)

But, only one event loop can use `signal.set_wakeup_fd` at a time. And
in guest mode that can cause problems: Trio and the host loop might
start fighting over who's using `signal.set_wakeup_fd`.

Some event loops, like asyncio, won't work correctly unless they win
this fight. Fortunately, Trio is a little less picky: as long as
*someone* makes sure that the program wakes up when a signal arrives,
it should work correctly. So if your host loop wants
`signal.set_wakeup_fd`, then you should disable Trio's
`signal.set_wakeup_fd` support, and then both loops will work
correctly.

On the other hand, if your host loop doesn't use
`signal.set_wakeup_fd`, then the only way to make everything work
correctly is to *enable* Trio's `signal.set_wakeup_fd` support.

By default, Trio assumes that your host loop doesn't use
`signal.set_wakeup_fd`. It does try to detect when this creates a
conflict with the host loop, and print a warning – but unfortunately,
by the time it detects it, the damage has already been done. So if
you're getting this warning, then you should disable Trio's
`signal.set_wakeup_fd` support by passing
``host_uses_signal_set_wakeup_fd=True`` to `start_guest_run`.

If you aren't seeing any warnings with your initial prototype, you're
*probably* fine. But the only way to be certain is to check your host
loop's source. For example, asyncio may or may not use
`signal.set_wakeup_fd` depending on the Python version and operating
system.


**A small optimization:** Finally, consider a small optimization. Some
event loops offer two versions of their "call this function soon" API:
one that can be used from any thread, and one that can only be used
from the event loop thread, with the latter being cheaper. For
example, asyncio has both `~asyncio.loop.call_soon_threadsafe` and
`~asyncio.loop.call_soon`.

If you have a loop like this, then you can also pass a
``run_sync_soon_not_threadsafe=...`` kwarg to `start_guest_run`, and
Trio will automatically use it when appropriate.

If your loop doesn't have a split like this, then don't worry about
it; ``run_sync_soon_not_threadsafe=`` is optional. (If it's not
passed, then Trio will just use your threadsafe version in all cases.)

**That's it!** If you've followed all these steps, you should now have
a cleanly-integrated hybrid event loop. Go make some cool
GUIs/games/whatever!


Limitations
-----------

In general, almost all Trio features should work in guest mode. The
exception is features which rely on Trio having a complete picture of
everything that your program is doing, since obviously, it can't
control the host loop or see what it's doing.

Custom clocks can be used in guest mode, but they only affect Trio
timeouts, not host loop timeouts. And the :ref:`autojump clock
<testing-time>` and related `trio.testing.wait_all_tasks_blocked` can
technically be used in guest mode, but they'll only take Trio tasks
into account when decided whether to jump the clock or whether all
tasks are blocked.


Reference
---------

.. autofunction:: start_guest_run


.. _live-coroutine-handoff:

Handing off live coroutine objects between coroutine runners
============================================================

Internally, Python's async/await syntax is built around the idea of
"coroutine objects" and "coroutine runners". A coroutine object
represents the state of an async callstack. But by itself, this is
just a static object that sits there. If you want it to do anything,
you need a coroutine runner to push it forward. Every Trio task has an
associated coroutine object (see :data:`Task.coro`), and the Trio
scheduler acts as their coroutine runner.

But of course, Trio isn't the only coroutine runner in Python –
:mod:`asyncio` has one, other event loops have them, you can even
define your own.

And in some very, very unusual circumstances, it even makes sense to
transfer a single coroutine object back and forth between different
coroutine runners. That's what this section is about. This is an
*extremely* exotic use case, and assumes a lot of expertise in how
Python async/await works internally. For motivating examples, see
`trio-asyncio issue #42
<https://github.com/python-trio/trio-asyncio/issues/42>`__, and `trio
issue #649 <https://github.com/python-trio/trio/issues/649>`__. For
more details on how coroutines work, we recommend André Caron's `A
tale of event loops
<https://github.com/AndreLouisCaron/a-tale-of-event-loops>`__, or
going straight to `PEP 492
<https://www.python.org/dev/peps/pep-0492/>`__ for the full details.

.. autofunction:: permanently_detach_coroutine_object

.. autofunction:: temporarily_detach_coroutine_object

.. autofunction:: reattach_detached_coroutine_object
