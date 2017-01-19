import cffi
import re
import enum

# cribbed from pywincffi
# programmatically strips out those annotations MSDN likes, like _In_
REGEX_SAL_ANNOTATION = re.compile(
    r"\b(_In_|_Inout_|_Out_|_Outptr_|_Reserved_)(opt_)?\b")

LIB = REGEX_SAL_ANNOTATION.sub(" ", """
// https://msdn.microsoft.com/en-us/library/windows/desktop/aa383751(v=vs.85).aspx
typedef int BOOL;
typedef unsigned char BYTE;
typedef BYTE BOOLEAN;
typedef void* PVOID;
typedef PVOID HANDLE;
typedef unsigned long DWORD;
typedef unsigned long ULONG;
typedef ULONG *PULONG;

typedef uintptr_t ULONG_PTR;

typedef struct _OVERLAPPED {
    ULONG_PTR Internal;
    ULONG_PTR InternalHigh;
    union {
        struct {
            DWORD Offset;
            DWORD OffsetHigh;
        } DUMMYSTRUCTNAME;
        PVOID Pointer;
    } DUMMYUNIONNAME;

    HANDLE  hEvent;
} OVERLAPPED, *LPOVERLAPPED;

typedef struct _OVERLAPPED_ENTRY {
    ULONG_PTR lpCompletionKey;
    LPOVERLAPPED lpOverlapped;
    ULONG_PTR Internal;
    DWORD dwNumberOfBytesTransferred;
} OVERLAPPED_ENTRY, *LPOVERLAPPED_ENTRY;

// kernel32.dll
HANDLE WINAPI CreateIoCompletionPort(
  _In_     HANDLE    FileHandle,
  _In_opt_ HANDLE    ExistingCompletionPort,
  _In_     ULONG_PTR CompletionKey,
  _In_     DWORD     NumberOfConcurrentThreads
);

BOOL WINAPI CloseHandle(
  _In_ HANDLE hObject
);

BOOL WINAPI PostQueuedCompletionStatus(
  _In_     HANDLE       CompletionPort,
  _In_     DWORD        dwNumberOfBytesTransferred,
  _In_     ULONG_PTR    dwCompletionKey,
  _In_opt_ LPOVERLAPPED lpOverlapped
);

BOOL WINAPI GetQueuedCompletionStatusEx(
  _In_  HANDLE             CompletionPort,
  _Out_ LPOVERLAPPED_ENTRY lpCompletionPortEntries,
  _In_  ULONG              ulCount,
  _Out_ PULONG             ulNumEntriesRemoved,
  _In_  DWORD              dwMilliseconds,
  _In_  BOOL               fAlertable
);

int WSAGetLastError(void);
""")

# doing GetLastError() + getting message: ffi.getwinerror()
# doing WSAGetLastError + getting message: call WSAGetLastError then pass to
#   getwinerror()

ffi = cffi.FFI()
ffi.cdef(LIB)

kernel32 = ffi.dlopen("kernel32.dll")
ws2_32 = ffi.dlopen("ws2_32.dll")

INVALID_HANDLE_VALUE = ffi.cast("HANDLE", -1)

def raise_GetLastError(filename=None, filename2=None):
    winerror, msg = ffi.getwinerror()
    # See:
    # https://docs.python.org/3/library/exceptions.html#exceptions.WindowsError
    raise OSError(0, msg, filename, winerror, filename2)

def raise_WSAGetLastError():
    winerror = ws2_32.WSAGetLastError()
    _, msg = ffi.getwinerror(winerror)
    raise OSError(0, msg, None, winerror, None)


class Error(enum.IntEnum):
    STATUS_TIMEOUT = 0x102
