#!/bin/bash

set -ex -o pipefail

# Log some general info about the environment
env | sort

if [ "$JOB_NAME" = "" ]; then
    JOB_NAME="${TRAVIS_OS_NAME}-${TRAVIS_PYTHON_VERSION:-unknown}"
fi

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
# Bootstrap python environment, if necessary
################################################################

### PyPy nightly (currently on Travis) ###

if [ "$PYPY_NIGHTLY_BRANCH" != "" ]; then
    JOB_NAME="pypy_nightly_${PYPY_NIGHTLY_BRANCH}"
    curl-harder -o pypy.tar.bz2 http://buildbot.pypy.org/nightly/${PYPY_NIGHTLY_BRANCH}/pypy-c-jit-latest-linux64.tar.bz2
    if [ ! -s pypy.tar.bz2 ]; then
        # We know:
        # - curl succeeded (200 response code)
        # - nonetheless, pypy.tar.bz2 does not exist, or contains no data
        # This isn't going to work, and the failure is not informative of
        # anything involving Trio.
        ls -l
        echo "PyPy3 nightly build failed to download – something is wrong on their end."
        echo "Skipping testing against the nightly build for right now."
        exit 0
    fi
    tar xaf pypy.tar.bz2
    # something like "pypy-c-jit-89963-748aa3022295-linux64"
    PYPY_DIR=$(echo pypy-c-jit-*)
    PYTHON_EXE=$PYPY_DIR/bin/pypy3

    if ! ($PYTHON_EXE -m ensurepip \
              && $PYTHON_EXE -m pip install virtualenv \
              && $PYTHON_EXE -m virtualenv testenv); then
        echo "pypy nightly is broken; skipping tests"
        exit 0
    fi
    source testenv/bin/activate
fi

################################################################
# We have a Python environment!
################################################################

python -c "import sys, struct, ssl; print('#' * 70); print('python:', sys.version); print('version_info:', sys.version_info); print('bits:', struct.calcsize('P') * 8); print('openssl:', ssl.OPENSSL_VERSION, ssl.OPENSSL_VERSION_INFO); print('#' * 70)"

python -m pip install -U pip setuptools wheel
python -m pip --version

python setup.py sdist --formats=zip
python -m pip install dist/*.zip

if python -c 'import sys; sys.exit(sys.version_info >= (3, 7))'; then
    # Python < 3.7, select last ipython with 3.6 support
    # macOS requires the suffix for --in-place or you get an undefined label error
    sed -i'.bak' 's/ipython==[^ ]*/ipython==7.16.1/' test-requirements.txt
    sed -i'.bak' 's/traitlets==[^ ]*/traitlets==4.3.3/' test-requirements.txt
    git diff test-requirements.txt
fi

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
        certutil -addstore "TrustedPublisher" .github/workflows/astrill-codesigning-cert.cer
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
    cp ../setup.cfg $INSTALLDIR
    # We have to copy .coveragerc into this directory, rather than passing
    # --cov-config=../.coveragerc to pytest, because codecov.sh will run
    # 'coverage xml' to generate the report that it uses, and that will only
    # apply the ignore patterns in the current directory's .coveragerc.
    cp ../.coveragerc .
    if pytest -W error -r a --junitxml=../test-results.xml --run-slow ${INSTALLDIR} --cov="$INSTALLDIR" --verbose; then
        PASSED=true
    else
        PASSED=false
    fi

    # Remove the LSP again; again we want to do this ASAP to avoid
    # accidentally breaking other stuff.
    if [ "$LSP" != "" ]; then
        netsh winsock reset
    fi

    # The codecov docs recommend something like 'bash <(curl ...)' to pipe the
    # script directly into bash as its being downloaded. But, the codecov
    # server is flaky, so we instead save to a temp file with retries, and
    # wait until we've successfully fetched the whole script before trying to
    # run it.
    curl-harder -o codecov.sh https://codecov.io/bash
    bash codecov.sh -n "${JOB_NAME}"

    $PASSED
fi
