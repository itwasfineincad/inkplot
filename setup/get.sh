#!/usr/bin/env bash
# Install, update or remove InkPlot with one command (macOS and Linux):
#
#   curl -fsSL https://raw.githubusercontent.com/itwasfineincad/inkplot/main/setup/get.sh | bash
#
# First time: downloads InkPlot into ~/InkPlot (or the folder in INKPLOT_DIR) and runs setup/install.sh.
# Already installed: asks whether to update it or remove it. Without a terminal to ask in, it updates.
#
#   … | bash -s -- --update     update without asking
#   … | bash -s -- --remove     remove (asks first; add --yes to skip the questions)
#   ~/InkPlot/setup/get.sh --remove    the same, from the installed copy (no download needed)
#
# Updating keeps your own files (fonts, layouts, calibration). Removing keeps a copy of them in
# ~/InkPlot-saved-<date> unless you say not to, and uses the Trash where there is one.
set -euo pipefail
REPO="itwasfineincad/inkplot"
DIR="${INKPLOT_DIR:-$HOME/InkPlot}"
DIR="${DIR%/}"
VENV="${INKPLOT_VENV:-$HOME/.venvs/handwriting-synthesis}"
TILDE="~"
MODE=""; YES=0
for a in "$@"; do
  case "$a" in
    --update|update) MODE=update ;;
    --remove|remove|--uninstall|uninstall) MODE=remove ;;
    --yes|-y) YES=1 ;;
    -h|--help) sed -n '2,14p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $a (use --update, --remove or --yes)" >&2; exit 2 ;;
  esac
done

# the same look as setup/install.sh: colour and symbols only in a real terminal, NO_COLOR respected
TTY=0; COLOR=0; UNI=0
if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ]; then
  TTY=1
  [ -z "${NO_COLOR:-}" ] && COLOR=1
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in *UTF-8*|*utf-8*|*UTF8*|*utf8*) UNI=1 ;; esac
fi
if [ $COLOR = 1 ]; then
  B=$'\033[1m'; D=$'\033[2m'; R=$'\033[0m'; RED=$'\033[31m'; GRN=$'\033[32m'; BLU=$'\033[34m'
  if [ "$(tput colors 2>/dev/null || echo 8)" -ge 256 ]; then
    INK=( $'\033[38;5;25m' $'\033[38;5;26m' $'\033[38;5;27m' $'\033[38;5;32m' $'\033[38;5;33m' $'\033[38;5;39m' )
  else
    INK=( "$BLU" "$BLU" "$BLU" "$BLU" "$BLU" "$BLU" )
  fi
else
  B=; D=; R=; RED=; GRN=; BLU=; INK=( "" "" "" "" "" "" )
fi
if [ $UNI = 1 ]; then OK="✓"; NO="✗"; DOT="›"; else OK="ok"; NO="x"; DOT=">"; fi
ok()   { printf '  %s%s%s %s\n' "$GRN" "$OK" "$R" "$*"; }
note() { printf '  %s%s %s%s\n' "$D" "$DOT" "$*" "$R"; }
die()  { printf '\n  %s%s%s %s%s%s\n' "$RED" "$NO" "$R" "$B" "$*" "$R" >&2; exit 1; }
short() { printf '%s' "${1/#$HOME/$TILDE}"; }

# questions are read from the terminal itself: with "curl … | bash", stdin is the script
CANASK=0
if [ -t 1 ] && (: </dev/tty) 2>/dev/null; then CANASK=1; fi
ask() {   # ask "question" default(y/n) -> 0 for yes
  local q="$1" def="$2" ans
  [ $YES = 1 ] && return 0                     # --yes answers yes to everything
  [ $CANASK = 1 ] || { [ "$def" = y ]; return; }
  printf '  %s %s ' "$q" "$([ "$def" = y ] && echo '[Y/n]' || echo '[y/N]')"
  read -r ans </dev/tty || ans=""
  case "${ans:-$def}" in y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}

echo
if [ $UNI = 1 ]; then
  rows=(
    "██╗███╗   ██╗██╗  ██╗██████╗ ██╗      ██████╗ ████████╗"
    "██║████╗  ██║██║ ██╔╝██╔══██╗██║     ██╔═══██╗╚══██╔══╝"
    "██║██╔██╗ ██║█████╔╝ ██████╔╝██║     ██║   ██║   ██║   "
    "██║██║╚██╗██║██╔═██╗ ██╔═══╝ ██║     ██║   ██║   ██║   "
    "██║██║ ╚████║██║  ██╗██║     ███████╗╚██████╔╝   ██║   "
    "╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝     ╚══════╝ ╚═════╝    ╚═╝   ")
  for i in 0 1 2 3 4 5; do printf '  %s%s%s\n' "${INK[$i]}" "${rows[$i]}" "$R"; done
  printf '\n  %s✎ ∿∿∿∿%s %sturns a 3D printer into a pen plotter that writes in your handwriting%s\n\n' "${INK[3]}" "$R" "$D" "$R"
else
  printf '%s\n' "  ___       _    ____  _       _   " "  |_ _|_ __ | | _|  _ \\| | ___ | |_ " \
    "   | || '_ \\| |/ / |_) | |/ _ \\| __|" "   | || | | |   <|  __/| | (_) | |_ " "  |___|_| |_|_|\\_\\_|   |_|\\___/ \\__|"
  printf '\n  turns a 3D printer into a pen plotter that writes in your handwriting\n\n'
fi

OS="$(uname -s)"
case "$OS" in
  Darwin|Linux) ;;
  *) die "InkPlot runs on macOS and Linux." ;;
esac

INSTALLED=0
[ -f "$DIR/inkplot" ] && [ -f "$DIR/setup/install.sh" ] && INSTALLED=1

# ---- already installed: update or remove? ----------------------------------------------------------
if [ $INSTALLED = 1 ] && [ -z "$MODE" ]; then
  printf '%sInkPlot is already installed%s %sin %s%s\n\n' "$B" "$R" "$D" "$(short "$DIR")" "$R"
  if [ $CANASK = 1 ] && [ $YES = 0 ]; then
    printf '    %s1%s  Update it %s(keeps your fonts, layouts and calibration)%s\n' "$B" "$R" "$D" "$R"
    printf '    %s2%s  Remove it\n' "$B" "$R"
    printf '    %s3%s  Cancel\n\n' "$B" "$R"
    printf '  Choose 1, 2 or 3 [1]: '
    read -r pick </dev/tty || pick=""
    case "${pick:-1}" in
      1) MODE=update ;;
      2) MODE=remove ;;
      *) echo; note "Nothing changed."; echo; exit 0 ;;
    esac
    echo
  else
    MODE=update
  fi
fi
[ -z "$MODE" ] && MODE=install

# ---- remove ------------------------------------------------------------------------------------------
# the files that are yours, not InkPlot's (all git-ignored, never in a download)
PERSONAL=( handwriting/fonts handwriting/styles.json handwriting/plot_state.json handwriting/ui_settings.json
           handwriting/uploads handwriting/out handwriting/handfont.py
           handwriting-synthesis/calibration.json handwriting-synthesis/magnets.json handwriting-synthesis/printers.json )

to_trash() {   # move to the Trash where there is one; otherwise delete
  local p="$1"
  [ -e "$p" ] || [ -L "$p" ] || return 0
  if [ "$OS" = Darwin ] && [ -d "$HOME/.Trash" ] && [ ! -L "$p" ]; then
    mv "$p" "$HOME/.Trash/$(basename "$p")-$(date +%Y%m%d-%H%M%S)"
  elif [ "$OS" = Linux ] && command -v gio >/dev/null 2>&1 && gio trash "$p" 2>/dev/null; then
    :
  else
    rm -rf "$p"
  fi
}

if [ "$MODE" = remove ]; then
  [ $INSTALLED = 1 ] || [ -d "$VENV" ] || [ -L "$HOME/.local/bin/inkplot" ] || die "InkPlot isn't installed in $(short "$DIR")."
  # never remove anything that isn't plainly an InkPlot folder
  if [ $INSTALLED = 1 ]; then
    case "$DIR" in "$HOME"|"/"|"") die "refusing to remove $DIR." ;; esac
  fi
  printf '%sRemove InkPlot%s\n' "$B" "$R"
  [ $INSTALLED = 1 ] && note "$(short "$DIR")  $(du -sh "$DIR" 2>/dev/null | cut -f1)"
  [ -d "$VENV" ] && note "$(short "$VENV")  $(du -sh "$VENV" 2>/dev/null | cut -f1)  (InkPlot's Python libraries)"
  [ -L "$HOME/.local/bin/inkplot" ] && note "the inkplot command"
  [ -f "$HOME/.local/share/applications/inkplot.desktop" ] && note "InkPlot in the app menu"
  mine=()
  if [ $INSTALLED = 1 ]; then
    for p in "${PERSONAL[@]}"; do [ -e "$DIR/$p" ] && mine+=( "$p" ); done
  fi
  echo
  if [ $CANASK = 0 ] && [ $YES = 0 ]; then
    die "To remove InkPlot without a terminal to ask in, add --yes."
  fi
  KEEP=0
  if [ ${#mine[@]} -gt 0 ]; then
    SAVED="$HOME/InkPlot-saved-$(date +%Y-%m-%d)"
    ask "Keep a copy of your fonts, layouts and calibration in $(short "$SAVED")?" y && KEEP=1
  fi
  where="$([ "$OS" = Darwin ] && echo "moves it to the Trash" || (command -v gio >/dev/null 2>&1 && echo "moves it to the Trash" || echo "deletes it for good"))"
  ask "Remove InkPlot? This $where." n || { echo; note "Nothing removed."; echo; exit 0; }
  echo
  if [ $KEEP = 1 ]; then
    mkdir -p "$SAVED"
    for p in "${mine[@]}"; do
      mkdir -p "$SAVED/$(dirname "$p")"
      cp -R "$DIR/$p" "$SAVED/$p"
    done
    ok "Your files are in $(short "$SAVED")"
  fi
  [ -L "$HOME/.local/bin/inkplot" ] && rm -f "$HOME/.local/bin/inkplot" && ok "Removed the inkplot command"
  if [ -f "$HOME/.local/share/applications/inkplot.desktop" ]; then
    rm -f "$HOME/.local/share/applications/inkplot.desktop" && ok "Removed InkPlot from the app menu"
  fi
  if [ -d "$VENV" ]; then to_trash "$VENV"; ok "Removed the Python libraries"; fi
  if [ $INSTALLED = 1 ]; then to_trash "$DIR"; ok "Removed $(short "$DIR")"; fi
  echo
  note "Python 3.11 and uv (if the installer added them) stay: other programs may use them."
  [ $KEEP = 1 ] && note "To bring your files back, install InkPlot again and copy them from $(short "$SAVED") into it."
  printf '\n  %s%s InkPlot is removed%s\n\n' "$GRN$B" "$OK" "$R"
  exit 0
fi

# ---- install or update -----------------------------------------------------------------------------------
command -v curl >/dev/null 2>&1 || die "curl is needed."
command -v tar >/dev/null 2>&1 || die "tar is needed."
if [ "$MODE" = update ] && [ $INSTALLED = 0 ]; then MODE=install; fi
printf '%s%s InkPlot%s %s%s %s%s\n' "$B" "$([ "$MODE" = update ] && echo Updating || echo Getting)" "$R" "$D" \
  "$([ "$MODE" = update ] && echo in || echo into)" "$(short "$DIR")" "$R"
if [ -d "$DIR/.git" ] && command -v git >/dev/null 2>&1; then
  before="$(git -C "$DIR" rev-parse --short HEAD 2>/dev/null || echo ?)"
  git -C "$DIR" pull --ff-only --quiet || die "InkPlot could not be updated with git. Check your connection, or move the folder away and run this again."
  after="$(git -C "$DIR" rev-parse --short HEAD 2>/dev/null || echo ?)"
  if [ "$before" = "$after" ]; then ok "Already up to date ($after)"; else ok "Updated ($before $DOT $after)"; fi
elif [ ! -e "$DIR" ] && command -v git >/dev/null 2>&1; then
  git clone --quiet --depth 1 "https://github.com/$REPO.git" "$DIR" || die "InkPlot could not be downloaded from GitHub. Check your connection."
  ok "Downloaded"
else
  # no git: unpack the latest version over the folder (personal files are not in the download, so they stay)
  mkdir -p "$DIR"
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar -xz -C "$DIR" --strip-components=1 \
    || die "InkPlot could not be downloaded from GitHub. Check your connection."
  ok "$([ "$MODE" = update ] && echo "Updated to the latest version" || echo Downloaded)"
fi

# stdin is the downloaded script when run as "curl … | bash": give the installer an empty one instead
INKPLOT_BANNER_SHOWN=1 exec bash "$DIR/setup/install.sh" </dev/null
