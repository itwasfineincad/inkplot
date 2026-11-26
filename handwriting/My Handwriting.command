#!/bin/bash
# Double-click to open the handwriting studio.
export TF_CPP_MIN_LOG_LEVEL=3
cd "$(dirname "$0")" && exec "$HOME/.venvs/handwriting-synthesis/bin/python" handwriting_ui.py 2> >(grep -v -E "WARNING|Instructions for updating|deprecat|LSTMCell|non-resource|^\s*$|^  " >&2)
