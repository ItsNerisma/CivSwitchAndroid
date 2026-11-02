#!/system/bin/sh
# One session owns USB setup, continuous reports and automatic restoration.
PYTHON=/data/data/com.termux/files/usr/bin/python3
SCRIPTS=/data/local/tmp/civswitch
if [ ! -x "$PYTHON" ]; then
    echo "ERROR: Python not found. Open Termux and run: pkg install python"
    exit 1
fi
exec "$PYTHON" -u "$SCRIPTS/civswitch.py" test "$@"
