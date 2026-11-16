#!/bin/bash
# Linux (Ubuntu/Debian) uchun: sudo apt install python3-venv ffmpeg
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo "ffmpeg kerak: sudo apt install ffmpeg"; exit 1; }
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -r requirements.txt || exit 1
.venv/bin/python -m kadrgo selfcheck && echo "TAYYOR: ./run_kadrgo.command"
