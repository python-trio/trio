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

### Alpine ###

if [ -e /etc/alpine-release ]; then
    apk add --no-cache gcc musl-dev libffi-dev openssl-dev python3-dev curl
    python3 -m venv venv
    source venv/bin/activate
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

### FreeBSD-in-Qemu virtual-machine inception, on Travis

# This is complex, because none of the pre-made images are set up to be
# controlled by an automatic process – making them do anything requires a
# human to look at the screen and type stuff. So we hack up an install CD, run
# it to build our own custom image, and use that. But that's slow and we don't
# want to do it every run, so we try to get Travis to cache the image for us.
#
# Additional subtlety: we actually re-use the same image in-place, and let
# Travis re-cache it every time. The point of this is that it saves our system
# packages + pip cache, so we don't have to re-fetch them from scratch every
# time. (In particular, this means that the first time we install a given
# version of cryptography, we have to build it from source, but on subsequent
# runs we'll have a pre-built wheel sitting in our disk image.)
#
# You can run this locally for testing. But some things to watch out for:
#
# - It'll modify /etc/exports on your host machine. You might want to clean
#   it up after.
# - It'll create a symlink at /host-files on your host machine. You might want
#   to clean it up after.
# - If you don't want to keep downloading the installer ISO over and over,
#   then drop an unpacked copy at ./local-freebsd-installer.iso

if [ "$FREEBSD_INSTALLER_ISO_XZ" != "" ]; then
    sudo apt update
    sudo apt install qemu-system-x86 qemu-utils nfs-kernel-server

    if [ ! -e travis-cache/image.qcow2 ]; then
        echo "--- No cached FreeBSD VM image; recreating from scratch ---"
        sudo apt install growisofs genisoimage
        rm -rf scratch
        mkdir scratch
        qemu-img create -f qcow2 scratch/image.qcow2 10G
        if [ -e local-freebsd-installer.iso ]; then
            cp local-freebsd-installer.iso scratch/installer.iso
        else
            curl-harder "$FREEBSD_INSTALLER_ISO_XZ" -o scratch/installer.iso.xz
            unxz scratch/installer.iso.xz
        fi

        # Files that we want to add to the ISO, to convert it into an
        # unattended-installer:
        mkdir -p scratch/overlay/etc
        mkdir -p scratch/overlay/boot
        # Use serial console, and disable the normal 10 second pause before
        # booting
        cat >scratch/overlay/boot/loader.conf.local <<EOF
console=comconsole
autoboot_delay=0
EOF
        # The default rc.local does a bunch of stuff. For example, if you're
        # using a serial console, it unconditionally stops the boot to ask you
        # what TERM to use. So we overwrite rc.local with a stripped-down
        # version that just handles the one thing we care about, and never
        # asks questions.
        cat >scratch/overlay/etc/rc.local <<EOF
#!/bin/sh
export TERM=vt100
bsdinstall script /etc/installerconfig
EOF

        # This is the installer script that manages the unattended install.
        # The first part sets some variables that control the install process.
        # The last part (everything after #!/bin/sh) is an arbitrary script
        # that gets run after the install is finished, inside the new
        # environment chroot, so it can apply any custom tweaks to the new
        # system. Specifically, it:
        # - does some basic network and boot configuration
        # - installs bash + python
        # - installs a boot script that mounts /host-files and then runs
        #   /host-files/freebsd-wrapper.sh as a bash script.
        # - powers off the system
        cat >scratch/overlay/etc/installerconfig <<EOF
PARTITIONS=ada0
DISTRIBUTIONS="base.txz kernel.txz"

#!/bin/sh
set -exuo pipefail

echo "ifconfig_em0=SYNCDHCP" >> /etc/rc.conf
/bin/cp /usr/share/zoneinfo/UTC /etc/localtime

echo 'autoboot_delay=0' >> /boot/loader.conf.local
echo 'console=comconsole' >> /boot/loader.conf.local

dhclient em0
export ASSUME_ALWAYS_YES=true
pkg install bash curl python38 py38-sqlite3

mkdir /host-files
cat >>/etc/rc.local <<INNER_RC_LOCAL
set +ex
export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/sbin:/usr/local/bin
pkg upgrade -y
mount_nfs -o nolockd 10.0.2.2:/host-files /host-files
cd /host-files
bash ./freebsd-wrapper.sh
INNER_RC_LOCAL

halt -p
EOF

        # Add these files to our .iso. This is a little tricky because (a)
        # iso9660 is a read-only filesystem, so it can't be modified in-place,
        # and (b) unpacking and repacking the .iso is really tricky, because
        # there's special boot metadata that has to be copied over.
        # Fortunately though, iso9660 has an obscure feature where you can
        # append some data on the end as a second "session", and add new files
        # that shadow whatever files are in the first "session". So that's
        # what we do. Also we have to set the volume label correctly, because
        # that the bootloader uses it to locate the install CD.
        LABEL=$(isoinfo -i scratch/installer.iso -d | grep "Volume id" | cut -f2 -d:)
        growisofs -V $LABEL -M scratch/installer.iso -R -J scratch/overlay

        # And now we can boot our custom install CD. When this VM exits again,
        # we'll have a FreeBSD install in travis-cache/image.qcow2
        sudo sudo -u $USER -g kvm qemu-system-x86_64 \
            -enable-kvm \
            -M pc \
            -m 2048 \
            -cdrom scratch/installer.iso \
            -hda scratch/image.qcow2 \
            -nographic \
            -net nic \
            -net user

        # Everything seems to have worked, so move the completed image into
        # the cache dir
        mkdir travis-cache || true
        mv scratch/image.qcow2 travis-cache/
    fi

    # OK, we have a FreeBSD image! Let's use it to run our tests.
    cat >freebsd-wrapper.sh <<EOF
#!/bin/bash

set -xeuo pipefail

# When this script exits, we shut down the machine, which causes the qemu on
# the host to exit
trap "halt -p" exit

uname -a
freebsd-version
echo $PWD
id

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

env | sort

# We put the venv into tmpfs, to prevent it getting cached with the rest of
# the system image (plus, it's fast).
mkdir /venv || true
mount -t tmpfs tmpfs /venv
python3.8 -m venv /venv
set +u
source /venv/bin/activate
set -u

# And put a tmpfs on the empty dir as well, because coverage uses it for
# storage, and this makes it *massively* faster than if it's on NFS
mkdir empty
mount -t tmpfs tmpfs ./empty

# And then we re-invoke ourselves!
bash ./ci.sh

# We can't pass our exit status out. So if we got this far without error, make
# a marker file where the host can see it.
touch /host-files/SUCCESS

EOF

    rm -f SUCCESS

    # I originally tried to use SMB, which is super convenient because qemu
    # has built-in support for exporting an SMB share to the guest. But it
    # turns out FreeBSD's SMB support has a bunch of limitations: no symlinks,
    # no os.utime, etc., that broke using it as a working directory.
    sudo ln -sfT $(pwd) /host-files
    if ! grep -q /host-files /etc/exports; then
        echo "/host-files 127.0.0.1/32(rw,async,all_squash,anonuid=$(id -u),anongid=$(id -g),no_subtree_check,insecure)" | sudo tee -a /etc/exports
    fi
    sudo systemctl start nfs-kernel-server.service
    sudo exportfs -a

    sudo sudo -u $USER -g kvm qemu-system-x86_64 \
      -enable-kvm \
      -M pc \
      -m 6144 \
      -nographic \
      -hda travis-cache/image.qcow2 \
      -net nic \
      -net user

    test -e SUCCESS
    exit
fi

### Linux-in-Qemu virtual-machine inception, on Travis

if [ "$LINUX_VM_IMAGE" != "" ]; then
    VM_CPU=${VM_CPU:-x86_64}

    sudo apt update
    sudo apt install cloud-image-utils qemu-system-x86

    # If the base image is already present, we don't try downloading it again;
    # and we use a scratch image for the actual run, in order to keep the base
    # image file pristine. None of this matters when running in CI, but it
    # makes local testing much easier.
    BASEIMG=$(basename $LINUX_VM_IMAGE)
    if [ ! -e $BASEIMG ]; then
        curl-harder "$LINUX_VM_IMAGE" -o $BASEIMG
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
cat /etc/fedora-release
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

env | sort

mkdir /host-files
mount -t 9p -o trans=virtio,version=9p2000.L host-files /host-files

# Set up the system Python (Fedora preinstalls Python 3)
python3 -m venv /venv
# Uses unbound shell variable PS1, so have to allow that temporarily
set +u
source /venv/bin/activate
set -u

# We put a tmpfs on the empty dir because coverage uses it for
# storage, and this is much faster than if coverage has to go through virtfs.
mkdir /host-files/empty
mount -t tmpfs tmpfs /host-files/empty

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
        curl-harder --insecure -o lsp-installer.exe "$LSP"
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
