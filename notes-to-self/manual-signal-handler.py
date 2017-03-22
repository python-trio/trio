# How to manually call the SIGINT handler on Windows without using raise() or
# similar.

if os.name == "nt":
    import cffi
    ffi = cffi.FFI()
    ffi.cdef("""
        void* WINAPI GetProcAddress(void* hModule, char* lpProcName);
        typedef void (*PyOS_sighandler_t)(int);
    """)
    kernel32 = ffi.dlopen("kernel32.dll")
    PyOS_getsig_ptr = kernel32.GetProcAddress(
        ffi.cast("void*", sys.dllhandle), b"PyOS_getsig")
    PyOS_getsig = ffi.cast("PyOS_sighandler_t (*)(int)", PyOS_getsig_ptr)


    import signal
    PyOS_getsig(signal.SIGINT)(signal.SIGINT)
