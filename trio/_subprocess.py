import math
import os
import select
import shlex
import signal
import subprocess
import sys
import attr
from async_generator import async_generator, yield_, asynccontextmanager
from typing import List, Tuple

from . import _core
from ._abc import AsyncResource, HalfCloseableStream, ReceiveStream
from ._sync import Lock
from ._highlevel_generic import NullStream
from ._subprocess_platform import (
    wait_child_exiting, create_pipe_to_child_stdin,
    create_pipe_from_child_output
)

__all__ = [
    "Process",
    "ProcessStream",
    "CompletedProcess",
    "open_process",
    "run_process",
    "delegate_to_process",
]


class Process(AsyncResource):
    r"""Execute a child program in a new process.

    Like :class:`subprocess.Popen`, but async.

    Constructing a :class:`Process` immediately spawns the child
    process, or throws an :exc:`OSError` if the spawning fails (for
    example, if the specified command could not be found).
    After construction, you can communicate with the child process
    by writing data to its :attr:`stdin` stream (a
    :class:`~trio.abc.SendStream`), reading data from its :attr:`stdout`
    and/or :attr:`stderr` streams (both :class:`~trio.abc.ReceiveStream`\s),
    sending it signals using :meth:`terminate`, :meth:`kill`, or
    :meth:`send_signal`, and waiting for it to exit using :meth:`wait`.

    Each standard stream is only available if it was specified at
    :class:`Process` construction time that a pipe should be created
    for it.  For example, if you constructed with
    ``stdin=subprocess.PIPE``, you can write to the :attr:`stdin`
    stream, else :attr:`stdin` will be ``None``.

    :class:`Process` implements :class:`~trio.abc.AsyncResource`, so
    you can use it as an async context manager or call its
    :meth:`aclose` method directly. "Closing" a :class:`Process` will
    close any pipes to the child and wait for it to exit; if the call
    to :meth:`aclose` is cancelled, the child will be terminated
    and we will ensure it has finished exiting before allowing the
    cancellation to propagate. It is *strongly recommended* that
    process lifetime be scoped using an ``async with`` block wherever
    possible, to avoid winding up with processes hanging around longer
    than you were planning on.

    By default, process termination when :meth:`aclose` is cancelled
    calls :meth:`kill`, which cannot be caught by the process.  *UNIX
    only:* If you want to allow the process to perform its own cleanup
    before exiting, you can specify a ``shutdown_signal`` at
    construction time; then :func:`aclose` will send the process that
    signal instead of killing it outright, and will wait up to
    ``shutdown_timeout`` seconds (forever if unspecified) for the
    process to exit in response to that signal. If the shutdown
    timeout expires after sending the shutdown signal, the process
    gets forcibly killed. (This might work on Windows if you can
    find a signal that Python knows how to send and the subprocess
    knows how to handle, but your options there are too limited
    to be of much use: only ``CTRL_BREAK_EVENT`` can be sent to
    a process group (not ``CTRL_C_EVENT``), and Python at least
    has no way of catching it.)

    Args:
      command (list or str): The command to run. Typically this is a
          sequence of strings such as ``['ls', '-l', 'directory with spaces']``,
          where the first element names the executable to invoke and the other
          elements specify its arguments. With ``shell=True`` in the
          ``**options``, or on Windows, ``command`` may alternatively
          be a string, which will be parsed following platform-dependent
          :ref:`quoting rules <subprocess-quoting>`.
      stdin: Specifies what the child process's standard input
          stream should connect to: output written by the parent
          (``subprocess.PIPE``), nothing (``subprocess.DEVNULL``),
          or an open file (pass a file descriptor or something whose
          ``fileno`` method returns one). If ``stdin`` is unspecified,
          the child process will have the same standard input stream
          as its parent.
      stdout: Like ``stdin``, but for the child process's standard output
          stream.
      stderr: Like ``stdin``, but for the child process's standard error
          stream. An additional value ``subprocess.STDOUT`` is supported,
          which causes the child's standard output and standard error
          messages to be intermixed on a single standard output stream,
          attached to whatever the ``stdout`` option says to attach it to.
      shutdown_signal (int): If specified, the process will be sent
          this signal when :meth:`aclose` or :meth:`join` is
          cancelled, which might give it a chance to clean itself up
          before exiting. The default shutdown signal forcibly kills
          the process and cannot be caught. A value of zero will send
          no signal, just close pipes to the process when we want it
          to exit. Zero is the only value likely to work on Windows.
      shutdown_timeout (float): If specified, and the process does not
          exit within this many seconds after receiving the
          ``shutdown_signal``, it will be forcibly killed anyway. The
          default is to wait as long as it takes for the process to
          exit. If you pass a ``shutdown_timeout`` but no
          ``shutdown_signal``, ``SIGTERM`` is used as the shutdown
          signal.  (On Windows this will still kill the process
          immediately, so you should pass a different signal there.)
      **options: Other :ref:`general subprocess options <subprocess-options>`
          are also accepted.

    Attributes:
      args (str or list): The ``command`` passed at construction time,
          specifying the process to execute and its arguments.
      pid (int): The process ID of the child process managed by this object.
      stdin (trio.abc.SendStream or None): A stream connected to the child's
          standard input stream: when you write bytes here, they become available
          for the child to read. Only available if the :class:`Process`
          was constructed using ``stdin=PIPE``; otherwise this will be None.
      stdout (trio.abc.ReceiveStream or None): A stream connected to
          the child's standard output stream: when the child writes to
          standard output, the written bytes become available for you
          to read here. Only available if the :class:`Process` was
          constructed using ``stdout=PIPE``; otherwise this will be None.
      stderr (trio.abc.ReceiveStream or None): A stream connected to
          the child's standard error stream: when the child writes to
          standard error, the written bytes become available for you
          to read here. Only available if the :class:`Process` was
          constructed using ``stderr=PIPE``; otherwise this will be None.
      cancelled (bool or None): If a call to :meth:`aclose` or :meth:`join`
          has completed, this is False if the process was allowed to exit
          on its own and True if we helped its exit along due to a
          cancellation. If no call to :meth:`aclose` or :meth:`join`
          has completed, this is None. Calls to :meth:`shutdown`
          work like :meth:`join` in a cancelled scope, so set
          :attr:`cancelled` unconditionally to True if the process
          is still running.

    """

    universal_newlines = False
    encoding = None
    errors = None

    # Available for the per-platform wait_child_exiting() implementations
    # to stash some state; waitid platforms use this to avoid spawning
    # arbitrarily many threads if wait() keeps getting cancelled.
    _wait_for_exit_data = None

    def __init__(
        self,
        command,
        *,
        stdin=None,
        stdout=None,
        stderr=None,
        shutdown_signal=None,
        shutdown_timeout=None,
        **options
    ):
        for key in (
            'universal_newlines', 'text', 'encoding', 'errors', 'bufsize'
        ):
            if options.get(key):
                raise TypeError(
                    "trio.Process only supports communicating over "
                    "unbuffered byte streams; the '{}' option is not supported"
                    .format(key)
                )

        self.stdin = None
        self.stdout = None
        self.stderr = None

        if shutdown_timeout is not None and shutdown_signal is None:
            shutdown_signal = signal.SIGTERM
        self._shutdown_signal = shutdown_signal
        self._shutdown_timeout = shutdown_timeout
        self.cancelled = None

        self._wait_lock = Lock()

        # State needed by the logic in the property `failed`:
        # - signals we've sent the process before we knew it had exited
        self._signals_sent_before_exit = set()

        # - whether we closed its stdout or stderr without receiving EOF
        #   before we knew it had exited
        self._maybe_broke_pipe_before_exit = None

        if os.name == "posix":
            if isinstance(command, str) and not options.get("shell"):
                raise TypeError(
                    "command must be a sequence (not a string) if shell=False "
                    "on UNIX systems"
                )
            if not isinstance(command, str) and options.get("shell"):
                raise TypeError(
                    "command must be a string (not a sequence) if shell=True "
                    "on UNIX systems"
                )

        if stdin == subprocess.PIPE:
            self.stdin, stdin = create_pipe_to_child_stdin()
        if stdout == subprocess.PIPE:
            self.stdout, stdout = create_pipe_from_child_output()
        if stderr == subprocess.STDOUT:
            # If we created a pipe for stdout, pass the same pipe for
            # stderr.  If stdout was some non-pipe thing (DEVNULL or a
            # given FD), pass the same thing. If stdout was passed as
            # None, keep stderr as STDOUT to allow subprocess to dup
            # our stdout. Regardless of which of these is applicable,
            # don't create a new trio stream for stderr -- if stdout
            # is piped, stderr will be intermixed on the stdout stream.
            if stdout is not None:
                stderr = stdout
        elif stderr == subprocess.PIPE:
            self.stderr, stderr = create_pipe_from_child_output()

        try:
            self._proc = subprocess.Popen(
                command, stdin=stdin, stdout=stdout, stderr=stderr, **options
            )
        finally:
            # Close the parent's handle for each child side of a pipe;
            # we want the child to have the only copy, so that when
            # it exits we can read EOF on our side.
            if self.stdin is not None:
                os.close(stdin)
            if self.stdout is not None:
                os.close(stdout)
            if self.stderr is not None:
                os.close(stderr)

        self.args = self._proc.args
        self.pid = self._proc.pid

    def __repr__(self):
        if self.returncode is None:
            status = "running with PID {}".format(self.pid)
        else:
            if self.returncode < 0:
                status = "exited with signal {}".format(-self.returncode)
            else:
                status = "exited with status {}".format(self.returncode)
            if self.returncode != 0 and not self.failed:
                status += " (our fault)"
        return "<trio.Process {!r}: {}>".format(self.args, status)

    @property
    def returncode(self):
        """The exit status of the process (an integer), or ``None`` if it is
        not yet known to have exited.

        By convention, a return code of zero indicates success.  On
        UNIX, negative values indicate termination due to a signal,
        e.g., -11 if terminated by signal 11 (``SIGSEGV``).  On
        Windows, a process that exits due to a call to
        :meth:`Process.terminate` will have an exit status of 1.

        Accessing this attribute does not check for termination; use
        :meth:`poll` or :meth:`wait` for that.
        """
        return self._proc.returncode

    @property
    def failed(self):
        """Whether this process should be considered to have failed.

        If the process hasn't exited yet, this is None. Otherwise, it is False
        if the :attr:`returncode` is zero, and True otherwise, unless the
        nonzero exit status appears to have been potentially caused by
        something done by the parent Trio process. Specifically:

        * If we terminate a process and it later exits for any reason,
          we don't consider that a failure. (On Windows it's hard to
          tell if the exit was caused by the termination or not, but
          termination can't be blocked so it's a good bet. On UNIX
          there are plenty of processes that respond to ``SIGTERM`` by
          cleaning up and then exiting with a nonzero status, and we'd
          like to consider that to be caused by the ``SIGTERM`` even
          though it's not reported as "exited due to ``SIGTERM``"
          directly.)

        * If we close a process's standard output or error stream
          before receiving EOF on it and the process later exits for
          any reason, we don't consider that a failure. (We could
          restrict this to only ``SIGPIPE`` exits on UNIX, but then we
          wouldn't handle processes that catch ``SIGPIPE`` and raise
          an ordinary error instead, like Python.)

        * On UNIX, if we send a process a signal and it later exits due
          to that signal, we don't consider that a failure. (This covers
          signals like ``SIGHUP``, ``SIGINT``, etc, which are exit
          signals for some processes and not for others.)

        The higher-level subprocess API functions such as :func:`run_process`
        use :attr:`failed` to determine whether they should throw a
        :exc:`subprocess.CalledProcessError` or not.

        """
        if self.returncode is None:
            return None
        return (
            self.returncode != 0
            and signal.SIGTERM not in self._signals_sent_before_exit
            and not self._maybe_broke_pipe_before_exit
            and -self.returncode not in self._signals_sent_before_exit
        )

    async def _close_pipes(self):
        if self.stdin is not None:
            await self.stdin.aclose()
        if self.stdout is not None:
            await self.stdout.aclose()
        if self.stderr is not None:
            await self.stderr.aclose()

    async def aclose(self):
        """Close any pipes we have to the process (both input and output)
        and wait for it to exit.

        If cancelled, shuts down the process following the shutdown
        parameters specified at construction time, or forcibly
        terminates the process if no shutdown parameters were given.
        The process is guaranteed to have exited by the time the call
        to :meth:`aclose` completes, whether normally or via an
        exception.
        """
        with _core.open_cancel_scope(shield=True):
            await self._close_pipes()
        await self.join()

    def _check_maybe_broke_pipe(self):
        """Called when the child process exits to set
        self._maybe_broke_pipe_before_exit, based on whether
        we have yet closed the child's stdout or stderr before reading
        EOF from it. This is an input to the logic in ``failed``.
        """
        if self._maybe_broke_pipe_before_exit is not None:
            return
        for stream in (self.stdout, self.stderr):
            if stream is not None and stream.did_close_before_receiving_eof:
                self._maybe_broke_pipe_before_exit = True
                break
        else:
            self._maybe_broke_pipe_before_exit = False

    async def wait(self):
        """Block until the process exits.

        Returns:
          The exit status of the process; see :attr:`returncode`.
        """
        if self.poll() is None:
            async with self._wait_lock:
                if self.poll() is None:
                    await wait_child_exiting(self)
                    self._proc.wait()
            self._check_maybe_broke_pipe()
            return self.returncode
        await _core.checkpoint()
        return self.returncode

    async def join(self):
        """Block until the process exits, and terminate the process if the
        call to :meth:`join` is cancelled.

        :meth:`join` behaves like :meth:`aclose` except that it
        doesn't close pipes. This is primarily useful if I/O is being
        handled in a concurrent task and an orderly shutdown signal
        was specified at :class:`Process` construction time; it
        ensures that if the call to :meth:`join` is cancelled, any
        output the process writes as it is shutting down won't be
        lost. If you don't have a concurrent task handling I/O, you
        should probably use :meth:`aclose` instead. Otherwise, you
        might get a deadlock as the process blocks waiting for I/O
        while you're waiting for it to exit.

        Returns:
          The exit status of the process; see :attr:`returncode`.

        """
        try:
            await self.wait()
            if self.cancelled is None:
                self.cancelled = False
            return self.returncode

        except (KeyboardInterrupt, _core.Cancelled):
            if self.cancelled is None:
                self.cancelled = True
            raise

        finally:
            if self.returncode is None and self._shutdown_signal is not None:
                with _core.open_cancel_scope(shield=True) as scope:
                    if self._shutdown_timeout is not None:
                        scope.deadline = (
                            _core.current_time() + self._shutdown_timeout
                        )
                    if self._shutdown_signal == 0:
                        await self._close_pipes()
                    else:
                        self.send_signal(self._shutdown_signal)
                    await self.wait()

            if self.returncode is None:  # still running
                self.kill()
                with _core.open_cancel_scope(shield=True):
                    await self.wait()

    def poll(self):
        """Check if the process has exited yet.

        Returns:
          The exit status of the process; see :attr:`returncode`.
        """
        if self.returncode is None and self._proc.poll() is not None:
            self._check_maybe_broke_pipe()
        return self.returncode

    def send_signal(self, sig):
        """Send signal ``sig`` to the process.

        On UNIX, ``sig`` may be any signal defined in the
        :mod:`signal` module, such as ``signal.SIGINT`` or
        ``signal.SIGTERM``. On Windows, it may be anything accepted by
        the standard library :meth:`subprocess.Popen.send_signal`.
        """
        if self.poll() is None:
            self._signals_sent_before_exit.add(sig)
            self._proc.send_signal(sig)

    def terminate(self):
        """Terminate the process, politely if possible.

        On UNIX, this is equivalent to
        ``send_signal(signal.SIGTERM)``; by convention this requests
        graceful termination, but a misbehaving or buggy process might
        ignore it. On Windows, :meth:`terminate` forcibly terminates the
        process in the same manner as :meth:`kill`.
        """
        if self.poll() is None:
            self._signals_sent_before_exit.add(signal.SIGTERM)
            self._proc.terminate()

    def kill(self):
        """Immediately terminate the process.

        On UNIX, this is equivalent to
        ``send_signal(signal.SIGKILL)``.  On Windows, it calls
        ``TerminateProcess``. In both cases, the process cannot
        prevent itself from being killed, but the termination will be
        delivered asynchronously; use :meth:`wait` if you want to
        ensure the process is actually dead before proceeding.
        """
        if not hasattr(signal, "SIGKILL"):  # Windows
            self.terminate()
        elif self.poll() is None:
            self._signals_sent_before_exit.add(signal.SIGKILL)
            self._proc.kill()

    async def shutdown(self):
        """Shut down the process in the manner used by a cancelled
        :meth:`aclose` or :meth:`join`.

        This is equivalent to (and implemented in terms of) making a
        call to :meth:`join` within a cancelled scope.

        Returns:
          The exit status of the process; see :attr:`returncode`.

        """
        with _core.open_cancel_scope() as scope:
            scope.cancel()
            return await self.join()


@attr.s(slots=True, cmp=False)
class ProcessStream(HalfCloseableStream):
    """A stream for communicating with a subprocess that is being managed
    by :func:`open_process`.

    Sending data on this stream writes it to the process's standard
    input, and receiving data receives from the process's standard
    output.  There is also an :attr:`errors` attribute which contains
    a :class:`~trio.abc.ReceiveStream` for reading from the process's
    standard error stream. If a stream is being redirected elsewhere,
    attempting to interact with it will raise :exc:`ClosedResourceError`.

    Closing a :class:`ProcessStream` closes all the underlying pipes,
    but unlike :meth:`Process.aclose`, it does *not* wait for the process
    to exit. You should use ``await stream.process.aclose()`` if you
    want the :meth:`Process.aclose` behavior.

    Args:
      process (:class:`Process`): The underlying process to wrap.

    Attributes:
      process (:class:`Process`): The underlying process, so you can
          :meth:`send it signals <Process.send_signal>`, inspect its
          :attr:`~Process.pid`, and so forth.
      errors (:class:`~trio.abc.ReceiveStream`): A stream which reads from
          the underlying process's standard error if we have access to it,
          or raises :exc:`ClosedResourceError` on all reads if not.
    """

    process = attr.ib(type=Process)
    errors = attr.ib(type=ReceiveStream, init=False, repr=False)

    def __attrs_post_init__(self) -> None:
        if self.process.stderr is None:
            self.errors = NullStream()
            self.errors.close()
        else:
            self.errors = self.process.stderr

    async def aclose(self) -> None:
        with _core.open_cancel_scope(shield=True):
            await self.process._close_pipes()
        await _core.checkpoint_if_cancelled()

    async def receive_some(self, max_bytes: int) -> bytes:
        if self.process.stdout is None:
            await _core.checkpoint()
            raise _core.ClosedResourceError(
                "can't read from process stdout that was redirected elsewhere"
            )
        return await self.process.stdout.receive_some(max_bytes)

    async def _stdin_operation(self, method, *args) -> None:
        if self.process.stdin is None:
            await _core.checkpoint()
            raise _core.ClosedResourceError(
                "can't write to process stdin that was redirected elsewhere"
            )
        await getattr(self.process.stdin, method)(*args)

    async def send_all(self, data: bytes) -> None:
        await self._stdin_operation("send_all", data)

    async def wait_send_all_might_not_block(self) -> None:
        await self._stdin_operation("wait_send_all_might_not_block")

    async def send_eof(self) -> None:
        await self._stdin_operation("aclose")


@asynccontextmanager
@async_generator
async def open_process(command, *, check=True, shield=False, **options):
    """An async context manager that runs ``command`` in a subprocess and
    evaluates to a :class:`ProcessStream` that can be used to communicate
    with it.

    The context manager's ``__aenter__`` executes a checkpoint before
    spawning the process but does not otherwise block. Its ``__aexit__``
    closes all pipes to and from the process and waits for it to
    exit, like :meth:`Process.aclose` does, so that the lifetime of
    the process is scoped to the ``async with`` block.  If
    the surrounding scope becomes cancelled or an exception propagates
    out of the ``async with`` block, the process is terminated and
    :func:`open_process` waits for the process to exit before
    continuing to propagate the exception.  If you need to allow the
    process to perform an orderly shutdown instead of being forcibly
    terminated, see the ``shutdown_signal`` and ``shutdown_timeout``
    arguments to :class:`Process`, which are accepted in the
    ``**options`` here.

    The default behavior of :func:`open_process` is designed to isolate
    the subprocess from potential impacts on the parent Trio process, and to
    reduce opportunities for errors to pass silently. Specifically:

    * The subprocess's standard input, output, and error streams are
      piped to the parent Trio process, so that data written to the
      :class:`ProcessStream` may be read by the subprocess and vice
      versa. (The subprocess's standard error output is available on a
      separate :class:`~trio.abc.ReceiveStream` accessible through the
      :attr:`~ProcessStream.errors` attribute of the
      :class:`ProcessStream`.)

    * If the subprocess exits with a nonzero status code, indicating
      failure, the body of the ``async with`` block will be cancelled
      (unless it is shielded by a ``shield=True`` argument) and a
      :exc:`subprocess.CalledProcessError` will be raised once it
      completes.  If the subprocess fails at the same time as an
      exception propagates out of the ``async with`` block, the two
      will be combined into a :exc:`~trio.MultiError`.

    To suppress the cancellation and
    :exc:`~subprocess.CalledProcessError` on failure, pass
    ``check=False``. To obtain different I/O behavior, use the
    lower-level ``stdin``, ``stdout``, and/or ``stderr``
    :ref:`subprocess options <subprocess-options>`; to skip
    redirecting a certain stream entirely, pass it as ``None``.  For
    example:

    * If you want the subprocess's input to come from the same
      place as the parent Trio process's input, pass ``stdin=None``.

    * If you want the subprocess's standard output and standard error
      to be intermixed and both be accessible through the main
      ``ProcessStream.receive_some`` channel, pass
      ``stderr=subprocess.STDOUT``.

    Args:
      command (list or str): The command to run. Typically this is a
          sequence of strings such as ``['ls', '-l', 'directory with spaces']``,
          where the first element names the executable to invoke and the other
          elements specify its arguments. With ``shell=True`` in the
          ``**options``, or on Windows, ``command`` may alternatively
          be a string, which will be parsed following platform-dependent
          :ref:`quoting rules <subprocess-quoting>`.
      check (bool): If false, don't cancel the ``async with`` block or
          throw an exception if the subprocess exits unsuccessfully.
          You should be sure to check the return code yourself if you
          pass ``check=False``, so that errors don't pass silently.
      shield (bool): If true, a cancellation from outside the ``async
          with`` block will cause the process to be terminated as usual,
          but will not cancel the body of the ``async with`` block.
          This is appropriate if the body of the ``async with`` block
          will terminate naturally as soon as the process exits, and
          you want to be sure not to miss the last bit of output.
      **options: :func:`run_process` also accepts any :ref:`general subprocess
          options <subprocess-options>` and passes them on to the
          :class:`~trio.Process` constructor.

    Raises:
      subprocess.CalledProcessError: if ``check=False`` is not passed
          and the process exits with an exit status indicating a
          failure that was not caused by the parent Trio process;
          see :attr:`Process.failed`
      OSError: if an error is encountered starting or communicating with
          the process

    """

    await _core.checkpoint()

    options.setdefault("stdin", subprocess.PIPE)
    options.setdefault("stdout", subprocess.PIPE)
    options.setdefault("stderr", subprocess.PIPE)

    async def join_and_check(proc):
        await proc.join()
        if proc.failed and check:
            raise subprocess.CalledProcessError(proc.returncode, proc.args)

    async with Process(command, **options) as proc:
        async with _core.open_nursery() as nursery:
            nursery.start_soon(
                join_and_check,
                proc,
                name="<subprocess: {!r}>".format(command)
            )
            with _core.open_cancel_scope(shield=shield):
                async with ProcessStream(proc) as stream:
                    await yield_(stream)


# This could be exposed publicly, but it might just clutter the API...
async def _communicate_with_process(stream, input=None):
    """Communicate with a subprocess over a :class:`ProcessStream` that
    has been created using :func:`open_process`.

    If the subprocess's standard input stream is connected to the
    parent Trio process, :func:`communicate_with_process` sends it the
    bytes provided as ``input``. Once all the ``input`` has been sent,
    or if none is provided, :func:`communicate_with_process` closes
    the stdin pipe so that the subprocess will receive end-of-file
    when it reads from standard input.

    For each of the subprocess's standard output or error streams that
    is connected to the parent Trio process,
    :func:`communicate_from_process` reads from that stream until EOF
    and aggregates the resulting data into a single ``bytes`` object
    which will form part of the return value from this function.  If a
    stream is not available for us to read from because it was
    redirected elsewhere, the corresponding slot in the return value
    will be None.

    Args:
      stream (ProcessStream): The process to communicate with.
      input (bytes): The data to send to the process.

    Returns:
      Once all input has been sent and end-of-file has been received on
      all outputs, returns a tuple ``(stdout, stderr)`` of the bytes
      received from the subprocess on each of its output streams.
      If a stream was not available for reading because it was redirected
      elsewhere, its corresponding slot will be set to None instead.
      If none of the subprocess's standard streams are piped to the
      parent Trio process, returns ``(None, None)`` immediately.

    """

    async def read_output(stream, chunks):
        while True:
            try:
                chunk = await stream.receive_some(32768)
            except _core.ClosedResourceError:
                break
            if not chunk:
                break
            chunks.append(chunk)

    manage_stdin = stream.process.stdin is not None
    manage_stdout = stream.process.stdout is not None
    manage_stderr = stream.process.stderr is not None

    stdout_chunks = []
    stderr_chunks = []

    async with _core.open_nursery() as nursery:
        if manage_stdout:
            nursery.start_soon(read_output, stream, stdout_chunks)
        if manage_stderr:
            nursery.start_soon(read_output, stream.errors, stderr_chunks)
        if manage_stdin:
            try:
                if input:
                    await stream.send_all(input)
            except (_core.BrokenResourceError, _core.ClosedResourceError):
                pass
            finally:
                await stream.send_eof()

    return (
        b"".join(stdout_chunks) if manage_stdout else None,
        b"".join(stderr_chunks) if manage_stderr else None
    )


@attr.s(init=False)
class CompletedProcess:
    """The result of a call to :func:`run_process`.

    Like :class:`subprocess.CompletedProcess`, but adds the :attr:`failed` and
    :attr:`cancelled` attributes.

    Attributes:
      command (list or str): The command that was run, as originally passed to
          :func:`run_process`.
      returncode (int): The exit status of the process (zero for success).
          On UNIX, if a subprocess is killed by signal number N, its
          :attr:`returncode` will be -N.
      failed (bool): Whether we consider the process to have failed. This
          will typically be true if the :attr:`returncode` is nonzero,
          unless we believe the nonzero return code was caused by
          the parent Trio process, following the rules documented under
          :attr:`Process.failed`.
      cancelled (bool): Whether the process was terminated early due to
          the :func:`run_process` call that was managing it becoming
          cancelled. A cancelled process will have a :attr:`returncode`
          reflecting forced termination, unless it exited normally after
          catching a configured ``shutdown_signal``. (You will only actually
          see a :class:`CompletedProcess` with ``cancelled=True`` get returned
          from a :func:`run_process` call with ``preserve_result=True``;
          otherwise you'll see a :exc:`Cancelled` exception propagating
          instead.)
      stdout (bytes or None): The captured standard output of the process,
          or None if it was not captured.
      stdout (bytes or None): The captured standard error of the process,
          or None if it was not captured.
    """

    command = attr.ib()
    returncode = attr.ib()
    failed = attr.ib()
    cancelled = attr.ib()
    stdout = attr.ib()
    stderr = attr.ib()

    def __init__(self, process, stdout=None, stderr=None):
        self.command = process.args
        self.returncode = process.returncode
        self.failed = process.failed
        self.cancelled = process.cancelled
        self.stdout = stdout
        self.stderr = stderr


async def run_process(
    command,
    *,
    input=None,
    check=True,
    preserve_result=False,
    task_status=_core.TASK_STATUS_IGNORED,
    **options
):
    """Run ``command`` in a subprocess, wait for it to complete, and
    return a :class:`CompletedProcess` instance describing
    the results.

    If cancelled, :func:`run_process` terminates the subprocess and
    waits for it to exit before propagating the cancellation, like
    :meth:`Process.aclose`.  If you need to allow the
    process to perform an orderly shutdown instead of being forcibly
    terminated, see the ``shutdown_signal`` and ``shutdown_timeout``
    arguments to :class:`Process`, which are accepted in the
    ``**options`` here.  If you need to be able to tell what
    partial output the process produced before a timeout,
    see the ``preserve_result`` argument.

    The default behavior of :func:`run_process` is designed to isolate
    the subprocess from potential impacts on the parent Trio process, and to
    reduce opportunities for errors to pass silently. Specifically:

    * The subprocess's standard input stream is set up to receive the
      bytes provided as ``input``.  Once the given input has been
      fully delivered, or if none is provided, the subprocess will
      receive end-of-file when reading from its standard input.

    * The subprocess's standard output and standard error streams are
      individually captured and returned as bytestrings from
      :func:`run_process`.

    * If the subprocess exits with a nonzero status code, indicating failure,
      :func:`run_process` raises a :exc:`subprocess.CalledProcessError`
      exception rather than returning normally. The captured outputs
      are still available as the ``stdout`` and ``stderr`` attributes
      of that exception.

    To suppress the :exc:`~subprocess.CalledProcessError` on failure,
    pass ``check=False``. To obtain different I/O behavior, use the
    lower-level ``stdin``, ``stdout``, and/or ``stderr``
    :ref:`subprocess options <subprocess-options>`. It is an error to
    specify ``input`` if ``stdin`` is specified. If ``stdout`` or
    ``stderr`` is specified (as something other than
    ``subprocess.PIPE``), the corresponding attribute of the returned
    :class:`CompletedProcess` object will be ``None``.

    Args:
      command (list or str): The command to run. Typically this is a
          sequence of strings such as ``['ls', '-l', 'directory with spaces']``,
          where the first element names the executable to invoke and the other
          elements specify its arguments. With ``shell=True`` in the
          ``**options``, or on Windows, ``command`` may alternatively
          be a string, which will be parsed following platform-dependent
          :ref:`quoting rules <subprocess-quoting>`.
      input (bytes): The input to provide to the subprocess on its
          standard input stream. If you want the subprocess's input
          to come from something other than data specified at the time
          of the :func:`run_process` call, you can specify a redirection
          using the lower-level ``stdin`` option; then ``input`` must
          be unspecified or None.
      check (bool): If false, don't validate that the subprocess exits
          successfully. You should be sure to check the
          ``returncode`` attribute of the returned object if you pass
          ``check=False``, so that errors don't pass silently.
      preserve_result (bool): If true, return normally even if cancelled,
          in order to give the caller a chance to inspect the process's
          partial output before a timeout.
      task_status: This function can be used with ``nursery.start``.
          If it is, it returns the :class:`Process` object, so that other tasks
          can send signals to the subprocess or wait for it to exit.
          (They shouldn't try to send or receive on the subprocess's
          input and output streams; use :func:`open_process` if you plan to do
          that.)
      **options: :func:`run_process` also accepts any :ref:`general subprocess
          options <subprocess-options>` and passes them on to the
          :class:`~trio.Process` constructor.

    Returns:
      A :class:`CompletedProcess` instance describing the
      return code and outputs.

    Raises:
      subprocess.CalledProcessError: if ``check=False`` is not passed
          and the process exits with an exit status indicating a
          failure that was not caused by the parent Trio process;
          see :attr:`Process.failed`
      OSError: if an error is encountered starting or communicating with
          the process

    .. warning::
       If you pass ``preserve_result=True``, :func:`run_process` has
       no way to directly propagate a :exc:`~trio.Cancelled`
       exception, so be careful when inspecting an enclosing cancel
       scope's ``cancelled_caught`` attribute if there are no other
       checkpoints between the end of :func:`run_process` and the end
       of the cancel scope::

           with trio.move_on_after(1) as scope:
               result = await trio.run_process(
                   "echo -n test; sleep 10", shell=True, preserve_result=True
               )

           print(result.stdout.encode("utf-8"))  # test
           print(result.cancelled)               # True
           print(scope.cancel_called)            # True
           print(scope.cancelled_caught)         # False

       As the above example demonstrates, you should usually look at
       :attr:`CompletedProcess.cancelled` instead.

    """

    if input is not None and "stdin" in options:
        raise ValueError(
            "can't provide input to a process whose stdin is redirected"
        )

    output = None

    try:
        async with open_process(
            command, check=check, shield=True, **options
        ) as stream:
            task_status.started(stream.process)
            output = await _communicate_with_process(stream, input)

    except subprocess.CalledProcessError as ex:
        # We can only get here with output still at None if the
        # CalledProcessError was raised out of open_process
        # __aenter__, which is not currently possible (it doesn't have
        # any checkpoints in between spawning the monitor task and
        # yielding to the context).
        if output is not None:  # pragma: no branch
            ex.stdout, ex.stderr = output
        raise

    except _core.Cancelled:
        if not preserve_result or output is None:
            raise

    return CompletedProcess(stream.process, *output)


async def delegate_to_process(command, **run_options):
    """Run ``command`` in a subprocess, with its standard streams inherited
    from the parent Trio process (no redirection), and return a
    :class:`CompletedProcess` describing the results.

    This is useful, for example, if you want to spawn an interactive process
    and allow the user to interact with it. It is equivalent to
    ``functools.partial(run_process, stdin=None, stdout=None, stderr=None)``.

    .. note:: The child is run in the same process group as the
       parent, so on UNIX a user Ctrl+C will be delivered to the
       parent Trio process as well.  You may wish to block signals
       while the child is running, start it in a new process group, or
       start it in a pseudoterminal. Trio does not currently provide
       facilities for this.

    """
    run_options.setdefault("stdin", None)
    run_options.setdefault("stdout", None)
    run_options.setdefault("stderr", None)
    return await run_process(command, **run_options)
