#!/bin/bash

set -ex -o pipefail

# disable warnings about pyright being out of date
# used in test_exports and in check.sh
export PYRIGHT_PYTHON_IGNORE_WARNINGS=1

# Log some general info about the environment
uname -a
env | sort

# Curl's built-in retry system is not very robust; it gives up on lots of
# network errors that we want to retry on. Wget might work better, but it's
# not installed on azure pipelines's windows boxes. So... let's try some good
# old-fashioned brute force. (This is also a convenient place to put options
# we always want, like -f to tell curl to give an error if the server sends an
# error response, and -L to follow redirects.)
function curl-harder() {
    for BACKOFF in 0 1 2 4 8 15 15 15 15; do
        sleep $BACKOFF
        if curl -fL --connect-timeout 5 "$@"; then
            return 0
        fi
    done
    return 1
}

################################################################
# We have a Python environment!
################################################################

python -c "import sys, struct, ssl; print('#' * 70); print('python:', sys.version); print('version_info:', sys.version_info); print('bits:', struct.calcsize('P') * 8); print('openssl:', ssl.OPENSSL_VERSION, ssl.OPENSSL_VERSION_INFO); print('#' * 70)"

python -m pip install -U pip setuptools wheel
python -m pip --version

python setup.py sdist --formats=zip
python -m pip install dist/*.zip

if [ "$CHECK_FORMATTING" = "1" ]; then
    python -m pip install -r test-requirements.txt
    source check.sh
else
    # Actual tests
    python -m pip install -r test-requirements.txt

    # So we can run the test for our apport/excepthook interaction working
    if [ -e /etc/lsb-release ] && grep -q Ubuntu /etc/lsb-release; then
        sudo apt install -q python3-apport
    fi

    # If we're testing with a LSP installed, then it might break network
    # stuff, so wait until after we've finished setting everything else
    # up.
    if [ "$LSP" != "" ]; then
        echo "Installing LSP from ${LSP}"
        # We use --insecure because one of the LSP's has been observed to give
        # cert verification errors:
        #
        #   https://github.com/python-trio/trio/issues/1478
        #
        # *Normally*, you should never ever use --insecure, especially when
        # fetching an executable! But *in this case*, we're intentionally
        # installing some untrustworthy quasi-malware onto into a sandboxed
        # machine for testing. So MITM attacks are really the least of our
        # worries.
        if [ "$LSP_EXTRACT_FILE" != "" ]; then
            # We host the Astrill VPN installer ourselves, and encrypt it
            # so as to decrease the chances of becoming an inadvertent
            # public redistributor.
            curl-harder -o lsp-installer.zip "$LSP"
            unzip -P "not very secret trio ci key" lsp-installer.zip "$LSP_EXTRACT_FILE"
            mv "$LSP_EXTRACT_FILE" lsp-installer.exe
        else
            curl-harder --insecure -o lsp-installer.exe "$LSP"
        fi
        # This is only needed for the Astrill LSP, but there's no harm in
        # doing it all the time. The cert was manually extracted by installing
        # the package in a VM, clicking "Always trust from this publisher"
        # when installing, and then running 'certmgr.msc' and exporting the
        # certificate. See:
        #    http://www.migee.com/2010/09/24/solution-for-unattendedsilent-installs-and-would-you-like-to-install-this-device-software/
        certutil -addstore "TrustedPublisher" trio/_tests/astrill-codesigning-cert.cer
        # Double-slashes are how you tell windows-bash that you want a single
        # slash, and don't treat this as a unix-style filename that needs to
        # be replaced by a windows-style filename.
        # http://www.mingw.org/wiki/Posix_path_conversion
        ./lsp-installer.exe //silent //norestart
        echo "Waiting for LSP to appear in Winsock catalog"
        while ! netsh winsock show catalog | grep "Layered Chain Entry"; do
            sleep 1
        done
        netsh winsock show catalog
    fi

    # We run the tests from inside an empty directory, to make sure Python
    # doesn't pick up any .py files from our working dir. Might have been
    # pre-created by some of the code above.
    mkdir empty || true
    cd empty

    INSTALLDIR=$(python -c "import os, trio; print(os.path.dirname(trio.__file__))")
    cp ../pyproject.toml $INSTALLDIR

    # TODO: remove this once we have a py.typed file
    touch "$INSTALLDIR/py.typed"

    # get mypy tests a nice cache
    MYPYPATH=".." mypy --config-file= --cache-dir=./.mypy_cache -c "import trio" >/dev/null 2>/dev/null || true

    # support subprocess spawning with coverage.py
    echo "import coverage; coverage.process_startup()" | tee -a "$INSTALLDIR/../sitecustomize.py"

    if COVERAGE_PROCESS_START=$(pwd)/../.coveragerc coverage run --rcfile=../.coveragerc -m pytest -r a -p trio._tests.pytest_plugin --junitxml=../test-results.xml --run-slow ${INSTALLDIR} --verbose; then
        PASSED=true
    else
        PASSED=false
    fi

    coverage combine --rcfile ../.coveragerc
    coverage report -m --rcfile ../.coveragerc
    coverage xml --rcfile ../.coveragerc

    # Remove the LSP again; again we want to do this ASAP to avoid
    # accidentally breaking other stuff.
    if [ "$LSP" != "" ]; then
        netsh winsock reset
    fi

    $PASSED
fi
