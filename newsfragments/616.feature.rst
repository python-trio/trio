If you're using :func:`trio.hazmat.wait_task_rescheduled` and other
low-level routines to implement a new sleeping primitive, you can now
use the new :data:`trio.hazmat.Task.custom_sleep_data` attribute to
pass arbitrary data between the sleeping task, abort function, and
waking task.
