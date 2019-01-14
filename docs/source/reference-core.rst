Trio's core functionality
=========================

.. module:: trio


Entering trio
-------------

If you want to use trio, then the first thing you have to do is call
:func:`trio.run`:

.. autofunction:: run


General principles
------------------

.. _checkpoints:

Checkpoints
~~~~~~~~~~~

When writing code using trio, it's very important to understand the
concept of a *checkpoint*. Many of trio's functions act as checkpoints.

A checkpoint is two things:

1. It's a point where trio checks for cancellation. For example, if
   the code that called your function set a timeout, and that timeout
   has expired, then the next time your function executes a checkpoint
   trio will raise a :exc:`Cancelled` exception. See
   :ref:`cancellation` below for more details.

2. It's a point where the trio scheduler checks its scheduling policy
   to see if it's a good time to switch to another task, and
   potentially does so. (Currently, this check is very simple: the
   scheduler always switches at every checkpoint. But `this might
   change in the future
   <https://github.com/python-trio/trio/issues/32>`__.)

When writing trio code, you need to keep track of where your
checkpoints are. Why? First, because checkpoints require extra
scrutiny: whenever you execute a checkpoint, you need to be prepared
to handle a :exc:`Cancelled` error, or for another task to run and
`rearrange some state out from under you
<https://glyph.twistedmatrix.com/2014/02/unyielding.html>`__. And
second, because you also need to make sure that you have *enough*
checkpoints: if your code doesn't pass through a checkpoint on a
regular basis, then it will be slow to notice and respond to
cancellation and – much worse – since trio is a cooperative
multi-tasking system where the *only* place the scheduler can switch
tasks is at checkpoints, it'll also prevent the scheduler from fairly
allocating time between different tasks and adversely effect the
response latency of all the other code running in the same
process. (Informally we say that a task that does this is "hogging the
run loop".)

So when you're doing code review on a project that uses trio, one of
the things you'll want to think about is whether there are enough
checkpoints, and whether each one is handled correctly. Of course this
means you need a way to recognize checkpoints. How do you do that?
The underlying principle is that any operation that blocks has to be a
checkpoint. This makes sense: if an operation blocks, then it might
block for a long time, and you'll want to be able to cancel it if a
timeout expires; and in any case, while this task is blocked we want
another task to be scheduled to run so our code can make full use of
the CPU.

But if we want to write correct code in practice, then this principle
is a little too sloppy and imprecise to be useful. How do we know
which functions might block?  What if a function blocks sometimes, but
not others, depending on the arguments passed / network speed / phase
of the moon? How do we figure out where the checkpoints are when
we're stressed and sleep deprived but still want to get this code
review right, and would prefer to reserve our mental energy for
thinking about the actual logic instead of worrying about check
points?

.. _checkpoint-rule:

Don't worry – trio's got your back. Since checkpoints are important
and ubiquitous, we make it as simple as possible to keep track of
them. Here are the rules:

* Regular (synchronous) functions never contain any checkpoints.

* Every async function provided by trio *always* acts as a check
  point; if you see ``await <something in trio>``, or ``async for
  ... in <a trio object>``, or ``async with <trio.something>``, then
  that's *definitely* a checkpoint.

  (Partial exception: for async context managers, it might be only the
  entry or only the exit that acts as a checkpoint; this is
  documented on a case-by-case basis.)

* Third-party async functions can act as checkpoints; if you see
  ``await <something>`` or one of its friends, then that *might* be a
  checkpoint. So to be safe, you should prepare for scheduling or
  cancellation happening there.

The reason we distinguish between trio functions and other functions
is that we can't make any guarantees about third party
code. Checkpoint-ness is a transitive property: if function A acts as
a checkpoint, and you write a function that calls function A, then
your function also acts as a checkpoint. If you don't, then it
isn't. So there's nothing stopping someone from writing a function
like::

   # technically legal, but bad style:
   async def why_is_this_async():
       return 7

that never calls any of trio's async functions. This is an async
function, but it's not a checkpoint. But why make a function async if
it never calls any async functions? It's possible, but it's a bad
idea. If you have a function that's not calling any async functions,
then you should make it synchronous. The people who use your function
will thank you, because it makes it obvious that your function is not
a checkpoint, and their code reviews will go faster.

(Remember how in the tutorial we emphasized the importance of the
:ref:`"async sandwich" <async-sandwich>`, and the way it means that
``await`` ends up being a marker that shows when you're calling a
function that calls a function that ... eventually calls one of trio's
built-in async functions? The transitivity of async-ness is a
technical requirement that Python imposes, but since it exactly
matches the transitivity of checkpoint-ness, we're able to exploit it
to help you keep track of checkpoints. Pretty sneaky, eh?)

A slightly trickier case is a function like::

   async def sleep_or_not(should_sleep):
       if should_sleep:
           await trio.sleep(1)
       else:
           pass

Here the function acts as a checkpoint if you call it with
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
            # recv() reads up to 'nbytes' bytes each time
            chunk = await sock.recv(nbytes)
            if not chunk:
                raise RuntimeError("socket unexpected closed")
            nbytes -= len(chunk)
            data += chunk
        return data

If called with an ``nbytes`` that's greater than zero, then it will
call ``sock.recv`` at least once, and ``recv`` is an async trio
function, and thus an unconditional checkpoint. So in this case,
``recv_exactly`` acts as a checkpoint. But if we do ``await
recv_exactly(sock, 0)``, then it will immediately return an empty
buffer without executing a checkpoint. If this were a function in
trio itself, then this wouldn't be acceptable, but you may decide you
don't want to worry about this kind of minor edge case in your own
code.

If you do want to be careful, or if you have some CPU-bound code that
doesn't have enough checkpoints in it, then it's useful to know that
``await trio.sleep(0)`` is an idiomatic way to execute a checkpoint
without doing anything else, and that
:func:`trio.testing.assert_checkpoints` can be used to test that an
arbitrary block of code contains a checkpoint.


Thread safety
~~~~~~~~~~~~~

The vast majority of trio's API is *not* thread safe: it can only be
used from inside a call to :func:`trio.run`. This manual doesn't
bother documenting this on individual calls; unless specifically noted
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

The default clock is currently implemented as :func:`time.perf_counter`
plus a large random offset. The idea here is to catch code that
accidentally uses :func:`time.perf_counter` early, which should help keep
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

We refer to :func:`move_on_after` as creating a "cancel scope", which
contains all the code that runs inside the ``with`` block. If the HTTP
request takes more than 30 seconds to run, then it will be cancelled:
we'll abort the request and we *won't* see ``result is ...`` printed
on the console; instead we'll go straight to printing the ``with block
finished`` message.

.. note::

   Note that this is a single 30 second timeout for the entire body of
   the ``with`` statement. This is different from what you might have
   seen with other Python libraries, where timeouts often refer to
   something `more complicated
   <http://docs.python-requests.org/en/master/user/quickstart/#timeouts>`__. We
   think this way is easier to reason about.

How does this work? There's no magic here: trio is built using
ordinary Python functionality, so we can't just abandon the code
inside the ``with`` block. Instead, we take advantage of Python's
standard way of aborting a large and complex piece of code: we raise
an exception.

Here's the idea: whenever you call a cancellable function like ``await
trio.sleep(...)`` or ``await sock.recv(...)`` – see :ref:`checkpoints`
– then the first thing that function does is to check if there's a
surrounding cancel scope whose timeout has expired, or otherwise been
cancelled. If so, then instead of performing the requested operation,
the function fails immediately with a :exc:`Cancelled` exception. In
this example, this probably happens somewhere deep inside the bowels
of ``do_http_get``. The exception then propagates out like any normal
exception (you could even catch it if you wanted, but that's generally
a bad idea), until it reaches the ``with move_on_after(...):``. And at
this point, the :exc:`Cancelled` exception has done its job – it's
successfully unwound the whole cancelled scope – so
:func:`move_on_after` catches it, and execution continues as normal
after the ``with`` block. And this all works correctly even if you
have nested cancel scopes, because every :exc:`Cancelled` object
carries an invisible marker that makes sure that the cancel scope that
triggered it is the only one that will catch it.


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
you have a task that has to do a lot of work without any I/O, then you
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

The end result is that trio has successfully cancelled exactly the
work that was happening within the scope that was cancelled.

Looking at this, you might wonder how you can tell whether the inner
block timed out – perhaps you want to do something different, like try
a fallback procedure or report a failure to our caller. To make this
easier, :func:`move_on_after`\´s ``__enter__`` function returns an
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
wouldn't fire again, and at this point our application would lock up
forever. But in trio, this *doesn't* happen: the ``await
conn.send_goodbye_msg()`` call is still inside the cancelled block, so
it will also raise :exc:`Cancelled`.

Of course, if you really want to make another blocking call in your
cleanup handler, trio will let you; it's trying to prevent you from
accidentally shooting yourself in the foot. Intentional foot-shooting
is no problem (or at least – it's not trio's problem). To do this,
create a new scope, and set its :attr:`~The cancel scope interface.shield`
attribute to :data:`True`::

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
cancellable operation... but we haven't gone into the details about
which operations are cancellable, and how exactly they behave when
they're cancelled.

Here's the rule: if it's in the trio namespace, and you use ``await``
to call it, then it's cancellable (see :ref:`checkpoints`
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
  socket receive buffer waiting for you to call ``recv`` again. And so
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
socket works: if the remote peer has disappeared, then our code may
never be able to actually send our shutdown notification, and it would
be nice if it didn't block forever trying. Therefore, the method for
closing a TLS-wrapped socket will *try* to send that notification –
and if it gets cancelled, then it will give up on sending the message,
but *will* still close the underlying socket before raising
:exc:`Cancelled`, so at least you don't leak that resource.


Cancellation API details
~~~~~~~~~~~~~~~~~~~~~~~~

The primitive operation for creating a new cancellation scope is:

.. autofunction:: open_cancel_scope
   :with: cancel_scope

Cancel scope objects provide the following interface:

.. interface:: The cancel scope interface

   .. attribute:: deadline

      Read-write, :class:`float`. An absolute time on the current
      run's clock at which this scope will automatically become
      cancelled. You can adjust the deadline by modifying this
      attribute, e.g.::

         # I need a little more time!
         cancel_scope.deadline += 30

      Note that for efficiency, the core run loop only checks for
      expired deadlines every once in a while. This means that in
      certain cases there may be a short delay between when the clock
      says the deadline should have expired, and when checkpoints
      start raising :exc:`~trio.Cancelled`. This is a very obscure
      corner case that you're unlikely to notice, but we document it
      for completeness. (If this *does* cause problems for you, of
      course, then `we want to know!
      <https://github.com/python-trio/trio/issues>`__)

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

   .. attribute:: cancelled_caught

      Readonly :class:`bool`. Records whether this scope caught a
      :exc:`~trio.Cancelled` exception. This requires two things: (1)
      the ``with`` block exited with a :exc:`~trio.Cancelled`
      exception, and (2) this scope is the one that was responsible
      for triggering this :exc:`~trio.Cancelled` exception.

   .. attribute:: cancel_called

      Readonly :class:`bool`. Records whether cancellation has been
      requested for this scope, either by an explicit call to
      :meth:`cancel` or by the deadline expiring.

      This attribute being True does *not* necessarily mean that
      the code within the scope has been, or will be, affected by
      the cancellation. For example, if :meth:`cancel` was called
      just before the scope exits, when it's too late to deliver
      a :exc:`~trio.Cancelled` exception, then this attribute will
      still be True.

      This attribute is mostly useful for debugging and introspection.
      If you want to know whether or not a chunk of code was actually
      cancelled, then :attr:`cancelled_caught` is usually more
      appropriate.

Trio also provides several convenience functions for the common
situation of just wanting to impose a timeout on some code:

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

Most libraries for concurrent programming let you start new child
tasks (or threads, or whatever) willy-nilly, whenever and where-ever
you feel like it. Trio is a bit different: you can't start a child
task unless you're prepared to be a responsible parent. The way you
demonstrate your responsibility is by creating a nursery::

   async with trio.open_nursery() as nursery:
       ...

And once you have a reference to a nursery object, you can start
children in that nursery::

   async def child():
       ...

   async def parent():
       async with trio.open_nursery() as nursery:
           # Make two concurrent calls to child()
           nursery.start_soon(child)
           nursery.start_soon(child)

This means that tasks form a tree: when you call :func:`run`, then
this creates an initial task, and all your other tasks will be
children, grandchildren, etc. of the initial task.

Essentially, the body of the ``async with`` block acts like an initial
task that's running inside the nursery, and then each call to
``nursery.start_soon`` adds another task that runs in parallel. Two
crucial things to keep in mind:

* If any task inside the nursery finishes with an unhandled exception,
  then the nursery immediately cancels all the tasks inside the
  nursery.

* Since all of the tasks are running concurrently inside the ``async
  with`` block, the block does not exit until *all* tasks have
  completed. If you've used other concurrency frameworks, then you can
  think of it as, the de-indentation at the end of the ``async with``
  automatically "joins" (waits for) all of the tasks in the nursery.

* Once all the tasks have finished, then:

  * The nursery is marked as "closed", meaning that no new tasks can
    be started inside it.

  * Any unhandled exceptions are re-raised inside the parent task. If
    there are multiple exceptions, then they're collected up into a
    single :exc:`MultiError` exception.

Since all tasks are descendents of the initial task, one consequence
of this is that :func:`run` can't finish until all tasks have
finished.


Child tasks and cancellation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In trio, child tasks inherit the parent nursery's cancel scopes. So in
this example, both the child tasks will be cancelled when the timeout
expires::

   with move_on_after(TIMEOUT):
       async with trio.open_nursery() as nursery:
           nursery.start_soon(child1)
           nursery.start_soon(child2)

Note that what matters here is the scopes that were active when
:func:`open_nursery` was called, *not* the scopes active when
``start_soon`` is called. So for example, the timeout block below does
nothing at all::

   async with trio.open_nursery() as nursery:
       with move_on_after(TIMEOUT):  # don't do this!
           nursery.start_soon(child)


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
            nursery.start_soon(broken1)
            nursery.start_soon(broken2)

``broken1`` raises ``KeyError``. ``broken2`` raises
``IndexError``. Obviously ``parent`` should raise some error, but
what? In some sense, the answer should be "both of these at once", but
in Python there can only be one exception at a time.

Trio's answer is that it raises a :exc:`MultiError` object. This is a
special exception which encapsulates multiple exception objects –
either regular exceptions or nested :exc:`MultiError`\s. To make these
easier to work with, trio installs a custom :obj:`sys.excepthook` that
knows how to print nice tracebacks for unhandled :exc:`MultiError`\s,
and it also provides some helpful utilities like
:meth:`MultiError.catch`, which allows you to catch "part of" a
:exc:`MultiError`.


Spawning tasks without becoming a parent
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sometimes it doesn't make sense for the task that starts a child to
take on responsibility for watching it. For example, a server task may
want to start a new task for each connection, but it can't listen for
connections and supervise children at the same time.

The solution here is simple once you see it: there's no requirement
that a nursery object stay in the task that created it! We can write
code like this::

   async def new_connection_listener(handler, nursery):
       while True:
           conn = await get_new_connection()
           nursery.start_soon(handler, conn)

   async def server(handler):
       async with trio.open_nursery() as nursery:
           nursery.start_soon(new_connection_listener, handler, nursery)

Notice that ``server`` opens a nursery and passes it to
``new_connection_listener``, and then ``new_connection_listener`` is
able to start new tasks as "siblings" of itself. Of course, in this
case, we could just as well have written::

   async def server(handler):
       async with trio.open_nursery() as nursery:
           while True:
               conn = await get_new_connection()
               nursery.start_soon(handler, conn)

\...but sometimes things aren't so simple, and this trick comes in
handy.

One thing to remember, though: cancel scopes are inherited from the
nursery, **not** from the task that calls ``start_soon``. So in this
example, the timeout does *not* apply to ``child`` (or to anything
else)::

   async def do_spawn(nursery):
       with move_on_after(TIMEOUT):  # don't do this, it has no effect
           nursery.start_soon(child)

   async with trio.open_nursery() as nursery:
       nursery.start_soon(do_spawn, nursery)


Custom supervisors
~~~~~~~~~~~~~~~~~~

The default cleanup logic is often sufficient for simple cases, but
what if you want a more sophisticated supervisor? For example, maybe
you have `Erlang envy <http://learnyousomeerlang.com/supervisors>`__
and want features like automatic restart of crashed tasks. Trio itself
doesn't provide these kinds of features, but you can build them on
top; Trio's goal is to enforce basic hygiene and then get out of your
way. (Specifically: Trio won't let you build a supervisor that exits
and leaves orphaned tasks behind, and if you have an unhandled
exception due to bugs or laziness then Trio will make sure they
propagate.) And then you can wrap your fancy supervisor up in a
library and put it on PyPI, because supervisors are tricky and there's
no reason everyone should have to write their own.

For example, here's a function that takes a list of functions, runs
them all concurrently, and returns the result from the one that
finishes first::

   async def race(*async_fns):
       if not async_fns:
           raise ValueError("must pass at least one argument")

       send_channel, receive_channel = trio.open_memory_channel(0)

       async def jockey(async_fn):
           await send_channel.send(await async_fn())

       async with trio.open_nursery() as nursery:
           for async_fn in async_fns:
               nursery.start_soon(jockey, async_fn)
           winner = await receive_channel.receive()
           nursery.cancel_scope.cancel()
           return winner

This works by starting a set of tasks which each try to run their
function, and then report back the value it returns. The main task
uses ``receive_channel.receive`` to wait for one to finish; as soon as
the first task crosses the finish line, it cancels the rest, and then
returns the winning value.

Here if one or more of the racing functions raises an unhandled
exception then Trio's normal handling kicks in: it cancels the others
and then propagates the exception. If you want different behavior, you
can get that by adding a ``try`` block to the ``jockey`` function to
catch exceptions and handle them however you like.


Task-related API details
~~~~~~~~~~~~~~~~~~~~~~~~

The nursery API
+++++++++++++++

.. autofunction:: open_nursery
   :async-with: nursery

Nursery objects provide the following interface:

.. interface:: The nursery interface

   .. method:: start_soon(async_fn, *args, name=None)

      Creates a new child task inside this nursery, and sets it up to
      run ``await async_fn(*args)``.

      This and :meth:`start` are the two fundamental methods for
      creating concurrent tasks in trio.

      Note that this is *not* an async function and you don't use await
      when calling it. It sets up the new task, but then returns
      immediately, *before* it has a chance to run. The new task won’t
      actually get a chance to do anything until some later point when
      you execute a checkpoint and the scheduler decides to run it.
      If you want to run a function and immediately wait for its result,
      then you don't need a nursery; just use ``await async_fn(*args)``.
      If you want to wait for the task to initialize itself before 
      continuing, see :meth:`start()`.

      It's possible to pass a nursery object into another task, which
      allows that task to start new child tasks in the first task's
      nursery.

      The child task inherits its parent nursery's cancel scopes.

      :param async_fn: An async callable.
      :param args: Positional arguments for ``async_fn``. If you want
                   to pass keyword arguments, use
                   :func:`functools.partial`.
      :param name: The name for this task. Only used for
                   debugging/introspection
                   (e.g. ``repr(task_obj)``). If this isn't a string,
                   :meth:`start_soon` will try to make it one. A
                   common use case is if you're wrapping a function
                   before spawning a new task, you might pass the
                   original function as the ``name=`` to make
                   debugging easier.
      :raises RuntimeError: If this nursery is no longer open
                            (i.e. its ``async with`` block has
                            exited).

   .. method:: start(async_fn, *args, name=None)
      :async:

      Like :meth:`start_soon`, but blocks until the new task has
      finished initializing itself, and optionally returns some
      information from it.

      The ``async_fn`` must accept a ``task_status`` keyword argument,
      and it must make sure that it (or someone) eventually calls
      ``task_status.started()``.

      The conventional way to define ``async_fn`` is like::

         async def async_fn(arg1, arg2, *, task_status=trio.TASK_STATUS_IGNORED):
             ...
             task_status.started()
             ...

      :attr:`trio.TASK_STATUS_IGNORED` is a special global object with
      a do-nothing ``started`` method. This way your function supports
      being called either like ``await nursery.start(async_fn, arg1,
      arg2)`` or directly like ``await async_fn(arg1, arg2)``, and
      either way it can call ``task_status.started()`` without
      worrying about which mode it's in. Defining your function like
      this will make it obvious to readers that it supports being used
      in both modes.

      Before the child calls ``task_status.started()``, it's
      effectively run underneath the call to :meth:`start`: if it
      raises an exception then that exception is reported by
      :meth:`start`, and does *not* propagate out of the nursery. If
      :meth:`start` is cancelled, then the child task is also
      cancelled.

      When the child calls ``task_status.started()``, it's moved from
      out from underneath :meth:`start` and into the given nursery.

      If the child task passes a value to
      ``task_status.started(value)``, then :meth:`start` returns this
      value. Otherwise it returns ``None``.

   .. attribute:: cancel_scope

      Creating a nursery also implicitly creates a cancellation scope,
      which is exposed as the :attr:`cancel_scope` attribute. This is
      used internally to implement the logic where if an error occurs
      then ``__aexit__`` cancels all children, but you can use it for
      other things, e.g. if you want to explicitly cancel all children
      in response to some external event.

   The last two attributes are mainly to enable introspection of the
   task tree, for example in debuggers.

   .. attribute:: parent_task

      The :class:`~trio.hazmat.Task` that opened this nursery.

   .. attribute:: child_tasks

      A :class:`frozenset` containing all the child
      :class:`~trio.hazmat.Task` objects which are still running.


.. attribute:: TASK_STATUS_IGNORED

   See :meth:`~The nursery interface.start`.


Working with :exc:`MultiError`\s
++++++++++++++++++++++++++++++++

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

We also monkey patch :class:`traceback.TracebackException` to be able
to handle formatting :exc:`MultiError`\s. This means that anything that
formats exception messages like :mod:`logging` will work out of the
box::

    import logging

    logging.basicConfig()

    try:
        raise MultiError([ValueError("foo"), KeyError("bar")])
    except:
        logging.exception("Oh no!")
        raise

Will properly log the inner exceptions:

.. code-block:: none

    ERROR:root:Oh no!
    Traceback (most recent call last):
      File "<stdin>", line 2, in <module>
    trio.MultiError: ValueError('foo',), KeyError('bar',)

    Details of embedded exception 1:

      ValueError: foo

    Details of embedded exception 2:

      KeyError: 'bar'


.. _task-local-storage:

Task-local storage
------------------

Suppose you're writing a server that responds to network requests, and
you log some information about each request as you process it. If the
server is busy and there are multiple requests being handled at the
same time, then you might end up with logs like this:

.. code-block:: none

   Request handler started
   Request handler started
   Request handler finished
   Request handler finished

In this log, it's hard to know which lines came from which
request. (Did the request that started first also finish first, or
not?) One way to solve this is to assign each request a unique
identifier, and then include this identifier in each log message:

.. code-block:: none

   request 1: Request handler started
   request 2: Request handler started
   request 2: Request handler finished
   request 1: Request handler finished

This way we can see that request 1 was slow: it started before request
2 but finished afterwards. (You can also get `much fancier
<https://opentracing.io/docs/>`__, but this is enough for an
example.)

Now, here's the problem: how does the logging code know what the
request identifier is? One approach would be to explicitly pass it
around to every function that might want to emit logs... but that's
basically every function, because you never know when you might need
to add a ``log.debug(...)`` call to some utility function buried deep
in the call stack, and when you're in the middle of a debugging a
nasty problem that last thing you want is to have to stop first and
refactor everything to pass through the request identifier! Sometimes
this is the right solution, but other times it would be much more
convenient if we could store the identifier in a global variable, so
that the logging function could look it up whenever it needed
it. Except... a global variable can only have one value at a time, so
if we have multiple handlers running at once then this isn't going to
work. What we need is something that's *like* a global variable, but
that can have different values depending on which request handler is
accessing it.

To solve this problem, Python 3.7 added a new module to the standard
library: :mod:`contextvars`. And not only does Trio have built-in
support for :mod:`contextvars`, but if you're using an earlier version
of Python, then Trio makes sure that a backported version of
:mod:`contextvars` is installed. So you can assume :mod:`contextvars`
is there and works regardless of what version of Python you're using.

Here's a toy example demonstrating how to use :mod:`contextvars`:

.. literalinclude:: reference-core/contextvar-example.py

Example output (yours may differ slightly):

.. code-block:: none

   request 1: Request handler started
   request 2: Request handler started
   request 0: Request handler started
   request 2: Helper task a started
   request 2: Helper task b started
   request 1: Helper task a started
   request 1: Helper task b started
   request 0: Helper task b started
   request 0: Helper task a started
   request 2: Helper task b finished
   request 2: Helper task a finished
   request 2: Request received finished
   request 0: Helper task a finished
   request 1: Helper task a finished
   request 1: Helper task b finished
   request 1: Request received finished
   request 0: Helper task b finished
   request 0: Request received finished

For more information, read the
`contextvar docs <https://docs.python.org/3.7/library/contextvars.html>`__.


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

* When a non-blocking method cannot succeed (the channel is empty, the
  lock is already held, etc.), then it raises :exc:`trio.WouldBlock`.
  There's no equivalent to the :exc:`queue.Empty` versus
  :exc:`queue.Full` distinction – we just have the one exception that
  we use consistently.


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
always immediately attempts to re-acquire it, before the other task has
a chance to run. (And remember that we're doing cooperative
multi-tasking here, so it's actually *deterministic* that the task
releasing the lock will call :meth:`~Lock.acquire` before the other
task wakes up; in trio releasing a lock is not a checkpoint.)  With
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
           nursery.start_soon(loopy_child, 1, lock)
           nursery.start_soon(loopy_child, 2, lock)

   trio.run(main)


Broadcasting an event with :class:`Event`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: Event
   :members:


.. _channels:

Using channels to pass values between tasks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

*Channels* allow you to safely and conveniently send objects between
different tasks. They're particularly useful for implementing
producer/consumer patterns.

The channel API is defined by the abstract base classes
:class:`trio.abc.SendChannel` and :class:`trio.abc.ReceiveChannel`.
You can use these to implement your own custom channels, that do
things like pass objects between processes or over the network. But in
many cases, you just want to pass objects between different tasks
inside a single process, and for that you can use
:func:`trio.open_memory_channel`:

.. autofunction:: open_memory_channel

.. note:: If you've used the :mod:`threading` or :mod:`asyncio`
   modules, you may be familiar with :class:`queue.Queue` or
   :class:`asyncio.Queue`. In Trio, :func:`open_memory_channel` is
   what you use when you're looking for a queue. The main difference
   is that Trio splits the classic queue interface up into two
   objects. The advantage of this is that it makes it possible to put
   the two ends in different processes, and that we can close the two
   sides separately.


A simple channel example
++++++++++++++++++++++++

Here's a simple example of how to use channels:

.. literalinclude:: reference-core/channels-simple.py

If you run this, it prints:

.. code-block:: none

   got value "message 0"
   got value "message 1"
   got value "message 2"

And then it hangs forever. (Use control-C to quit.)


.. _channel-shutdown:

Clean shutdown with channels
++++++++++++++++++++++++++++

Of course we don't generally like it when programs hang. What
happened? The problem is that the producer sent 3 messages and then
exited, but the consumer has no way to tell that the producer is gone:
for all it knows, another message might be coming along any moment. So
it hangs forever waiting for the 4th message.

Here's a new version that fixes this: it produces the same output as
the previous version, and then exits cleanly. The only change is the
addition of ``async with`` blocks inside the producer and consumer:

.. literalinclude:: reference-core/channels-shutdown.py
   :emphasize-lines: 10,15

The really important thing here is the producer's ``async with`` .
When the producer exits, this closes the ``send_channel``, and that
tells the consumer that no more messages are coming, so it can cleanly
exit its ``async for`` loop. Then the program shuts down because both
tasks have exited.

We also added an ``async with`` to the consumer. This isn't as
important, but can it help us catch mistakes or other problems. For
example, suppose that the consumer exited early for some reason –
maybe because of a bug. Then the producer would be sending messages
into the void, and might get stuck indefinitely. But, if the consumer
closes its ``receive_channel``, then the producer will get a
:exc:`BrokenResourceError` to alert it that it should stop sending
messages because no-one is listening.

If you want to see the effect of the consumer exiting early, try
adding a ``break`` statement to the ``async for`` loop – you should
see a :exc:`BrokenResourceError` from the producer.


.. _channel-mpmc:

Managing multiple producers and/or multiple consumers
+++++++++++++++++++++++++++++++++++++++++++++++++++++

You can also have multiple producers, and multiple consumers, all
sharing the same channel. However, this makes shutdown a little more
complicated.

For example, consider this naive extension of our previous example,
now with two producers and two consumers:

.. literalinclude:: reference-core/channels-mpmc-broken.py

The two producers, A and B, send 3 messages apiece. These are then
randomly distributed between the two consumers, X and Y. So we're
hoping to see some output like:

.. code-block:: none

   consumer Y got value '0 from producer B'
   consumer X got value '0 from producer A'
   consumer Y got value '1 from producer A'
   consumer Y got value '1 from producer B'
   consumer X got value '2 from producer B'
   consumer X got value '2 from producer A'

However, on most runs, that's not what happens – the first part of the
output is OK, and then when we get to the end the program crashes with
:exc:`ClosedResourceError`. If you run the program a few times, you'll
see that sometimes the traceback shows ``send`` crashing, and other
times it shows ``receive`` crashing, and you might even find that on
some runs it doesn't crash at all.

Here's what's happening: suppose that producer A finishes first. It
exits, and its ``async with`` block closes the ``send_channel``. But
wait! Producer B was still using that ``send_channel``... so the next
time B calls ``send``, it gets a :exc:`ClosedResourceError`.

Sometimes, though if we're lucky, the two producers might finish at
the same time (or close enough), so they both make their last ``send``
before either of them closes the ``send_channel``.

But, even if that happens, we're not out of the woods yet! After the
producers exit, the two consumers race to be the first to notice that
the ``send_channel`` has closed. Suppose that X wins the race. It
exits its ``async for`` loop, then exits the ``async with`` block...
and closes the ``receive_channel``, while Y is still using it. Again,
this causes a crash.

We could avoid this by using some complicated bookkeeping to make sure
that only the *last* producer and the *last* consumer close their
channel endpoints... but that would be tiresome and fragile.
Fortunately, there's a better way! Here's a fixed version of our
program above:

.. literalinclude:: reference-core/channels-mpmc-fixed.py
   :emphasize-lines: 7, 9, 10, 12, 13

This example demonstrates using the :meth:`SendChannel.clone
<trio.abc.SendChannel.clone>` and :meth:`ReceiveChannel.clone
<trio.abc.ReceiveChannel.clone>` methods. What these do is create
copies of our endpoints, that act just like the original – except that
they can be closed independently. And the underlying channel is only
closed after *all* the clones have been closed. So this completely
solves our problem with shutdown, and if you run this program, you'll
see it print its six lines of output and then exits cleanly.

Notice a small trick we use: the code in ``main`` creates clone
objects to pass into all the child tasks, and then closes the original
objects using ``async with``. Another option is to pass clones into
all-but-one of the child tasks, and then pass the original object into
the last task, like::

   # Also works, but is more finicky:
   send_channel, receive_channel = trio.open_memory_channel(0)
   nursery.start_soon(producer, "A", send_channel.clone())
   nursery.start_soon(producer, "B", send_channel)
   nursery.start_soon(consumer, "X", receive_channel.clone())
   nursery.start_soon(consumer, "Y", receive_channel)

But this is more error-prone, especially if you use a loop to spawn
the producers/consumers.

Just make sure that you don't write::

   # Broken, will cause program to hang:
   send_channel, receive_channel = trio.open_memory_channel(0)
   nursery.start_soon(producer, "A", send_channel.clone())
   nursery.start_soon(producer, "B", send_channel.clone())
   nursery.start_soon(consumer, "X", receive_channel.clone())
   nursery.start_soon(consumer, "Y", receive_channel.clone())

Here we pass clones into the tasks, but never close the original
objects. That means we have 3 send channel objects (the original + two
clones), but we only close 2 of them, so the consumers will hang
around forever waiting for that last one to be closed.


.. _channel-buffering:

Buffering in channels
+++++++++++++++++++++

When you call :func:`open_memory_channel`, you have to specify how
many values can be buffered internally in the channel. If the buffer
is full, then any task that calls :meth:`~trio.abc.SendChannel.send`
will stop and wait for another task to call
:meth:`~trio.abc.ReceiveChannel.receive`. This is useful because it
produces *backpressure*: if the channel producers are running faster
than the consumers, then it forces the producers to slow down.

You can disable buffering entirely, by doing
``open_memory_channel(0)``. In that case any task calls
:meth:`~trio.abc.SendChannel.send` will wait until another task calls
:meth:`~trio.abc.ReceiveChannel.receive`, and vice versa. This is similar to
how channels work in the `classic Communicating Sequential Processes
model <https://en.wikipedia.org/wiki/Channel_(programming)>`__, and is
a reasonable default if you aren't sure what size buffer to use.
(That's why we used it in the examples above.)

At the other extreme, you can make the buffer unbounded by using
``open_memory_channel(math.inf)``. In this case,
:meth:`~trio.abc.SendChannel.send` *always* returns immediately.
Normally, this is a bad idea. To see why, consider a program where the
producer runs more quickly than the consumer:

.. literalinclude:: reference-core/channels-backpressure.py

If you run this program, you'll see output like:

.. code-block:: none

   Sent message: 0
   Received message: 0
   Sent message: 1
   Sent message: 2
   Sent message: 3
   Sent message: 4
   Sent message: 5
   Sent message: 6
   Sent message: 7
   Sent message: 8
   Sent message: 9
   Received message: 1
   Sent message: 10
   Sent message: 11
   Sent message: 12
   ...

On average, the producer sends ten messages per second, but the
consumer only calls ``receive`` once per second. That means that each
second, the channel's internal buffer has to grow to hold an extra
nine items. After a minute, the buffer will have ~540 items in it;
after an hour, that grows to ~32,400. Eventually, the program will run
out of memory. And well before we run out of memory, our latency on
handling individual messages will become abysmal. For example, at the
one minute mark, the producer is sending message ~600, but the
producer is still processing message ~60. Message 600 will have to sit
in the channel for ~9 minutes before the consumer catches up and
processes it.

Now try replacing ``open_memory_channel(math.inf)`` with
``open_memory_channel(0)``, and run it again. We get output like:

.. code-block:: none

   Sent message: 0
   Received message: 0
   Received message: 1
   Sent message: 1
   Received message: 2
   Sent message: 2
   Sent message: 3
   Received message: 3
   ...

Now the ``send`` calls wait for the ``receive`` calls to finish, which
forces the producer to slow down to match the consumer's speed. (It
might look strange that some values are reported as "Received" before
they're reported as "Sent"; this happens because the actual
send/receive happen at the same time, so which line gets printed first
is random.)

Now, let's try setting a small but nonzero buffer size, like
``open_memory_channel(3)``. what do you think will happen?

I get:

.. code-block:: none

   Sent message: 0
   Received message: 0
   Sent message: 1
   Sent message: 2
   Sent message: 3
   Received message: 1
   Sent message: 4
   Received message: 2
   Sent message: 5
   ...

So you can see that the producer runs ahead by 3 messages, and then
stops to wait: when the consumer reads message 1, it sends message 4,
then when the consumer reads message 2, it sends message 5, and so on.
Once it reaches the steady state, this version acts just like our
previous version where we set the buffer size to 0, except that it
uses a bit more memory and each message sits in the buffer for a bit
longer before being processed (i.e., the message latency is higher).

Of course real producers and consumers are usually more complicated
than this, and in some situations, a modest amount of buffering might
improve throughput. But too much buffering wastes memory and increases
latency, so if you want to tune your application you should experiment
to see what value works best for you.

**Why do we even support unbounded buffers then?** Good question!
Despite everything we saw above, there are times when you actually do
need an unbounded buffer. For example, consider a web crawler that
uses a channel to keep track of all the URLs it still wants to crawl.
Each crawler runs a loop where it takes a URL from the channel,
fetches it, checks the HTML for outgoing links, and then adds the new
URLs to the channel. This creates a *circular flow*, where each
consumer is also a producer. In this case, if your channel buffer gets
full, then the crawlers will block when they try to add new URLs to
the channel, and if all the crawlers got blocked, then they aren't
taking any URLs out of the channel, so they're stuck forever in a
deadlock. Using an unbounded channel avoids this, because it means
that :meth:`~trio.abc.SendChannel.send` never blocks.


Lower-level synchronization primitives
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Personally, I find that events and channels are usually enough to
implement most things I care about, and lead to easier to read code
than the lower-level primitives discussed in this section. But if you
need them, they're here. (If you find yourself reaching for these
because you're trying to implement a new higher-level synchronization
primitive, then you might also want to check out the facilities in
:mod:`trio.hazmat` for a more direct exposure of trio's underlying
synchronization logic. All of classes discussed in this section are
implemented on top of the public APIs in :mod:`trio.hazmat`; they
don't have any special access to trio's internals.)

.. autoclass:: CapacityLimiter
   :members:

.. autoclass:: Semaphore
   :members:

.. autoclass:: Lock
   :members:

.. autoclass:: StrictFIFOLock
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
need to push some blocking I/O into a thread, there's
:func:`run_sync_in_worker_thread`. And if you're in a thread and need
to communicate back with trio, you can use a
:class:`BlockingTrioPortal`.


.. _worker-thread-limiting:

Trio's philosophy about managing worker threads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you've used other I/O frameworks, you may have encountered the
concept of a "thread pool", which is most commonly implemented as a
fixed size collection of threads that hang around waiting for jobs to
be assigned to them. These solve two different problems: First,
re-using the same threads over and over is more efficient than
starting and stopping a new thread for every job you need done;
basically, the pool acts as a kind of cache for idle threads. And
second, having a fixed size avoids getting into a situation where
100,000 jobs are submitted simultaneously, and then 100,000 threads
are spawned and the system gets overloaded and crashes. Instead, the N
threads start executing the first N jobs, while the other
(100,000 - N) jobs sit in a queue and wait their turn. Which is
generally what you want, and this is how
:func:`trio.run_sync_in_worker_thread` works by default.

The downside of this kind of thread pool is that sometimes, you need
more sophisticated logic for controlling how many threads are run at
once. For example, you might want a policy like "at most 20 threads
total, but no more than 3 of those can be running jobs associated with
the same user account", or you might want a pool whose size is
dynamically adjusted over time in response to system conditions.

It's even possible for a fixed-size policy to cause unexpected
`deadlocks <https://en.wikipedia.org/wiki/Deadlock>`__. Imagine a
situation where we have two different types of blocking jobs that you
want to run in the thread pool, type A and type B. Type A is pretty
simple: it just runs and completes pretty quickly. But type B is more
complicated: it has to stop in the middle and wait for some other work
to finish, and that other work includes running a type A job. Now,
suppose you submit N jobs of type B to the pool. They all start
running, and then eventually end up submitting one or more jobs of
type A. But since every thread in our pool is already busy, the type A
jobs don't actually start running – they just sit in a queue waiting
for the type B jobs to finish. But the type B jobs will never finish,
because they're waiting for the type A jobs. Our system has
deadlocked. The ideal solution to this problem is to avoid having type
B jobs in the first place – generally it's better to keep complex
synchronization logic in the main Trio thread. But if you can't do
that, then you need a custom thread allocation policy that tracks
separate limits for different types of jobs, and make it impossible
for type B jobs to fill up all the slots that type A jobs need to run.

So, we can see that it's important to be able to change the policy
controlling the allocation of threads to jobs. But in many frameworks,
this requires implementing a new thread pool from scratch, which is
highly non-trivial; and if different types of jobs need different
policies, then you may have to create multiple pools, which is
inefficient because now you effectively have two different thread
caches that aren't sharing resources.

Trio's solution to this problem is to split worker thread management
into two layers. The lower layer is responsible for taking blocking
I/O jobs and arranging for them to run immediately on some worker
thread. It takes care of solving the tricky concurrency problems
involved in managing threads and is responsible for optimizations like
re-using threads, but has no admission control policy: if you give it
100,000 jobs, it will spawn 100,000 threads. The upper layer is
responsible for providing the policy to make sure that this doesn't
happen – but since it *only* has to worry about policy, it can be much
simpler. In fact, all there is to it is the ``limiter=`` argument
passed to :func:`run_sync_in_worker_thread`. This defaults to a global
:class:`CapacityLimiter` object, which gives us the classic fixed-size
thread pool behavior. (See
:func:`current_default_worker_thread_limiter`.) But if you want to use
"separate pools" for type A jobs and type B jobs, then it's just a
matter of creating two separate :class:`CapacityLimiter` objects and
passing them in when running these jobs. Or here's an example of
defining a custom policy that respects the global thread limit, while
making sure that no individual user can use more than 3 threads at a
time::

   class CombinedLimiter:
        def __init__(self, first, second):
            self._first = first
            self._second = second

        async def acquire_on_behalf_of(self, borrower):
            # Acquire both, being careful to clean up properly on error
            await self._first.acquire_on_behalf_of(borrower)
            try:
                await self._second.acquire_on_behalf_of(borrower)
            except:
                self._first.release_on_behalf_of(borrower)
                raise

        def release_on_behalf_of(self, borrower):
            # Release both, being careful to clean up properly on error
            try:
                self._second.release_on_behalf_of(borrower)
            finally:
                self._first.release_on_behalf_of(borrower)


   # Use a weak value dictionary, so that we don't waste memory holding
   # limiter objects for users who don't have any worker threads running.
   USER_LIMITERS = weakref.WeakValueDictionary()
   MAX_THREADS_PER_USER = 3

   def get_user_limiter(user_id):
       try:
           return USER_LIMITERS[user_id]
       except KeyError:
           per_user_limiter = trio.CapacityLimiter(MAX_THREADS_PER_USER)
           global_limiter = trio.current_default_worker_thread_limiter()
           # IMPORTANT: acquire the per_user_limiter before the global_limiter.
           # If we get 100 jobs for a user at the same time, we want
           # to only allow 3 of them at a time to even compete for the
           # global thread slots.
           combined_limiter = CombinedLimiter(per_user_limiter, global_limiter)
           USER_LIMITERS[user_id] = combined_limiter
           return combined_limiter


   async def run_in_worker_thread_for_user(user_id, async_fn, *args, **kwargs):
       # *args belong to async_fn; **kwargs belong to run_sync_in_worker_thread
       kwargs["limiter"] = get_user_limiter(user_id)
       return await trio.run_sync_in_worker_thread(asycn_fn, *args, **kwargs)


Putting blocking I/O into worker threads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autofunction:: run_sync_in_worker_thread

.. autofunction:: current_default_worker_thread_limiter


Getting back into the trio thread from another thread
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: BlockingTrioPortal
   :members:

This will probably be clearer with an example. Here we demonstrate how
to spawn a child thread, and then use a :ref:`memory channel
<channels>` to send messages between the thread and a trio task:

.. literalinclude:: reference-core/blocking-trio-portal-example.py


Exceptions and warnings
-----------------------

.. autoexception:: Cancelled

.. autoexception:: TooSlowError

.. autoexception:: WouldBlock

.. autoexception:: EndOfChannel

.. autoexception:: BusyResourceError

.. autoexception:: ClosedResourceError

.. autoexception:: BrokenResourceError

.. autoexception:: RunFinishedError

.. autoexception:: TrioInternalError

.. autoexception:: TrioDeprecationWarning
   :show-inheritance:
