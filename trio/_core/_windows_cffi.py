import cffi
import re
import enum

LIB = """
// https://msdn.microsoft.com/en-us/library/windows/desktop/aa383751(v=vs.85).aspx
typedef int BOOL;
typedef unsigned char BYTE;
typedef BYTE BOOLEAN;
typedef void* PVOID;
typedef PVOID HANDLE;
typedef unsigned long DWORD;
typedef unsigned long ULONG;
typedef unsigned long u_long;
typedef ULONG *PULONG;

typedef uintptr_t ULONG_PTR;
typedef uintptr_t UINT_PTR;

typedef UINT_PTR SOCKET;

typedef struct _GUID {
    unsigned long  Data1;
    unsigned short Data2;
    unsigned short Data3;
    unsigned char  Data4[ 8 ];
} GUID;

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

typedef OVERLAPPED WSAOVERLAPPED;
typedef LPOVERLAPPED LPWSAOVERLAPPED;

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

BOOL WINAPI CancelIoEx(
  _In_     HANDLE       hFile,
  _In_opt_ LPOVERLAPPED lpOverlapped
);

int WSAGetLastError(void);

int WSAIoctl(
  _In_  SOCKET                             s,
  _In_  DWORD                              dwIoControlCode,
  _In_  LPVOID                             lpvInBuffer,
  _In_  DWORD                              cbInBuffer,
  _Out_ LPVOID                             lpvOutBuffer,
  _In_  DWORD                              cbOutBuffer,
  _Out_ LPDWORD                            lpcbBytesReturned,
  _In_  LPWSAOVERLAPPED                    lpOverlapped,
  // _In_  LPWSAOVERLAPPED_COMPLETION_ROUTINE lpCompletionRoutine
  _In_  void* lpCompletionRoutine
);

typedef BOOL (*AcceptEx)(
  _In_  SOCKET       sListenSocket,
  _In_  SOCKET       sAcceptSocket,
  _In_  PVOID        lpOutputBuffer,
  _In_  DWORD        dwReceiveDataLength,
  _In_  DWORD        dwLocalAddressLength,
  _In_  DWORD        dwRemoteAddressLength,
  _Out_ LPDWORD      lpdwBytesReceived,
  _In_  LPOVERLAPPED lpOverlapped
);

struct sockaddr_in {
        short   sin_family;
        // u_short sin_port;
        uint16_t sin_port;
        //struct  in_addr sin_addr;
        uint8_t  sin_addr[4];
        char    sin_zero[8];
};

typedef struct sockaddr_in6 {
    //ADDRESS_FAMILY sin6_family; // AF_INET6.
    short sin6_family;
    //USHORT sin6_port;           // Transport level port number.
    uint16_t sin6_port;
    //ULONG  sin6_flowinfo;       // IPv6 flow information.
    uint32_t sin6_flowinfo;
    //IN6_ADDR sin6_addr;         // IPv6 address.
    uint8_t sin6_addr[16];
    //union {
    //    ULONG sin6_scope_id;     // Set of interfaces for a scope.
    //    SCOPE_ID sin6_scope_struct;
    //};
    uint32_t sin6_scope_id;
};

typedef BOOL PASCAL (*ConnectEx)(
  _In_     SOCKET                s,
  //_In_     const struct sockaddr *name,
  _In_     void *                name,
  _In_     int                   namelen,
  _In_opt_ PVOID                 lpSendBuffer,
  _In_     DWORD                 dwSendDataLength,
  _Out_    LPDWORD               lpdwBytesSent,
  _In_     LPOVERLAPPED          lpOverlapped
);

typedef struct __WSABUF {
  u_long   len;
  char FAR *buf;
} WSABUF, *LPWSABUF;

int WSARecvFrom(
  _In_    SOCKET                             s,
  _Inout_ LPWSABUF                           lpBuffers,
  _In_    DWORD                              dwBufferCount,
  _Out_   LPDWORD                            lpNumberOfBytesRecvd,
  _Inout_ LPDWORD                            lpFlags,
  //_Out_   struct sockaddr                    *lpFrom,
  _Out_   void*                              lpFrom,
  _Inout_ LPINT                              lpFromlen,
  _In_    LPWSAOVERLAPPED                    lpOverlapped,
  //_In_    LPWSAOVERLAPPED_COMPLETION_ROUTINE lpCompletionRoutine
  _In_    void*                              lpCompletionRoutine
);

"""

# cribbed from pywincffi
# programmatically strips out those annotations MSDN likes, like _In_
REGEX_SAL_ANNOTATION = re.compile(
    r"\b(_In_|_Inout_|_Out_|_Outptr_|_Reserved_)(opt_)?\b")
LIB = REGEX_SAL_ANNOTATION.sub(" ", LIB)

# Other fixups:
# - get rid of FAR, cffi doesn't like it
LIB = re.sub(r"\bFAR\b", " ", LIB)
# - PASCAL is apparently an alias for __stdcall (on modern compilers - modern
#   being _MSC_VER >= 800)
LIB = re.sub(r"\bPASCAL\b", "__stdcall", LIB)

# doing GetLastError() + getting message: ffi.getwinerror()
# doing WSAGetLastError + getting message: call WSAGetLastError then pass to
#   getwinerror()

ffi = cffi.FFI()
ffi.cdef(LIB)

kernel32 = ffi.dlopen("kernel32.dll")
ws2_32 = ffi.dlopen("ws2_32.dll")

INVALID_HANDLE_VALUE = ffi.cast("HANDLE", -1)


def raise_winerror(winerror=None, *, filename=None, filename2=None):
    if winerror is None:
        winerror, msg = ffi.getwinerror()
    else:
        _, msg = ffi.getwinerror(winerror)
    # See:
    # https://docs.python.org/3/library/exceptions.html#exceptions.WindowsError
    raise OSError(0, msg, filename, winerror, filename2)

def raise_WSAGetLastError():
    raise_winerror(ws2_32.WSAGetLastError())


class Error(enum.IntEnum):
    STATUS_TIMEOUT = 0x102
    ERROR_IO_PENDING = 997
    ERROR_OPERATION_ABORTED = 995


#define IOC_WS2                       0x08000000
IOC_WS2 = 0x08000000
#define IOC_IN          0x80000000      /* copy in parameters */
IOC_IN = 0x80000000
#define IOC_OUT         0x40000000      /* copy out parameters */
IOC_OUT = 0x40000000
#define IOC_INOUT       (IOC_IN|IOC_OUT)
IOC_INOUT = IOC_IN | IOC_OUT
#define _WSAIORW(x,y)                 (IOC_INOUT|(x)|(y))
def _WSAIORW(x, y):
    return IOC_INOUT | x | y
#define SIO_GET_EXTENSION_FUNCTION_POINTER  _WSAIORW(IOC_WS2,6)
SIO_GET_EXTENSION_FUNCTION_POINTER = _WSAIORW(IOC_WS2, 6)

# Oh this is horrible. Original:
#
# #define WSAID_ACCEPTEX \
#        {0xb5367df1,0xcbac,0x11cf,{0x95,0xca,0x00,0x80,0x5f,0x48,0xa1,0x92}}
#
# cffi:
WSAID_ACCEPTEX = ffi.new("GUID*")
WSAID_ACCEPTEX.Data1 = 0xb5367df1
WSAID_ACCEPTEX.Data2 = 0xcbac
WSAID_ACCEPTEX.Data3 = 0x11cf
WSAID_ACCEPTEX.Data4 = bytes([0x95,0xca,0x00,0x80,0x5f,0x48,0xa1,0x92])
