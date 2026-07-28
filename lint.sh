#!/usr/bin/env bash
# Run both linters on the project.
#   Usage:  ./lint.sh
#
# The script exits non-zero if EITHER linter reports a problem, so it can gate
# commits / CI. All tracked modules currently pass both linters cleanly.

py_files="sushi_harvest_tracker.py libinsight_usage_reports.py springshare_auth.py sushi_reharvest.py"

echo "=== Ruff ==="
ruff check .
ruff_status=$?

echo
echo "=== Pylint ==="
# shellcheck disable=SC2086
pylint $py_files
pylint_status=$?

echo
echo "=== Summary ==="
if [ "$ruff_status" -eq 0 ]; then
  echo "Ruff:   passed"
else
  echo "Ruff:   issues found (see above)"
fi
if [ "$pylint_status" -eq 0 ]; then
  echo "Pylint: passed"
else
  echo "Pylint: issues found (see above)"
fi

if [ "$ruff_status" -ne 0 ] || [ "$pylint_status" -ne 0 ]; then
  exit 1
fi
exit 0
