#!/bin/bash
# KADRGO Studio o'rnatish (macOS). Ishga tushirish: Finder da ikki marta bosing yoki terminalda ./install_mac.command
cd "$(dirname "$0")"
echo "======================================================"
echo "  KADRGO Studio o'rnatish (macOS)"
echo "======================================================"
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew kerak: https://brew.sh  (o'rnatib, so'ng bu skriptni qayta ishga tushiring)"; exit 1
fi
command -v python3 >/dev/null 2>&1 || brew install python@3.12
python3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" || { echo "Python 3.10+ kerak: brew install python@3.12"; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || brew install ffmpeg
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt || { echo "O'rnatish xatosi"; exit 1; }
LAUNCH="$HOME/Desktop/KADRGO Studio.command"
printf '#!/bin/bash\ncd "%s"\nexec .venv/bin/python -m kadrgo "$@"\n' "$(pwd)" > "$LAUNCH"
chmod +x "$LAUNCH" run_kadrgo.command 2>/dev/null
echo; echo "O'z-o'zini tekshirish..."
.venv/bin/python -m kadrgo info
.venv/bin/python -m kadrgo selfcheck
echo; echo "TAYYOR. Desktop dagi 'KADRGO Studio.command' ni ishga tushiring."
