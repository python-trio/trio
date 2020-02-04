#!/bin/bash

set -ex -o pipefail

# Log some general info about the environment
env | sort

if [ "$JOB_NAME" = "" ]; then
    if [ "$SYSTEM_JOBIDENTIFIER" != "" ]; then
        # azure pipelines
        JOB_NAME="$SYSTEM_JOBDISPLAYNAME"
    else
        JOB_NAME="${TRAVIS_OS_NAME}-${TRAVIS_PYTHON_VERSION:-unknown}"
    fi
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

### Azure pipelines + Windows ###

# On azure pipeline's windows VMs, to get reasonable performance, we need to
# jump through hoops to avoid touching the C:\ drive as much as possible.
if [ "$AGENT_OS" = "Windows_NT" ]; then
    # By default temp and cache directories are on C:\. Fix that.
    export TEMP="${AGENT_TEMPDIRECTORY}"
    export TMP="${AGENT_TEMPDIRECTORY}"
    export TMPDIR="${AGENT_TEMPDIRECTORY}"
    export PIP_CACHE_DIR="${AGENT_TEMPDIRECTORY}\\pip-cache"

    # Download and install Python from scratch onto D:\, instead of using the
    # pre-installed versions that azure pipelines provides on C:\.
    # Also use -DirectDownload to stop nuget from caching things on C:\.
    nuget install "${PYTHON_PKG}" -Version "${PYTHON_VERSION}" \
          -OutputDirectory "$PWD/pyinstall" -ExcludeVersion \
          -Source "https://api.nuget.org/v3/index.json" \
          -Verbosity detailed -DirectDownload -NonInteractive

    pydir="$PWD/pyinstall/${PYTHON_PKG}"
    export PATH="${pydir}/tools:${pydir}/tools/scripts:$PATH"

    # Fix an issue with the nuget python 3.5 packages
    # https://github.com/python-trio/trio/pull/827#issuecomment-457433940
    rm -f "${pydir}/tools/pyvenv.cfg" || true
fi

### Travis + macOS ###

if [ "$TRAVIS_OS_NAME" = "osx" ]; then
    JOB_NAME="osx_${MACPYTHON}"
    curl-harder -o macpython.pkg https://www.python.org/ftp/python/${MACPYTHON}/python-${MACPYTHON}-macosx10.6.pkg
    sudo installer -pkg macpython.pkg -target /
    ls /Library/Frameworks/Python.framework/Versions/*/bin/
    PYTHON_EXE=/Library/Frameworks/Python.framework/Versions/*/bin/python3
    # The pip in older MacPython releases doesn't support a new enough TLS
    curl-harder -o get-pip.py https://bootstrap.pypa.io/get-pip.py
    sudo $PYTHON_EXE get-pip.py
    sudo $PYTHON_EXE -m pip install virtualenv
    $PYTHON_EXE -m virtualenv testenv
    source testenv/bin/activate
fi

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

### Qemu virtual-machine inception, on Travis

if [ "$VM_IMAGE" != "" ]; then
    VM_CPU=${VM_CPU:-x86_64}

    sudo apt update
    sudo apt install cloud-image-utils qemu-system-x86

    # If the base image is already present, we don't try downloading it again;
    # and we use a scratch image for the actual run, in order to keep the base
    # image file pristine. None of this matters when running in CI, but it
    # makes local testing much easier.
    BASEIMG=$(basename $VM_IMAGE)
    if [ ! -e $BASEIMG ]; then
        curl-harder "$VM_IMAGE" -o $BASEIMG
    fi
    rm -f os-working.img
    qemu-img create -f qcow2 -b $BASEIMG os-working.img

    # This is the test script, that runs inside the VM, using cloud-init.
    #
    # This script goes through shell expansion, so use \ to quote any
    # $variables you want to expand inside the guest.
    cloud-localds -H test-host seed.img /dev/stdin << EOF
#!/bin/bash

set -xeuo pipefail

# When this script exits, we shut down the machine, which causes the qemu on
# the host to exit
trap "poweroff" exit

uname -a
echo \$PWD
id
cat /etc/lsb-release
cat /proc/cpuinfo

# Pass-through JOB_NAME + the env vars that codecov-bash looks at
export JOB_NAME="$JOB_NAME"
export CI="$CI"
export TRAVIS="$TRAVIS"
export TRAVIS_COMMIT="$TRAVIS_COMMIT"
export TRAVIS_PULL_REQUEST_SHA="$TRAVIS_PULL_REQUEST_SHA"
export TRAVIS_JOB_NUMBER="$TRAVIS_JOB_NUMBER"
export TRAVIS_PULL_REQUEST="$TRAVIS_PULL_REQUEST"
export TRAVIS_JOB_ID="$TRAVIS_JOB_ID"
export TRAVIS_REPO_SLUG="$TRAVIS_REPO_SLUG"
export TRAVIS_TAG="$TRAVIS_TAG"
export TRAVIS_BRANCH="$TRAVIS_BRANCH"

env

mkdir /host-files
mount -t 9p -o trans=virtio,version=9p2000.L host-files /host-files

# Install and set up the system Python (assumes Debian/Ubuntu)
apt update
apt install -y python3-dev python3-virtualenv git build-essential curl
python3 -m virtualenv -p python3 /venv
# Uses unbound shell variable PS1, so have to allow that temporarily
set +u
source /venv/bin/activate
set -u

# And then we re-invoke ourselves!
cd /host-files
./ci.sh

# We can't pass our exit status out. So if we got this far without error, make
# a marker file where the host can see it.
touch /host-files/SUCCESS
EOF

    rm -f SUCCESS
    # Apparently Travis's bionic images have nested virtualization enabled, so
    # we can use KVM... but the default user isn't in the appropriate groups
    # to use KVM, so we have to use 'sudo' to add that. And then a second
    # 'sudo', because by default we have rights to run arbitrary commands as
    # root, but we don't have rights to run a command as ourselves but with a
    # tweaked group setting.
    #
    # Travis Linux VMs have 7.5 GiB RAM, so we give our nested VM 6 GiB RAM
    # (-m 6144).
    sudo sudo -u $USER -g kvm qemu-system-$VM_CPU \
      -enable-kvm \
      -M pc \
      -m 6144 \
      -nographic \
      -drive "file=./os-working.img,if=virtio" \
      -drive "file=./seed.img,if=virtio,format=raw" \
      -net nic \
      -net "user,hostfwd=tcp:127.0.0.1:50022-:22" \
      -virtfs local,path=$PWD,security_model=mapped-file,mount_tag=host-files

    test -e SUCCESS
    exit
fi

################################################################
# We have a Python environment!
################################################################

python -c "import sys, struct, ssl; print('#' * 70); print('python:', sys.version); print('version_info:', sys.version_info); print('bits:', struct.calcsize('P') * 8); print('openssl:', ssl.OPENSSL_VERSION, ssl.OPENSSL_VERSION_INFO); print('#' * 70)"

python -m pip install -U pip setuptools wheel
python -m pip --version

python setup.py sdist --formats=zip
python -m pip install dist/*.zip

if [ "$CHECK_DOCS" = "1" ]; then
    python -m pip install -r docs-requirements.txt
    towncrier --yes  # catch errors in newsfragments
    cd docs
    # -n (nit-picky): warn on missing references
    # -W: turn warnings into errors
    sphinx-build -nW  -b html source build
elif [ "$CHECK_FORMATTING" = "1" ]; then
    python -m pip install -r test-requirements.txt
    source check.sh
else
    # Actual tests
    python -m pip install -r test-requirements.txt

    # If we're testing with a LSP installed, then it might break network
    # stuff, so wait until after we've finished setting everything else
    # up.
    if [ "$LSP" != "" ]; then
        echo "Installing LSP from ${LSP}"
        curl-harder -o lsp-installer.exe "$LSP"
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

    mkdir empty
    cd empty

    INSTALLDIR=$(python -c "import os, trio; print(os.path.dirname(trio.__file__))")
    cp ../setup.cfg $INSTALLDIR
    if pytest -W error -r a --junitxml=../test-results.xml --run-slow ${INSTALLDIR} --cov="$INSTALLDIR" --cov-config=../.coveragerc --verbose; then
        PASSED=true
    else
        PASSED=false
    fi

    # Remove the LSP again; again we want to do this ASAP to avoid
    # accidentally breaking other stuff.
    if [ "$LSP" != "" ]; then
        netsh winsock reset
    fi

    # coverage is broken in pypy3 7.1.1, but is fixed in nightly and should be
    # fixed in the next release after 7.1.1.
    # See: https://bitbucket.org/pypy/pypy/issues/2943/
    if [[ "$TRAVIS_PYTHON_VERSION" = "pypy3" ]]; then
        true;
    else
        # Flag pypy and cpython coverage differently, until it settles down...
        FLAG="cpython"
        if [[ "$PYPY_NIGHTLY_BRANCH" == "py3.8" ]]; then
            FLAG="pypy36nightly"
        elif [[ "$(python -V)" == *PyPy* ]]; then
            FLAG="pypy36release"
        fi
        # It's more common to do
        #   bash <(curl ...)
        # but azure is broken:
        #   https://developercommunity.visualstudio.com/content/problem/743824/bash-task-on-windows-suddenly-fails-with-bash-devf.html
        curl-harder -o codecov.sh https://codecov.io/bash
        bash codecov.sh -n "${JOB_NAME}" -F "$FLAG"
    fi

    $PASSED
fi
