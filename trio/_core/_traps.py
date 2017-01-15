# These are the only 3 functions that ever yield back to the task runner.

import enum

__all__ = ["yield_briefly", "yield_briefly_no_cancel", "Interrupt"]

@_hazmat
@types.coroutine
def yield_briefly():
    return yield (yield_briefly,)

@_hazmat
@types.coroutine
def yield_briefly_no_cancel():
    return yield (yield_briefly_no_cancel,)

# Return values for interrupt functions
@_hazmat
Interrupt = enum.Enum("Interrupt", "SUCCEEDED FAILED")

# This one is so tricky to use that we don't even make it a hazmat function;
# we only use it internally within this module. ParkingLot provides a much
# more pleasant abstraction on top of it.
#
# Basically, before calling this make arrangements for the current task to be
# rescheduled "eventually".
#
# interrupt_func gets called if we want to cancel the wait (e.g. a
# timeout). It should attempt to cancel whatever arrangements were made, and
# must return either Interupt.SUCCEEDED, in which case the task will be
# rescheduled immediately with the exception raised, or else Interrupt.FAILED,
# in which case no magic happens and you still have to make sure that
# reschedule will be called eventually.
@types.coroutine
def yield_indefinitely(status, interrupt_func):
    return yield (yield_indefinitely, status, interrupt_func)
