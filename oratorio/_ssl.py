# Use SSLObject to make a generic wrapper around Stream

# See also notes in _stream.py

# XX how closely should we match the stdlib API?
# - maybe suppress_ragged_eofs=False is a better default?
# - maybe check crypto folks for advice?
# - this is also interesting: https://bugs.python.org/issue8108#msg102867

from ._stream import Stream

class SSLStream(Stream):
    async def unwrap(self):
        # does a clean shutdown (!) by calling SSLObject.unwrap(), sends the
        # resulting close_notify data, and *then* returns the underlying
        # stream.
        XX

    # XX
