# This is a public namespace, so we don't want to expose any non-underscored
# attributes that aren't actually part of our public API. But it's very
# annoying to carefully always use underscored names for module-level
# temporaries, imports, etc. when implementing the module. So we put the
# implementation in an underscored module, and then re-export the public parts
# here.

from ._ssl import (SSLStream, SSLListener, aclose_forcefully, ConflictDetector)

# Fake import to enable static analysis tools to catch the names
try:
    from ._ssl import (
        SSLError, SSLZeroReturnError, SSLSyscallError, SSLEOFError,
        CertificateError, create_default_context, match_hostname,
        cert_time_to_seconds, DER_cert_to_PEM_cert, PEM_cert_to_DER_cert,
        get_default_verify_paths, Purpose, enum_certificates, enum_crls,
        SSLSession, VerifyMode, VerifyFlags, Options, AlertDescription,
        SSLErrorNumber
    )
except ImportError:
    pass

# We reexport certain names from the ssl module
# SSLContext is excluded intentionally
import ssl as _stdlib_ssl

globals().update(
    {
        _name: _value
        for (_name, _value) in _stdlib_ssl.__dict__.items() if _name in [
            "SSLError", "SSLZeroReturnError", "SSLSyscallError", "SSLEOFError",
            "CertificateError", "create_default_context", "match_hostname",
            "cert_time_to_seconds", "DER_cert_to_PEM_cert",
            "PEM_cert_to_DER_cert", "get_default_verify_paths", "Purpose",
            "enum_certificates", "enum_crls", "SSLSession", "VerifyMode",
            "VerifyFlags", "Options", "AlertDescription", "SSLErrorNumber"
        ]
    }
)
