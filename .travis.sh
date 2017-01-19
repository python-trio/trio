#!/bin/bash

set -ex

if [ "$TRAVIS_OS_NAME" = "osx" ]; then
    curl -o macpython.pkg https://www.python.org/ftp/python/${MACPYTHON}/python-${MACPYTHON}-macosx10.6.pkg
    sudo installer -pkg macpython.pkg -target /
    ls /Library/Frameworks/Python.framework/Versions/*/bin/
    if expr "${MACPYTHON}" : 2; then
        PYBASE=python
    else
        PYBASE=python3
    fi
    PYTHON_EXE=/Library/Frameworks/Python.framework/Versions/*/bin/${PYBASE}
    sudo $PYTHON_EXE -m pip install virtualenv
    $PYTHON_EXE -m virtualenv testenv
    source testenv/bin/activate
fi

pip install -U pip setuptools wheel
pip install -Ur test-requirements.txt

python setup.py sdist --formats=zip
pip install dist/*.zip

mkdir empty
cd empty

INSTALLDIR=$(python -c "import os, trio; print(os.path.dirname(trio.__file__))")
pytest -ra --pyargs trio --cov="$INSTALLDIR" --cov-config=../.coveragerc

pip install codecov && codecov
