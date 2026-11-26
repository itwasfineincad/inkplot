"""
Writing any character, in both modes (AI model and font).

Neither the AI model nor a hand font knows every character, so text is
handled in three ways:
  - typographic characters become plain ones (curly quotes, dashes, ellipsis,
    special spaces) and a few letters are spelt out (ß -> ss, æ -> ae, œ -> oe);
  - letters with accents are written as the plain letter with the accent drawn
    on top (é, ü, ñ, å, ç, č, ő ...), and ø, ł, đ, ħ get a bar drawn through;
  - anything else (symbols such as & @ € %) is written with a font: the AI
    model leaves a gap and the font fills it.
What is still left (emoji, Chinese, Arabic and so on) can't be written and is
reported as skipped.

Glyph shapes here are in units where the x-height is 1, baseline 0, y up.
"""
import math
import unicodedata

import numpy as np

C = 'c'                     # corner tag understood by handfont's spline

TYPO = {
    '‘': "'", '’': "'", '‚': ',', '‛': "'", '′': "'", '“': '"', '”': '"', '„': '"', '‟': '"', '″': '"',
    '«': '"', '»': '"', '‹': "'", '›': "'",
    '‐': '-', '‑': '-', '‒': '-', '−': '-', '﹣': '-',
    '…': '...', '\t': ' ', ' ': ' ', ' ': ' ', ' ': ' ', ' ': ' ', ' ': ' ', '​': '',
}
SPELL = {'ß': 'ss', 'ẞ': 'SS', 'æ': 'ae', 'Æ': 'AE', 'œ': 'oe', 'Œ': 'OE', 'ĳ': 'ij', 'Ĳ': 'IJ',
         'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬀ': 'ff', 'þ': 'th', 'Þ': 'Th', 'ð': 'd', 'Ð': 'D', 'ı': 'i', 'ſ': 's'}
BAR = {'ø': 'o', 'Ø': 'O', 'ł': 'l', 'Ł': 'L', 'đ': 'd', 'Đ': 'D', 'ħ': 'h', 'Ħ': 'H', 'ƀ': 'b', 'ŧ': 't', 'Ŧ': 'T'}
MARKS = {'̀': 'grave', '́': 'acute', '̂': 'circumflex', '̃': 'tilde', '̄': 'macron',
         '̆': 'breve', '̇': 'dot', '̈': 'diaeresis', '̊': 'ring', '̋': 'double_acute',
         '̌': 'caron', '̧': 'cedilla', '̨': 'ogonek', '̣': 'dot_below', '̦': 'comma_below'}
BELOW = {'cedilla', 'ogonek', 'dot_below', 'comma_below'}


def prepare(text, keep=lambda c: False):
    """Typographic characters -> plain ones, spelt-out letters -> two letters. Characters keep(c) says the
    writer can already do are left alone."""
    out = []
    for ch in text:
        if keep(ch):
            out.append(ch)
        else:
            out.append(TYPO.get(ch, SPELL.get(ch, ch)))
    return ''.join(out)


def split(ch):
    """An accented or barred letter -> (base letter, [mark names]); None if it isn't one."""
    if ch in BAR:
        return BAR[ch], ['bar']
    d = unicodedata.normalize('NFD', ch)
    if len(d) < 2 or unicodedata.combining(d[0]):
        return None
    marks = [MARKS[m] for m in d[1:] if m in MARKS]
    if not marks or any(unicodedata.combining(m) and m not in MARKS for m in d[1:]):
        return None
    return d[0], marks


def is_tall(ch):
    """Characters about as tall as a capital (used to pick the model's stand-in)."""
    return ch.isupper() or ch.isdigit() or ch in '&@%$€£¥#?!/\\[]{}()|§¶©®'


# marks ------------------------------------------------------------------------
def _arc(cx, cy, rx, ry, a0, a1, n=9):
    return [(cx + rx*math.cos(math.radians(a)), cy + ry*math.sin(math.radians(a))) for a in np.linspace(a0, a1, n)]


def mark_strokes(name, m):
    """Strokes of one mark, m = mark size; centred on x = 0. Marks above sit on y = 0 and rise;
    marks below hang from y = 0. Points tagged C are corners."""
    if name == 'acute':
        return [[(-0.22*m, 0, C), (0.25*m, 0.55*m, C)]]
    if name == 'grave':
        return [[(0.22*m, 0, C), (-0.25*m, 0.55*m, C)]]
    if name == 'circumflex':
        return [[(-0.38*m, 0.05*m, C), (0, 0.5*m, C), (0.38*m, 0.05*m, C)]]
    if name == 'caron':
        return [[(-0.38*m, 0.5*m, C), (0, 0.05*m, C), (0.38*m, 0.5*m, C)]]
    if name == 'tilde':
        return [[(-0.45*m, 0.12*m), (-0.22*m, 0.36*m), (0.02*m, 0.2*m), (0.24*m, 0.08*m), (0.46*m, 0.34*m)]]
    if name == 'macron':
        return [[(-0.4*m, 0.25*m, C), (0.4*m, 0.25*m, C)]]
    if name == 'breve':
        return [_arc(0, 0.45*m, 0.36*m, 0.38*m, 190, 350)]
    if name in ('dot', 'dot_below'):
        y = 0.15*m if name == 'dot' else -0.25*m
        return [[(0, y, C), (0.06*m, y + 0.08*m, C)]]
    if name == 'diaeresis':
        return [[(-0.28*m, 0.15*m, C), (-0.22*m, 0.23*m, C)], [(0.22*m, 0.15*m, C), (0.28*m, 0.23*m, C)]]
    if name == 'ring':
        return [_arc(0, 0.3*m, 0.22*m, 0.24*m, 90, 450, 14)]
    if name == 'double_acute':
        return [[(-0.38*m, 0, C), (-0.08*m, 0.55*m, C)], [(0.08*m, 0, C), (0.38*m, 0.55*m, C)]]
    if name == 'cedilla':
        return [[(0, -0.02*m), (0.05*m, -0.22*m), (0.28*m, -0.42*m), (0.04*m, -0.66*m), (-0.2*m, -0.62*m)]]
    if name == 'comma_below':
        return [[(0.04*m, -0.18*m), (0.0, -0.32*m), (-0.08*m, -0.5*m)]]
    if name == 'ogonek':
        return [[(0.1*m, -0.02*m), (-0.12*m, -0.3*m), (0.02*m, -0.58*m), (0.26*m, -0.56*m)]]
    return []


def _bar(base, x0, x1, top, u=1.0):
    """The stroke through ø, ł, đ, ħ (and capitals); x0, x1, top in glyph units, u = x-height."""
    w = x1 - x0
    if base in 'oO':
        return [[(x0 - 0.12*w, -0.08*top, C), (x1 + 0.12*w, 1.08*top, C)]]
    if base in 'lL':
        y = 0.42*u if base == 'l' else 0.38*top
        return [[(x0 - 0.28*u, y - 0.18*u, C), (x0 + 0.32*u, y + 0.22*u, C)]]
    if base in 'dbh':
        y = 0.82*top
        side = x1 if base == 'd' else x0
        return [[(side - 0.3*u, y, C), (side + 0.3*u, y, C)]]
    if base in 'tT':
        y = 0.5*top if base == 'T' else 0.55*u
        return [[(x0 + 0.15*w, y, C), (x1 - 0.15*w, y, C)]]
    return [[(x0 - 0.05*w, 0.72*top, C), (x1 + 0.05*w, 0.72*top, C)]]       # D, H


def without_dot(strokes, base, unit=1.0):
    """i and j lose their dot under an accent: drop small strokes above the x-height."""
    if base not in 'ij':
        return strokes
    keep = [s for s in strokes if not (min(p[1] for p in s) > 1.12*unit and
                                       max(p[1] for p in s) - min(p[1] for p in s) < 0.45*unit)]
    return keep or strokes


def compose(strokes, base, marks, unit=1.0, jitter=None, size=0.55):
    """
    Base letter strokes (y up, x-height = unit) + its marks -> new list of strokes.
    jitter(n) may return small random offsets in units of `unit` for a hand-placed look.
    """
    strokes = without_dot([list(s) for s in strokes], base, unit)
    pts = [p for s in strokes for p in s]
    if not pts:
        return strokes
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    top, x0, x1 = max(ys), min(xs), max(xs)
    if base.islower() and base not in 'bdfhklt':           # no ascender: sit just above the x-height,
        top = min(top, 1.15*unit)                           # whatever bits of a neighbour got counted in
    upper = [p[0] for p in pts if 0.55*top <= p[1] <= 1.3*top] or xs   # centre over the body, not the joining hairlines
    cx_top = float(np.median(upper))                              # where most of the letter's ink is
    lower = [p[0] for p in pts if p[1] <= 0.35*top] or xs
    cx_bot = (min(lower) + max(lower))/2
    m = size*unit
    out = list(strokes)
    stack = top + 0.28*unit
    for name in marks:
        if name == 'bar':
            if base in 'oO':
                bx0, bx1 = min(upper), max(upper)
            else:
                body = [p for p in pts if p[1] >= -0.05*unit]
                bx0, bx1 = min(p[0] for p in body), max(p[0] for p in body)
                if base in 'lLdbhDH':                                  # the stem, not the joining hairlines
                    stem = [p[0] for p in pts if p[1] >= 0.6*top] or [bx0]
                    bx0 = bx1 = sum(stem)/len(stem) if base in 'lLdbh' else bx0
                    if base in 'DH':
                        bx0, bx1 = min(p[0] for p in body), max(p[0] for p in body)
            out += [list(s) for s in _bar(base, bx0, bx1, top, unit)]
            continue
        dx, dy = (jitter(2)*unit) if jitter else (0.0, 0.0)
        if name in BELOW:
            cx = x1 - 0.15*(x1 - x0) if name == 'ogonek' else cx_bot
            for s in mark_strokes(name, m):
                out.append([(p[0] + cx + dx, p[1] + dy) + tuple(p[2:]) for p in s])
        else:
            for s in mark_strokes(name, m):
                out.append([(p[0] + cx_top + dx, p[1] + stack + dy) + tuple(p[2:]) for p in s])
            stack += 0.65*m
    return out
