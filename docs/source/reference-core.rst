Trio's core functionality
=========================

.. module:: trio


Entering trio
-------------

If you want to use trio, then the first thing you have to do is call
:func:`trio.run`:

.. autofunction:: run


General notes
-------------

.. _check-points:

Check points
~~~~~~~~~~~~

When writing code using trio, it's very important to understand the
concept of a *check point*. Many of trio's functions act as check
points.

A check point is two things:

1. It's a point where trio checks for cancellation. For example, if
   the code that called your function set a timeout, and that timeout
   has expired, then the next time your code executes a check point
   then trio will raise a :exc:`Cancelled` exception. See
   :ref:`cancellation` below for more details.

2. It's a point where the trio scheduler checks its scheduling policy
   to see if it's a good time to switch to another task, and
   potentially does so. (Currently, this check is very simple: the
   scheduler always switches at every check point. But `this might
   change in the future
   <https://github.com/python-trio/trio/issues/32>`__.)

When writing trio code, you need to keep track of where your check
points are. Why? First, because check points require extra scrutiny:
whenever you execute a check point, you need to be prepared to handle
a :exc:`Cancelled` error, or for another task to run and `rearrange
some state out from under you
<https://glyph.twistedmatrix.com/2014/02/unyielding.html>`__. And
second, because you also need to make sure that you have *enough*
check points: if your code doesn't pass through a check point on a
regular basis, then it will be slow to notice and respond to
cancellation and – much worse – since trio is a cooperative
multi-tasking system where the *only* place the scheduler can switch
tasks is at check points, it'll also prevent the scheduler from fairly
allocating time between different tasks and adversely effect the
response latency of all the other code running in the same
process. (Informally we say that a task that does this is "hogging the
run loop".)

So when you're doing code review on a project that uses trio, one of
the things you'll want to think about is whether there are enough
check points, and whether each one is handled correctly. Of course
this means you need a way to recognize check points. How do you do
that?  The underlying principle is that any operation that blocks has
to be a check point. This makes sense: if an operation blocks, then it
might block for a long time, and you'll want to be able to cancel it
if a timeout expires; and in any case, while this task is blocked we
want to schedule another task to run so we can make full use of the
CPU.

But if we want to write correct code in practice, then this principle
is a little too sloppy and imprecise to be useful. How do we know
which functions might block?  What if a function blocks sometimes, but
not others, depending on the arguments passed / network speed / phase
of the moon? How do we figure out where the check points are when
we're stressed and sleep deprived but still want to get this code
review right, and would prefer to reserve our mental energy for
thinking about the actual logic instead of worrying about check
points?

.. _check-point-rule:

Don't worry – trio's got your back. Since check points are important
and ubiquitous, we make it as simple as possible to keep track of
them. Here are the rules:

* Regular (synchronous) functions never contain any check points.

* Every async function provided by trio *always* acts as a check
  point; if you see ``await <something in trio>``, or ``async for
  ... in <a trio object>``, or ``async with <trio.something>``, then
  that's *definitely* a check point.

  (Partial exception: for async context managers, it might be only the
  entry or only the exit that acts as a check point; this is
  documented on a case-by-case basis.)

* Third-party async functions can act as check points; if you see
  ``await <something>`` or one of its friends, then that *might* be a
  check point. So to be safe, you should prepare for scheduling or
  cancellation happening there.

The reason we distinguish between trio functions and other functions
is that we can't make any guarantees about third party
code. Check-point-ness is a transitive property: if function A acts as
a check point, and you write a function that calls function A, then
your function also acts as a check point. If you don't, then it
isn't. So there's nothing stopping someone from writing a function
like::

   # technically legal, but bad style:
   async def why_is_this_async():
       return 7

that never calls any of trio's async functions. This is an async
function, but it's not a check point. But why make a function async if
it never calls any async functions? It's possible, but it's a bad
idea. If you have a function that's not calling any async functions,
then you should make it synchronous. The people who use your function
will thank you, because it makes it obvious that your function is not
a check point, and their code reviews will go faster.

(Remember how in the tutorial we emphasized the importance of the
:ref:`"async sandwich" <async-sandwich>`, and the way it means that
``await`` ends up being a marker that shows when you're calling a
function that calls a function that ... eventually calls one of trio's
built-in async functions? The transitivity of async-ness is a
technical requirement that Python imposes, but since it exactly
matches the transitivity of check-point-ness, we're able to exploit it
to help you keep track of check points. Pretty sneaky, eh?)

A slightly trickier case is a function like::

   async def sleep_or_not(should_sleep):
       if should_sleep:
           await trio.sleep(1)
       else:
           pass

Here the function acts as a check point if you call it with
``should_sleep`` set to a true value, but not otherwise. This is why
we emphasize that trio's own async functions are *unconditional* check
points: they *always* check for cancellation and check for scheduling,
regardless of what arguments they're passed. If you find an async
function in trio that doesn't follow this rule, then it's a bug and
you should `let us know
<https://github.com/python-trio/trio/issues>`__.

Inside trio, we're very picky about this, because trio is the
foundation of the whole system so we think it's worth the extra effort
to make things extra predictable. It's up to you how picky you want to
be in your code. To give you a more realistic example of what this
kind of issue looks like in real life, consider this function::

    async def recv_exactly(sock, nbytes):
        data = bytearray()
        while nbytes > 0:
            # SocketType.recv() reads up to 'nbytes' bytes each time
            chunk += await sock.recv(nbytes)
            if not chunk:
                raise RuntimeError("socket unexpected closed")
            nbytes -= len(chunk)
            data += chunk
        return data

If called with an ``nbytes`` that's greater than zero, then it will
call ``sock.recv`` at least once, and ``recv`` is an async trio
function, and thus an unconditional check point. So in this case,
``recv_exactly`` acts as a check point. But if we do ``await
recv_exactly(sock, 0)``, then it will immediately return an empty
buffer without executing a check point. If this were a function in
trio itself, then this wouldn't be acceptable, but you may decide you
don't want to worry about this kind of minor edge case in your own
code.

If you do want to be careful, or if you have some CPU-bound code that
doesn't have enough check points in it, then it's useful to know that
``await trio.sleep(0)`` is an idiomatic way to execute a check point
without doing anything else, and that
:func:`trio.testing.assert_yields` can be used to test that an
arbitrary block of code contains a check point.


Thread safety
~~~~~~~~~~~~~

The vast majority of trio's API is *not* thread safe: it can only be
used from inside a call to :func:`trio.run`. We don't bother
documenting this on individual calls; unless specifically noted
otherwise, you should assume that it isn't safe to call any trio
functions from anywhere except the trio thread. (But :ref:`see below
<threads>` if you really do need to work with threads.)


.. _time-and-clocks:

Time and clocks
---------------

Every call to :func:`run` has an associated clock.

By default, trio uses an unspecified monotonic clock, but this can be
changed by passing a custom clock object to :func:`run` (e.g. for
testing).

You should not assume that trio's internal clock matches any other
clock you have access to, including the clocks of simultaneous calls
to :func:`trio.run` happening in other processes or threads!

The default clock is currently implemented as :func:`time.monotonic`
plus a large random offset. The idea here is to catch code that
accidentally uses :func:`time.monotonic` early, which should help keep
our options open for `changing the clock implementation later
<https://github.com/python-trio/trio/issues/33>`__, and (more importantly)
make sure you can be confident that custom clocks like
:class:`trio.testing.MockClock` will work with third-party libraries
you don't control.

.. autofunction:: current_time

.. autofunction:: sleep
.. autofunction:: sleep_until
.. autofunction:: sleep_forever

If you're a mad scientist or otherwise feel the need to take direct
control over the PASSAGE OF TIME ITSELF, then you can implement a
custom :class:`~trio.abc.Clock` class:

.. autoclass:: trio.abc.Clock
   :members:

You can also fetch a reference to the current clock, which might be
useful if you're using a custom clock class:

.. autofunction:: current_clock


.. _cancellation:

Cancellation and timeouts
-------------------------

Trio has a rich, composable system for cancelling work, either
explicitly or when a timeout expires.


A simple timeout example
~~~~~~~~~~~~~~~~~~~~~~~~

In the simplest case, you can apply a timeout to a block of code::

   with trio.move_on_after(30):
       result = await do_http_get("https://...")
       print("result is", result)
   print("with block finished")

We refer :func:`move_on_after` as creating a "cancel scope", that
contains all the code that runs inside the ``with`` block.

If the HTTP request finishes in less than 30 seconds, then ``result``
is set and the ``with`` block exits normally. If it does *not* finish
within 30 seconds, then the cancel scope becomes "cancelled", and the
next time ``do_http_get`` attempts to call a blocking trio operation
it will fail immediately with a :exc:`Cancelled` exception. This
exception eventually propagates out of ``do_http_get``, is caught by
the ``with`` block, and execution then continues on the line
``print("with block statement")``.

.. note::

   Note that this is a simple 30 second timeout for the entire body of
   the ``with`` statement. This is different from what you might have
   seen with other Python libraries, where timeouts often refer to
   something `more complicated
   <http://docs.python-requests.org/en/master/user/quickstart/#timeouts>`__. We
   think this way is easier to reason about.


Handling cancellation
~~~~~~~~~~~~~~~~~~~~~

Pretty much any code you write using trio needs to have some strategy
to handle :exc:`Cancelled` exceptions – even if you didn't set a
timeout, then your caller might (and probably will).

You can catch :exc:`Cancelled`, but you shouldn't! Or more precisely,
if you do catch it, then you should do some cleanup and then re-raise
it or otherwise let it continue propagating (unless you encounter an
error, in which case it's OK to let that propagate instead). To help
remind you of this fact, :exc:`Cancelled` inherits from
:exc:`BaseException`, like :exc:`KeyboardInterrupt` and
:exc:`SystemExit` do, so that it won't be caught by catch-all ``except
Exception:`` blocks.

It's also important in any long-running code to make sure that you
regularly check for cancellation, because otherwise timeouts won't
work! This happens implicitly every time you call a cancellable
operation; see :ref:`below <cancellable-primitives>` for details. If
you have a task that has to do a lot of work without any IO, then you
can use ``await sleep(0)`` to insert an explicit cancel+schedule
point.

Here's a rule of thumb for designing good trio-style ("trionic"?)
APIs: if you're writing a reusable function, then you shouldn't take a
``timeout=`` parameter, and instead let your caller worry about
it. This has several advantages. First, it leaves the caller's options
open for deciding how they prefer to handle timeouts – for example,
they might find it easier to work with absolute deadlines instead of
relative timeouts. If they're the ones calling into the cancellation
machinery, then they get to pick, and you don't have to worry about
it. Second, and more importantly, this makes it easier for others to
re-use your code. If you write a ``http_get`` function, and then I
come along later and write a ``log_in_to_twitter`` function that needs
to internally make several ``http_get`` calls, I don't want to have to
figure out how to configure the individual timeouts on each of those
calls – and with trio's timeout system, it's totally unnecessary.

Of course, this rule doesn't apply to APIs that need to impose
internal timeouts. For example, if you write a ``start_http_server``
function, then you probably should give your caller some way to
configure timeouts on individual requests.


Cancellation semantics
~~~~~~~~~~~~~~~~~~~~~~

You can freely nest cancellation blocks, and each :exc:`Cancelled`
exception "knows" which block it belongs to. So long as you don't stop
it, the exception will keep propagating until it reaches the block
that raised it, at which point it will stop automatically.

Here's an example::

   print("starting...")
   with trio.move_on_after(5):
       with trio.move_on_after(10):
           await sleep(20)
           print("sleep finished without error")
       print("move_on_after(10) finished without error")
   print("move_on_after(5) finished without error")

In this code, the outer scope will expire after 5 seconds, causing the
:func:`sleep` call to return early with a :exc:`Cancelled`
exception. Then this exception will propagate through the ``with
move_on_after(10)`` line until it's caught by the ``with
move_on_after(5)`` context manager. So this code will print:

.. code-block:: none

   starting...
   move_on_after(5) finished without error

The end result is that we have successfully cancelled exactly the work
that was happening within the scope that was cancelled.

Looking at this, you might wonder how we can tell whether the inner
block timed out – perhaps we want to do something different, like try
a fallback procedure or report a failure to our caller. To make this
easier, :func:`move_on_after`'s ``__enter__`` function returns an
object representing this cancel scope, which we can use to check
whether this scope caught a :exc:`Cancelled` exception::

   with trio.move_on_after(5) as cancel_scope:
       await sleep(10)
   print(cancel_scope.cancelled_caught)  # prints "True"

The ``cancel_scope`` object also allows you to check or adjust this
scope's deadline, explicitly trigger a cancellation without waiting
for the deadline, check if the scope has already been cancelled, and
so forth – see :func:`open_cancel_scope` below for the full details.

.. _blocking-cleanup-example:

Cancellations in trio are "level triggered", meaning that once a block
has been cancelled, *all* cancellable operations in that block will
keep raising :exc:`Cancelled`. This helps avoid some pitfalls around
resource clean-up. For example, imagine that we have a function that
connects to a remote server and sends some messages, and then cleans
up on the way out::

   with trio.move_on_after(TIMEOUT):
       conn = make_connection()
       try:
           await conn.send_hello_msg()
       finally:
           await conn.send_goodbye_msg()

Now suppose that the remote server stops responding, so our call to
``await conn.send_hello_msg()`` hangs forever. Fortunately, we were
clever enough to put a timeout around this code, so eventually the
timeout will expire and ``send_hello_msg`` will raise
:exc:`Cancelled`. But then, in the ``finally`` block, we make another
blocking operation, which will also hang forever! At this point, if we
were using :mod:`asyncio` or another library with "edge-triggered"
cancellation, we'd be in trouble: since our timeout already fired, it
wouldn't fire again, and at this point our application would lock
up. But in trio, this *doesn't* happen: the ``await
conn.send_goodbye_msg()`` call is still inside the cancelled block, so
it will also raise :exc:`Cancelled`.

Of course, if you really want to make another blocking call in your
cleanup handler, trio will let you; it's trying to prevent you from
accidentally shooting yourself in the foot. Intentional foot-shooting
is no problem (or at least – it's not trio's problem). To do this,
create a new scope, and set its :attr:`shield` attribute to
:data:`True`::

   with trio.move_on_after(TIMEOUT):
       conn = make_connection()
       try:
           await conn.send_hello_msg()
       finally:
           with move_on_after(CLEANUP_TIMEOUT) as cleanup_scope:
               cleanup_scope.shield = True
               await conn.send_goodbye_msg()

So long as you're inside a scope with ``shield = True`` set, then
you'll be protected from outside cancellations. Note though that this
*only* applies to *outside* cancellations: if ``CLEANUP_TIMEOUT``
expires then ``await conn.send_goodbye_msg()`` will still be
cancelled, and if ``await conn.send_goodbye_msg()`` call uses any
timeouts internally, then those will continue to work normally as
well. This is a pretty advanced feature that most people probably
won't use, but it's there for the rare cases where you need it.


.. _cancellable-primitives:

Cancellation and primitive operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

We've talked a lot about what happens when an operation is cancelled,
and how you need to be prepared for this whenever calling a
cancellable operation... but we haven't said which operations are
cancellable.

Here's the rule: if it's in the trio namespace, and you use ``await``
to call it, then it's cancellable (see :ref:`check-points`
above). Cancellable means:

* If you try to call it when inside a cancelled scope, then it will
  raise :exc:`Cancelled`.

* If it blocks, and while it's blocked then one of the scopes around
  it becomes cancelled, it will return early and raise
  :exc:`Cancelled`.

* Raising :exc:`Cancelled` means that the operation *did not
  happen*. If a trio socket's ``send`` method raises :exc:`Cancelled`,
  then no data was sent. If a trio socket's ``recv`` method raises
  :exc:`Cancelled` then no data was lost – it's still sitting in the
  socket recieve buffer waiting for you to call ``recv`` again. And so
  forth.

There are a few idiosyncratic cases where external constraints make it
impossible to fully implement these semantics. These are always
documented. There is also one systematic exception:

* Async cleanup operations – like ``__aexit__`` methods or async close
  methods – are cancellable just like anything else *except* that if
  they are cancelled, they still perform a minimum level of cleanup
  before raising :exc:`Cancelled`.

For example, closing a TLS-wrapped socket normally involves sending a
notification to the remote peer, so that they can be cryptographically
assured that you really meant to close the socket, and your connection
wasn't just broken by a man-in-the-middle attacker. But handling this
robustly is a bit tricky. Remember our :ref:`example
<blocking-cleanup-example>` above where the blocking
``send_goodbye_msg`` caused problems? That's exactly how closing a TLS
socket works: if the remote peer has disappeared, then we may never be
able to actually send our shutdown notification, and it would be nice
if we didn't block forever trying. Therefore, the ``close`` method on
a TLS-wrapped socket will *try* to send that notification – but if it
gets cancelled, then it will give up on sending the message but will
still close the underlying socket before raising :exc:`Cancelled`, so
at least you don't leak that resource.


Cancellation API details
~~~~~~~~~~~~~~~~~~~~~~~~

The primitive operation for creating a new cancellation scope is:

.. autofunction:: open_cancel_scope
   :with: cancel_scope

   Cancel scope objects provide the following interface:

   .. currentmodule:: None

   .. attribute:: deadline

      Read-write, :class:`float`. An absolute time on the current
      run's clock at which this scope will automatically become
      cancelled. You can adjust the deadline by modifying this
      attribute, e.g.::

         # I need a little more time!
         cancel_scope.deadline += 30

      Note that the core run loop alternates between running tasks and
      processing deadlines, so if the very first check point after the
      deadline expires doesn't actually block, then it may complete
      before we process deadlines::

         with trio.open_cancel_scope(deadline=current_time()):
             # current_time() is now >= deadline, so cancel should fire,
             # at the next check point. BUT, if the next check point
             # completes instantly -- e.g., a recv on a socket that
             # already has data pending -- then the operation may
             # complete before we process deadlines, and then it's too
             # late to cancel (the data's already been read from the
             # socket):
             await sock.recv(1)

             # But the next call after that *is* guaranteed to raise
             # Cancelled:
             await sock.recv(1)

      Defaults to :data:`math.inf`, which means "no deadline", though
      this can be overridden by the ``deadline=`` argument to
      :func:`~trio.open_cancel_scope`.

   .. attribute:: shield

      Read-write, :class:`bool`, default :data:`False`. So long as
      this is set to :data:`True`, then the code inside this scope
      will not receive :exc:`~trio.Cancelled` exceptions from scopes
      that are outside this scope. They can still receive
      :exc:`~trio.Cancelled` exceptions from (1) this scope, or (2)
      scopes inside this scope. You can modify this attribute::

         with trio.open_cancel_scope() as cancel_scope:
             cancel_scope.shield = True
             # This cannot be interrupted by any means short of
             # killing the process:
             await sleep(10)

             cancel_scope.shield = False
             # Now this can be cancelled normally:
             await sleep(10)

      Defaults to :data:`False`, though this can be overridden by the
      ``shield=`` argument to :func:`~trio.open_cancel_scope`.

   .. method:: cancel()

      Cancels this scope immediately.

      This method is idempotent, i.e. if the scope was already
      cancelled then this method silently does nothing.

   .. attribute:: cancel_called

      Readonly :class:`bool`. Records whether this scope has been
      cancelled, either by an explicit call to :meth:`cancel` or by
      the deadline expiring.

   .. attribute:: cancelled_caught

      Readonly :class:`bool`. Records whether this scope caught a
      :exc:`~trio.Cancelled` exception. This requires two things: (1)
      the ``with`` block exited with a :exc:`~trio.Cancelled`
      exception, and (2) this scope is the one that was responsible
      for triggering this :exc:`~trio.Cancelled` exception.

   .. currentmodule:: trio

We also provide several convenience functions for the common situation
of just wanting to impose a timeout on some code:

.. autofunction:: move_on_after
   :with: cancel_scope

.. autofunction:: move_on_at
   :with: cancel_scope

.. autofunction:: fail_after
   :with: cancel_scope

.. autofunction:: fail_at
   :with: cancel_scope

Cheat sheet:

* If you want to impose a timeout on a function, but you don't care
  whether it timed out or not::

     with trio.move_on_after(TIMEOUT):
         await do_whatever()
     # carry on!

* If you want to impose a timeout on a function, and then do some
  recovery if it timed out::

     with trio.move_on_after(TIMEOUT) as cancel_scope:
         await do_whatever()
     if cancel_scope.cancelled_caught:
         # The operation timed out, try something else
         try_to_recover()

* If you want to impose a timeout on a function, and then if it times
  out then just give up and raise an error for your caller to deal
  with::

     with trio.fail_after(TIMEOUT):
         await do_whatever()

It's also possible to check what the current effective deadline is,
which is sometimes useful:

.. autofunction:: current_effective_deadline


.. _tasks:

Tasks let you do multiple things at once
----------------------------------------

One of trio's core design principles is: *no implicit
concurrency*. Every function executes in a straightforward,
top-to-bottom manner, finishing each operation before moving on to the
next – *like Guido intended*.

But, of course, the entire point of an async library is to let you do
multiple things at once. The one and only way to do that in trio is
through the task spawning interface. So if you want your program to
walk *and* chew gum, this is the section for you.


Nurseries and spawning
~~~~~~~~~~~~~~~~~~~~~~

Most libraries for concurrent programming let you spawn new child
tasks (or threads, or whatever) willy-nilly, whenever and where-ever
you feel like it. Trio is a bit different: you can't spawn a child
task unless you're prepared to be a responsible parent. The way you
demonstrate your responsibility is by creating a nursery::

   async with trio.open_nursery() as nursery:
       ...

And once you have a reference to a nursery object, you can spawn
children into that nursery::

   async def child():
       ...

   async def parent():
       async with trio.open_nursery() as nursery:
           # Make two concurrent calls to child()
           nursery.spawn(child)
           nursery.spawn(child)

This means that tasks form a tree: when you call :func:`run`, then
this creates an initial task, and all your other tasks will be
children, grandchildren, etc. of the initial task.

The crucial thing about this setup is that when we exit the ``async
with`` block, then the nursery cleanup code runs. The nursery cleanup
code does the following things:

* If the body of the ``async with`` block raised an exception, then it
  cancels all remaining child tasks and saves the exception.

* It watches for child tasks to exit. If a child task exits with an
  exception, then it cancels all remaining child tasks and saves the
  exception.

* Once all child tasks have exited:

  * It marks the nursery as "closed", so no new tasks can be spawned
    in it.

  * If there's just one saved exception, it re-raises it, or

  * If there are multiple saved exceptions, it re-raises them as a
    :exc:`MultiError`, or

  * if there are no saved exceptions, it exits normally.

Since all tasks are descendents of the initial task, one consequence
of this is that :func:`run` can't finish until all tasks have
finished.


Getting results from child tasks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``spawn`` method returns a :class:`Task` object that can be used
for various things – and in particular, for retrieving the task's
return value. Example::

   async def child_fn(x):
       return 2 * x

   async with trio.open_nursery() as nursery:
       child_task = nursery.spawn(child_fn, 3)
   # We've left the nursery, so we know child_task has completed
   assert child_task.result.unwrap() == 6

See :attr:`Task.result` and :class:`Result` for more details.


Child tasks and cancellation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In trio, child tasks inherit the parent nursery's cancel scopes. So in
this example, both the child tasks will be cancelled when the timeout
expires::

   with move_on_after(TIMEOUT):
       async with trio.open_nursery() as nursery:
           nursery.spawn(child1)
           nursery.spawn(child2)

Note that what matters here is the scopes that were active when
:func:`open_nursery` was called, *not* the scopes active when
``spawn`` is called. So for example, the timeout block below does
nothing at all::

   async with trio.open_nursery() as nursery:
       with move_on_after(TIMEOUT):  # don't do this!
           nursery.spawn(child)


Errors in multiple child tasks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Normally, in Python, only one thing happens at a time, which means
that only one thing can wrong at a time. Trio has no such
limitation. Consider code like::

    async def broken1():
        d = {}
        return d["missing"]

    async def broken2():
        seq = range(10)
        return seq[20]

    async def parent():
        async with trio.open_nursery() as nursery:
            nursery.spawn(broken1)
            nursery.spawn(broken2)

``broken1`` raises ``KeyError``. ``broken2`` raises
``IndexError``. Obviously ``parent`` should raise some error, but
what? In some sense, the answer should be "both of these at once", but
in Python there can only be one exception at a time.

Trio's answer is that it raises a :exc:`MultiError` object. This is a
special exception which encapsulates multiple exception objects –
either regular exceptions or nested :exc:`MultiError`\s. To make these
easier to work with, trio installs a custom :obj:`sys.excepthook` that
knows how to print nice tracebacks for unhandled :exc:`MultiError`\s,
and we also provide some helpful utilities like
:meth:`MultiError.catch`, which allows you to catch "part of" a
:exc:`MultiError`.


How to be a good parent task
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Supervising child tasks is a full time job. If you want your program
to do two things at once, then don't expect the parent task to do one
while a child task does another – instead, spawn two children and let
the parent focus on managing them.

So, don't do this::

    # bad idea!
    async with trio.open_nursery() as nursery:
        nursery.spawn(walk)
        await chew_gum()

Instead, do this::

    # good idea!
    async with trio.open_nursery() as nursery:
        nursery.spawn(walk)
        nursery.spawn(chew_gum)
        # now parent task blocks in the nursery cleanup code

The difference between these is that in the first example, if ``walk``
crashes, the parent is off distracted chewing gum, and won't
notice. In the second example, the parent is watching both children,
and will notice and respond appropriately if anything happens.


Spawning tasks without becoming a parent
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sometimes it doesn't make sense for the task that spawns a child to
take on responsibility for watching it. For example, a server task may
want to spawn a new task for each connection, but it can't listen for
connections and supervise children at the same time.

The solution here is simple once you see it: there's no requirement
that a nursery object stay in the task that created it! We can write
code like this::

   async def new_connection_listener(handler, nursery):
       while True:
           conn = await get_new_connection()
           nursery.spawn(handler, conn)

   async def server(handler):
       async with trio.open_nursery() as nursery:
           nursery.spawn(new_connection_listener, handler, nursery)

Now ``new_connection_listener`` can focus on handling new connections,
while its parent focuses on supervising both it and all the individual
connection handlers.

And remember that cancel scopes are inherited from the nursery,
**not** from the task that calls ``spawn``. So in this example, the
timeout does *not* apply to ``child`` (or to anything else)::

   async with do_spawn(nursery):
       with move_on_after(TIMEOUT):  # don't do this, it has no effect
           nursery.spawn(child)

   async with trio.open_nursery() as nursery:
       nursery.spawn(do_spawn, nursery)


Custom supervisors
~~~~~~~~~~~~~~~~~~

The default cleanup logic is often sufficient for simple cases, but
what if you want a more sophisticated supervisor? For example, maybe
you have `Erlang envy <http://learnyousomeerlang.com/supervisors>`__
and want features like automatic restart of crashed tasks. Trio itself
doesn't provide such a feature, but the nursery interface is designed
to give you all the tools you need to build such a thing, while
enforcing basic hygiene (e.g., it's not possible to build a supervisor
that exits and leaves orphaned tasks behind). And then hopefully
you'll wrap your fancy supervisor up in a library and put it on PyPI,
because building custom supervisors is a challenging task that most
people don't want to deal with!

For simple custom supervisors, it's often possible to lean on the
default nursery logic to take care of annoying details. For example,
here's a function that takes a list of functions, runs them all
concurrently, and returns the result from the one that finishes
first::

   async def race(*async_fns):
       if not async_fns:
           raise ValueError("must pass at least one argument")
       async with trio.open_nursery() as nursery:
           for async_fn in async_fns:
               nursery.spawn(async_fn)
           task_batch = await nursery.monitor.get_batch()
           nursery.cancel_scope.cancel()
           finished_task = task_batch[0]
           return nursery.reap_and_unwrap(finished_task)

This works by waiting until at least one task has finished, then
cancelling all remaining tasks and returning the result from the first
task. This implicitly invokes the default logic to take care of all
the other tasks, so we block to wait for the cancellation to finish,
and if any of them raise errors in the process we'll propagate
those.


Task-related API details
~~~~~~~~~~~~~~~~~~~~~~~~

The nursery API
+++++++++++++++

.. autofunction:: open_nursery
   :async-with: nursery

   Nursery objects provide the following interface:

   .. currentmodule:: None

   .. method:: spawn(async_fn, *args, name=None)

      Runs ``await async_fn(*args)`` in a new child task inside this nursery.

      This is *the* method for creating concurrent tasks in trio.

      It's possible to pass a nursery object into another task, which
      allows that task to spawn new tasks into the first task's
      nursery.

      The child task inherits its parent nursery's cancel scopes.

      :param async_fn: An async callable.
      :param args: Positional arguments for ``async_fn``. If you want
                   to pass keyword arguments, use
                   :func:`functools.partial`.
      :param name: The name for this task. Only used for
                   debugging/introspection
                   (e.g. ``repr(task_obj)``). If this isn't a string,
                   :meth:`spawn` will try to make it one. A common use
                   case is if you're wrapping a function before
                   spawning a new task, you might pass the original
                   function as the ``name=`` to make debugging easier.
      :return: the newly spawned task
      :rtype trio.Task:
      :raises RuntimeError: If this nursery is no longer open
                            (i.e. its ``async with`` block has
                            exited).

   .. attribute:: cancel_scope

      Creating a nursery also implicitly creates a cancellation scope,
      which is exposed as the :attr:`cancel_scope` attribute. This is
      used internally to implement the logic where if an error occurs
      then ``__aexit__`` cancels all children, but you can use it for
      other things, e.g. if you want to explicitly cancel all children
      in response to some external event.

   The remaining attributes and methods are mainly used for
   implementing new types of task supervisor:

   .. attribute:: monitor

      A :class:`~trio.UnboundedQueue` which receives each child
      :class:`~trio.Task` object when it exits.

   .. attribute:: children

      A :class:`frozenset` containing all the child
      :class:`~trio.Task` objects which are still running.

   .. attribute:: zombies

      A :class:`frozenset` containing all the child
      :class:`~trio.Task` objects which have exited, but not yet been
      reaped.

   .. method:: reap(task)

      Removes the given task from the :attr:`zombies` set.

      Calling this method indicates to the nursery that you have taken
      care of any cleanup needed. In particular, if the task exited
      with an exception and you don't call this method, then
      ``__aexit__`` will eventually re-raise that exception. If you do
      call this method, then ``__aexit__`` won't do anything.

      Once you call this method, then as far as trio is concerned the
      :class:`~trio.Task` object no longer exists. You can hold onto a
      reference to it as long as you like, but trio no longer has any
      record of it.

      :raises ValueError: If the given ``task`` is not in :attr:`zombies`.

   .. method:: reap_and_unwrap(task)

      A convenience shorthand for::

         nursery.reap(task)
         return task.result.unwrap()

   .. currentmodule:: trio


Task object API
+++++++++++++++

.. autofunction:: current_task()

.. class:: Task()

   A :class:`Task` object represents a concurrent "thread" of
   execution.

   .. attribute:: result

      If this :class:`Task` is still running, then its :attr:`result`
      attribute is ``None``. (This can be used to check whether a task
      has finished running.)

      Otherwise, this is a :class:`Result` object holding the value
      returned or the exception raised by the async function that was
      spawned to create this task.

   The next three methods allow another task to monitor the result of
   this task, even if it isn't supervising it:

   .. automethod:: wait

   .. automethod:: add_monitor

   .. automethod:: discard_monitor

   The remaining members are mostly useful for introspection and
   debugging:

   .. attribute:: name

      String containing this :class:`Task`\'s name. Usually (but not
      always) the name of the function this :class:`Task` is running.

   .. attribute:: coro

      This task's coroutine object. Example usage: extracting a stack
      trace.

   .. autoattribute:: parent_task


Working with :exc:`MultiError`\s
++++++++++++++++++++++++++++++++

.. autofunction:: format_exception

.. autoexception:: MultiError

   .. attribute:: exceptions

      The list of exception objects that this :exc:`MultiError`
      represents.

   .. automethod:: filter

   .. automethod:: catch
      :with:

Examples:

Suppose we have a handler function that discards :exc:`ValueError`\s::

    def handle_ValueError(exc):
        if isinstance(exc, ValueError):
            return None
        else:
            return exc

Then these both raise :exc:`KeyError`::

    with MultiError.catch(handle_ValueError):
         raise MultiError([KeyError(), ValueError()])

    with MultiError.catch(handle_ValueError):
         raise MultiError([
             ValueError(),
             MultiError([KeyError(), ValueError()]),
         ])

And both of these raise nothing at all::

    with MultiError.catch(handle_ValueError):
         raise MultiError([ValueError(), ValueError()])

    with MultiError.catch(handle_ValueError):
         raise MultiError([
             MultiError([ValueError(), ValueError()]),
             ValueError(),
         ])

You can also return a new or modified exception, for example::

    def convert_ValueError_to_MyCustomError(exc):
        if isinstance(exc, ValueError):
            # Similar to 'raise MyCustomError from exc'
            new_exc = MyCustomError(...)
            new_exc.__cause__ = exc
            return new_exc
        else:
            return exc

In the example above, we set ``__cause__`` as a form of explicit
context chaining. :meth:`MultiError.filter` and
:meth:`MultiError.catch` also perform implicit exception chaining – if
you return a new exception object, then the new object's
``__context__`` attribute will automatically be set to the original
exception.


Result objects
++++++++++++++

.. autoclass:: Result
   :members:

.. autoclass:: Value
   :members:

.. autoclass:: Error
   :members:

.. note::

   Since :class:`Result` objects are simple immutable data structures
   that don't otherwise interact with the trio machinery, it's safe to
   create and access :class:`Result` objects from any thread you like.


Task-local storage and run-local storage
----------------------------------------

`Not implemented yet! <https://github.com/python-trio/trio/issues/2>`__


.. _synchronization:

Synchronizing and communicating between tasks
---------------------------------------------

Trio provides a standard set of synchronization and inter-task
communication primitives. These objects' APIs are generally modelled
off of the analogous classes in the standard library, but with some
differences.


Blocking and non-blocking methods
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The standard library synchronization primitives have a variety of
mechanisms for specifying timeouts and blocking behavior, and of
signaling whether an operation returned due to success versus a
timeout.

In trio, we standardize on the following conventions:

* We don't provide timeout arguments. If you want a timeout, then use
  a cancel scope.

* For operations that have a non-blocking variant, the blocking and
  non-blocking variants are different methods with names like ``X``
  and ``X_nowait``, respectively. (This is similar to
  :class:`queue.Queue`, but unlike most of the classes in
  :mod:`threading`.) We like this approach because it allows us to
  make the blocking version async and the non-blocking version sync.

* When a non-blocking method cannot succeed (the queue is empty, the
  lock is already held, etc.), then it raises
  :exc:`trio.WouldBlock`. There's no equivalent to the
  :exc:`queue.Empty` versus :exc:`queue.Full` distinction – we just
  have the one exception that we use consistently.


Fairness
~~~~~~~~

These classes are all guaranteed to be "fair", meaning that when it
comes time to choose who will be next to acquire a lock, get an item
from a queue, etc., then it always goes to the task which has been
waiting longest. It's `not entirely clear
<https://github.com/python-trio/trio/issues/54>`__ whether this is the
best choice, but for now that's how it works.

As an example of what this means, here's a small program in which two
tasks compete for a lock. Notice that the task which releases the lock
always immedately attempts to re-acquire it, before the other task has
a chance to run. (And remember that we're doing cooperative
multi-tasking here, so it's actually *deterministic* that the task
releasing the lock will call :meth:`~Lock.acquire` before the other
task wakes up; in trio releasing a lock is not a check point.)  With
an unfair lock, this would result in the same task holding the lock
forever and the other task being starved out. But if you run this,
you'll see that the two tasks politely take turns::

   # fairness-demo.py

   import trio

   async def loopy_child(number, lock):
       while True:
           async with lock:
               print("Child {} has the lock!".format(number))
               await trio.sleep(0.5)

   async def main():
       async with trio.open_nursery() as nursery:
           lock = trio.Lock()
           nursery.spawn(loopy_child, 1, lock)
           nursery.spawn(loopy_child, 2, lock)

   trio.run(main)


Broadcasting an event with :class:`Event`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: Event
   :members:


Passing messages with :class:`Queue` and :class:`UnboundedQueue`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Trio provides two types of queues suitable for different
purposes. Where they differ is in their strategies for handling flow
control. Here's a toy example to demonstrate the problem. Suppose we
have a queue with two producers and one consumer::

   async def producer(queue):
       while True:
           await queue.put(1)

   async def consumer(queue):
       while True:
           print(await queue.get())

   async def main():
       # Trio's actual queue classes have countermeasures to prevent
       # this example from working, so imagine we have some sort of
       # platonic ideal of a queue here
       queue = trio.HypotheticalQueue()
       async with trio.open_nursery() as nursery:
           # Two producers
           nursery.spawn(producer, queue)
           nursery.spawn(producer, queue)
           # One consumer
           nursery.spawn(consumer, queue)

   trio.run(main)

If we naively cycle between these three tasks in round-robin style,
then we put an item, then put an item, then get an item, then put an
item, then put an item, then get an item, ... and since on each cycle
we add two items to the queue but only remove one, then over time the
queue size grows arbitrarily large, our latency is terrible, we run
out of memory, it's just generally bad news all around.

There are two potential strategies for avoiding this problem.

The preferred solution is to apply *backpressure*. If our queue starts
getting too big, then we can make the producers slow down by having
``put`` block until ``get`` has had a chance to remove an item. This
is the strategy used by :class:`trio.Queue`.

The other possibility is for the queue consumer to get greedy: each
time it runs, it could eagerly consume all of the pending items before
allowing another task to run. (In some other systems, this would
happen automatically because their queue's ``get`` method doesn't
invoke the scheduler unless it has to block. But :ref:`in trio, get is
always a check point <check-point-rule>`.) This would work, but it's a
bit risky: basically instead of applying backpressure to specifically
the producer tasks, we're applying it to *all* the tasks in our
system. The danger here is that if enough items have built up in the
queue, then "stopping the world" to process them all may cause
unacceptable latency spikes in unrelated tasks. Nonetheless, this is
still the right choice in situations where it's impossible to apply
backpressure more precisely. For example, when monitoring exiting
tasks, blocking tasks from reporting their death doesn't really
accomplish anything – the tasks are taking up memory either way,
etc. (In this particular case it `might be possible to do better
<https://github.com/python-trio/trio/issues/64>`__, but in general the
principle holds.) So this is the strategy implemented by
:class:`trio.UnboundedQueue`.

tl;dr: use :class:`Queue` if you can.

.. autoclass:: Queue
   :members:

.. autoclass:: UnboundedQueue
   :members:


Lower-level synchronization primitives
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Personally, I find that events and queues are usually enough to
implement most things I care about, and lead to easier to read code
than the lower-level primitives discussed in this section. But if you
need them, they're here. (If you find yourself reaching for these
because you're trying to implement a new higher-level synchronization
primitive, then you might also want to check out the facilities in
:mod:`trio.hazmat` for a more direct exposure of trio's underlying
synchronization logic. All of classes discussed in this section are
implemented on top of the public APIs in :mod:`trio.hazmat`; they
don't have any special access to trio's internals.)

.. autoclass:: Semaphore
   :members:

.. autoclass:: Lock
   :members:

.. autoclass:: Condition
   :members:


.. _threads:

Threads (if you must)
---------------------

In a perfect world, all third-party libraries and low-level APIs would
be natively async and integrated into Trio, and all would be happiness
and rainbows.

That world, alas, does not (yet) exist. Until it does, you may find
yourself needing to interact with non-Trio APIs that do rude things
like "blocking".

In acknowledgment of this reality, Trio provides two useful utilities
for working with real, operating-system level,
:mod:`threading`\-module-style threads. First, if you're in Trio but
need to push some work into a thread, there's
:func:`run_in_worker_thread`. And if you're in a thread and need to
communicate back with trio, there's the closely related
:func:`current_run_in_trio_thread` and
:func:`current_await_in_trio_thread`.

.. autofunction:: run_in_worker_thread

.. function:: current_run_in_trio_thread
              current_await_in_trio_thread

   Call these from inside a trio run to get a reference to the current
   run's :func:`run_in_trio_thread` or :func:`await_in_trio_thread`:

   .. function:: run_in_trio_thread(sync_fn, *args)
      :module:
   .. function:: await_in_trio_thread(async_fn, *args)
      :module:

   These functions schedule a call to ``sync_fn(*args)`` or ``await
   async_fn(*args)`` to happen in the main trio thread, wait for it to
   complete, and then return the result or raise whatever exception it
   raised.

   These are the *only* non-hazmat functions that interact with the
   trio run loop and that can safely be called from a different thread
   than the one that called :func:`trio.run`. These two functions
   *must* be called from a different thread than the one that called
   :func:`trio.run`. (After all, they're blocking functions!)

   .. warning::

      If the relevant call to :func:`trio.run` finishes while a call
      to ``await_in_trio_thread`` is in progress, then the call to
      ``async_fn`` will be :ref:`cancelled <cancellation>` and the
      resulting :exc:`~trio.Cancelled` exception may propagate out of
      ``await_in_trio_thread`` and into the calling thread. You should
      be prepared for this.

   :raises RunFinishedError: If the corresponding call to
      :func:`trio.run` has already completed.


This will probably be clearer with an example. Here we demonstrate how
to spawn a child thread, and then use a :class:`trio.Queue` to send
messages between the thread and a trio task::

   import trio
   import threading

   def thread_fn(await_in_trio_thread, request_queue, response_queue):
       while True:
           # Since we're in a thread, we can't call trio.Queue methods
           # directly -- so we use await_in_trio_thread to call them.
           request = await_in_trio_thread(request_queue.get)
           # We use 'None' as a request to quit
           if request is not None:
               response = request + 1
               await_in_trio_thread(response_queue.put, response)
           else:
               # acknowledge that we're shutting down, and then do it
               await_in_trio_thread(response_queue.put, None)
               return

   async def main():
       # Get a reference to the await_in_trio_thread function
       await_in_trio_thread = trio.current_await_in_trio_thread()
       request_queue = trio.Queue(1)
       response_queue = trio.Queue(1)
       thread = threading.Thread(
           target=thread_fn,
           args=(await_in_trio_thread, request_queue, response_queue))
       thread.start()

       # prints "1"
       await request_queue.put(0)
       print(await response_queue.get())

       # prints "2"
       await request_queue.put(1)
       print(await response_queue.get())

       # prints "None"
       await request_queue.put(None)
       print(await response_queue.get())
       thread.join()

   trio.run(main)


.. _instrumentation:

Debugging and instrumentation
-----------------------------

Trio tries hard to provide useful hooks for debugging and
instrumentation. Some are documented above (:attr:`Task.name`,
:meth:`Queue.statistics`, etc.). Here are some more:


Global statistics
~~~~~~~~~~~~~~~~~

.. autofunction:: current_statistics


Instrument API
~~~~~~~~~~~~~~

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

Since this hooks into trio at a rather low level, you do have to be
somewhat careful. The callbacks are run synchronously, and in many
cases if they error out then we don't have any plausible way to
propagate this exception (for instance, we might be deep in the guts
of the exception propagation machinery...). Therefore our `current
strategy <https://github.com/python-trio/trio/issues/47>`__ for handling
exceptions raised by instruments is to (a) dump a stack trace to
stderr and (b) disable the offending instrument.

You can register an initial list of instruments by passing them to
:func:`trio.run`. :func:`current_instruments` lets you introspect and
modify this list at runtime from inside trio:

.. autofunction:: current_instruments

And here's the instrument API:

.. autoclass:: trio.abc.Instrument
   :members:

The tutorial has a :ref:`fully-worked example
<tutorial-instrument-example>` of defining a custom instrument to log
trio's internal scheduling decisions.


Exceptions
----------

.. autoexception:: TrioInternalError

.. autoexception:: Cancelled

.. autoexception:: TooSlowError

.. autoexception:: WouldBlock

.. autoexception:: RunFinishedError
