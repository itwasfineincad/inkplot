#!/usr/bin/env bash
# Install or update InkPlot with one command (macOS and Linux):
#
#   curl -fsSL https://raw.githubusercontent.com/itwasfineincad/inkplot/main/setup/get.sh | bash
#
# It downloads InkPlot into ~/InkPlot (or the folder in INKPLOT_DIR) and runs setup/install.sh.
# Running it again updates InkPlot; your own files (fonts, layouts, calibration) are kept.
set -euo pipefail
REPO="itwasfineincad/inkplot"
DIR="${INKPLOT_DIR:-$HOME/InkPlot}"
TILDE="~"

# the same look as setup/install.sh: colour and symbols only in a real terminal, NO_COLOR respected
TTY=0; COLOR=0; UNI=0
if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ]; then
  TTY=1
  [ -z "${NO_COLOR:-}" ] && COLOR=1
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in *UTF-8*|*utf-8*|*UTF8*|*utf8*) UNI=1 ;; esac
fi
if [ $COLOR = 1 ]; then
  B=$'\033[1m'; D=$'\033[2m'; R=$'\033[0m'; RED=$'\033[31m'; GRN=$'\033[32m'
  if [ "$(tput colors 2>/dev/null || echo 8)" -ge 256 ]; then
    INK=( $'\033[38;5;25m' $'\033[38;5;26m' $'\033[38;5;27m' $'\033[38;5;32m' $'\033[38;5;33m' $'\033[38;5;39m' )
  else
    INK=( $'\033[34m' $'\033[34m' $'\033[34m' $'\033[34m' $'\033[34m' $'\033[34m' )
  fi
else
  B=; D=; R=; RED=; GRN=; INK=( "" "" "" "" "" "" )
fi
if [ $UNI = 1 ]; then OK="✓"; NO="✗"; else OK="ok"; NO="x"; fi
die() { printf '\n  %s%s%s %sInkPlot could not be downloaded:%s %s\n' "$RED" "$NO" "$R" "$B" "$R" "$*" >&2; exit 1; }

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

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) die "InkPlot runs on macOS and Linux." ;;
esac
command -v curl >/dev/null 2>&1 || die "curl is needed."
command -v tar >/dev/null 2>&1 || die "tar is needed."

printf '%sGetting InkPlot%s %sinto %s%s\n' "$B" "$R" "$D" "${DIR/#$HOME/$TILDE}" "$R"
if [ -d "$DIR/.git" ] && command -v git >/dev/null 2>&1; then
  git -C "$DIR" pull --ff-only --quiet || die "could not update $DIR with git. Check your connection, or move the folder away and run this again."
  printf '  %s%s%s Updated\n' "$GRN" "$OK" "$R"
elif [ ! -e "$DIR" ] && command -v git >/dev/null 2>&1; then
  git clone --quiet --depth 1 "https://github.com/$REPO.git" "$DIR" || die "could not download from GitHub. Check your connection."
  printf '  %s%s%s Downloaded\n' "$GRN" "$OK" "$R"
else
  # no git: unpack the latest version over the folder (personal files are not in the download, so they stay)
  mkdir -p "$DIR"
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar -xz -C "$DIR" --strip-components=1 \
    || die "could not download from GitHub. Check your connection."
  printf '  %s%s%s Downloaded\n' "$GRN" "$OK" "$R"
fi

# stdin is the downloaded script when run as "curl … | bash": give the installer an empty one instead
INKPLOT_BANNER_SHOWN=1 exec bash "$DIR/setup/install.sh" </dev/null
