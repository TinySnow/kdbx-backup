#!/bin/sh
# Compatibility wrapper for the cross-platform Python manager.
set -eu
exec python3 "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/manage.py" "$@"
