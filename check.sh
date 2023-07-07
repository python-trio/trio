#!/bin/bash

set -ex

EXIT_STATUS=0

# Test if the generated code is still up to date
python ./trio/_tools/gen_exports.py --test \
    || EXIT_STATUS=$?

# Autoformatter *first*, to avoid double-reporting errors
# (we'd like to run further autoformatters but *after* merging;
# see https://forum.bors.tech/t/pre-test-and-pre-merge-hooks/322)
# autoflake --recursive --in-place .
# pyupgrade --py3-plus $(find . -name "*.py")
if ! black --check setup.py trio; then
    EXIT_STATUS=1
    black --diff setup.py trio
fi

if ! isort --check setup.py trio; then
    EXIT_STATUS=1
    isort --diff setup.py trio
fi

# Run flake8, configured in pyproject.toml
flake8 trio/ || EXIT_STATUS=$?

# Run mypy on all supported platforms
mypy -m trio -m trio.testing --platform linux || EXIT_STATUS=$?
mypy -m trio -m trio.testing --platform darwin || EXIT_STATUS=$?  # tests FreeBSD too
mypy -m trio -m trio.testing --platform win32 || EXIT_STATUS=$?

# Check pip compile is consistent
pip-compile test-requirements.in
pip-compile docs-requirements.in

if git status --porcelain | grep -q "requirements.txt"; then
    git status --porcelain
    git --no-pager diff --color *requirements.txt
    EXIT_STATUS=1
fi

python trio/_tests/check_type_completeness.py --overwrite-file || EXIT_STATUS=$?
if git status --porcelain trio/_tests/verify_types.json | grep -q "M"; then
    echo "Type completeness changed, please update!"
    git --no-pager diff --color trio/_tests/verify_types.json
    EXIT_STATUS=1
fi

# Finally, leave a really clear warning of any issues and exit
if [ $EXIT_STATUS -ne 0 ]; then
    cat <<EOF
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

Problems were found by static analysis (listed above).
To fix formatting and see remaining errors, run

    pip install -r test-requirements.txt
    black setup.py trio
    isort setup.py trio
    ./check.sh

in your local checkout.

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
EOF
    exit 1
fi
exit 0
