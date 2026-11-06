#!/usr/bin/env bash
# Termux checks only. USB and root access belong to the session, not installation.
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
    echo "[setup] Python is missing. In the normal Termux shell, run: pkg install python" >&2
    exit 1
fi
for tool in su getenforce setenforce; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "[setup] $tool not found. A rooted Android phone is required." >&2
        exit 1
    fi
done
echo "[setup] Ready! Grant Termux root access when prompted by npm run test or npm start."
