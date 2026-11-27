#!/bin/bash
# Double-click to remove InkPlot (macOS). It asks before removing anything and can keep a copy of your files.
exec bash "$(cd "$(dirname "$0")" && pwd)/setup/get.sh" --remove
