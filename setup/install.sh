#!/usr/bin/env bash
# InkPlot installer for macOS and Linux.
#   1. finds Python 3.11 (or installs it with uv, no admin password needed)
#   2. makes a Python environment in ~/.venvs/handwriting-synthesis
#   3. installs the libraries
#   4. downloads the handwriting model (github.com/sjvasquez/handwriting-synthesis, pinned commit)
#      into handwriting-synthesis/ and applies setup/model.patch
#   5. adds the "inkplot" command (and on Linux an app-menu entry)
# Safe to run again: it skips what is already done.
# Colour and symbols only in a real terminal; NO_COLOR or a dumb terminal gives plain ASCII.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${INKPLOT_VENV:-$HOME/.venvs/handwriting-synthesis}"   # INKPLOT_VENV: use another folder (for testing)
MODEL_REPO="https://github.com/sjvasquez/handwriting-synthesis"
MODEL_COMMIT="5f58984c3bc793bd8930bad7012cd2008d4a4a66"
SYN="$ROOT/handwriting-synthesis"
OS="$(uname -s)"
TMPD="${TMPDIR:-/tmp}"
LOG="$(mktemp "${TMPD%/}/inkplot-install.XXXXXX")"
STEPS=5
TILDE="~"            # a variable, so bash 5 does not expand it back to the home folder
STEP=0

# ---- look -------------------------------------------------------------------------
TTY=0; COLOR=0; UNI=0
if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ]; then
  TTY=1
  [ -z "${NO_COLOR:-}" ] && COLOR=1
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in *UTF-8*|*utf-8*|*UTF8*|*utf8*) UNI=1 ;; esac
fi
if [ $COLOR = 1 ]; then
  B=$'\033[1m'; D=$'\033[2m'; R=$'\033[0m'; RED=$'\033[31m'; GRN=$'\033[32m'; BLU=$'\033[34m'
  if [ "$(tput colors 2>/dev/null || echo 8)" -ge 256 ]; then
    INK=(  $'\033[38;5;25m' $'\033[38;5;26m' $'\033[38;5;27m' $'\033[38;5;32m' $'\033[38;5;33m' $'\033[38;5;39m' )
  else
    INK=( "$BLU" "$BLU" "$BLU" "$BLU" "$BLU" "$BLU" )
  fi
else
  B=; D=; R=; RED=; GRN=; BLU=; INK=( "" "" "" "" "" "" )
fi
if [ $UNI = 1 ]; then
  OK="✓"; NO="✗"; DOT="›"; FRAMES=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
else
  OK="ok"; NO="x"; DOT=">"; FRAMES=('|' '/' '-' '\')
fi

banner() {
  [ -n "${INKPLOT_BANNER_SHOWN:-}" ] && return 0
  echo
  if [ $UNI = 1 ]; then
    local rows=(
      "██╗███╗   ██╗██╗  ██╗██████╗ ██╗      ██████╗ ████████╗"
      "██║████╗  ██║██║ ██╔╝██╔══██╗██║     ██╔═══██╗╚══██╔══╝"
      "██║██╔██╗ ██║█████╔╝ ██████╔╝██║     ██║   ██║   ██║   "
      "██║██║╚██╗██║██╔═██╗ ██╔═══╝ ██║     ██║   ██║   ██║   "
      "██║██║ ╚████║██║  ██╗██║     ███████╗╚██████╔╝   ██║   "
      "╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝     ╚══════╝ ╚═════╝    ╚═╝   ")
    local i
    for i in 0 1 2 3 4 5; do printf '  %s%s%s\n' "${INK[$i]}" "${rows[$i]}" "$R"; done
    printf '\n  %s✎ ∿∿∿∿%s %sturns a 3D printer into a pen plotter that writes in your handwriting%s\n' "${INK[3]}" "$R" "$D" "$R"
  else
    printf '%s\n' "  ___       _    ____  _       _   " "  |_ _|_ __ | | _|  _ \\| | ___ | |_ " \
      "   | || '_ \\| |/ / |_) | |/ _ \\| __|" "   | || | | |   <|  __/| | (_) | |_ " "  |___|_| |_|_|\\_\\_|   |_|\\___/ \\__|"
    printf '\n  turns a 3D printer into a pen plotter that writes in your handwriting\n'
  fi
  echo
}

step() { STEP=$((STEP + 1)); printf '\n%s%s[%d/%d]%s %s%s%s\n' "$B" "$BLU" "$STEP" "$STEPS" "$R" "$B" "$*" "$R"; }
ok()   { printf '  %s%s%s %s\n' "$GRN" "$OK" "$R" "$*"; }
note() { printf '  %s%s %s%s\n' "$D" "$DOT" "$*" "$R"; }
die()  {
  printf '\n  %s%s%s %sInkPlot could not be installed:%s %s\n' "$RED" "$NO" "$R" "$B" "$R" "$*" >&2
  if [ -s "$LOG" ]; then
    printf '\n  %sLast lines of the log (%s):%s\n' "$D" "$LOG" "$R" >&2
    tail -n 15 "$LOG" | sed 's/^/    /' >&2
  fi
  exit 1
}
has() { command -v "$1" >/dev/null 2>&1; }
elapsed() { local s=$1; [ "$s" -ge 60 ] && printf '%dm %02ds' $((s / 60)) $((s % 60)) || printf '%ds' "$s"; }

# run "label" command...: a spinner while it works (output goes to the log), then ✓ or ✗ with the log's tail
SPIN_PID=
run() {
  local label="$1"; shift
  local start=$SECONDS rc=0
  if [ $TTY = 1 ]; then
    "$@" >>"$LOG" 2>&1 &
    SPIN_PID=$!
    local i=0
    printf '\033[?25l'
    while kill -0 "$SPIN_PID" 2>/dev/null; do
      printf '\r  %s%s%s %s %s%s%s' "$BLU" "${FRAMES[$((i % ${#FRAMES[@]}))]}" "$R" "$label" "$D" "$(elapsed $((SECONDS - start)))" "$R"
      i=$((i + 1)); sleep 0.1
    done
    wait "$SPIN_PID" || rc=$?
    SPIN_PID=
    printf '\r\033[K\033[?25h'
  else
    printf '  .. %s\n' "$label"
    "$@" >>"$LOG" 2>&1 || rc=$?
  fi
  [ $rc = 0 ] || die "$label failed."
  ok "$label ${D}($(elapsed $((SECONDS - start))))${R}"
}
cleanup() {
  [ -n "$SPIN_PID" ] && kill "$SPIN_PID" 2>/dev/null
  [ $TTY = 1 ] && printf '\033[?25h'
  return 0
}
trap cleanup EXIT
trap 'cleanup; printf "\n  Stopped.\n" >&2; exit 130' INT TERM

# ---- checks ----------------------------------------------------------------------------
banner
case "$OS" in
  Darwin|Linux) ;;
  *) die "InkPlot runs on macOS and Linux (this is $OS)." ;;
esac
has curl || die "curl is needed. On Linux: sudo apt install curl (or your system's package manager)."
has tar || die "tar is needed."

# ---- 1. Python 3.11 --------------------------------------------------------------------
step "Python 3.11"
PY="$(command -v python3.11 || true)"
for p in /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11; do
  [ -z "$PY" ] && [ -x "$p" ] && PY="$p"
done
UV="$(command -v uv || true)"
[ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
[ -z "$UV" ] && [ -x "$HOME/.cargo/bin/uv" ] && UV="$HOME/.cargo/bin/uv"
if [ -z "$PY" ] && [ -n "$UV" ]; then
  PY="$("$UV" python find 3.11 2>/dev/null || true)"
fi
# a Python 3.11 without venv support (Debian/Ubuntu without python3.11-venv) is no use
if [ -n "$PY" ] && ! "$PY" -c "import venv, ensurepip" >/dev/null 2>&1; then
  PY=""
fi
if [ -z "$PY" ]; then
  if [ -z "$UV" ]; then
    get_uv() { curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh; }
    run "Installing uv, which fetches Python for you (no password needed)" get_uv
    UV="$HOME/.local/bin/uv"
    [ -x "$UV" ] || UV="$HOME/.cargo/bin/uv"
    [ -x "$UV" ] || die "uv did not install. Install Python 3.11 yourself, then run this again."
  fi
  run "Downloading Python 3.11" "$UV" python install 3.11
  PY="$("$UV" python find 3.11)"
fi
ok "Using ${D}$PY${R}"

# ---- 2. environment ------------------------------------------------------------------------
step "Python environment"
if [ ! -x "$VENV/bin/python" ]; then
  mkdir -p "$(dirname "$VENV")"
  run "Making it in ${VENV/#$HOME/$TILDE}" "$PY" -m venv "$VENV"
else
  ok "Already there: ${D}${VENV/#$HOME/$TILDE}${R}"
fi

# ---- 3. libraries ----------------------------------------------------------------------------
step "Libraries"
if [ "$OS" = Darwin ]; then
  EXTRA="ocrmac==1.0.1"              # macOS text recognition: picks the most readable try of each AI line
else
  EXTRA="pillow-heif"                # iPhone photos (HEIC) for scanned fonts
fi
pip_install() {
  "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install "numpy<2" "tensorflow==2.15.1" "tensorflow-probability==0.23.0" \
    scipy matplotlib pandas scikit-learn svgwrite svgelements pillow fonttools "$EXTRA"
}
note "TensorFlow is large: the first time takes a few minutes."
run "Installing TensorFlow and the rest" pip_install

# ---- 4. the handwriting model ------------------------------------------------------------------
step "Handwriting model"
get_model() {
  local tmp src
  tmp="$(mktemp -d)"
  curl -fsSL "$MODEL_REPO/archive/$MODEL_COMMIT.tar.gz" | tar -xz -C "$tmp"
  src="$tmp/handwriting-synthesis-$MODEL_COMMIT"
  [ -f "$src/rnn.py" ] || { echo "the model download looks incomplete"; return 1; }
  if has patch; then
    ( cd "$src" && patch -p1 --quiet < "$ROOT/setup/model.patch" )
  else
    ( cd "$src" && git apply "$ROOT/setup/model.patch" )
  fi
  mkdir -p "$SYN"
  for f in checkpoints styles data_frame.py demo.py drawing.py lyrics.py readme.md requirements.txt \
           rnn.py rnn_cell.py rnn_ops.py tf_base_model.py tf_utils.py; do
    [ -e "$SYN/$f" ] || cp -R "$src/$f" "$SYN/"
  done
  rm -rf "$tmp"
}
if [ ! -f "$SYN/rnn.py" ]; then
  has patch || has git || die "'patch' or 'git' is needed to set up the model. On Linux: sudo apt install patch"
  run "Downloading and setting up the model" get_model
else
  ok "Already there"
fi
[ -f "$SYN/calibration.json" ] || cp "$SYN/calibration.example.json" "$SYN/calibration.json"
chmod +x "$ROOT/inkplot" "$SYN/plotcheck" "$SYN/calibrate" "$SYN/magnets" "$ROOT/handwriting/My Handwriting.command" \
  "$ROOT/Install InkPlot.command" "$ROOT/setup/install.sh" 2>/dev/null || true

# ---- 5. shortcuts -------------------------------------------------------------------------------
step "Shortcuts"
mkdir -p "$HOME/.local/bin"
ln -sf "$ROOT/inkplot" "$HOME/.local/bin/inkplot"
ok "The ${B}inkplot${R} command ${D}(~/.local/bin)${R}"
if [ "$OS" = Linux ]; then
  mkdir -p "$HOME/.local/share/applications"
  cat > "$HOME/.local/share/applications/inkplot.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=InkPlot
Comment=Handwriting for a pen plotter
Exec="$ROOT/inkplot"
Icon=$ROOT/handwriting/static/icon.svg
Terminal=true
Categories=Graphics;
EOF
  ok "InkPlot in your app menu"
fi
rm -f "$LOG"

# ---- done -----------------------------------------------------------------------------------------
case ":$PATH:" in *":$HOME/.local/bin:"*) CMD="inkplot" ;; *) CMD="${ROOT/#$HOME/$TILDE}/inkplot" ;; esac
if [ $UNI = 1 ]; then H="─"; else H="-"; fi
LINE=""; for _ in $(seq 1 58); do LINE="$LINE$H"; done
printf '\n  %s%s%s\n' "$D" "$LINE" "$R"
printf '  %s%s InkPlot is installed%s\n\n' "$GRN$B" "$OK" "$R"
if [ "$OS" = Darwin ]; then
  printf '  %sStart it%s    double-click %shandwriting/My Handwriting.command%s\n' "$B" "$R" "$B" "$R"
  printf '              in %s, or run %s%s%s\n' "${ROOT/#$HOME/$TILDE}" "$B" "$CMD" "$R"
else
  printf '  %sStart it%s    pick %sInkPlot%s in your app menu, or run %s%s%s\n' "$B" "$R" "$B" "$R" "$B" "$CMD" "$R"
fi
printf '  %sThen%s        Plotter %s Machine: choose your printer and calibrate the pen\n' "$B" "$R" "$DOT"
printf '  %sGuide%s       https://github.com/itwasfineincad/inkplot/blob/main/docs/GUIDE.md\n' "$B" "$R"
if [ "$OS" = Linux ]; then
  has tesseract || printf '\n  %s%s Optional: sudo apt install tesseract-ocr for better AI handwriting%s\n' "$D" "$DOT" "$R"
  has pdftoppm || printf '  %s%s Optional: sudo apt install poppler-utils to scan font templates saved as PDF%s\n' "$D" "$DOT" "$R"
fi
printf '  %s%s%s\n\n' "$D" "$LINE" "$R"
