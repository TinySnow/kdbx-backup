# Optional Windows wrapper. "python scripts/manage.py ..." needs no policy changes.
$ErrorActionPreference = 'Stop'
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 "$PSScriptRoot/manage.py" @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python "$PSScriptRoot/manage.py" @args
} else {
    throw 'Install Python 3.9+ and add it to PATH.'
}
exit $LASTEXITCODE
