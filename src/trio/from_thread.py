"""
This namespace represents special functions that can call back into Trio from
an external thread by means of a Trio Token present in Thread Local Storage
"""

from ._threads import from_thread_run as run
from ._threads import from_thread_run_sync as run_sync
