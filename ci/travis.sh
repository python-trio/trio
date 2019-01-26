#!/bin/bash

set -ex

git rev-parse HEAD

CODECOV_NAME="${TRAVIS_OS_NAME}_${TRAVIS_PYTHON_VERSION:-unknown}"

if [ "$TRAVIS_OS_NAME" = "osx" ]; then
    CODECOV_NAME="osx_${MACPYTHON}"
    curl -Lo macpython.pkg https://www.python.org/ftp/python/${MACPYTHON}/python-${MACPYTHON}-macosx10.6.pkg
    sudo installer -pkg macpython.pkg -target /
    ls /Library/Frameworks/Python.framework/Versions/*/bin/
    PYTHON_EXE=/Library/Frameworks/Python.framework/Versions/*/bin/python3
    # The pip in older MacPython releases doesn't support a new enough TLS
    curl https://bootstrap.pypa.io/get-pip.py | sudo $PYTHON_EXE
    sudo $PYTHON_EXE -m pip install virtualenv
    $PYTHON_EXE -m virtualenv testenv
    source testenv/bin/activate
fi

if [ "$PYPY_NIGHTLY_BRANCH" != "" ]; then
    CODECOV_NAME="pypy_nightly_${PYPY_NIGHTLY_BRANCH}"
    curl -fLo pypy.tar.bz2 http://buildbot.pypy.org/nightly/${PYPY_NIGHTLY_BRANCH}/pypy-c-jit-latest-linux64.tar.bz2
    if [ ! -s pypy.tar.bz2 ]; then
        # We know:
        # - curl succeeded (200 response code; -f means "exit with error if
        # server returns 4xx or 5xx")
        # - nonetheless, pypy.tar.bz2 does not exist, or contains no data
        # This isn't going to work, and the failure is not informative of
        # anything involving trio.
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

# Fix https://github.com/python-trio/trio/issues/487
pip --version
curl https://bootstrap.pypa.io/get-pip.py | python
pip --version

pip install -U pip setuptools wheel

python setup.py sdist --formats=zip
pip install dist/*.zip

# flags have a restricted set of characters, maybe names are the same?
CODECOV_NAME=$(echo -n "$CODECOV_NAME" | tr -c a-z0-9 _)

if [ "$CHECK_DOCS" = "1" ]; then
    pip install -r ci/rtd-requirements.txt
    towncrier --yes  # catch errors in newsfragments
    cd docs
    # -n (nit-picky): warn on missing references
    # -W: turn warnings into errors
    sphinx-build -nW  -b html source build
else
    # Actual tests
    pip install -r test-requirements.txt

    if [ "$CHECK_FORMATTING" = "1" ]; then
        source check.sh
    fi

    mkdir empty
    cd empty

    INSTALLDIR=$(python -c "import os, trio; print(os.path.dirname(trio.__file__))")
    pytest -W error -ra --run-slow --faulthandler-timeout=60 ${INSTALLDIR} --cov="$INSTALLDIR" --cov-config=../.coveragerc --verbose

    # Disable coverage on 3.8-dev, at least until it's fixed (or a1 comes out):
    #   https://github.com/python-trio/trio/issues/711
    #   https://github.com/nedbat/coveragepy/issues/707#issuecomment-426455490
    if [ "$(python -V)" != "Python 3.8.0a0" ]; then
        # Disable coverage on pypy py3.6 nightly for now:
        # https://bitbucket.org/pypy/pypy/issues/2943/
        if [ "$PYPY_NIGHTLY_BRANCH" != "py3.6" ]; then
            bash <(curl -s https://codecov.io/bash) -n "${CODECOV_NAME}"
        fi
    fi
fi
