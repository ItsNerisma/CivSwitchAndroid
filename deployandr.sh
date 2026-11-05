#!/bin/sh
# Build the payload and set everything up from the phone.
#port of this script by Kris The Dog
# Usage: ./deployandr.sh
echo "make sure to run ./patchsudo first"
set -euo pipefail

DEST=/data/local/tmp/civswitch
TERMUX_HOME=/data/data/com.termux/files/home
PYTHON=/data/data/com.termux/files/usr/bin/python3

# --- Check prerequisites before building or copying anything ---
for tool in node npm; do
    if ! command -v "$tool" > /dev/null 2>&1; then
        echo "ERROR: $tool not found. Install Node.js and npm with pkg install."
        exit 1
    fi
done

echo "Checking Termux and root access (allow root on the phone if prompted)..."

if ! sudo echo "sudo working!"; then
     echo "ERROR: install sudo and run this with sudo, if it doesnt work run ./patchsudo.sh"
     exit 1
fi

if ! [ -x $PYTHON ]; then
    echo "ERROR: Python not found.Run: pkg install python"
    exit 1
fi

# --- Always build from the current source; payload.txt is not versioned ---
echo "Building payload..."
setenforce 0
(cd PicoSwitch && npm install --silent && node compress.js)

if [ ! -f PicoSwitch/payload.txt ]; then
    echo "ERROR: Failed to generate payload.txt."
    exit 1
fi
echo "Payload ready ($(wc -l < PicoSwitch/payload.txt) lines)"

# --- Push scripts ---
echo "Setting up scripts"
mkdir -p "$DEST"
for f in AndroidSwitch/*.sh AndroidSwitch/*.py; do
    cp "$f" "$DEST/"
done
cp PicoSwitch/payload.txt "$DEST/payload.txt"

# --- Create shortcuts in Termux home ---
echo "Creating shortcuts in Termux home..."
for script in teardown.sh test.sh run.sh; do
    ln -sf $DEST/$script $TERMUX_HOME/$script
done
ln -sfn $DEST $TERMUX_HOME/civswitch
echo "/  Shortcuts created: ~/test.sh ~/run.sh ~/teardown.sh"

echo ""
echo "========================================"
echo "  SETUP COMPLETE"
echo "========================================"
echo ""
echo "Now run:"
echo "  su"
echo "  setenforce 0"
echo "  sh test.sh        # Type two test messages"
echo "  sh run.sh         # Run the full procedure after the test succeeds"
echo ""
echo "Run one command at a time."
echo "Connect it to the Switch dock when prompted. Normal USB is restored automatically."
echo "Recovery: sh teardown.sh"
