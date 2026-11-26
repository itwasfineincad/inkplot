"""
Write handwriting as pen-plotter SVG (millimetres, strokes only).

BambuPlot rescales every SVG to 60 mm tall on import. With split=True the
text is packed into 60 mm frames (as many lines as actually fit) marked by two
zero-length paths, so each file imports at true size. Every SVG stores the
text and settings it was made from in <metadata>.
"""
import json
import os
from xml.sax.saxutils import escape

import numpy as np

BAMBUPLOT_HEIGHT = 60.0


def svg_text(paths, width, height, meta, frame=False):
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" width="{0:.2f}mm" height="{1:.2f}mm" viewBox="0 0 {0:.2f} {1:.2f}">'
           .format(width, height),
           '<metadata>{}</metadata>'.format(escape(json.dumps(meta, ensure_ascii=False))),
           '<g fill="none" stroke="black" stroke-width="0.4" stroke-linecap="round" stroke-linejoin="round">']
    if frame:
        out.append('<!-- zero-length frame markers: BambuPlot measures them but never draws them -->')
        out.append('<path d="M0,0 L0,0"/>\n<path d="M0,{0:.2f} L0,{0:.2f}"/>'.format(height))
    for p in paths:
        out.append('<path d="M{}"/>'.format(' L'.join('{:.3f},{:.3f}'.format(x, y) for x, y in p)))
    out += ['</g>', '</svg>', '']
    return '\n'.join(out)


def _placed(lines, lh):
    return [p + [0, (r + 1)*lh] for r, line in enumerate(lines) for p in (line or [])]


def save(path, lines, line_height, meta, split=True):
    """
    lines: one list of paths per line (mm, y down, baseline at 0).
    Returns a list of (file path, mm below the first file's top edge).
    """
    if not any(lines):
        raise ValueError('nothing to write')
    lh = line_height
    if not split:
        paths = _placed(lines, lh)
        pts = np.concatenate(paths)
        height = max((len(lines) + 0.7)*lh, float(pts[:, 1].max()) + 1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(svg_text(paths, float(pts[:, 0].max()) + 1, height, meta))
        return [(path, 0.0)]

    def fits(chunk):
        ys = [p[:, 1] for p in _placed(chunk, lh)]
        return not ys or (min(y.min() for y in ys) >= 0 and max(y.max() for y in ys) <= BAMBUPLOT_HEIGHT)

    chunks, i = [], 0
    while i < len(lines):
        n = 1
        while i + n < len(lines) and fits(lines[i:i + n + 1]):
            n += 1
        chunks.append(lines[i:i + n])
        i += n
    chunks = [c for c in chunks if any(c)]

    stem, ext = os.path.splitext(path)
    written, down = [], 0.0
    for k, chunk in enumerate(chunks, 1):
        out = path if len(chunks) == 1 else '{}_{}{}'.format(stem, k, ext or '.svg')
        paths = _placed(chunk, lh)
        width = float(np.concatenate(paths)[:, 0].max()) + 1
        with open(out, 'w', encoding='utf-8') as f:
            f.write(svg_text(paths, width, BAMBUPLOT_HEIGHT, meta, frame=True))
        written.append((out, down))
        down += len(chunk)*lh
    return written
