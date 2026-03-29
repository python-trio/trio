Upon a ``SSL.CertificateError``, a TLS alert is now sent to the peer before
raising ``trio.BrokenResourceError`` from the original error, preventing the
client from hanging.
