#!/bin/bash

set -ex -o pipefail

# On azure pipeline's windows VMs, we need to jump through hoops to avoid
# touching the C:\ drive as much as possible.
if [ $AGENT_OS = "Windows_NT" ]; then
    env | sort
    # By default temp and cache directories are on C:\. Fix that.
    export TEMP=${AGENT_TEMPDIRECTORY}
    export TMP=${AGENT_TEMPDIRECTORY}
    export TMPDIR=${AGENT_TEMPDIRECTORY}
    export PIP_CACHE_DIR=${AGENT_TEMPDIRECTORY}\\pip-cache

    # Download and install Python from scratch onto D:\, instead of using the
    # pre-installed versions that azure pipelines provides on C:\.
    # Also use -DirectDownload to stop nuget from caching things on C:\.
    nuget install ${PYTHON_PKG} -Version ${PYTHON_VERSION} \
          -OutputDirectory $PWD/pyinstall -ExcludeVersion \
          -Source "https://api.nuget.org/v3/index.json" \
          -Verbosity detailed -DirectDownload -NonInteractive

    pydir=$PWD/pyinstall/${PYTHON_PKG}
    export PATH="${pydir}/tools:${pydir}/tools/scripts:$PATH"
fi

python -c "import sys, struct, ssl; print('python:', sys.version); print('bits:', struct.calcsize('P') * 8); print('openssl:', ssl.OPENSSL_VERSION, ssl.OPENSSL_VERSION_INFO)"

python -m pip install -U pip setuptools wheel
python -m pip --version

python setup.py sdist --formats=zip
python -m pip install dist/*.zip

if [ "$CHECK_DOCS" = "1" ]; then
    python -m pip install -r ci/rtd-requirements.txt
    towncrier --yes  # catch errors in newsfragments
    cd docs
    # -n (nit-picky): warn on missing references
    # -W: turn warnings into errors
    sphinx-build -nW  -b html source build
else
    # Actual tests
    python -m pip install -r test-requirements.txt

    if [ "$CHECK_FORMATTING" = "1" ]; then
        source check.sh
    fi

    mkdir empty
    cd empty

    INSTALLDIR=$(python -c "import os, trio; print(os.path.dirname(trio.__file__))")
    pytest -W error -ra --junitxml=../test-results.xml --run-slow --faulthandler-timeout=60 ${INSTALLDIR} --cov="$INSTALLDIR" --cov-config=../.coveragerc --verbose

    # Disable coverage on 3.8-dev, at least until it's fixed (or a1 comes out):
    #   https://github.com/python-trio/trio/issues/711
    #   https://github.com/nedbat/coveragepy/issues/707#issuecomment-426455490
    if [ "$(python -V)" != "Python 3.8.0a0" ]; then
        bash <(curl -s https://codecov.io/bash)
    fi
fi
