#!/usr/bin/env bash
# Keep the request/control pipe connected across su. Python owns all restoration.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
python="$1"
shift
export PATH="$(dirname -- "$python"):/system/bin:/system/xbin:$PATH"
unset LD_PRELOAD

if [[ "$EUID" == 0 ]]; then
    exec "$python" -u "$root/AndroidSwitch/civswitch.py" "$@"
fi

# su -c uses Android's shell: quote arguments as POSIX strings, including paths
# containing spaces or apostrophes. Never interpret project paths as shell code.
quote() { printf "'%s'" "${1//\'/\'\\\'\'}"; }
command="export PATH=$(quote "$PATH"); unset LD_PRELOAD; exec"
for arg in "$python" -u "$root/AndroidSwitch/civswitch.py" "$@"; do
    command+=" $(quote "$arg")"
done
exec su -c "$command"
