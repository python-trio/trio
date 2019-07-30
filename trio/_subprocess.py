import os
import subprocess
from typing import Optional

from ._abc import AsyncResource, SendStream, ReceiveStream
from ._highlevel_generic import StapledStream
from ._sync import Lock
from ._subprocess_platform import (
    wait_child_exiting, create_pipe_to_child_stdin,
    create_pipe_from_child_output
)
import trio


class Process(AsyncResource):
    r"""A child process. Like :class:`subprocess.Popen`, but async.

    This class has no public constructor. To create a child process, use
    `open_process`::

       process = await trio.open_process(...)

    `Process` implements the `~trio.abc.AsyncResource` interface. In order to
    make sure your process doesn't end up getting abandoned by mistake or
    after an exception, you can use ``async with``::

       async with await trio.open_process(...) as process:
           ...

    "Closing" a :class:`Process` will close any pipes to the child and wait
    for it to exit; if cancelled, the child will be forcibly killed and we
    will ensure it has finished exiting before allowing the cancellation to
    propagate.

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

    # After the deprecation period:
    # - delete __init__ and _create
    # - add metaclass=NoPublicConstructor
    # - rename _init to __init__
    # - move most of the code into open_process()
    # - put the subprocess.Popen(...) call into a thread
    def __init__(self, *args, **kwargs):
        trio._deprecate.warn_deprecated(
            "directly constructing Process objects",
            "0.12.0",
            issue=1109,
            instead="trio.open_process"
        )
        self._init(*args, **kwargs)

    @classmethod
    def _create(cls, *args, **kwargs):
        self = cls.__new__(cls)
        self._init(*args, **kwargs)
        return self

    def _init(
        self, command, *, stdin=None, stdout=None, stderr=None, **options
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

        self.stdin = None  # type: Optional[SendStream]
        self.stdout = None  # type: Optional[ReceiveStream]
        self.stderr = None  # type: Optional[ReceiveStream]
        self.stdio = None  # type: Optional[StapledStream]

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
            # don't create a new Trio stream for stderr -- if stdout
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

        if self.stdin is not None and self.stdout is not None:
            self.stdio = StapledStream(self.stdin, self.stdout)

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
        with trio.CancelScope(shield=True):
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
                with trio.CancelScope(shield=True):
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
            await trio.hazmat.checkpoint()
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


async def open_process(
    command, *, stdin=None, stdout=None, stderr=None, **options
) -> Process:
    r"""Execute a child program in a new process.

    After construction, you can interact with the child process by writing
    data to its `~Process.stdin` stream (a `~trio.abc.SendStream`), reading
    data from its `~Process.stdout` and/or `~Process.stderr` streams (both
    `~trio.abc.ReceiveStream`\s), sending it signals using
    `~Process.terminate`, `~Process.kill`, or `~Process.send_signal`, and
    waiting for it to exit using `~Process.wait`. See `Process` for details.

    Each standard stream is only available if you specify that a pipe should
    be created for it. For example, if you pass ``stdin=subprocess.PIPE``, you
    can write to the `~Process.stdin` stream, else `~Process.stdin` will be
    ``None``.

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
      **options: Other :ref:`general subprocess options <subprocess-options>`
          are also accepted.

    Returns:
      A new `Process` object.

    Raises:
      OSError: if the process spawning fails, for example because the
         specified command could not be found.

    """
    # XX FIXME: move the process creation into a thread as soon as we're done
    # deprecating Process(...)
    await trio.hazmat.checkpoint()
    return Process._create(
        command, stdin=stdin, stdout=stdout, stderr=stderr, **options
    )


async def run_process(
    command,
    *,
    stdin=b"",
    capture_stdout=False,
    capture_stderr=False,
    check=True,
    **options
):
    """Run ``command`` in a subprocess, wait for it to complete, and
    return a :class:`subprocess.CompletedProcess` instance describing
    the results.

    If cancelled, :func:`run_process` terminates the subprocess and
    waits for it to exit before propagating the cancellation, like
    :meth:`Process.aclose`.

    **Input:** The subprocess's standard input stream is set up to
    receive the bytes provided as ``stdin``.  Once the given input has
    been fully delivered, or if none is provided, the subprocess will
    receive end-of-file when reading from its standard input.
    Alternatively, if you want the subprocess to read its
    standard input from the same place as the parent Trio process, you
    can pass ``stdin=None``.

    **Output:** By default, any output produced by the subprocess is
    passed through to the standard output and error streams of the
    parent Trio process. If you would like to capture this output and
    do something with it, you can pass ``capture_stdout=True`` to
    capture the subprocess's standard output, and/or
    ``capture_stderr=True`` to capture its standard error.  Captured
    data is provided as the
    :attr:`~subprocess.CompletedProcess.stdout` and/or
    :attr:`~subprocess.CompletedProcess.stderr` attributes of the
    returned :class:`~subprocess.CompletedProcess` object.  The value
    for any stream that was not captured will be ``None``.
    
    If you want to capture both stdout and stderr while keeping them
    separate, pass ``capture_stdout=True, capture_stderr=True``.
    
    If you want to capture both stdout and stderr but mixed together
    in the order they were printed, use: ``capture_stdout=True, stderr=subprocess.STDOUT``.
    This directs the child's stderr into its stdout, so the combined
    output will be available in the `~subprocess.CompletedProcess.stdout`
    attribute.

    **Error checking:** If the subprocess exits with a nonzero status
    code, indicating failure, :func:`run_process` raises a
    :exc:`subprocess.CalledProcessError` exception rather than
    returning normally. The captured outputs are still available as
    the :attr:`~subprocess.CalledProcessError.stdout` and
    :attr:`~subprocess.CalledProcessError.stderr` attributes of that
    exception.  To disable this behavior, so that :func:`run_process`
    returns normally even if the subprocess exits abnormally, pass
    ``check=False``.

    Args:
      command (list or str): The command to run. Typically this is a
          sequence of strings such as ``['ls', '-l', 'directory with spaces']``,
          where the first element names the executable to invoke and the other
          elements specify its arguments. With ``shell=True`` in the
          ``**options``, or on Windows, ``command`` may alternatively
          be a string, which will be parsed following platform-dependent
          :ref:`quoting rules <subprocess-quoting>`.
      stdin (:obj:`bytes`, file descriptor, or None): The bytes to provide to
          the subprocess on its standard input stream, or ``None`` if the
          subprocess's standard input should come from the same place as
          the parent Trio process's standard input. As is the case with
          the :mod:`subprocess` module, you can also pass a
          file descriptor or an object with a ``fileno()`` method,
          in which case the subprocess's standard input will come from
          that file.
      capture_stdout (bool): If true, capture the bytes that the subprocess
          writes to its standard output stream and return them in the
          :attr:`~subprocess.CompletedProcess.stdout` attribute
          of the returned :class:`~subprocess.CompletedProcess` object.
      capture_stderr (bool): If true, capture the bytes that the subprocess
          writes to its standard error stream and return them in the
          :attr:`~subprocess.CompletedProcess.stderr` attribute
          of the returned :class:`~subprocess.CompletedProcess` object.
      check (bool): If false, don't validate that the subprocess exits
          successfully. You should be sure to check the
          ``returncode`` attribute of the returned object if you pass
          ``check=False``, so that errors don't pass silently.
      **options: :func:`run_process` also accepts any :ref:`general subprocess
          options <subprocess-options>` and passes them on to the
          :class:`~trio.Process` constructor. This includes the
          ``stdout`` and ``stderr`` options, which provide additional
          redirection possibilities such as ``stderr=subprocess.STDOUT``,
          ``stdout=subprocess.DEVNULL``, or file descriptors.

    Returns:
      A :class:`subprocess.CompletedProcess` instance describing the
      return code and outputs.

    Raises:
      UnicodeError: if ``stdin`` is specified as a Unicode string, rather
          than bytes
      ValueError: if multiple redirections are specified for the same
          stream, e.g., both ``capture_stdout=True`` and
          ``stdout=subprocess.DEVNULL``
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

    if isinstance(stdin, str):
        raise UnicodeError("process stdin must be bytes, not str")
    if stdin == subprocess.PIPE:
        raise ValueError(
            "stdin=subprocess.PIPE doesn't make sense since the pipe "
            "is internal to run_process(); pass the actual data you "
            "want to send over that pipe instead"
        )
    if isinstance(stdin, (bytes, bytearray, memoryview)):
        input = stdin
        options["stdin"] = subprocess.PIPE
    else:
        # stdin should be something acceptable to Process
        # (None, DEVNULL, a file descriptor, etc) and Process
        # will raise if it's not
        input = None
        options["stdin"] = stdin

    if capture_stdout:
        if "stdout" in options:
            raise ValueError("can't specify both stdout and capture_stdout")
        options["stdout"] = subprocess.PIPE
    if capture_stderr:
        if "stderr" in options:
            raise ValueError("can't specify both stderr and capture_stderr")
        options["stderr"] = subprocess.PIPE

    stdout_chunks = []
    stderr_chunks = []

    async with await open_process(command, **options) as proc:

        async def feed_input():
            async with proc.stdin:
                try:
                    await proc.stdin.send_all(input)
                except trio.BrokenResourceError:
                    pass

        async def read_output(stream, chunks):
            async with stream:
                async for chunk in stream:
                    chunks.append(chunk)

        async with trio.open_nursery() as nursery:
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
