#!/bin/bash
# Double-click to open InkPlot (macOS). On Linux, run the "inkplot" command instead.
exec "$(cd "$(dirname "$0")/.." && pwd)/inkplot"
