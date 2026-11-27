"""
Make a single-line pen font from someone's handwriting, for InkPlot.

A pen plotter needs every letter as the line the pen travels (a "single-line"
or "stroke" font), not the outline of the letter that ordinary fonts store.
Three ways in:

  1. Scan template (best): print the template, write every letter in its box
     with a dark pen, scan or photograph the page. The pen lines are traced to
     their centre line, so the font is the person's own strokes.
         python fontimport.py template template.pdf
         python fontimport.py scan filled-in.png --name "Jo's hand"
  2. A font file made elsewhere (Calligraphr, FontCrafter, FontForge...):
     .ttf / .otf outline fonts are traced down to their centre lines.
         python fontimport.py font MyHand.ttf --name "Jo's hand"
  3. A single-line SVG font (Inkscape Hershey Text / Custom Stroke Font):
     already pen lines, imported as they are.
         python fontimport.py svgfont MyStrokes.svg --name "Jo's hand"

Check the result with:
         python fontimport.py preview <font id> preview.png

Fonts are saved as handwriting/fonts/<id>.json (personal: git-ignored) and
appear in the studio's font list. Glyphs are stored in units where the
x-height is 1 and the baseline is 0, y up, the same as plainfont.py, so the
studio writes with them exactly like its built-in print font. A letter
written more than once on the template keeps every version, and the studio
picks between them so repeated letters don't look stamped.
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.environ.get('INKPLOT_FONTS') or os.path.join(HERE, 'fonts')     # INKPLOT_FONTS: a separate folder for tests

# ---------------------------------------------------------------- template
PAGE_W, PAGE_H = 210.0, 297.0
MARK = 6.0                                          # side of the black corner squares
MARKS = [(14.0, 14.0), (196.0, 14.0), (14.0, 283.0), (196.0, 283.0)]   # their centres, mm from the top-left
COLS, ROWS = 12, 9
GRID_X0, GRID_Y0 = 15.0, 34.0
CELL_W, CELL_H = 15.0, 26.6
BASE = 17.0                                         # baseline, mm below the top of a cell
XH = 6.0                                            # x-height guide above the baseline
LOWER = 'abcdefghijklmnopqrstuvwxyz'
UPPER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
CHARS = list(LOWER + LOWER + UPPER + '0123456789' + '.,;:!?\'"-()&/@#%+=*$')
assert len(CHARS) == COLS*ROWS
SHORT = set('acemnorsuvwxz')                        # lowercase letters with no ascender or tail: they set the x-height


def cell_box(i):
    """(left, top) of template cell i, mm from the page's top-left."""
    r, c = divmod(i, COLS)
    return GRID_X0 + c*CELL_W, GRID_Y0 + r*CELL_H


def make_template(path):
    """Write the scan template (PDF or PNG, from the file name)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    fig = plt.figure(figsize=(PAGE_W/25.4, PAGE_H/25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, PAGE_W)
    ax.set_ylim(PAGE_H, 0)
    ax.axis('off')
    guide, label, edge = '#8db8f0', '#b4b4b4', '#d0d0d0'      # light: the scan reader ignores them
    for x, y in MARKS:
        ax.add_patch(Rectangle((x - MARK/2, y - MARK/2), MARK, MARK, color='black', lw=0))
    ax.text(PAGE_W/2, 15.5, 'InkPlot handwriting template', ha='center', va='center', fontsize=11, color='#888888')
    ax.text(PAGE_W/2, 21.5, 'Write each character in its box with a dark pen, sitting on the solid line; small letters reach '
            'the dashed line. Lowercase twice.', ha='center', va='center', fontsize=6.3, color='#999999')
    ax.text(PAGE_W/2, 26, 'Print at 100% (no "fit to page"). Scan or photograph the whole page, flat, with all four black squares.',
            ha='center', va='center', fontsize=6.3, color='#999999')
    for i, ch in enumerate(CHARS):
        x, y = cell_box(i)
        ax.add_patch(Rectangle((x, y), CELL_W, CELL_H, fill=False, ec=edge, lw=0.4))
        ax.plot([x + 1, x + CELL_W - 1], [y + BASE]*2, color=guide, lw=0.6)
        ax.plot([x + 1, x + CELL_W - 1], [y + BASE - XH]*2, color=guide, lw=0.5, ls=(0, (3, 2)))
        ax.text(x + 1.2, y + 3.4, ch, fontsize=7, color=label, ha='left', va='center')
    ax.text(PAGE_W/2, 276, 'Keep the letters inside their boxes. A pencil line or a very light pen won\'t scan well.',
            ha='center', va='center', fontsize=6.3, color='#999999')
    fig.savefig(path, dpi=300)
    plt.close(fig)
    return path


# ---------------------------------------------------------------- images
def load_image(path):
    """A scan or photo -> grey levels 0 (black) .. 1 (white). PDFs are turned into a picture first (macOS sips)."""
    from PIL import Image, ImageOps
    if path.lower().endswith('.pdf'):
        # Quick Look renders the first page at about 300 dpi for A4 (sips would only give 72 dpi)
        tmp = tempfile.mkdtemp()
        subprocess.run(['qlmanage', '-t', '-s', '3508', '-o', tmp, path], capture_output=True, timeout=120)
        out = os.path.join(tmp, os.path.basename(path) + '.png')
        if not os.path.exists(out):
            out = os.path.join(tmp, 'page.png')
            r = subprocess.run(['sips', '-s', 'format', 'png', path, '--out', out], capture_output=True)
            if r.returncode != 0 or not os.path.exists(out):
                raise ValueError('Could not read the PDF; save the scan as a PNG or JPG instead.')
        path = out
    if path.lower().endswith(('.heic', '.heif')):
        # iPhone photos: Pillow can't read HEIC here, macOS can
        tmp = tempfile.mkdtemp()
        out = os.path.join(tmp, 'photo.jpg')
        r = subprocess.run(['sips', '-s', 'format', 'jpeg', path, '--out', out], capture_output=True)
        if r.returncode != 0 or not os.path.exists(out):
            raise ValueError('Could not read that iPhone photo; open it in Preview, File > Export as JPEG, and upload that.')
        path = out
    try:
        im = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
    except OSError:
        raise ValueError('Could not read that picture; save it as a JPG or PNG and try again.')
    a = np.asarray(im, dtype=np.float32)/255.0
    return 0.2126*a[..., 0] + 0.7152*a[..., 1] + 0.0722*a[..., 2], a


def otsu(values):
    hist, edges = np.histogram(values, bins=128, range=(0, 1))
    w = np.cumsum(hist)
    m = np.cumsum(hist*(edges[:-1] + edges[1:])/2)
    total, mt = w[-1], m[-1]
    w0, w1 = w[:-1], total - w[:-1]
    ok = (w0 > 0) & (w1 > 0)
    between = np.zeros_like(w0, dtype=float)
    between[ok] = (mt*w0[ok]/total - m[:-1][ok])**2/(w0[ok]*w1[ok])
    return float(edges[1:][np.argmax(between)])


def find_marks(grey):
    """Centres (x, y in pixels) of the four black corner squares: top-left, top-right, bottom-left, bottom-right."""
    from scipy import ndimage
    h, w = grey.shape
    dark = grey < min(0.45, otsu(grey[::4, ::4].ravel()))
    lab, n = ndimage.label(dark)
    if n == 0:
        raise ValueError('The scan looks blank.')
    objs = ndimage.find_objects(lab)
    areas = ndimage.sum(dark, lab, index=np.arange(1, n + 1))
    px_per_mm = max(w, h)/PAGE_H if h >= w else max(w, h)/PAGE_W
    side = MARK*px_per_mm
    cands = []
    for k, sl in enumerate(objs):
        hh, ww = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if not (0.4*side < ww < 2.5*side and 0.4*side < hh < 2.5*side and 0.6 < ww/max(hh, 1) < 1.6):
            continue
        if areas[k]/(ww*hh) < 0.7:
            continue
        cy, cx = ndimage.center_of_mass(dark[sl], lab[sl], k + 1)
        cands.append((sl[1].start + cx, sl[0].start + cy))
    corners = [(0, 0), (w, 0), (0, h), (w, h)]
    found = []
    for cx0, cy0 in corners:
        best = min(cands, key=lambda p: (p[0] - cx0)**2 + (p[1] - cy0)**2, default=None)
        if best is None or math.hypot(best[0] - cx0, best[1] - cy0) > 0.45*math.hypot(w, h):
            raise ValueError('Couldn\'t find all four black squares in the corners. Scan or photograph the whole page, '
                             'including the squares, with nothing covering them.')
        found.append(best)
    if len(set(found)) < 4:
        raise ValueError('Couldn\'t tell the four corner squares apart. Scan the whole page, straight on.')
    return found


def homography(src, dst):
    """3x3 matrix taking src points (x, y) to dst points (4 or more pairs)."""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u*x, -u*y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v*x, -v*y]); b.append(v)
    hvec = np.linalg.lstsq(np.array(A, float), np.array(b, float), rcond=None)[0]
    return np.append(hvec, 1).reshape(3, 3)


def sample(grey, H, x0, y0, w, h, res):
    """The page area (x0..x0+w, y0..y0+h mm) resampled at `res` mm per pixel, via the mm -> pixel homography H."""
    from scipy import ndimage
    xs = x0 + (np.arange(int(round(w/res))) + 0.5)*res
    ys = y0 + (np.arange(int(round(h/res))) + 0.5)*res
    X, Y = np.meshgrid(xs, ys)
    P = H @ np.vstack([X.ravel(), Y.ravel(), np.ones(X.size)])
    px, py = P[0]/P[2], P[1]/P[2]
    return ndimage.map_coordinates(grey, [py, px], order=1, cval=1.0).reshape(X.shape)


# ---------------------------------------------------------------- centre lines
def thin(mask):
    """Zhang-Suen thinning: a filled shape -> its one-pixel-wide centre line."""
    img = np.pad(mask.astype(np.uint8), 1)
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            P2, P3, P4 = img[:-2, 1:-1], img[:-2, 2:], img[1:-1, 2:]
            P5, P6, P7 = img[2:, 2:], img[2:, 1:-1], img[2:, :-2]
            P8, P9 = img[1:-1, :-2], img[:-2, :-2]
            seq = [P2, P3, P4, P5, P6, P7, P8, P9, P2]
            B = sum(seq[:8])
            A = sum(((seq[k] == 0) & (seq[k + 1] == 1)).astype(np.uint8) for k in range(8))
            c = img[1:-1, 1:-1] == 1
            if step == 0:
                m = c & (B >= 2) & (B <= 6) & (A == 1) & (P2*P4*P6 == 0) & (P4*P6*P8 == 0)
            else:
                m = c & (B >= 2) & (B <= 6) & (A == 1) & (P2*P4*P8 == 0) & (P2*P6*P8 == 0)
            if m.any():
                img[1:-1, 1:-1][m] = 0
                changed = True
    return img[1:-1, 1:-1].astype(bool)


NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def trace(skel):
    """One-pixel centre line -> list of polylines (lists of (row, col)), split at ends and junctions."""
    pts = set(zip(*np.nonzero(skel)))

    def linked(p, dr, dc):
        q = (p[0] + dr, p[1] + dc)
        if q not in pts:
            return False
        # a diagonal step only counts when there's no way round through a side neighbour: otherwise every
        # corner of a staircase line would look like a junction
        return not (dr and dc and ((p[0] + dr, p[1]) in pts or (p[0], p[1] + dc) in pts))
    nb = {p: [(p[0] + dr, p[1] + dc) for dr, dc in NB if linked(p, dr, dc)] for p in pts}
    nodes = {p for p in pts if len(nb[p]) != 2}
    used = set()
    lines = []

    def walk(a, b):
        line = [a, b]
        used.add(frozenset((a, b)))
        prev, cur = a, b
        while cur not in nodes:
            nxt = [q for q in nb[cur] if q != prev and frozenset((cur, q)) not in used]
            if not nxt:
                break
            q = nxt[0]
            used.add(frozenset((cur, q)))
            line.append(q)
            prev, cur = cur, q
            if cur == a:
                break
        return line

    for p in sorted(nodes):
        for q in nb[p]:
            if frozenset((p, q)) not in used:
                lines.append(walk(p, q))
    for p in sorted(pts):                                   # closed loops with no ends (an o drawn in one go)
        for q in nb[p]:
            if frozenset((p, q)) not in used:
                lines.append(walk(p, q))
    return [l for l in lines if len(l) > 1]


def _dir(line, at_start, k=6):
    a = np.array(line[0] if at_start else line[-1], float)
    b = np.array(line[min(k, len(line) - 1)] if at_start else line[max(-k - 1, -len(line))], float)
    d = a - b
    n = np.hypot(*d)
    return d/n if n else d


def join(lines, gap=2.0):
    """Join pieces that meet end to end and carry on in the same direction (through a crossing, round a junction)."""
    lines = [list(l) for l in lines]
    merged = True
    while merged:
        merged = False
        best = None
        for i in range(len(lines)):
            for j in range(len(lines)):
                if i == j:
                    continue
                for ei in (False, True):              # False: end of i, True: start of i
                    for ej in (True, False):          # True: start of j, False: end of j
                        pa = np.array(lines[i][0 if ei else -1], float)
                        pb = np.array(lines[j][0 if ej else -1], float)
                        d = np.hypot(*(pa - pb))
                        if d > gap:
                            continue
                        da, db = _dir(lines[i], ei), _dir(lines[j], ej)
                        straight = -float(da @ db)          # 1 when j carries straight on from i
                        if straight < 0.6:
                            continue
                        score = straight - 0.05*d
                        if best is None or score > best[0]:
                            best = (score, i, j, ei, ej)
        if best:
            _, i, j, ei, ej = best
            a = lines[i][::-1] if ei else lines[i]
            b = lines[j] if ej else lines[j][::-1]
            lines[i] = a + b[1:]
            del lines[j]
            merged = True
    return lines


def length(p):
    p = np.asarray(p, float)
    return float(np.hypot(*np.diff(p, axis=0).T).sum()) if len(p) > 1 else 0.0


def rdp(p, tol):
    """Ramer-Douglas-Peucker: drop points that sit within tol of a straight line."""
    p = np.asarray(p, float)
    if len(p) < 3:
        return p
    a, b = p[0], p[-1]
    d = b - a
    n = np.hypot(*d)
    dist = np.abs(np.cross(d, p - a))/n if n else np.hypot(*(p - a).T)
    k = int(np.argmax(dist))
    if dist[k] > tol:
        return np.vstack([rdp(p[:k + 1], tol)[:-1], rdp(p[k:], tol)])
    return np.vstack([a, b])


def smooth(p, n=2):
    p = np.asarray(p, float)
    closed = len(p) > 3 and np.hypot(*(p[0] - p[-1])) < 1e-6
    for _ in range(n):
        if len(p) < 3:
            break
        q = p.copy()
        q[1:-1] = (p[:-2] + 2*p[1:-1] + p[2:])/4
        if closed:
            q[0] = q[-1] = (p[-2] + 2*p[0] + p[1])/4
        p = q
    return p


def strokes_from_mask(mask, res, min_mm=0.8):
    """Ink mask (True = ink) at `res` mm per pixel -> pen strokes in mm (x right, y down), short spurs removed."""
    from scipy import ndimage
    mask = ndimage.binary_closing(mask, iterations=1)            # close pin-holes inside the ink line
    lab, n = ndimage.label(mask)
    if n:
        sizes = ndimage.sum(mask, lab, range(1, n + 1))
        mask = np.isin(lab, 1 + np.flatnonzero(sizes*res*res >= 0.05))      # drop specks under ~0.05 mm²
        lab, n = ndimage.label(mask)
    skel = thin(mask)
    lines = trace(skel)
    # drop short whiskers that hang off a junction (thinning leaves them at stroke ends and corners)
    ends = {}
    for l in lines:
        for e in (l[0], l[-1]):
            ends[e] = ends.get(e, 0) + 1
    keep = []
    for l in lines:
        if length(l)*res < min_mm and (ends[l[0]] > 1) != (ends[l[-1]] > 1):
            continue
        keep.append(l)
    lines = join(keep, gap=2.5)
    # dots (i, j, full stops) thin down to almost nothing: any blob of ink with no line through it becomes a dot
    covered = {int(lab[r, c]) for l in lines for r, c in l}
    dots = []
    if n:
        for k in range(1, n + 1):
            if k in covered:
                continue
            rr, cc = np.nonzero(lab == k)
            if len(rr)*res*res < 0.05:
                continue
            cx, cy = cc.mean()*res, rr.mean()*res
            dots.append(np.array([[cx - 0.12, cy], [cx + 0.12, cy]]))
    out = []
    for l in lines:
        p = np.array([(c*res, r*res) for r, c in l], float)
        if length(p) < 0.3:                                  # a dot that thinned to a few pixels
            c = p.mean(axis=0)
            out.append(np.array([c - [0.12, 0], c + [0.12, 0]]))
            continue
        out.append(rdp(smooth(p), 0.05))
    return out + dots


# ---------------------------------------------------------------- building a font
def normalise(glyphs, source):
    """
    glyphs: {char: [strokes in mm, y up from the baseline]} (one entry per version) ->
    the font in x-height units, each version shifted to start at x = 0.
    """
    tops = [max(float(s[:, 1].max()) for s in strokes) for ch, vers in glyphs.items() if ch in SHORT for strokes in vers]
    if not tops:
        raise ValueError('No small letters (a, c, e, m, n, o...) came out, so the letter size can\'t be measured.')
    xh = float(np.median(tops))
    caps = [max(float(s[:, 1].max()) for s in strokes) for ch, vers in glyphs.items() if ch in UPPER for strokes in vers]
    out = {}
    for ch, vers in glyphs.items():
        vv = []
        for strokes in vers:
            x0 = min(float(s[:, 0].min()) for s in strokes)
            x1 = max(float(s[:, 0].max()) for s in strokes)
            st = [[[round((x - x0)/xh, 4), round(y/xh, 4)] for x, y in s] for s in strokes]
            vv.append([round(max(0.12, (x1 - x0)/xh), 4), st])
        out[ch] = vv
    cap = float(np.median(caps))/xh if caps else 1.45
    return dict(cap=round(cap, 3), x_height_mm=round(xh, 2), source=source, glyphs=out)


def from_scan(path, report=None):
    """A filled-in template (scan or photo) -> font dict."""
    grey, _ = load_image(path)
    marks = find_marks(grey)
    H = homography(MARKS, marks)                          # template mm -> picture pixels
    res = 0.08
    sample_cells = [sample(grey, H, *cell_box(i), CELL_W, CELL_H, res) for i in range(len(CHARS))]
    allpix = np.concatenate([c.ravel() for c in sample_cells])
    thr = min(0.62, max(0.25, otsu(allpix)))               # dark pen ink; the light guides and labels stay white
    glyphs, empty = {}, []
    inset = int(round(0.9/res))
    for i, (ch, cell) in enumerate(zip(CHARS, sample_cells)):
        ink = cell < thr
        ink[:inset, :] = ink[-inset:, :] = False
        ink[:, :inset] = ink[:, -inset:] = False
        ink[:int(round(5.0/res)), :int(round(4.0/res))] = False      # the printed label corner
        if ink.sum()*res*res < 0.08:                                # less ink than a small dot: left empty
            empty.append(ch)
            continue
        strokes = strokes_from_mask(ink, res)
        if not strokes:
            empty.append(ch)
            continue
        up = [np.column_stack([s[:, 0], BASE - s[:, 1]]) for s in strokes]      # y up from the baseline
        glyphs.setdefault(ch, []).append(up)
    if report is not None:
        report.update(empty=empty, threshold=round(thr, 3))
    return normalise(glyphs, 'scan')


def from_outline_font(path, report=None):
    """A normal .ttf/.otf font (e.g. from Calligraphr) -> centre lines of its letters."""
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    from matplotlib.path import Path
    fp = FontProperties(fname=path)
    size = 40.0                                           # font units for tracing; 40 mm tall em
    res = 0.1
    glyphs, empty = {}, []
    wanted = list(LOWER + UPPER + '0123456789' + '.,;:!?\'"-()&/@#%+=*$') + [chr(c) for c in range(0xC0, 0x180)]
    try:
        from fontTools.ttLib import TTFont
        cmap = TTFont(path, fontNumber=0).getBestCmap() or {}
        wanted = [c for c in wanted if ord(c) in cmap]
    except Exception:
        pass
    for ch in wanted:
        try:
            tp = TextPath((0, 0), ch, size=size, prop=fp)
        except Exception:
            continue
        polys = [p for p in tp.to_polygons() if len(p) > 2]
        if not polys:
            empty.append(ch)
            continue
        allp = np.concatenate(polys)
        (x0, y0), (x1, y1) = allp.min(axis=0) - 1, allp.max(axis=0) + 1
        xs = np.arange(x0, x1, res)
        ys = np.arange(y1, y0, -res)
        X, Y = np.meshgrid(xs, ys)
        pts = np.column_stack([X.ravel(), Y.ravel()])
        inside = np.zeros(len(pts), bool)
        for poly in polys:                                   # even-odd fill: holes in o, e, a come out right
            inside ^= Path(poly).contains_points(pts)
        mask = inside.reshape(X.shape)
        strokes = strokes_from_mask(mask, res, min_mm=size*0.03)
        if not strokes:
            empty.append(ch)
            continue
        up = [np.column_stack([x0 + s[:, 0], y1 - s[:, 1]]) for s in strokes]
        glyphs[ch] = [up]
    if report is not None:
        report.update(empty=empty)
    return normalise(glyphs, 'font file (traced to centre lines)')


def from_svg_font(path, report=None):
    """A single-line SVG font (<font><glyph unicode=.. d=..>): already pen lines."""
    from svgelements import Path as SvgPath, Move
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    font = next((e for e in root.iter() if e.tag.endswith('}font') or e.tag == 'font'), None)
    if font is None:
        raise ValueError('That SVG has no <font> in it; it isn\'t an SVG font.')
    glyphs = {}
    for g in font.iter():
        if not (g.tag.endswith('glyph') and not g.tag.endswith('missing-glyph')):
            continue
        ch, d = g.get('unicode'), g.get('d')
        if not ch or len(ch) != 1 or not d:
            continue
        strokes, cur = [], []
        for seg in SvgPath(d):
            if isinstance(seg, Move):
                if len(cur) > 1:
                    strokes.append(np.array(cur))
                cur = [(seg.end.x, seg.end.y)]
                continue
            n = max(2, int(seg.length()/2) + 2) if hasattr(seg, 'length') else 2
            for t in np.linspace(0, 1, n)[1:]:
                q = seg.point(t)
                cur.append((q.x, q.y))
        if len(cur) > 1:
            strokes.append(np.array(cur))
        if strokes:
            glyphs.setdefault(ch, []).append(strokes)       # SVG fonts are y up already
    if not glyphs:
        raise ValueError('No letters found in that SVG font.')
    return normalise(glyphs, 'single-line SVG font')


# ---------------------------------------------------------------- saving and listing
def slug(name):
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return s or 'font'


def save(font, name):
    os.makedirs(FONTS, exist_ok=True)
    fid = slug(name)
    font = dict(font, id=fid, name=name.strip(), made=time.strftime('%Y-%m-%d'))
    with open(os.path.join(FONTS, fid + '.json'), 'w') as f:
        json.dump(font, f, separators=(',', ':'))
    return fid


def list_fonts():
    out = []
    if os.path.isdir(FONTS):
        for fn in sorted(os.listdir(FONTS)):
            if fn.endswith('.json'):
                try:
                    with open(os.path.join(FONTS, fn)) as f:
                        d = json.load(f)
                    out.append(dict(id=fn[:-5], name=d.get('name', fn[:-5]), glyphs=len(d.get('glyphs', {})),
                                    source=d.get('source', ''), made=d.get('made', '')))
                except (OSError, ValueError):
                    pass
    return out


def delete(fid):
    p = os.path.join(FONTS, os.path.basename(fid) + '.json')
    if os.path.isfile(p):
        os.remove(p)


def import_file(path, name, report=None):
    """Any supported file -> saved font id. Picks the reader from the file type."""
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.heic', '.heif', '.pdf', '.bmp', '.webp'):
        font = from_scan(path, report)
    elif ext in ('.ttf', '.otf'):
        font = from_outline_font(path, report)
    elif ext == '.svg':
        font = from_svg_font(path, report)
    else:
        raise ValueError('Use a scan (PNG, JPG, PDF), a .ttf / .otf font, or a single-line .svg font.')
    missing = [c for c in LOWER + UPPER + '0123456789' if c not in font['glyphs']]
    if report is not None:
        report.update(missing=missing, glyphs=len(font['glyphs']))
        if font['source'] == 'scan':
            report['x_height_mm'] = font['x_height_mm']
    return save(font, name)


def preview(fid, path, text=None):
    """Draw a sample of the font to a PNG so it can be checked by eye."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    sys.path.insert(0, HERE)
    import penfont
    mod = penfont.get(fid)
    text = text or ('The quick brown fox jumps over the lazy dog.\nPACK MY BOX WITH FIVE DOZEN LIQUOR JUGS!\n'
                    'abcdefghijklmnopqrstuvwxyz 0123456789 .,;:!?\'"-()&/')
    st = mod.Style(size=4.0, line_height=12.0, max_width=180.0, tidiness=1.0, slant=0.0)   # upright: shows the letters as written
    lines = mod.render_lines(text, st)
    fig = plt.figure(figsize=(8, 0.5 + 0.55*len(lines)))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')
    for i, line in enumerate(lines):
        y = (i + 1)*12.0
        ax.plot([0, 185], [y, y], color='#cfe0f5', lw=0.6)
        for p in line:
            ax.plot(p[:, 0] + 3, p[:, 1] + y, color='#062b8a', lw=1.0, solid_capstyle='round')
    ax.set_xlim(0, 188)
    ax.set_ylim((len(lines) + 0.6)*12.0, 2)
    ax.set_aspect('equal')
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    t = sub.add_parser('template', help='write the scan template (PDF or PNG)')
    t.add_argument('out')
    for cmd in ('scan', 'font', 'svgfont'):
        p = sub.add_parser(cmd, help='import a ' + {'scan': 'filled-in template', 'font': '.ttf/.otf font',
                                                       'svgfont': 'single-line SVG font'}[cmd])
        p.add_argument('file')
        p.add_argument('--name', required=True)
    p = sub.add_parser('preview', help='draw a sample of a font')
    p.add_argument('font')
    p.add_argument('out')
    p.add_argument('--text')
    sub.add_parser('list', help='list the imported fonts')
    d = sub.add_parser('delete', help='delete an imported font')
    d.add_argument('font')
    a = ap.parse_args(argv)
    if a.cmd == 'template':
        print('Wrote', make_template(a.out))
    elif a.cmd in ('scan', 'font', 'svgfont'):
        rep = {}
        fid = import_file(a.file, a.name, rep)
        print(json.dumps(dict(id=fid, **rep), indent=1))
    elif a.cmd == 'preview':
        print('Wrote', preview(a.font, a.out, a.text))
    elif a.cmd == 'list':
        print(json.dumps(list_fonts(), indent=1))
    elif a.cmd == 'delete':
        delete(a.font)


if __name__ == '__main__':
    try:
        main()
    except ValueError as e:
        sys.exit(str(e))
