from contextlib import contextmanager
import trio

class GracefulShutdownManager:
    def __init__(self):
        self._shutting_down = False
        self._cancel_scopes = set()

    def start_shutdown(self):
        self._shutting_down = True
        for cancel_scope in self._cancel_scopes:
            cancel_scope.cancel()

    def cancel_on_graceful_shutdown(self):
        cancel_scope = trio.CancelScope()
        self._cancel_scopes.add(cancel_scope)
        if self._shutting_down:
            cancel_scope.cancel()
        return cancel_scope

    @property
    def shutting_down(self):
        return self._shutting_down

# Code can check gsm.shutting_down occasionally at appropriate points to see
# if it should exit.
#
# When doing operations that might block for an indefinite about of time and
# that should be aborted when a graceful shutdown starts, wrap them in 'with
# gsm.cancel_on_graceful_shutdown()'.
async def stream_handler(stream):
    while True:
        with gsm.cancel_on_graceful_shutdown():
            data = await stream.receive_some(...)
        if gsm.shutting_down:
            break

# To trigger the shutdown:
async def listen_for_shutdown_signals():
    with trio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signal_aiter:
        async for sig in signal_aiter:
            gsm.start_shutdown()
            break
        # TODO: it'd be nice to have some logic like "if we get another
        # signal, or if 30 seconds pass, then do a hard shutdown".
        # That's easy enough:
        #
        # with trio.move_on_after(30):
        #     async for sig in signal_aiter:
        #         break
        # sys.exit()
        #
        # The trick is, if we do finish shutting down in (say) 10 seconds,
        # then we want to exit immediately. So I guess you'd need the main
        # part of the program to detect when it's finished shutting down, and
        # then cancel listen_for_shutdown_signals?
        #
        # I guess this would be a good place to use @smurfix's daemon task
        # construct:
        # https://github.com/python-trio/trio/issues/569#issuecomment-408419260
