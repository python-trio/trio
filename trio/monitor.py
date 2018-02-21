import os
import random
import string
import sys
import signal

import inspect

from ._version import __version__
from .abc import Instrument
from .hazmat import current_task, Task

# inspiration: https://github.com/python-trio/trio/blob/master/notes-to-self/print-task-tree.py

# example usage:
# monitor = Monitor()
# trio.


class Monitor(Instrument):
    """Represents a monitor; a simple way of monitoring the health of your
    Trio application using the Trio instrumentation API.

    The monitor protocol is a simple text-based protocol, accessible from a
    telnet client, for example.
    """
    MID_PREFIX = "|─ "
    MID_CONTINUE = "|  "
    END_PREFIX = "\─ "
    END_CONTINUE = " " * len(END_PREFIX)

    def __init__(self):
        self.authenticated = False

        # authentication for running code in a frame
        rand = random.SystemRandom()
        self.auth_pin = ''.join(
            rand.choice(string.ascii_letters) for x in range(0, 8)
        )

    @staticmethod
    def get_root_task() -> Task:
        """Gets the current root task."""
        task = current_task()
        while task.parent_nursery is not None:
            task = task.parent_nursery.parent_task
        return task

    @staticmethod
    def flatten_tasks():
        """Gets a list of all tasks."""
        root = Monitor.get_root_task()
        tasks = [root]
        for child in root.child_nurseries:
            tasks.extend(Monitor.recursively_get_tasks(child))

        return tasks

    @staticmethod
    def recursively_get_tasks(nursery):
        """Recursively gets all tasks from a nursery."""
        tasks = []
        for task in nursery.child_tasks:
            tasks.append(task)
            for nursery in task.child_nurseries:
                tasks.extend(Monitor.recursively_get_tasks(nursery))

        return tasks

    async def listen_on_stream(self, stream):
        """Makes the monitor server listen on a stream.
        Use this as a callback from a listener.
        """
        return await self.main_loop(stream)

    async def main_loop(self, stream):
        """Runs the main loop of the monitor.
        """
        # send the banner
        version = __version__
        await stream.send_all(
            b"Connected to the Trio monitor, using "
            b"trio " + version.encode(encoding="ascii") + b"\n"
        )

        while True:
            await stream.send_all(b"trio> ")
            command = await stream.receive_some(2048)
            if command == b"":
                return

            command = command.decode("ascii").rstrip("\n").rstrip("\r")
            name, *args = command.split(" ")

            # special handling for closing
            if name in ["exit", "ex", "quit", "q", ":q"]:
                return await stream.aclose()

            try:
                fn = getattr(self, "command_{}".format(name))
            except AttributeError:
                await stream.send_all(
                    b"No such command: " + name.encode() + b"\n"
                )
                continue

            try:
                lines = await fn(*args)
            except Exception as e:
                if isinstance(e, TypeError) and \
                        "takes at most" in ' '.join(e.args):
                    # hacky, but idk what else to do
                    await stream.send_all(' '.join(e.args).encode("ascii"))
                    continue

                errormessage = type(e).__name__ + ": " + ' '.join(e.args)
                await stream.send_all(b"Error: " + errormessage.encode())
                raise

            await stream.send_all(
                "\n".join(lines).encode(encoding="ascii") + b"\n"
            )

    # command definitions
    async def command_help(self):
        """Sends help.
        """
        name_rpad = 12

        def pred(i):
            return hasattr(i, "__name__") \
                   and i.__name__.startswith("command_")

        commands = inspect.getmembers(self, predicate=pred)
        lines = ["Commands:"]
        for name, command in commands:
            doc = inspect.getdoc(command).splitlines(keepends=False)[0]
            name = name.split("_", 1)[1]
            lines.append(name.ljust(name_rpad) + doc)

        return lines

    async def command_signal(self, signame: str):
        """Sends a signal to the server process.
        """
        signame = signame.upper()
        if not signame.startswith("SIG"):
            signame = "SIG{}".format(signame)

        try:
            tosend = getattr(signal, signame)
        except AttributeError:
            return ["Invalid signal: {}".format(signame)]

        os.kill(os.getpid(), tosend)
        return ["Signal sent successfully"]

    async def command_ps(self):
        """Gets the current list of tasks.
        """
        lines = []
        headers = ('ID', 'Name')
        widths = (15, 50)
        header_line = []

        for name, width in zip(headers, widths):
            header_line.append(name.ljust(width))

        lines.append(' '.join(header_line))
        lines.append("-" * sum(widths))

        for task in self.flatten_tasks():
            if len(task.name) >= 50:
                name = task.name[:46] + "..."
            else:
                name = task.name

            lines.append(' '.join([
                str(id(task)).ljust(widths[0]),
                name,
            ]))

        return lines


def main():
    import argparse
    import telnetlib
    try:
        import readline
    except ImportError:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-a",
        "--address",
        default="127.0.0.1",
        help="The address to connect to"
    )
    parser.add_argument(
        "-p", "--port", default=14761, help="The port to connect to"
    )

    args = parser.parse_args()
    # TODO: Potentially wrap sys.stdin
    client = telnetlib.Telnet(host=args.address, port=args.port)
    client.interact()

    return 0


if __name__ == "__main__":
    sys.exit(main())
