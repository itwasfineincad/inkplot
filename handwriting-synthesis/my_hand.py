"""
Default settings for the AI handwriting (tuned to look like a real person's everyday writing).

The model sometimes loses its place partway through a line and scribbles.
To avoid that, each line is generated several times, read back with text
recognition (macOS's own, or tesseract on Linux when it is installed), and the
version that reads most like the intended text is kept. Without either, the
version whose length is closest to the middle of the tries is kept: a derailed
line comes out much longer (scribbles) or shorter than the others.

Usage:
    from my_hand import write_plotter_svg, write_my_hand
    write_plotter_svg('out/note.svg', ["first line", "second line"])  # for BambuPlot
    write_my_hand('img/note.svg', ["first line", "second line"])      # preview on a white page

or from the command line, see handwrite.py.
"""
import difflib
import os
import shutil
import subprocess
import sys
import tempfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

import drawing
from demo import Hand

MY_STYLE = dict(
    style=11,     # closest built-in writer: joined-up, small x-height, long descenders
    bias=0.75,    # lower values look looser but derail more often
    slant=0.35,   # forward lean
    x_scale=0.7,  # narrower letters
)

# Hand._draw scales offsets by 1.5 and spaces lines 60 units apart; the plotter
# export keeps the same offset scale. At that scale style 11 averages about
# 8.7 units per character (measured), which converts letter size to mm.
_OFFSET_SCALE = 1.5
_UNITS_PER_LINE = 60.0
_UNITS_PER_CHAR = 8.7

BAMBUPLOT_IMPORT_HEIGHT_MM = 60.0

_hand = None


def _get_hand():
    global _hand
    if _hand is None:
        _hand = Hand()
    return _hand


def _line_coords(offsets, slant, x_scale):
    """Offsets -> aligned, slanted absolute coords (x, y up, pen_up)."""
    offsets = offsets.copy()
    offsets[:, :2] *= _OFFSET_SCALE
    coords = drawing.denoise(drawing.offsets_to_coords(offsets))
    coords[:, :2] = drawing.align(coords[:, :2])
    coords[:, 0] = coords[:, 0]*x_scale + slant*coords[:, 1]
    return coords


def _split_strokes(coords):
    return [s for s in np.split(coords, np.where(coords[:, 2] == 1)[0] + 1) if len(s) > 1]


def _ocr(path):
    """Text read from a picture: macOS text recognition, else tesseract if installed, else None."""
    if sys.platform == 'darwin' and os.environ.get('INKPLOT_OCR') != 'off':
        try:
            from ocrmac import ocrmac
            return ' '.join(t for t, _, _ in ocrmac.OCR(path, recognition_level='accurate').recognize())
        except ImportError:
            pass
    exe = shutil.which('tesseract') if os.environ.get('INKPLOT_OCR') != 'off' else None
    if exe:
        try:
            r = subprocess.run([exe, path, 'stdout', '--psm', '7'], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def can_read():
    """Whether text recognition is available (else readability falls back to the line's length)."""
    if os.environ.get('INKPLOT_OCR') == 'off':
        return False
    return (sys.platform == 'darwin' and _has_ocrmac()) or shutil.which('tesseract') is not None


def _has_ocrmac():
    try:
        import ocrmac  # noqa: F401
        return True
    except ImportError:
        return False


def _width(coords):
    return float(coords[:, 0].max() - coords[:, 0].min()) if len(coords) else 0.0


def scores(candidates, line, slant, x_scale):
    """
    0-1 for each try of one line: how well it reads (text recognition), or, without it, how close its
    length is to the middle of all the tries (the length varies a lot between writers, so it is
    compared with the other tries, not with a fixed number).
    """
    if len(candidates) > 1 and not can_read():
        widths = [_width(_line_coords(c, slant, x_scale)) for c in candidates]
        mid = float(np.median([w for w in widths if w > 0] or [1.0]))
        return [max(0.0, 1.0 - 2.5 * abs(np.log(max(w, 1e-6) / mid))) for w in widths]
    return [_readability(c, line, slant, x_scale) for c in candidates]


def _readability(offsets, line, slant, x_scale):
    """Similarity (0-1) between the intended text and what OCR reads from the strokes."""
    coords = _line_coords(offsets, slant, x_scale)

    fig, ax = plt.subplots(figsize=(14, 1.6))
    for stroke in _split_strokes(coords):
        ax.plot(stroke[:, 0], stroke[:, 1], 'k', lw=1.5)
    ax.set_aspect('equal')
    ax.axis('off')
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        path = f.name
    fig.savefig(path, dpi=100, facecolor='white')
    plt.close(fig)

    try:
        text = _ocr(path)
    finally:
        os.remove(path)
    if text is None:
        return 1.0
    return difflib.SequenceMatcher(None, text.lower(), line.lower()).ratio()


def generate(lines, attempts=6, verbose=True, **overrides):
    """
    Returns (style settings, list of offsets per line). Blank lines give None.
    """
    s = dict(MY_STYLE, **overrides)
    hand = _get_hand()

    text_lines = [line for line in lines if line]
    batch = [line for line in text_lines for _ in range(attempts)]
    samples = hand._sample(batch, biases=[s['bias']]*len(batch), styles=[s['style']]*len(batch))

    best = []
    for i, line in enumerate(text_lines):
        candidates = samples[i*attempts:(i + 1)*attempts]
        sc = scores(candidates, line, s['slant'], s['x_scale'])
        best.append(candidates[int(np.argmax(sc))])
        if verbose:
            print('  readability {:.2f}  {}'.format(max(sc), line))

    it = iter(best)
    return s, [next(it) if line else None for line in lines]


def layout(lines, line_height_mm=8.0, char_width_mm=2.3, attempts=6, verbose=True, **overrides):
    """
    Generates the lines and converts them to millimetres. Returns one list of
    strokes per line (empty for blank lines). Each stroke is an (n, 2) array,
    x from the left margin, y pointing down with the line's baseline at 0.
    """
    s, offsets = generate(lines, attempts=attempts, verbose=verbose, **overrides)
    scale = char_width_mm / _UNITS_PER_CHAR

    rows = []
    for o in offsets:
        if o is None:
            rows.append([])
            continue
        coords = _line_coords(o, s['slant'], s['x_scale'])
        coords[:, :2] *= scale
        coords[:, 0] -= coords[:, 0].min()
        # most ink sits in the x-height band, so a low percentile of y tracks the
        # baseline while ignoring the few points in descenders
        baseline = np.percentile(coords[:, 1], 15)
        coords[:, 1] = baseline - coords[:, 1]  # y down, baseline at 0
        rows.append([stroke[:, :2] for stroke in _split_strokes(coords)])
    return rows


def write_plotter_svg(filename, lines, line_height_mm=8.0, char_width_mm=2.3, attempts=6, verbose=True,
                      **overrides):
    """
    Writes SVGs containing only pen strokes (no background, no fills), in
    millimetres, left-aligned, ready for BambuPlot's "Vector outlines" mode.
    Lines are line_height_mm apart (8 mm = standard ruled paper) with each
    line's baseline on the rule; char_width_mm sets the letter size.

    BambuPlot ignores SVG units and imports every SVG scaled to 60 mm tall,
    with no way to type in a size. So each file is framed to exactly 60 mm
    tall by two zero-length marker paths (BambuPlot measures them but never
    draws them), which makes it import at true size. The frame's top edge is
    the ruled line above the first line of text. Text that doesn't fit in one
    frame continues in more files: note.svg -> note_1.svg, note_2.svg, ...
    For one file per plot, write G-code directly instead (see plotter.py).

    Returns a list of (filename, rows) for the files written.
    """
    rows = layout(lines, line_height_mm, char_width_mm, attempts, verbose, **overrides)

    # fill each 60 mm frame with as many lines as fit, measuring the real ink
    # so long descenders on the last line never spill out of the frame
    def fits(chunk):
        pts = [st[:, 1] + (r + 1)*line_height_mm for r, row in enumerate(chunk) for st in row]
        return not pts or (min(p.min() for p in pts) >= 0 and
                           max(p.max() for p in pts) <= BAMBUPLOT_IMPORT_HEIGHT_MM)

    chunks, i = [], 0
    while i < len(rows):
        n = 1
        while i + n < len(rows) and fits(rows[i:i + n + 1]):
            n += 1
        chunks.append(rows[i:i + n])
        i += n
    chunks = [c for c in chunks if any(c)]

    stem, ext = os.path.splitext(filename)
    written = []
    for n, chunk in enumerate(chunks, 1):
        path = filename if len(chunks) == 1 else '{}_{}{}'.format(stem, n, ext)
        strokes = [st + [0, (r + 1)*line_height_mm] for r, row in enumerate(chunk) for st in row]
        pts = np.concatenate(strokes)
        if pts[:, 1].min() < 0 or pts[:, 1].max() > BAMBUPLOT_IMPORT_HEIGHT_MM:
            print('warning: some strokes in {} fall outside the 60 mm frame and will be scaled'.format(path))
        _write_svg(path, strokes, width=pts[:, 0].max(), height=BAMBUPLOT_IMPORT_HEIGHT_MM)
        written.append((path, len(chunk)))
    return written


def _write_svg(path, strokes, width, height):
    with open(path, 'w') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write('<svg xmlns="http://www.w3.org/2000/svg" width="{0:.2f}mm" height="{1:.2f}mm" '
                'viewBox="0 0 {0:.2f} {1:.2f}">\n'.format(width, height))
        f.write('<g fill="none" stroke="black" stroke-width="0.4" '
                'stroke-linecap="round" stroke-linejoin="round">\n')
        f.write('<!-- zero-length frame markers: set the import size, never drawn -->\n')
        f.write('<path d="M0,0 L0,0"/>\n<path d="M0,{0:.2f} L0,{0:.2f}"/>\n'.format(height))
        for stroke in strokes:
            f.write('<path d="M{}"/>\n'.format(' L'.join('{:.3f},{:.3f}'.format(x, y) for x, y in stroke)))
        f.write('</g>\n</svg>\n')


def write_my_hand(filename, lines, stroke_width=1.5, attempts=6, **overrides):
    s, offsets = generate(lines, attempts=attempts, **overrides)
    strokes = [o if o is not None else np.zeros((0, 3)) for o in offsets]
    _get_hand()._draw(
        strokes, lines, filename,
        stroke_widths=[stroke_width]*len(lines),
        slant=s['slant'],
        x_scale=s['x_scale'],
    )


if __name__ == '__main__':
    write_my_hand('img/my_hand_sample.svg', [
        "Hello There! The quick brown fox jumped over the lazy dog, THE QUICK BROWN FOX JUMPED OVER THE LAZY DOG. The Quick Brown Fox Jumped Over The Lazy Dog."
    ])
