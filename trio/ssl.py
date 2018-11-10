# This is a public namespace, so we don't want to expose any non-underscored
# attributes that aren't actually part of our public API. But it's very
# annoying to carefully always use underscored names for module-level
# temporaries, imports, etc. when implementing the module. So we put the
# implementation in an underscored module, and then re-export the public parts
# here.

from ._ssl import (SSLStream, SSLListener)

# Fake import to enable static analysis tools to catch the names
try:
    from ssl import (
        OPENSSL_VERSION_NUMBER, OPENSSL_VERSION_INFO, OPENSSL_VERSION, HAS_SNI,
        HAS_ECDH, HAS_NPN, HAS_ALPN, PROTOCOL_TLS, PROTOCOL_TLS_CLIENT,
        PROTOCOL_TLS_SERVER, OP_NO_TICKET, OP_NO_COMPRESSION,
        OP_SINGLE_ECDH_USE, OP_SINGLE_DH_USE, OP_CIPHER_SERVER_PREFERENCE,
        OP_ALL, ALERT_DESCRIPTION_CLOSE_NOTIFY,
        ALERT_DESCRIPTION_UNEXPECTED_MESSAGE, ALERT_DESCRIPTION_BAD_RECORD_MAC,
        ALERT_DESCRIPTION_RECORD_OVERFLOW,
        ALERT_DESCRIPTION_DECOMPRESSION_FAILURE,
        ALERT_DESCRIPTION_HANDSHAKE_FAILURE, ALERT_DESCRIPTION_BAD_CERTIFICATE,
        ALERT_DESCRIPTION_UNSUPPORTED_CERTIFICATE,
        ALERT_DESCRIPTION_CERTIFICATE_REVOKED,
        ALERT_DESCRIPTION_CERTIFICATE_EXPIRED,
        ALERT_DESCRIPTION_CERTIFICATE_UNKNOWN,
        ALERT_DESCRIPTION_ILLEGAL_PARAMETER, ALERT_DESCRIPTION_UNKNOWN_CA,
        ALERT_DESCRIPTION_ACCESS_DENIED, ALERT_DESCRIPTION_DECODE_ERROR,
        ALERT_DESCRIPTION_DECRYPT_ERROR, ALERT_DESCRIPTION_PROTOCOL_VERSION,
        ALERT_DESCRIPTION_INSUFFICIENT_SECURITY,
        ALERT_DESCRIPTION_INTERNAL_ERROR, ALERT_DESCRIPTION_USER_CANCELLED,
        ALERT_DESCRIPTION_NO_RENEGOTIATION,
        ALERT_DESCRIPTION_UNSUPPORTED_EXTENSION,
        ALERT_DESCRIPTION_CERTIFICATE_UNOBTAINABLE,
        ALERT_DESCRIPTION_UNRECOGNIZED_NAME,
        ALERT_DESCRIPTION_BAD_CERTIFICATE_STATUS_RESPONSE,
        ALERT_DESCRIPTION_BAD_CERTIFICATE_HASH_VALUE,
        ALERT_DESCRIPTION_UNKNOWN_PSK_IDENTITY, SSL_ERROR_SSL,
        SSL_ERROR_WANT_READ, SSL_ERROR_WANT_WRITE, SSL_ERROR_WANT_X509_LOOKUP,
        SSL_ERROR_SYSCALL, SSL_ERROR_ZERO_RETURN, SSL_ERROR_WANT_CONNECT,
        SSL_ERROR_EOF, SSL_ERROR_INVALID_ERROR_CODE, VERIFY_DEFAULT,
        VERIFY_CRL_CHECK_LEAF, VERIFY_CRL_CHECK_CHAIN, VERIFY_X509_STRICT,
        VERIFY_X509_TRUSTED_FIRST, CERT_NONE, CERT_OPTIONAL, CERT_REQUIRED,
        SOCK_STREAM, SOL_SOCKET, SO_TYPE, CHANNEL_BINDING_TYPES,
        HAS_NEVER_CHECK_COMMON_NAME, PEM_HEADER, PEM_FOOTER
    )

    from ssl import (
        VerifyMode, VerifyFlags, Options, AlertDescription, SSLErrorNumber,
        SSLSession, enum_certificates, enum_crls, SSLError, SSLZeroReturnError,
        SSLSyscallError, SSLEOFError, CertificateError, create_default_context,
        match_hostname, cert_time_to_seconds, DER_cert_to_PEM_cert,
        PEM_cert_to_DER_cert, get_default_verify_paths, Purpose
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
            "enum_certificates", "enum_crls", "VerifyMode", "VerifyFlags",
            "Options", "AlertDescription", "SSLErrorNumber", "SSLSession",
            "SSLError", "SSLZeroReturnError", "SSLSyscallError", "SSLEOFError",
            "CertificateError", "create_default_context", "match_hostname",
            "cert_time_to_seconds", "DER_cert_to_PEM_cert",
            "PEM_cert_to_DER_cert", "get_default_verify_paths", "Purpose"
        ]
    }
)

# Dynamically re-export whatever constants this particular Python happens to
# have:
globals().update(
    {
        _name: getattr(_stdlib_ssl, _name)
        for _name in _stdlib_ssl.__dict__.keys()
        if _name.isupper() and not _name.startswith('_')
    }
)
