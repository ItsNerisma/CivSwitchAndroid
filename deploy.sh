#!/bin/bash
# Build the payload and deploy everything to the phone via ADB.
# Usage: ./deploy.sh

set -euo pipefail

# Resolve files relative to this script, even when called from another directory.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

DEST=/data/local/tmp/civswitch
TERMUX_HOME=/data/data/com.termux/files/home
PYTHON=/data/data/com.termux/files/usr/bin/python3

# --- Check prerequisites before building or copying anything ---
for tool in adb node npm; do
    if ! command -v "$tool" > /dev/null 2>&1; then
        echo "ERROR: $tool not found. Install ADB, Node.js and npm on the PC."
        exit 1
    fi
done

if ! adb get-state > /dev/null 2>&1; then
    echo "ERROR: Connect exactly one phone via USB, enable USB debugging and accept authorization."
    exit 1
fi

echo "Checking Termux and root access (allow root on the phone if prompted)..."
if ! adb shell "su -c '[ -d $TERMUX_HOME ]'"; then
    echo "ERROR: Open Termux on the phone and grant root access before deploying."
    exit 1
fi
if ! adb shell "su -c '[ -x $PYTHON ]'"; then
    echo "ERROR: Python not found. In Termux, outside the root shell, run: pkg install python"
    exit 1
fi

# --- Always build from the current source; payload.txt is not versioned ---
echo "Building payload..."
(cd PicoSwitch && npm install --silent && node compress.js)

if [ ! -f PicoSwitch/payload.txt ]; then
    echo "ERROR: Failed to generate payload.txt."
    exit 1
fi
echo "Payload ready ($(wc -l < PicoSwitch/payload.txt) lines)"

# --- Push scripts ---
echo "Pushing scripts to phone..."
adb shell mkdir -p "$DEST"
for f in AndroidSwitch/*.sh AndroidSwitch/*.py; do
    adb push "$f" "$DEST/"
done
adb push PicoSwitch/payload.txt "$DEST/payload.txt"

# --- Create shortcuts in Termux home ---
echo "Creating shortcuts in Termux home..."
for script in teardown.sh test.sh run.sh; do
    adb shell "su -c 'ln -sf $DEST/$script $TERMUX_HOME/$script'"
done
adb shell "su -c 'ln -sfn $DEST $TERMUX_HOME/civswitch'"
echo "  Shortcuts created: ~/test.sh ~/run.sh ~/teardown.sh"

echo ""
echo "========================================"
echo "  DEPLOY COMPLETE"
echo "========================================"
echo ""
echo ">>> Unplug the phone from the PC. <<<"
echo ""
echo "On the phone, open Termux and type:"
echo "  su"
echo "  setenforce 0"
echo "  sh ~/test.sh      # Type two test messages"
echo "  sh ~/run.sh       # Run the full procedure after the test succeeds"
echo ""
echo "Run one command at a time, with the phone unplugged."
echo "Connect it to the Switch dock when prompted. Normal USB is restored automatically."
echo "Recovery: sh ~/teardown.sh"
