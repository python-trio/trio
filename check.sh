#!/bin/bash

set -ex

EXIT_STATUS=0

# If not running on Github's CI, discard the summaries
if [ -z "${GITHUB_STEP_SUMMARY+x}"]; then
    GITHUB_STEP_SUMMARY=/dev/null
fi

# Test if the generated code is still up to date
echo "::group::Generate Exports"
python ./trio/_tools/gen_exports.py --test \
    || EXIT_STATUS=$?
echo "::endgroup::"

# Autoformatter *first*, to avoid double-reporting errors
# (we'd like to run further autoformatters but *after* merging;
# see https://forum.bors.tech/t/pre-test-and-pre-merge-hooks/322)
# autoflake --recursive --in-place .
# pyupgrade --py3-plus $(find . -name "*.py")
echo "::group::Black"
if ! black --check setup.py trio; then
    echo "* Black found issues" >> $GITHUB_STEP_SUMMARY
    EXIT_STATUS=1
    black --diff setup.py trio
fi
echo "::endgroup::"

echo "::group::ISort"
if ! isort --check setup.py trio; then
    echo "* isort found issues" >> $GITHUB_STEP_SUMMARY
    EXIT_STATUS=1
    isort --diff setup.py trio
fi
echo "::endgroup::"

# Run flake8, configured in pyproject.toml
echo "::group::Flake8"
flake8 trio/ || EXIT_STATUS=$?
echo "::endgroup::"

# Run mypy on all supported platforms
MYPY=0
echo "::group::Mypy"
mypy trio --show-error-end --platform linux | python ./trio/_tools/mypy_annotate.py Linux
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "* Mypy (Linux) found type errors." >> $GITHUB_STEP_SUMMARY
    EXIT_STATUS=1
fi
mypy trio --show-error-end --platform darwin | python ./trio/_tools/mypy_annotate.py Mac  # tests FreeBSD too
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "* Mypy (Mac) found type errors." >> $GITHUB_STEP_SUMMARY
    EXIT_STATUS=1
fi
mypy trio --show-error-end --platform win32 | python ./trio/_tools/mypy_annotate.py Windows
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "* Mypy (Windows) found type errors." >> $GITHUB_STEP_SUMMARY
    EXIT_STATUS=1
fi
echo "::endgroup::"

# Check pip compile is consistent
echo "::group::Pip Compile - Tests"
pip-compile test-requirements.in
echo "::endgroup::"
echo "::group::Pip Compile - Docs"
pip-compile docs-requirements.in
echo "::endgroup::"

if git status --porcelain | grep -q "requirements.txt"; then
    echo "::group::requirements.txt changed"
    echo "* requirements.txt changed" >> $GITHUB_STEP_SUMMARY
    git status --porcelain
    git --no-pager diff --color *requirements.txt
    EXIT_STATUS=1
    echo "::endgroup::"
fi

codespell || EXIT_STATUS=$?

python trio/_tests/check_type_completeness.py --overwrite-file || EXIT_STATUS=$?
if git status --porcelain trio/_tests/verify_types*.json | grep -q "M"; then
    echo "* Type completeness changed, please update!" >> $GITHUB_STEP_SUMMARY
    echo "Type completeness changed, please update!"
    git --no-pager diff --color trio/_tests/verify_types*.json
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
echo "# Formatting checks succeeded." >> $GITHUB_STEP_SUMMARY
exit 0
