import abc as _abc

__all__ = ["Clock", "Instrument"]

class Clock(_abc.ABC):
    """The interface for custom run loop clocks.

    """

    @_abc.abstractmethod
    def start_clock(self):
        """Do any setup this clock might need.

        Called at the beginning of the run.

        """

    @_abc.abstractmethod
    def current_time(self):
        """Return the current time, according to this clock.

        This is used to implement functions like :func:`trio.current_time` and
        :func:`trio.move_on_after`.

        Returns:
            float: The current time.

        """

    @_abc.abstractmethod
    def deadline_to_sleep_time(self, deadline):
        """Compute the real time until the given deadline.

        This is called before we enter a system-specific wait function like
        :func:~select.select`, to get the timeout to pass.

        For a clock using wall-time, this should be something like::

           return deadline - self.current_time()

        but of course it may be different if you're implementing some kind of
        virtual clock.

        Args:
            deadline (float): The absolute time of the next deadline,
                according to this clock.

        Returns:
            float: The number of real seconds to sleep until the given
            deadline. May be :data:`math.inf`.

        """


class Instrument(_abc.ABC):
    """The interface for run loop instrumentation.

    Instruments don't have to inherit from this abstract base class, and all
    of these methods are optional. This class serves mostly as documentation.

    """

    def before_run(self):
        """Called at the beginning of :func:`trio.run`.

        """

    def after_run(self):
        """Called just before :func:`trio.run` returns.

        """

    def task_spawned(self, task):
        """Called when the given task is created.

        Args:
            task (trio.Task): The new task.

        """

    def task_scheduled(self, task):
        """Called when the given task becomes runnable.

        It may still be some time before it actually runs, if there are other
        runnable tasks ahead of it.

        Args:
            task (trio.Task): The task that became runnable.

        """

    def before_task_step(self, task):
        """Called immediately before we resume running the given task.

        Args:
            task (trio.Task): The task that is about to run.

        """

    def after_task_step(self, task):
        """Called when we return to the main run loop after a task has yielded.

        Args:
            task (trio.Task): The task that just ran.

        """

    def task_exited(self, task):
        """Called when the given task exits.

        Args:
            task (trio.Task): The finished task.

        """

    def before_io_wait(self, timeout):
        """Called before blocking to wait for I/O readiness.

        Args:
            timeout (float): The number of seconds we are willing to wait.

        """

    def after_io_wait(self, timeout):
        """Called after handling pending I/O.

        Args:
            timeout (float): The number of seconds we were willing to
                wait. This much time may or may not have elapsed, depending on
                whether any I/O was ready.

        """
