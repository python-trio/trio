#!/bin/bash

set -ex

EXIT_STATUS=0

# Test if the generated code is still up to date
python ./trio/_tools/gen_exports.py --test \
    || EXIT_STATUS=$?

# Run mypy on all supported platforms
mypy -p trio --platform linux || EXIT_STATUS=$?
mypy -p trio --platform darwin || EXIT_STATUS=$?  # tests FreeBSD too
mypy -p trio --platform win32 || EXIT_STATUS=$?

# Finally, leave a really clear warning of any issues and exit
if [ $EXIT_STATUS -ne 0 ]; then
    cat <<EOF
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

Problems were found by type checking (listed above).
To see remaining errors after attempting to addres them, run

    pip install -r test-requirements.txt
    ./typing.sh

in your local checkout.

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
EOF
    exit 1
fi
exit 0
