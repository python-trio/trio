import math
import os
import select
import subprocess
import sys

from . import _core
from ._abc import AsyncResource
from ._sync import CapacityLimiter, Lock
from ._threads import run_sync_in_worker_thread
from ._platform import wait_child_exiting

__all__ = ["Process", "run"]

# OS-specific hooks:
#
# create_pipe_to_child_stdin() -> (int, int):
#    Create a new pipe suitable for sending data from this
#    process to the standard input of a child we're about to spawn.
#
#    Returns:
#      A pair ``(trio_end, subprocess_end)`` where ``trio_end`` is
#      something suitable for constructing a PipeSendStream around
#      and ``subprocess_end`` is something suitable for passing as
#      the ``stdin`` argument of :class:`subprocess.Popen`.
#
# create_pipe_from_child_output() -> (int, int):
#    Create a new pipe suitable for receiving data into this
#    process from the standard output or error stream of a child
#    we're about to spawn.
#
#    Returns:
#      A pair ``(trio_end, subprocess_end)`` where ``trio_end`` is
#      something suitable for constructing a PipeReceiveStream around
#      and ``subprocess_end`` is something suitable for passing as
#      the ``stdout`` or ``stderr`` argument of :class:`subprocess.Popen`.

if os.name == "posix":
    from ._unix_pipes import PipeSendStream, PipeReceiveStream

    def create_pipe_to_child_stdin():
        rfd, wfd = os.pipe()
        return wfd, rfd

    def create_pipe_from_child_output():
        rfd, wfd = os.pipe()
        return rfd, wfd

elif os.name == "nt":
    import msvcrt

    # TODO: implement the pipes
    class PipeSendStream:
        def __init__(self, handle):
            raise NotImplementedError

    PipeReceiveStream = PipeSendStream

    # This isn't exported or documented, but it's also not
    # underscore-prefixed, and seems kosher to use. The asyncio docs
    # for 3.5 included an example that imported socketpair from
    # windows_utils (before socket.socketpair existed on Windows), and
    # when asyncio.windows_utils.socketpair was removed in 3.7, the
    # removal was mentioned in the release notes.
    from asyncio.windows_utils import pipe as windows_pipe

    def create_pipe_to_child_stdin():
        # for stdin, we want the write end (our end) to use overlapped I/O
        rh, wh = windows_pipe(overlapped=(False, True))
        return wh, msvcrt.open_osfhandle(rh, os.O_RDONLY)

    def create_pipe_from_child_output():
        # for stdout/err, it's the read end that's overlapped
        rh, wh = windows_pipe(overlapped=(True, False))
        return rh, msvcrt.open_osfhandle(wh, 0)

else:  # pragma: no cover
    raise NotImplementedError("unsupported os.name {!r}".format(os.name))


def wrap_process_stream(child_fd, given_value):
    """Perform any wrapping necessary to be able to use async operations
    to interact with a subprocess stream.

    Args:
      child_fd (0, 1, or 2): The file descriptor in the child that this
          stream will be used to communicate with.
      given_value (int or None): Anything accepted by the ``stdin``,
          ``stdout``, or ``stderr`` kwargs to :class:`subprocess.Popen`.
          For example, this could be ``None``, a file descriptor,
          :data:`subprocess.PIPE`, :data:`subprocess.STDOUT`, or
          :data:`subprocess.DEVNULL`.

    Returns:
      A pair ``(trio_stream, subprocess_value)`` where ``trio_stream``
      is a :class:`trio.abc.SendStream` (for stdin) or
      :class:`trio.abc.ReceiveStream` (for stdout/stderr) that can be
      used to communicate with the child process, and
      ``subprocess_value`` is the value that should be passed as the
      ``stdin``, ``stdout``, or ``stderr`` argument of
      :class:`subprocess.Popen` in order to set up the child end
      appropriately. If ``given_value`` was not :data:`subprocess.PIPE`,
      ``trio_stream`` will be ``None`` and ``subprocess_value`` will
      equal ``given_value``.
    """

    if given_value == subprocess.PIPE:
        maker, stream_cls = {
            0: (create_pipe_to_child_stdin, PipeSendStream),
            1: (create_pipe_from_child_output, PipeReceiveStream),
            2: (create_pipe_from_child_output, PipeReceiveStream),
        }[child_fd]

        trio_end, subprocess_end = maker()
        return stream_cls(trio_end), subprocess_end

    return None, given_value


class Process(AsyncResource):
    """Like :class:`subprocess.Popen`, but async.

    :class:`Process` has a public API identical to that of
    :class:`subprocess.Popen`, except for the following differences:

    * All constructor arguments except the command to execute
      must be passed as keyword arguments.

    * Text I/O is not supported: you may not use the constructor
      arguments ``universal_newlines``, ``encoding``, or ``errors``.

    * :attr:`stdin` is a :class:`~trio.abc.SendStream` and
      :attr:`stdout` and :attr:`stderr` are :class:`~trio.abc.ReceiveStream`s,
      rather than file objects. The constructor argument ``bufsize`` is
      not supported since there would be no file object to pass it to.

    * :meth:`wait` is an async function that does not take a ``timeout``
      argument; combine it with :func:`~trio.fail_after` if you want a timeout.

    * :meth:`~subprocess.Popen.communicate` does not exist due to the confusing
      cancellation behavior exhibited by the stdlib version. Use :func:`run`
      instead, or interact with :attr:`stdin` / :attr:`stdout` / :attr:`stderr`
      directly.

    * :meth:`aclose` (and thus also ``__aexit__``) behave like the
      standard :class:`Popen` context manager exit (close pipes to the
      process, then wait for it to exit), but add additional behavior
      if cancelled: kill the process and wait for it to finish
      terminating.  This is useful for scoping the lifetime of a
      simple subprocess that doesn't spawn any children of its
      own. (For subprocesses that do in turn spawn their own
      subprocesses, there is not currently any way to clean up the
      whole tree; moreover, using the :class:`Process` context manager
      in such cases is likely to be counterproductive as killing the
      top-level subprocess leaves it no chance to do any cleanup of
      its children that might be desired.)

    """

    universal_newlines = False
    encoding = None
    errors = None

    def __init__(self, args, *, stdin=None, stdout=None, stderr=None, **kwds):
        if any(
            kwds.get(key)
            for key in ('universal_newlines', 'encoding', 'errors')
        ):
            raise NotImplementedError(
                "trio.Process does not support text I/O yet"
            )
        if kwds.get('bufsize', -1) != -1:
            raise ValueError("bufsize does not make sense for trio subprocess")

        self.stdin, stdin = wrap_process_stream(0, stdin)
        self.stdout, stdout = wrap_process_stream(1, stdout)
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
            self.stderr = None
        else:
            self.stderr, stderr = wrap_process_stream(2, stderr)

        try:
            self._proc = subprocess.Popen(
                args, stdin=stdin, stdout=stdout, stderr=stderr, **kwds
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
        if self.stdin is not None:
            with _core.open_cancel_scope(shield=True):
                await self.stdin.aclose()
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
        while True:
            if self.poll() is not None:
                await _core.checkpoint()
                return self.returncode
            await wait_child_exiting(self.pid)

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


async def run(
    *popenargs, input=None, timeout=None, deadline=None, check=False, **kwargs
):
    """Like :func:`subprocess.run`, but async.

    Unlike most Trio adaptations of standard library functions, this
    one keeps the ``timeout`` parameter, so that it can provide you
    with the process's partial output if it is killed due to a
    timeout. It also adds ``deadline`` as an option if you prefer to
    express your timeout absolutely. If you don't care about preserving
    partial output on a timeout, you can of course also nest run()
    inside a normal Trio cancel scope.

    Returns:
      A :class:`subprocess.CompletedProcess` instance describing the
      return code and outputs.

    Raises:
      subprocess.TimeoutExpired: if the process is killed due to timeout
          expiry
      subprocess.CalledProcessError: if check=True is passed and the process
          exits with a nonzero exit status
      OSError: if an error is encountered starting or communicating with
          the process

    """
    if input is not None:
        if 'stdin' in kwargs:
            raise ValueError('stdin and input arguments may not both be used')
        kwargs['stdin'] = subprocess.PIPE

    if timeout is not None and deadline is not None:
        raise ValueError('timeout and deadline arguments may not both be used')

    stdout_chunks = []
    stderr_chunks = []

    async with Process(*popenargs, **kwargs) as proc:

        async def feed_input():
            if input:
                try:
                    await proc.stdin.send_all(input)
                except _core.BrokenResourceError:
                    pass
                except OSError as e:  # pragma: no cover
                    # According to the stdlib subprocess module, EINVAL can
                    # occur on Windows if the child closes its end of the
                    # pipe, and must be ignored.
                    if e.errno != errno.EINVAL:
                        raise
            await proc.stdin.aclose()

        async def read_output(stream, chunks):
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

            with _core.open_cancel_scope() as wait_scope:
                if timeout is not None:
                    wait_scope.deadline = _core.current_time() + timeout
                if deadline is not None:
                    wait_scope.deadline = deadline
                    timeout = deadline - _core.current_time()
                await proc.wait()

            if wait_scope.cancelled_caught:
                proc.kill()
                nursery.cancel_scope.cancel()

    stdout = b"".join(stdout_chunks) if proc.stdout is not None else None
    stderr = b"".join(stderr_chunks) if proc.stderr is not None else None

    if wait_scope.cancelled_caught:
        raise subprocess.TimeoutExpired(
            proc.args, timeout, output=stdout, stderr=stderr
        )
    if check and proc.returncode:
        raise subprocess.CalledProcessError(
            proc.returncode, proc.args, output=stdout, stderr=stderr
        )

    return subprocess.CompletedProcess(
        proc.args, proc.returncode, stdout, stderr
    )


async def call(*popenargs, **kwargs):
    """Like :func:`subprocess.call`, but async."""
    async with Process(*popenargs, **kwargs) as proc:
        return await proc.wait()


async def check_call(*popenargs, **kwargs):
    """Like :func:`subprocess.check_call`, but async."""
    async with Process(*popenargs, **kwargs) as proc:
        retcode = await proc.wait()
        if retcode:
            raise subprocess.CalledProcessError(retcode, proc.args)
    return 0


async def check_output(*popenargs, timeout=None, deadline=None, **kwargs):
    """Like :func:`subprocess.check_output`, but async.

    Like :func:`run`, this takes an optional ``timeout`` or ``deadline``
    argument; if the timeout expires or deadline passes, the child process
    will be killed and its partial output wrapped up in a
    :exc:`subprocess.TimeoutExpired` exception. You can also nest
    :func:`check_output` in a normal Trio cancel scope to impose
    a timeout without capturing partial output.
    """
    if 'stdout' in kwargs:
        raise ValueError("stdout argument not allowed, it will be overridden.")

    result = await run(
        *popenargs,
        stdout=subprocess.PIPE,
        timeout=timeout,
        deadline=deadline,
        check=True,
        **kwargs
    )
    return result.stdout
