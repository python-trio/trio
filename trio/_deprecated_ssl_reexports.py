# This is a public namespace, so we don't want to expose any non-underscored
# attributes that aren't actually part of our public API. But it's very
# annoying to carefully always use underscored names for module-level
# temporaries, imports, etc. when implementing the module. So we put the
# implementation in an underscored module, and then re-export the public parts
# here.

# Trio-specific symbols:
from ._ssl import SSLStream, SSLListener, NeedHandshakeError

# Symbols re-exported from the stdlib ssl module:

# Always available
from ssl import (
    cert_time_to_seconds, CertificateError, create_default_context,
    DER_cert_to_PEM_cert, get_default_verify_paths, match_hostname,
    PEM_cert_to_DER_cert, Purpose, SSLEOFError, SSLError, SSLSyscallError,
    SSLZeroReturnError
)

# Added in python 3.6
try:
    from ssl import AlertDescription, SSLErrorNumber, SSLSession, VerifyFlags, VerifyMode, Options  # noqa
except ImportError:
    pass

# Added in python 3.7
try:
    from ssl import SSLCertVerificationError, TLSVersion  # noqa
except ImportError:
    pass

# Windows-only
try:
    from ssl import enum_certificates, enum_crls  # noqa
except ImportError:
    pass

# Fake import to enable static analysis tools to catch the names
# (Real import is below)
try:
    from ssl import (
        AF_INET, ALERT_DESCRIPTION_ACCESS_DENIED,
        ALERT_DESCRIPTION_BAD_CERTIFICATE_HASH_VALUE,
        ALERT_DESCRIPTION_BAD_CERTIFICATE_STATUS_RESPONSE,
        ALERT_DESCRIPTION_BAD_CERTIFICATE, ALERT_DESCRIPTION_BAD_RECORD_MAC,
        ALERT_DESCRIPTION_CERTIFICATE_EXPIRED,
        ALERT_DESCRIPTION_CERTIFICATE_REVOKED,
        ALERT_DESCRIPTION_CERTIFICATE_UNKNOWN,
        ALERT_DESCRIPTION_CERTIFICATE_UNOBTAINABLE,
        ALERT_DESCRIPTION_CLOSE_NOTIFY, ALERT_DESCRIPTION_DECODE_ERROR,
        ALERT_DESCRIPTION_DECOMPRESSION_FAILURE,
        ALERT_DESCRIPTION_DECRYPT_ERROR, ALERT_DESCRIPTION_HANDSHAKE_FAILURE,
        ALERT_DESCRIPTION_ILLEGAL_PARAMETER,
        ALERT_DESCRIPTION_INSUFFICIENT_SECURITY,
        ALERT_DESCRIPTION_INTERNAL_ERROR, ALERT_DESCRIPTION_NO_RENEGOTIATION,
        ALERT_DESCRIPTION_PROTOCOL_VERSION, ALERT_DESCRIPTION_RECORD_OVERFLOW,
        ALERT_DESCRIPTION_UNEXPECTED_MESSAGE, ALERT_DESCRIPTION_UNKNOWN_CA,
        ALERT_DESCRIPTION_UNKNOWN_PSK_IDENTITY,
        ALERT_DESCRIPTION_UNRECOGNIZED_NAME,
        ALERT_DESCRIPTION_UNSUPPORTED_CERTIFICATE,
        ALERT_DESCRIPTION_UNSUPPORTED_EXTENSION,
        ALERT_DESCRIPTION_USER_CANCELLED, CERT_NONE, CERT_OPTIONAL,
        CERT_REQUIRED, CHANNEL_BINDING_TYPES, HAS_ALPN, HAS_ECDH,
        HAS_NEVER_CHECK_COMMON_NAME, HAS_NPN, HAS_SNI, OP_ALL,
        OP_ALLOW_UNSAFE_LEGACY_RENEGOTIATION, OP_COOKIE_EXCHANGE,
        OP_DONT_INSERT_EMPTY_FRAGMENTS, OP_EPHEMERAL_RSA,
        OP_LEGACY_SERVER_CONNECT, OP_MICROSOFT_BIG_SSLV3_BUFFER,
        OP_MICROSOFT_SESS_ID_BUG, OP_MSIE_SSLV2_RSA_PADDING,
        OP_NETSCAPE_CA_DN_BUG, OP_NETSCAPE_CHALLENGE_BUG,
        OP_NETSCAPE_DEMO_CIPHER_CHANGE_BUG,
        OP_NETSCAPE_REUSE_CIPHER_CHANGE_BUG, OP_NO_QUERY_MTU, OP_PKCS1_CHECK_1,
        OP_PKCS1_CHECK_2, OP_SSLEAY_080_CLIENT_DH_BUG,
        OP_SSLREF2_REUSE_CERT_TYPE_BUG, OP_TLS_BLOCK_PADDING_BUG,
        OP_TLS_D5_BUG, OP_TLS_ROLLBACK_BUG, SSL_ERROR_NONE,
        SSL_ERROR_NO_SOCKET, OP_CIPHER_SERVER_PREFERENCE, OP_NO_COMPRESSION,
        OP_NO_RENEGOTIATION, OP_NO_TICKET, OP_SINGLE_DH_USE,
        OP_SINGLE_ECDH_USE, OPENSSL_VERSION_INFO, OPENSSL_VERSION_NUMBER,
        OPENSSL_VERSION, PEM_FOOTER, PEM_HEADER, PROTOCOL_TLS_CLIENT,
        PROTOCOL_TLS_SERVER, PROTOCOL_TLS, SO_TYPE, SOCK_STREAM, SOL_SOCKET,
        SSL_ERROR_EOF, SSL_ERROR_INVALID_ERROR_CODE, SSL_ERROR_SSL,
        SSL_ERROR_SYSCALL, SSL_ERROR_WANT_CONNECT, SSL_ERROR_WANT_READ,
        SSL_ERROR_WANT_WRITE, SSL_ERROR_WANT_X509_LOOKUP,
        SSL_ERROR_ZERO_RETURN, VERIFY_CRL_CHECK_CHAIN, VERIFY_CRL_CHECK_LEAF,
        VERIFY_DEFAULT, VERIFY_X509_STRICT, VERIFY_X509_TRUSTED_FIRST,
        OP_ENABLE_MIDDLEBOX_COMPAT
    )
except ImportError:
    pass

# Dynamically re-export whatever constants this particular Python happens to
# have:
import ssl as _stdlib_ssl
globals().update(
    {
        _name: getattr(_stdlib_ssl, _name)
        for _name in _stdlib_ssl.__dict__.keys()
        if _name.isupper() and not _name.startswith('_')
    }
)
