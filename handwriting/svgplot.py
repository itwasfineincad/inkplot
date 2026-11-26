"""
Read any SVG drawing as pen lines for the plotter.

Every visible shape (paths with curves and arcs, lines, polylines, polygons,
rectangles, circles, ellipses, <use> copies, nested transforms) becomes one
or more polylines. Text and embedded pictures are skipped, because a pen can't
draw them as they are. Filled shapes are drawn as their outline.

    paths, (w, h) = load('blueprints/06_nasa_apollo_csm.svg')
    placed = place(paths, (w, h), width_mm=150, left_mm=30, top_mm=40, rotate=0)
"""
import math

import numpy as np
from svgelements import SVG, Shape, Path, Move, Close, Line, Image, Text


def load(path_or_text, step=0.5):
    """
    -> (paths, (width, height)): polylines in the drawing's own units with the
    top-left of everything at (0, 0), y pointing down, plus the overall size.
    `step` is roughly how finely curves are followed, in drawing units.
    """
    if path_or_text.lstrip().startswith('<'):
        import io
        svg = SVG.parse(io.StringIO(path_or_text))
    else:
        svg = SVG.parse(path_or_text)
    raw = []
    for el in svg.elements():
        if isinstance(el, (Text, Image)) or not isinstance(el, Shape):
            continue
        if str(el.values.get('display', '')).strip() == 'none' or str(el.values.get('visibility', '')).strip() == 'hidden':
            continue
        try:
            p = Path(el)
            p.reify()                       # apply transforms
        except Exception:
            continue
        for sub in p.as_subpaths():
            pts = []
            for seg in sub:
                if isinstance(seg, Move):
                    if len(pts) > 1:
                        raw.append(np.array(pts))
                    pts = [(seg.end.x, seg.end.y)]
                elif isinstance(seg, (Line, Close)):
                    if seg.start is not None and not pts:
                        pts.append((seg.start.x, seg.start.y))
                    if seg.end is not None:
                        pts.append((seg.end.x, seg.end.y))
                else:
                    try:
                        n = max(4, min(400, int(seg.length(error=1e-3)/step) + 2))
                    except Exception:
                        n = 16
                    for t in np.linspace(0, 1, n)[(1 if pts else 0):]:
                        q = seg.point(t)
                        pts.append((q.x, q.y))
            if len(pts) > 1:
                raw.append(np.array(pts))
    raw = [p for p in raw if np.isfinite(p).all() and np.ptp(p, axis=0).max() > 1e-6]
    if not raw:
        return [], (0.0, 0.0)
    allp = np.concatenate(raw)
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    return [p - lo for p in raw], tuple(float(v) for v in (hi - lo))


def _simplify(p, tol):
    keep = [p[0]]
    for q in p[1:-1]:
        if np.hypot(*(q - keep[-1])) >= tol:
            keep.append(q)
    keep.append(p[-1])
    return np.array(keep)


def order(paths):
    """Greedy nearest-neighbour order (reversing paths when that's shorter) to cut pen travel."""
    if len(paths) < 3:
        return paths
    starts = np.array([p[0] for p in paths])
    ends = np.array([p[-1] for p in paths])
    left = np.ones(len(paths), bool)
    out, pos = [], np.array([0.0, 0.0])
    for _ in range(len(paths)):
        idx = np.flatnonzero(left)
        ds = np.hypot(*(starts[idx] - pos).T)
        de = np.hypot(*(ends[idx] - pos).T)
        j, k = int(np.argmin(ds)), int(np.argmin(de))
        if ds[j] <= de[k]:
            i, rev = idx[j], False
        else:
            i, rev = idx[k], True
        left[i] = False
        p = paths[i][::-1] if rev else paths[i]
        out.append(p)
        pos = p[-1]
    return out


def place(paths, size, width_mm, left_mm, top_mm, rotate=0):
    """
    Scale the drawing to width_mm wide and put its top-left corner left_mm from
    the paper's left edge and top_mm down from the paper's top edge.
    rotate: 0 or 90 (a quarter turn clockwise). Returns paths in paper mm (y down).
    """
    w, h = size
    if rotate % 180 == 90:
        paths = [np.column_stack([h - p[:, 1], p[:, 0]]) for p in paths]
        w, h = h, w
    s = width_mm/w if w else 1.0
    out = []
    for p in paths:
        q = _simplify(p*s, 0.08)
        out.append(q + [left_mm, top_mm])
    return out, (width_mm, h*s)


def total_length(paths):
    return sum(float(np.hypot(*np.diff(p, axis=0).T).sum()) for p in paths)
