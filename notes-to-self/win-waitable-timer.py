# Sandbox for exploring the Windows "waitable timer" API.
# Cf https://github.com/python-trio/trio/issues/173
#
# Observations:
# - if you set a timer in the far future, then block in
#   WaitForMultipleObjects, then set the computer's clock forward by a few
#   years (past the target sleep time), then the timer immediately wakes up
#   (which is good!)
# - if you set a timer in the past, then it wakes up immediately

# Random thoughts:
# - top-level API sleep_until_datetime
# - portable manages the heap of outstanding sleeps, runs a system task to
#   wait for the next one, wakes up tasks when their deadline arrives, etc.
# - non-portable code: async def sleep_until_datetime_raw, which simply blocks
#   until the given time using system-specific methods. Can assume that there
#   is only one call to this method at a time.
#   Actually, this should be a method, so it can hold persistent state (e.g.
#   timerfd).
#   Can assume that the datetime passed in has tzinfo=timezone.utc
#   Need a way to override this object for testing.
#
# should we expose wake-system-on-alarm functionality? windows and linux both
# make this fairly straightforward, but you obviously need to use a separate
# time source

import cffi
from datetime import datetime, timedelta, timezone
import time

import trio
from trio._core._windows_cffi import (ffi, kernel32, raise_winerror)

try:
    ffi.cdef(
        """
typedef struct _PROCESS_LEAP_SECOND_INFO {
  ULONG Flags;
  ULONG Reserved;
} PROCESS_LEAP_SECOND_INFO, *PPROCESS_LEAP_SECOND_INFO;

typedef struct _SYSTEMTIME {
  WORD wYear;
  WORD wMonth;
  WORD wDayOfWeek;
  WORD wDay;
  WORD wHour;
  WORD wMinute;
  WORD wSecond;
  WORD wMilliseconds;
} SYSTEMTIME, *PSYSTEMTIME, *LPSYSTEMTIME;
"""
    )
except cffi.CDefError:
    pass

ffi.cdef(
    """
typedef LARGE_INTEGER FILETIME;
typedef FILETIME* LPFILETIME;

HANDLE CreateWaitableTimerW(
  LPSECURITY_ATTRIBUTES lpTimerAttributes,
  BOOL                  bManualReset,
  LPCWSTR               lpTimerName
);

BOOL SetWaitableTimer(
  HANDLE              hTimer,
  const LPFILETIME    lpDueTime,
  LONG                lPeriod,
  void*               pfnCompletionRoutine,
  LPVOID              lpArgToCompletionRoutine,
  BOOL                fResume
);

BOOL SetProcessInformation(
  HANDLE                    hProcess,
  /* Really an enum, PROCESS_INFORMATION_CLASS */
  int32_t                   ProcessInformationClass,
  LPVOID                    ProcessInformation,
  DWORD                     ProcessInformationSize
);

void GetSystemTimeAsFileTime(
  LPFILETIME       lpSystemTimeAsFileTime
);

BOOL SystemTimeToFileTime(
  const SYSTEMTIME *lpSystemTime,
  LPFILETIME       lpFileTime
);
""",
    override=True
)

ProcessLeapSecondInfo = 8
PROCESS_LEAP_SECOND_INFO_FLAG_ENABLE_SIXTY_SECOND = 1


def set_leap_seconds_enabled(enabled):
    plsi = ffi.new("PROCESS_LEAP_SECOND_INFO*")
    if enabled:
        plsi.Flags = PROCESS_LEAP_SECOND_INFO_FLAG_ENABLE_SIXTY_SECOND
    else:
        plsi.Flags = 0
    plsi.Reserved = 0
    if not kernel32.SetProcessInformation(
            ffi.cast("HANDLE", -1),  # current process
            ProcessLeapSecondInfo,
            plsi,
            ffi.sizeof("PROCESS_LEAP_SECOND_INFO"),
    ):
        raise_winerror()


def now_as_filetime():
    ft = ffi.new("LARGE_INTEGER*")
    kernel32.GetSystemTimeAsFileTime(ft)
    return ft[0]


# "FILETIME" is a specific Windows time representation, that I guess was used
# for files originally but now gets used in all kinds of non-file-related
# places. Essentially: integer count of "ticks" since an epoch in 1601, where
# each tick is 100 nanoseconds, in UTC but pretending that leap seconds don't
# exist. (Fortunately, the Python datetime module also pretends that
# leapseconds don't exist, so we can use datetime arithmetic to compute
# FILETIME values.)
#
#   https://docs.microsoft.com/en-us/windows/win32/sysinfo/file-times
#
# This page has FILETIME convertors and can be useful for debugging:
#
#   https://www.epochconverter.com/ldap
#
FILETIME_TICKS_PER_SECOND = 10**7
FILETIME_EPOCH = datetime.strptime(
    '1601-01-01 00:00:00 Z', '%Y-%m-%d %H:%M:%S %z'
)
# XXX THE ABOVE IS WRONG:
#
#   https://techcommunity.microsoft.com/t5/networking-blog/leap-seconds-for-the-appdev-what-you-should-know/ba-p/339813#
#
# Sometimes Windows FILETIME does include leap seconds! It depends on Windows
# version, process-global state, environment state, registry settings, and who
# knows what else!
#
# So actually the only correct way to convert a YMDhms-style representation of
# a time into a FILETIME is to use SystemTimeToFileTime
#
# ...also I can't even run this test on my VM, because it's running an ancient
# version of Win10 that doesn't have leap second support. Also also, Windows
# only tracks leap seconds since they added leap second support, and there
# haven't been any, so right now things work correctly either way.
#
# It is possible to insert some fake leap seconds for testing, if you want.


def py_datetime_to_win_filetime(dt):
    # We'll want to call this on every datetime as it comes in
    #dt = dt.astimezone(timezone.utc)
    assert dt.tzinfo is timezone.utc
    return round(
        (dt - FILETIME_EPOCH).total_seconds() * FILETIME_TICKS_PER_SECOND
    )


async def main():
    h = kernel32.CreateWaitableTimerW(ffi.NULL, True, ffi.NULL)
    if not h:
        raise_winerror()
    print(h)

    SECONDS = 2

    wakeup = datetime.now(timezone.utc) + timedelta(seconds=SECONDS)
    wakeup_filetime = py_datetime_to_win_filetime(wakeup)
    wakeup_cffi = ffi.new("LARGE_INTEGER *")
    wakeup_cffi[0] = wakeup_filetime

    print(wakeup_filetime, wakeup_cffi)

    print(f"Sleeping for {SECONDS} seconds (until {wakeup})")

    if not kernel32.SetWaitableTimer(
        h,
        wakeup_cffi,
        0,
        ffi.NULL,
        ffi.NULL,
        False,
    ):
        raise_winerror()

    await trio.hazmat.WaitForSingleObject(h)

    print(f"Current FILETIME: {now_as_filetime()}")
    set_leap_seconds_enabled(False)
    print(f"Current FILETIME: {now_as_filetime()}")
    set_leap_seconds_enabled(True)
    print(f"Current FILETIME: {now_as_filetime()}")
    set_leap_seconds_enabled(False)
    print(f"Current FILETIME: {now_as_filetime()}")


trio.run(main)
