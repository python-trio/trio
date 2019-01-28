import math
import os
import select
import subprocess
import sys

from . import _core
from ._abc import AsyncResource
from ._highlevel_generic import StapledStream
from ._sync import Lock
from ._subprocess_platform import (
    wait_child_exiting, create_pipe_to_child_stdin,
    create_pipe_from_child_output
)

__all__ = ["Process", "run_process"]


class Process(AsyncResource):
    r"""Execute a child program in a new process.

    Like :class:`subprocess.Popen`, but async.

    Constructing a :class:`Process` immediately spawns the child
    process, or throws an :exc:`OSError` if the spawning fails (for
    example, if the specified command could not be found).
    After construction, you can interact with the child process
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

    :class:`Process` implements :class:`~trio.abc.AsyncResource`,
    so you can use it as an async context manager or call its
    :meth:`aclose` method directly. "Closing" a :class:`Process`
    will close any pipes to the child and wait for it to exit;
    if cancelled, the child will be forcibly killed and we will
    ensure it has finished exiting before allowing the cancellation
    to propagate. It is *strongly recommended* that process lifetime
    be scoped using an ``async with`` block wherever possible, to
    avoid winding up with processes hanging around longer than you
    were planning on.

    Args:
      command (str or list): The command to run. Typically this is a
          list of strings such as ``['ls', '-l', 'directory with spaces']``,
          where the first element names the executable to invoke and the other
          elements specify its arguments. If ``shell=True`` is given as
          an option, ``command`` should be a single string like
          ``"ls -l 'directory with spaces'"``, which will
          split into words following the shell's quoting rules.
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
      stdio (trio.StapledStream or None): A stream that sends data to
          the child's standard input and receives from the child's standard
          output. Only available if both :attr:`stdin` and :attr:`stdout` are
          available; otherwise this will be None.

    """

    universal_newlines = False
    encoding = None
    errors = None

    # Available for the per-platform wait_child_exiting() implementations
    # to stash some state; waitid platforms use this to avoid spawning
    # arbitrarily many threads if wait() keeps getting cancelled.
    _wait_for_exit_data = None

    def __init__(
        self, args, *, stdin=None, stdout=None, stderr=None, **options
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

        self._wait_lock = Lock()

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
                args, stdin=stdin, stdout=stdout, stderr=stderr, **options
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

        if self.stdin is not None and self.stdout is not None:
            self.stdio = StapledStream(self.stdin, self.stdout)
        else:
            self.stdio = None

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

        Accessing this attribute does not check for termination;
        use :meth:`poll` or :meth:`wait` for that.
        """
        return self._proc.returncode

    async def aclose(self):
        """Close any pipes we have to the process (both input and output)
        and wait for it to exit.

        If cancelled, kills the process and waits for it to finish
        exiting before propagating the cancellation.
        """
        with _core.open_cancel_scope(shield=True):
            if self.stdin is not None:
                await self.stdin.aclose()
            if self.stdout is not None:
                await self.stdout.aclose()
            if self.stderr is not None:
                await self.stderr.aclose()
        try:
            await self.wait()
        finally:
            if self.returncode is None:
                self.kill()
                with _core.open_cancel_scope(shield=True):
                    await self.wait()

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
        else:
            await _core.checkpoint()
        return self.returncode

    def poll(self):
        """Check if the process has exited yet.

        Returns:
          The exit status of the process, or ``None`` if it is still
          running; see :attr:`returncode`.
        """
        return self._proc.poll()

    def send_signal(self, sig):
        """Send signal ``sig`` to the process.

        On UNIX, ``sig`` may be any signal defined in the
        :mod:`signal` module, such as ``signal.SIGINT`` or
        ``signal.SIGTERM``. On Windows, it may be anything accepted by
        the standard library :meth:`subprocess.Popen.send_signal`.
        """
        self._proc.send_signal(sig)

    def terminate(self):
        """Terminate the process, politely if possible.

        On UNIX, this is equivalent to
        ``send_signal(signal.SIGTERM)``; by convention this requests
        graceful termination, but a misbehaving or buggy process might
        ignore it. On Windows, :meth:`terminate` forcibly terminates the
        process in the same manner as :meth:`kill`.
        """
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
        self._proc.kill()


async def run_process(
    command,
    *,
    input=None,
    check=True,
    passthrough=False,
    task_status=_core.TASK_STATUS_IGNORED,
    **options
):
    """Run ``command`` in a subprocess, wait for it to complete, and
    return a :class:`subprocess.CompletedProcess` instance describing
    the results.

    If cancelled, :func:`run_process` terminates the subprocess and
    waits for it to exit before propagating the cancellation, like
    :meth:`Process.aclose`.

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
    pass ``check=False``. To run the subprocess without I/O capturing,
    pass ``passthrough=True``. To redirect some standard streams
    differently than others, use the lower-level ``stdin``,
    ``stdout``, and/or ``stderr`` :ref:`options <subprocess-options>`.

    If you specify ``passthrough=True`` or a value for ``stdin`` other
    than ``PIPE``, you can't specify ``input`` (because we'd have no
    way to send it). If you specify ``passthrough=True`` or a value
    for ``stdout`` or ``stderr`` other than ``PIPE``, you can't
    observe the subprocess's output or errors; the corresponding
    attributes of the returned returned
    :class:`~subprocess.CompletedProcess` object will be ``None``.

    Args:
      command (list or str): The command to run. Typically this is a
          sequence of strings such as ``['ls', '-l', 'directory with spaces']``,
          where the first element names the executable to invoke and the other
          elements specify its arguments. With ``shell=True`` in the
          ``**options``, or on Windows, ``command`` may alternatively
          be a string, which will be parsed following platform-dependent
          quoting rules.
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
      passthrough (bool): If true, set up the subprocess to inherit the
          parent Trio process's standard streams; for example, if the parent
          Trio process is running in an interactive console, the subprocess
          will be able to interact with the user via that console. Only
          one call to :func:`run_process` should be active at a time with
          ``passthrough=True``, to avoid different processes' I/O being
          unpredictably interleaved.
      task_status: This function can be used with ``nursery.start``.
          If it is, it returns the :class:`Process` object, so that other tasks
          can send signals to the subprocess or wait for it to exit.
          They shouldn't try to send or receive on the subprocess's
          input and output streams, because :func:`run_process` is
          already doing that. Note that signals which terminate a
          subprocess often result in a nonzero return code; you
          probably want to pass ``check=False`` and do your own
          more specific error check if you're planning on sending any.
      **options: :func:`run_process` also accepts any :ref:`general subprocess
          options <subprocess-options>` and passes them on to the
          :class:`~trio.Process` constructor.

    Returns:
      A :class:`subprocess.CompletedProcess` instance describing the
      return code and outputs.

    Raises:
      subprocess.CalledProcessError: if ``check=False`` is not passed
          and the process exits with a nonzero exit status
      OSError: if an error is encountered starting or communicating with
          the process

    .. note:: The child process runs in the same process group as the parent
       Trio process, so a Ctrl+C will be delivered simultaneously to both
       parent and child. If you don't want this behavior, consult your
       platform's documentation for starting child processes in a different
       process group.

    """
    default_redirect = None if passthrough else subprocess.PIPE
    options.setdefault("stdin", default_redirect)
    options.setdefault("stdout", default_redirect)
    options.setdefault("stderr", default_redirect)

    if input is not None and options["stdin"] != subprocess.PIPE:
        raise ValueError(
            "can't provide input to a process whose stdin is redirected"
        )

    if options["stdin"] == subprocess.PIPE and not input:
        options["stdin"] = subprocess.DEVNULL

    stdout_chunks = []
    stderr_chunks = []

    async with Process(command, **options) as proc:
        task_status.started(proc)

        async def feed_input():
            async with proc.stdin:
                try:
                    await proc.stdin.send_all(input)
                except _core.BrokenResourceError:
                    pass

        async def read_output(stream, chunks):
            async with stream:
                while True:
                    chunk = await stream.receive_some(32768)
                    if not chunk:
                        break
                    chunks.append(chunk)

        async with _core.open_nursery() as nursery:
            if proc.stdin is not None:
                nursery.start_soon(feed_input)
            if proc.stdout is not None:
                nursery.start_soon(read_output, proc.stdout, stdout_chunks)
            if proc.stderr is not None:
                nursery.start_soon(read_output, proc.stderr, stderr_chunks)
            await proc.wait()

    stdout = b"".join(stdout_chunks) if proc.stdout is not None else None
    stderr = b"".join(stderr_chunks) if proc.stderr is not None else None

    if proc.returncode and check:
        raise subprocess.CalledProcessError(
            proc.returncode, proc.args, output=stdout, stderr=stderr
        )
    else:
        return subprocess.CompletedProcess(
            proc.args, proc.returncode, stdout, stderr
        )
