#!/bin/bash
# InkPlot installer for macOS.
#   1. makes a Python 3.11 environment in ~/.venvs/handwriting-synthesis
#   2. installs TensorFlow 2.15 and the other libraries
#   3. downloads the handwriting model (github.com/sjvasquez/handwriting-synthesis,
#      pinned commit) into handwriting-synthesis/ and applies setup/model.patch
# Safe to run again: it skips what is already done.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${INKPLOT_VENV:-$HOME/.venvs/handwriting-synthesis}"   # INKPLOT_VENV: use another folder (for testing)
MODEL_REPO="https://github.com/sjvasquez/handwriting-synthesis.git"
MODEL_COMMIT="5f58984c3bc793bd8930bad7012cd2008d4a4a66"
SYN="$ROOT/handwriting-synthesis"

say() { printf '\n== %s\n' "$*"; }

say "Checking for Python 3.11"
PY="$(command -v python3.11 || true)"
for p in /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11; do
  [ -z "$PY" ] && [ -x "$p" ] && PY="$p"
done
if [ -z "$PY" ] && command -v uv >/dev/null 2>&1; then
  PY="$(uv python find 3.11 2>/dev/null || true)"
fi
if [ -z "$PY" ]; then
  echo "Python 3.11 is needed (TensorFlow 2.15 does not run on newer versions)."
  echo "Install it with Homebrew:  brew install python@3.11   then run this again."
  exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
  say "Making the Python environment in $VENV"
  mkdir -p "$(dirname "$VENV")"
  "$PY" -m venv "$VENV"
fi

say "Installing libraries (TensorFlow is large; this can take a few minutes)"
"$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install "numpy<2" "tensorflow==2.15.1" "tensorflow-probability==0.23.0" \
  scipy matplotlib pandas scikit-learn svgwrite svgelements pillow fonttools "ocrmac==1.0.1"

if [ ! -f "$SYN/rnn.py" ]; then
  say "Downloading the handwriting model"
  TMP="$(mktemp -d)"
  git clone --quiet "$MODEL_REPO" "$TMP/model"
  git -C "$TMP/model" checkout --quiet "$MODEL_COMMIT"
  ( cd "$TMP/model" && patch -p1 --quiet < "$ROOT/setup/model.patch" )
  mkdir -p "$SYN"
  for f in checkpoints styles data_frame.py demo.py drawing.py lyrics.py readme.md requirements.txt \
           rnn.py rnn_cell.py rnn_ops.py tf_base_model.py tf_utils.py; do
    [ -e "$SYN/$f" ] || cp -R "$TMP/model/$f" "$SYN/"
  done
  rm -rf "$TMP"
else
  say "Handwriting model already there"
fi

[ -f "$SYN/calibration.json" ] || cp "$SYN/calibration.example.json" "$SYN/calibration.json"
chmod +x "$SYN/plotcheck" "$SYN/calibrate" "$SYN/magnets" "$ROOT/handwriting/My Handwriting.command" 2>/dev/null || true

say "Done"
echo "Start InkPlot by double-clicking handwriting/My Handwriting.command."
echo "Before plotting, calibrate the pen: Plotter page > Calibration > Calibrate."
