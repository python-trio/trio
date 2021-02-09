#!/bin/bash

set -ex

EXIT_STATUS=0

# Test if the generated code is still up to date
python ./trio/_tools/gen_exports.py --test \
    || EXIT_STATUS=$?

# Run mypy on all supported platforms
for PLATFORM in linux darwin win32; do
  for VERSION in 3.6 3.7 3.8 3.9; do
    mypy -p trio --platform $PLATFORM --python-version $VERSION || EXIT_STATUS=$?
  done
done

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
