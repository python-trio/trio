# Use SSLObject to make a generic wrapper around Stream

# SSL shutdown:
# - call unwrap() on the SSLSocket/SSLObject
# - this sends the "all done here" SSL message
# - but in many practical applications this is neither sent nor checked for,
#   e.g. HTTPS usually ignores it:
#   https://security.stackexchange.com/questions/82028/ssl-tls-is-a-server-always-required-to-respond-to-a-close-notify
#   BUT it is important in some cases, so should be possible to handle
#   properly.
#
# I think the answer is: close is synchronous, and the TLS Stream also has an
# async def unwrap() which sends the close_notify message.
# Possibly we should also default suppress_ragged_eofs to False, unlike the
# stdlib? not sure.

# XX how closely should we match the stdlib API?
# - maybe suppress_ragged_eofs=False is a better default?
# - maybe check crypto folks for advice?
# - this is also interesting: https://bugs.python.org/issue8108#msg102867

# Definitely keep an eye on Cory's TLS API ideas on security-sig etc.

# from ._stream import Stream

# class SSLStream(Stream):
#     async def unwrap(self):
#         # does a clean shutdown (!) by calling SSLObject.unwrap(), sends the
#         # resulting close_notify data, and *then* returns the underlying
#         # stream.
#         XX

#     # XX
