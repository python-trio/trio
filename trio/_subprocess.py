import math
import os
import select
import subprocess
import sys

from . import _core
from ._abc import AsyncResource
from ._sync import CapacityLimiter, Lock
from ._threads import run_sync_in_worker_thread
from ._subprocess_platform import (
    wait_child_exiting, create_pipe_to_child_stdin,
    create_pipe_from_child_output
)

__all__ = ["Process"]


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
          speifying the process to execute and its arguments.
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
                    "trio.subprocess.Process only supports communicating over "
                    "unbuffered byte streams; the '{}' option is not supported"
                    .format(key)
                )

        self.stdin = None
        self.stdout = None
        self.stderr = None

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

        self.args = self._proc.args
        self.pid = self._proc.pid

    @property
    def returncode(self):
        """The exit status of the process (an integer), or ``None`` if it has
        not exited.

        Negative values indicate termination due to a signal (on UNIX only).
        Like :attr:`subprocess.Popen.returncode`, this is not updated outside
        of a call to :meth:`wait` or :meth:`poll`.
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
          The exit status of the process (a nonnegative integer, with
          zero usually indicating success). On UNIX systems, a process
          that exits due to a signal will have its exit status reported
          as the negative of that signal number, e.g., -11 for ``SIGSEGV``.
        """
        if self.poll() is None:
            await wait_child_exiting(self)
            self._proc.wait()
        else:
            await _core.checkpoint()
        return self.returncode

    def poll(self):
        """Forwards to :meth:`subprocess.Popen.poll`."""
        return self._proc.poll()

    def send_signal(self, sig):
        """Forwards to :meth:`subprocess.Popen.send_signal`."""
        self._proc.send_signal(sig)

    def terminate(self):
        """Forwards to :meth:`subprocess.Popen.terminate`."""
        self._proc.terminate()

    def kill(self):
        """Forwards to :meth:`subprocess.Popen.kill`."""
        self._proc.kill()
