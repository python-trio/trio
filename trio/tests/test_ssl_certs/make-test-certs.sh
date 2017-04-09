#!/bin/bash

# This file generates 3 .pem files that we use in the test suite.
#
# trio-test-CA.pem contains the public key for a root CA certificate.
#
# trio-test-{1,2}.pem contain, concatenated in order:
# - a private key
# - a certificate signed by our CA claiming that this is the key for the host
#   "trio-test-$N.example.org"
# - the root CA certificate again (to complete the cert chain)
#
# End result is that if you do
#
#    ssl.create_default_context(cafile="trio-test-CA.pem")
#
# then your SSLContext will trust the trio-test-{1,2} certificates.
#
# And if you do
#
#    sslcontext.load_cert_chain("trio-test-1.pem")
#
# then you can claim to be trio-test-1.example.org.

set -uxe -o pipefail

# Generate a self-signed 2048-bit RSA key as our signing root
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 99999   \
        -subj '/O=Trio test CA'                                 \
        -keyout trio-test-CA.key -out trio-test-CA.pem

for CERT in 1 2; do
    # Create a key and CSR.
    #
    # Our tests only use one name, so CN= is enough. (Otherwise we would need
    # to use subjectAltNames=, which *replaces* CN=.)
    openssl req -new -newkey rsa:2048 -nodes -sha256                \
            -subj "/CN=trio-test-${CERT}.example.org"               \
            -keyout trio-test-${CERT}.key -out trio-test-${CERT}.csr
    # Use the CSR and CA to sign the key, generating a certificate
    openssl x509 -req -in trio-test-${CERT}.csr -sha256 -days 99999 \
            -CA trio-test-CA.pem -CAkey trio-test-CA.key            \
            -set_serial ${CERT}                                     \
            -out trio-test-${CERT}.crt
    # Combine key/cert/root-CA into a single file for convenience
    # (see https://docs.python.org/3/library/ssl.html#ssl-certificates)
    cat trio-test-${CERT}.key trio-test-${CERT}.crt trio-test-CA.pem \
        > trio-test-${CERT}.pem
    rm -f trio-test-${CERT}.{csr,key,crt}
done

# We don't need the signing key anymore, remove it to reduce clutter
rm -f trio-test-CA.key
