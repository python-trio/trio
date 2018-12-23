# Add the module file to the list of module files if it
# contains methodes to be exposed as public api
EXPORT_MODULE_FILES = [
    './trio/_core/_run.py', './trio/_core/_io_windows.py',
    './trio/_core/_io_epoll.py', './trio/_core/_io_kqueue.py'
]

# Add the functions to the list of exported functions
# if you want it to be exposed as public api
EXPORT_FUNCTIONS = [
    'current_iocp', 'register_with_iocp', 'wait_overlapped',
    'monitor_completion_key', 'wait_socket_readable', 'wait_socket_writable',
    'notify_socket_close', 'current_statistics', 'current_time',
    'current_clock', 'current_root_task', 'reschedule', 'spawn_system_task',
    'current_trio_token', 'wait_all_tasks_blocked', 'add_instrument',
    'remove_instrument'
]

# # ****************************************************************************
# # DO NOT EDIT PAST THIS POINT. ALL CHANGES MADE HERE WILL BE LOST AS GENERATED
# # ****************************************************************************

# # All of the following functions are exported as part of the trio or trio.hazmat
# # namespaces. The wrapper is called as common code to call the methods as
# # functions

# # Wrapper to call methods that are publicly available in trio or trio.hazmat
# def wrapper(ctx_name, meth_name, *args, **kwargs):
#     locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
#     try:
#         context = GLOBAL_RUN_CONTEXT
#         ctx = ctx_name.split('.')
#         while (ctx):
#             attr_name = ctx.pop(0)
#             context = getattr(context, attr_name)
#         meth = getattr(context, meth_name)
#     except AttributeError:
#         raise RuntimeError(
#             "must be called from async context " + attr_name
#         ) from None
#     return meth(*args, **kwargs)

# # Exported functions dependent on os and events
# # Windows
# if os.name == "nt":

#     def current_iocp(*args, **kwargs):
#        return wrapper('runner.io_manager', 'current_iocp')

#     def register_with_iocp(handle):
#         return wrapper('runner.io_manager', 'register_with_iocp', handle)

#     def wait_overlapped(handle, lpOverlapped):
#         return wrapper(
#             'runner.io_manager', 'wait_overlapped', handle, lpOverlapped
#         )

#     def monitor_completion_key():
#         return wrapper('runner.io_manager', 'monitor_completion_key')

#     def wait_socket_readable(sock):
#         return wrapper('runner.io_manager', 'wait_socket_readable', sock)

#     def wait_socket_writable(sock):
#         return wrapper('runner.io_manager', 'wait_socket_writable', sock)

#     def notify_socket_close(sock):
#         return wrapper('runner.io_manager', 'notify_socket_close', sock)

# # OSX
# elif hasattr(select, "epoll"):

#     def wait_readable(fd):
#         return wrapper('runner.io_manager', 'wait_readable', fd)

#     def wait_writable(fd):
#         return wrapper('runner.io_manager', 'wait_writable', fd)

#     def notify_fd_close(fd):
#         return wrapper('runner.io_manager', 'notify_fd_close', fd)

# # Linux
# elif hasattr(select, "kqueue"):

#     def current_kqueue():
#         return wrapper('runner.io_manager', 'current_kqueue')

#     def monitor_kevent(ident, filter):
#         return wrapper('runner.io_manager', 'monitor_kevent', ident, filter)

#     def wait_kevent(ident, filter, abort_func):
#         return wrapper(
#             'runner.io_manager', 'wait_kevent', ident, filter, abort_func
#         )

#     def wait_readable(fd):
#         return wrapper('runner.io_manager', 'wait_readable', fd)

#     def wait_writable(fd):
#         return wrapper('runner.io_manager', 'wait_writable', fd)

#     def notify_fd_close(fd):
#         return wrapper('runner.io_manager', 'notify_fd_close', fd)

# # Always available independent of os
# def current_statistics():
#     """Returns an object containing run-loop-level debugging information.

#     Currently the following fields are defined:

#     * ``tasks_living`` (int): The number of tasks that have been spawned
#         and not yet exited.
#     * ``tasks_runnable`` (int): The number of tasks that are currently
#         queued on the run queue (as opposed to blocked waiting for something
#         to happen).
#     * ``seconds_to_next_deadline`` (float): The time until the next
#         pending cancel scope deadline. May be negative if the deadline has
#         expired but we haven't yet processed cancellations. May be
#         :data:`~math.inf` if there are no pending deadlines.
#     * ``run_sync_soon_queue_size`` (int): The number of
#         unprocessed callbacks queued via
#         :meth:`trio.hazmat.TrioToken.run_sync_soon`.
#     * ``io_statistics`` (object): Some statistics from trio's I/O
#         backend. This always has an attribute ``backend`` which is a string
#         naming which operating-system-specific I/O backend is in use; the
#         other attributes vary between backends.

#     """
#     return wrapper('runner', 'current_statistics')

# def current_time():
#     """Returns the current time according to trio's internal clock.

#     Returns:
#         float: The current time.

#     Raises:
#         RuntimeError: if not inside a call to :func:`trio.run`.

#     """
#     return wrapper('runner', 'current_time')

# def current_clock():
#     """Returns the current :class:`~trio.abc.Clock`.

#     """
#     return wrapper('runner', 'current_clock')

# def current_root_task():
#     """Returns the current root :class:`Task`.

#     This is the task that is the ultimate parent of all other tasks.

#     """
#     return wrapper('runner', 'current_root_task')

# def reschedule(task, next_send=Runner._NO_SEND, *args, **kwargs):
#     """Reschedule the given task with the given
#     :class:`outcome.Outcome`.

#     See :func:`wait_task_rescheduled` for the gory details.

#     There must be exactly one call to :func:`reschedule` for every call to
#     :func:`wait_task_rescheduled`. (And when counting, keep in mind that
#     returning :data:`Abort.SUCCEEDED` from an abort callback is equivalent
#     to calling :func:`reschedule` once.)

#     Args:
#         task (trio.hazmat.Task): the task to be rescheduled. Must be blocked
#         in a call to :func:`wait_task_rescheduled`.
#         next_send (outcome.Outcome): the value (or error) to return (or
#         raise) from :func:`wait_task_rescheduled`.

#     """
#     return wrapper(
#         'runner', 'reschedule', task, next_send=next_send, *args, **kwargs
#     )

# def spawn_system_task(async_fn, *args, name=None, **kwargs):
#     """Spawn a "system" task.

#     System tasks have a few differences from regular tasks:

#     * They don't need an explicit nursery; instead they go into the
#         internal "system nursery".

#     * If a system task raises an exception, then it's converted into a
#         :exc:`~trio.TrioInternalError` and *all* tasks are cancelled. If you
#         write a system task, you should be careful to make sure it doesn't
#         crash.

#     * System tasks are automatically cancelled when the main task exits.

#     * By default, system tasks have :exc:`KeyboardInterrupt` protection
#         *enabled*. If you want your task to be interruptible by control-C,
#         then you need to use :func:`disable_ki_protection` explicitly (and
#         come up with some plan for what to do with a
#         :exc:`KeyboardInterrupt`, given that system tasks aren't allowed to
#         raise exceptions).

#     * System tasks do not inherit context variables from their creator.

#     Args:
#         async_fn: An async callable.
#         args: Positional arguments for ``async_fn``. If you want to pass
#             keyword arguments, use :func:`functools.partial`.
#         name: The name for this task. Only used for debugging/introspection
#             (e.g. ``repr(task_obj)``). If this isn't a string,
#             :func:`spawn_system_task` will try to make it one. A common use
#             case is if you're wrapping a function before spawning a new
#             task, you might pass the original function as the ``name=`` to
#             make debugging easier.

#     Returns:
#         Task: the newly spawned task

#     """
#     return wrapper(
#         'runner', 'spawn_system_task', async_fn, *args, name=name, **kwargs
#     )

# def current_trio_token():
#     """Retrieve the :class:`TrioToken` for the current call to
#     :func:`trio.run`.

#     """
#     return wrapper('runner', 'current_trio_token')

# def wait_all_tasks_blocked(cushion=0.0, tiebreaker=0):
#     """Block until there are no runnable tasks.

#     This is useful in testing code when you want to give other tasks a
#     chance to "settle down". The calling task is blocked, and doesn't wake
#     up until all other tasks are also blocked for at least ``cushion``
#     seconds. (Setting a non-zero ``cushion`` is intended to handle cases
#     like two tasks talking to each other over a local socket, where we
#     want to ignore the potential brief moment between a send and receive
#     when all tasks are blocked.)

#     Note that ``cushion`` is measured in *real* time, not the trio clock
#     time.

#     If there are multiple tasks blocked in :func:`wait_all_tasks_blocked`,
#     then the one with the shortest ``cushion`` is the one woken (and
#     this task becoming unblocked resets the timers for the remaining
#     tasks). If there are multiple tasks that have exactly the same
#     ``cushion``, then the one with the lowest ``tiebreaker`` value is
#     woken first. And if there are multiple tasks with the same ``cushion``
#     and the same ``tiebreaker``, then all are woken.

#     You should also consider :class:`trio.testing.Sequencer`, which
#     provides a more explicit way to control execution ordering within a
#     test, and will often produce more readable tests.

#     Example:
#         Here's an example of one way to test that trio's locks are fair: we
#         take the lock in the parent, start a child, wait for the child to be
#         blocked waiting for the lock (!), and then check that we can't
#         release and immediately re-acquire the lock::

#             async def lock_taker(lock):
#                 await lock.acquire()
#                 lock.release()

#             async def test_lock_fairness():
#                 lock = trio.Lock()
#                 await lock.acquire()
#                 async with trio.open_nursery() as nursery:
#                     child = nursery.start_soon(lock_taker, lock)
#                     # child hasn't run yet, we have the lock
#                     assert lock.locked()
#                     assert lock._owner is trio.current_task()
#                     await trio.testing.wait_all_tasks_blocked()
#                     # now the child has run and is blocked on lock.acquire(), we
#                     # still have the lock
#                     assert lock.locked()
#                     assert lock._owner is trio.current_task()
#                     lock.release()
#                     try:
#                         # The child has a prior claim, so we can't have it
#                         lock.acquire_nowait()
#                     except trio.WouldBlock:
#                         assert lock._owner is child
#                         print("PASS")
#                     else:
#                         print("FAIL")

#     """
#     return wrapper(
#         'runner',
#         'wait_all_tasks_blocked',
#         cushion=cushion,
#         tiebreaker=tiebreaker
#     )

# def add_instrument(instrument):
#     """Start instrumenting the current run loop with the given instrument.

#     Args:
#         instrument (trio.abc.Instrument): The instrument to activate.

#     If ``instrument`` is already active, does nothing.

#     """
#     return wrapper('runner', 'add_instrument', instrument)

# def remove_instrument(instrument):
#     """Stop instrumenting the current run loop with the given instrument.

#     Args:
#         instrument (trio.abc.Instrument): The instrument to de-activate.

#     Raises:
#         KeyError: if the instrument is not currently active. This could
#             occur either because you never added it, or because you added it
#             and then it raised an unhandled exception and was automatically
#             deactivated.

#     """
#     return wrapper('runner', 'remove_instrument', instrument)
