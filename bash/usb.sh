#!/usr/bin/env bash
# Keep the request/control pipe connected across su. Python owns all restoration.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
python="$1"
shift

export PATH="$(dirname -- "$python"):/system/bin:/system/xbin:/sbin:$PATH"
unset LD_PRELOAD

if [[ "$EUID" == 0 ]]; then
    exec "$python" -u "$root/AndroidSwitch/civswitch.py" "$@"
fi

if ! command -v su >/dev/null 2>&1; then
    echo "ERROR: su is unavailable. Root this phone and grant Termux root access." >&2
    exit 1
fi

# Quote each argument so Android's shell keeps project paths intact.
quote() { printf "'%s'" "${1//\'/\'\\\'\'}"; }

command="export PATH=$(quote "$PATH"); unset LD_PRELOAD; exec"
for arg in "$python" -u "$root/AndroidSwitch/civswitch.py" "$@"; do
    command+=" $(quote "$arg")"
done
exec su -c "$command"
