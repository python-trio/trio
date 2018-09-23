#!/bin/bash

set -ex

EXIT_STATUS=0

# Autoformatter *first*, to avoid double-reporting errors
yapf -rpd setup.py trio \
    || EXIT_STATUS=$?

# Run flake8 with lots of ignores (mostly import-related)
flake8 trio/ \
    --ignore=D,E201,E402,E501,E722,E741,F401,F403,F405,F821,F822,W503 \
    || EXIT_STATUS=$?

# Bandit is a security-oriented linter
bandit --recursive --exclude=trio/tests --skip=B101,B311,B404 trio/ \
    || EXIT_STATUS=$?

# Finally, leave a really clear warning of any issues and exit
if [ $EXIT_STATUS -ne 0 ]; then
    cat <<EOF
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

Problems were found by static analysis (listed above).
To fix formatting and see remaining errors, run

    pip install -r test-requirements.txt
    yapf -rpi setup.py trio
    ./check.sh

in your local checkout.

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
EOF
    exit 1
fi
exit 0
