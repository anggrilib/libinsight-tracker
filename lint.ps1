# Run both linters on the project.
#   Usage:  ./lint.ps1
#
# The script exits non-zero if EITHER linter reports a problem, so it can gate
# commits / CI. All tracked modules currently pass both linters cleanly.

$pyFiles = @(
    "sushi_harvest_tracker.py",
    "libinsight_usage_reports.py",
    "springshare_auth.py",
    "sushi_reharvest.py"
)

Write-Host "=== Ruff ===" -ForegroundColor Cyan
ruff check .
$ruffStatus = $LASTEXITCODE

Write-Host ""
Write-Host "=== Pylint ===" -ForegroundColor Cyan
pylint @pyFiles
$pylintStatus = $LASTEXITCODE

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
if ($ruffStatus -eq 0) {
    Write-Host "Ruff:   passed" -ForegroundColor Green
} else {
    Write-Host "Ruff:   issues found (see above)" -ForegroundColor Red
}
if ($pylintStatus -eq 0) {
    Write-Host "Pylint: passed" -ForegroundColor Green
} else {
    Write-Host "Pylint: issues found (see above)" -ForegroundColor Red
}

if ($ruffStatus -ne 0 -or $pylintStatus -ne 0) { exit 1 } else { exit 0 }
