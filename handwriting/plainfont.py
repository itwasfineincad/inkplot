"""
A neat single-line print font for the pen plotter: the public stand-in for a
font drawn from your own handwriting.

The studio uses a hand font for "My font" on the Write page, for Labels on
the Plotter page and for the capitals Q, X and Z the AI model can't write.
If handwriting/handfont.py exists (a font made from your own writing, which
is personal and never published) it is used; otherwise this one is. Both
have the same functions: Style, CAP, supported, render_lines, render,
text_width, text_paths.

Glyphs are drawn upright in units where the x-height is 1 and the baseline is
0 (y up). Every letter is a few strokes of straight lines and elliptical arcs,
so the pen draws each one in one or two movements. `tidiness` adds a small
wobble, `mistakes` crosses out a misspelt word before writing it again, and
the same text, style and seed always give exactly the same strokes.
"""
import math
import zlib
from dataclasses import dataclass, asdict

import numpy as np

NAME = 'Print font'
CAP = 1.45            # capital height
ASC = 1.5             # ascender height
DESC = -0.5           # descender depth
FIG = 1.4             # figure height
GAP = 0.24            # space between letters before letter_spacing


@dataclass
class Style:
    size: float = 2.0            # x-height in mm
    tidiness: float = 0.85       # 1 = no wobble at all, 0 = scruffy
    slant: float = 0.12          # forward lean (x += slant*y)
    width: float = 1.0           # letter width multiplier
    ascender: float = 1.0        # height of tall letters and capitals above the x-height
    descender: float = 1.0       # depth of tails below the baseline
    letter_spacing: float = 0.1  # extra space between letters, in x-heights
    word_spacing: float = 1.3    # space between words (1.3 = a normal space)
    line_height: float = 8.0     # mm between baselines
    max_width: float = 180.0     # mm; longer lines wrap
    mistakes: float = 0.0        # chance that a word gets a crossed-out mistake first
    seed: int = 0

    def as_dict(self):
        return asdict(self)


# drawing helpers ---------------------------------------------------------
def arc(cx, cy, rx, ry, a0, a1, step=12):
    """Points on an ellipse from angle a0 to a1 (degrees, counter-clockwise when a1 > a0)."""
    n = max(2, int(abs(a1 - a0)/step) + 1)
    return [(cx + rx*math.cos(math.radians(a)), cy + ry*math.sin(math.radians(a))) for a in np.linspace(a0, a1, n)]


def ring(cx, cy, rx, ry, start=90):
    return arc(cx, cy, rx, ry, start, start + 360)


def L(*pts):
    return list(pts)


def dot(x, y):
    return [(x, y - 0.03), (x, y + 0.03)]


# glyphs: (width, [strokes]) ------------------------------------------------
G = {}
B = ring(.33, .5, .33, .5, 0)                     # the round bowl of a, b, d, g, p, q, o

G['a'] = (.66, [ring(.33, .5, .33, .5, 20), L((.66, 1), (.66, 0))])
G['b'] = (.66, [L((0, ASC), (0, 0)), ring(.33, .5, .33, .5, 180)])
G['c'] = (.62, [arc(.33, .5, .33, .5, 40, 320)])
G['d'] = (.66, [ring(.33, .5, .33, .5, 0), L((.66, ASC), (.66, 0))])
G['e'] = (.66, [L((.02, .52), (.66, .52)) + arc(.33, .5, .33, .5, 3, 318)])
G['f'] = (.5, [arc(.42, 1.28, .2, .2, 20, 180) + [(.22, 0)], L((0, 1), (.46, 1))])
G['g'] = (.66, [ring(.33, .5, .33, .5, 0), L((.66, 1), (.66, -.22)) + arc(.33, -.22, .33, .28, 0, -160)])
G['h'] = (.62, [L((0, ASC), (0, 0)), arc(.31, .6, .31, .4, 180, 0) + [(.62, 0)]])
G['i'] = (0, [L((0, 1), (0, 0)), dot(0, 1.32)])
G['j'] = (.22, [L((.22, 1), (.22, -.3)) + arc(.02, -.3, .2, .2, 0, -150), dot(.22, 1.32)])
G['k'] = (.58, [L((0, ASC), (0, 0)), L((.56, 1), (0, .38)), L((.2, .6), (.6, 0))])
G['l'] = (0, [L((0, ASC), (0, 0))])
G['m'] = (1.0, [L((0, 1), (0, 0)), arc(.25, .65, .25, .35, 180, 0) + [(.5, 0)], arc(.75, .65, .25, .35, 180, 0) + [(1, 0)]])
G['n'] = (.62, [L((0, 1), (0, 0)), arc(.31, .6, .31, .4, 180, 0) + [(.62, 0)]])
G['o'] = (.68, [ring(.34, .5, .34, .5, 90)])
G['p'] = (.66, [L((0, 1), (0, DESC)), ring(.33, .5, .33, .5, 180)])
G['q'] = (.66, [ring(.33, .5, .33, .5, 0), L((.66, 1), (.66, DESC))])
G['r'] = (.42, [L((0, 1), (0, 0)), arc(.32, .62, .32, .38, 180, 70)])
G['s'] = (.56, [arc(.29, .75, .26, .25, 25, 270) + arc(.29, .25, .28, .25, 90, -150)])
G['t'] = (.46, [L((.18, 1.32), (.18, .16)) + arc(.38, .16, .2, .16, 180, 300), L((0, 1), (.44, 1))])
G['u'] = (.62, [L((0, 1), (0, .4)) + arc(.31, .4, .31, .4, 180, 360) + [(.62, 1)], L((.62, 1), (.62, 0))])
G['v'] = (.62, [L((0, 1), (.31, 0), (.62, 1))])
G['w'] = (.96, [L((0, 1), (.24, 0), (.48, .78), (.72, 0), (.96, 1))])
G['x'] = (.6, [L((0, 1), (.6, 0)), L((.6, 1), (0, 0))])
G['y'] = (.62, [L((0, 1), (.31, .04)), L((.62, 1), (.12, DESC))])
G['z'] = (.58, [L((0, 1), (.58, 1), (0, 0), (.6, 0))])

C = CAP
G['A'] = (.92, [L((0, 0), (.46, C), (.92, 0)), L((.17, .5), (.75, .5))])
G['B'] = (.78, [L((0, 0), (0, C), (.42, C)) + arc(.42, 1.1, .32, .35, 90, -90) + [(0, .75)],
                L((.42, .75)) + arc(.42, .375, .36, .375, 90, -90) + [(0, 0)]])
G['C'] = (1.0, [arc(.62, C/2, .62, C/2, 42, 318)])
G['D'] = (.92, [L((0, 0), (0, C), (.3, C)) + arc(.3, C/2, .62, C/2, 90, -90) + [(0, 0)]])
G['E'] = (.72, [L((.72, C), (0, C), (0, 0), (.74, 0)), L((0, .75), (.6, .75))])
G['F'] = (.7, [L((.72, C), (0, C), (0, 0)), L((0, .75), (.6, .75))])
G['G'] = (1.08, [arc(.62, C/2, .62, C/2, 42, 360) + [(1.24, .1)], L((1.24, C/2), (.74, C/2))])
G['H'] = (.86, [L((0, 0), (0, C)), L((.86, 0), (.86, C)), L((0, .75), (.86, .75))])
G['I'] = (0, [L((0, 0), (0, C))])
G['J'] = (.58, [L((.58, C), (.58, .34)) + arc(.3, .34, .28, .34, 0, -180)])
G['K'] = (.78, [L((0, 0), (0, C)), L((.76, C), (0, .45)), L((.26, .74), (.8, 0))])
G['L'] = (.68, [L((0, C), (0, 0), (.7, 0))])
G['M'] = (1.04, [L((0, 0), (0, C), (.52, .36), (1.04, C), (1.04, 0))])
G['N'] = (.86, [L((0, 0), (0, C), (.86, 0), (.86, C))])
G['O'] = (1.28, [ring(.64, C/2, .64, C/2, 90)])
G['P'] = (.76, [L((0, 0), (0, C), (.42, C)) + arc(.42, 1.08, .34, .37, 90, -90) + [(0, .71)]])
G['Q'] = (1.28, [ring(.64, C/2, .64, C/2, 90), L((.78, .36), (1.34, -.06))])
G['R'] = (.8, [L((0, 0), (0, C), (.42, C)) + arc(.42, 1.08, .34, .37, 90, -90) + [(0, .71)], L((.4, .71), (.84, 0))])
G['S'] = (.84, [arc(.42, 1.08, .38, .37, 30, 270) + arc(.42, .355, .44, .355, 90, -148)])
G['T'] = (.86, [L((0, C), (.86, C)), L((.43, C), (.43, 0))])
G['U'] = (.86, [L((0, C), (0, .44)) + arc(.43, .44, .43, .44, 180, 360) + [(.86, C)]])
G['V'] = (.9, [L((0, C), (.45, 0), (.9, C))])
G['W'] = (1.3, [L((0, C), (.32, 0), (.65, 1.1), (.98, 0), (1.3, C))])
G['X'] = (.84, [L((0, C), (.84, 0)), L((.84, C), (0, 0))])
G['Y'] = (.88, [L((0, C), (.44, .68), (.88, C)), L((.44, .68), (.44, 0))])
G['Z'] = (.84, [L((0, C), (.84, C), (0, 0), (.86, 0))])

F = FIG
G['0'] = (.8, [ring(.4, F/2, .4, F/2, 90)])
G['1'] = (.4, [L((0, 1.12), (.4, F), (.4, 0))])
G['2'] = (.78, [arc(.39, 1.02, .37, .38, 160, -38) + [(0, 0), (.8, 0)]])
G['3'] = (.76, [arc(.37, 1.06, .34, .34, 150, -90) + arc(.37, .36, .4, .36, 90, -150)])
G['4'] = (.84, [L((.62, 0), (.62, F), (0, .44), (.86, .44))])
G['5'] = (.78, [L((.74, F), (.1, F), (.04, .78)) + arc(.38, .45, .4, .45, 135, -150)])
G['6'] = (.8, [L((.66, F), (.12, .72)) + ring(.4, .44, .4, .44, 160)])
G['7'] = (.8, [L((0, F), (.8, F), (.24, 0))])
G['8'] = (.8, [ring(.4, 1.06, .33, .34, -90), ring(.4, .36, .4, .36, 90)])
G['9'] = (.8, [ring(.4, .96, .4, .44, -20), L((.8, .96), (.3, 0))])

G['.'] = (0, [dot(0, .04)])
G[','] = (.1, [L((.1, .08), (0, -.22))])
G[':'] = (0, [dot(0, .04), dot(0, .76)])
G[';'] = (.1, [dot(.1, .76), L((.1, .08), (0, -.22))])
G['!'] = (0, [L((0, C), (0, .38)), dot(0, .04)])
G['?'] = (.64, [arc(.32, 1.1, .32, .33, 160, -60) + [(.32, .58), (.32, .4)], dot(.32, .04)])
G["'"] = (0, [L((0, C), (0, 1.05))])
G['"'] = (.22, [L((0, C), (0, 1.05)), L((.22, C), (.22, 1.05))])
G['-'] = (.42, [L((0, .5), (.42, .5))])
G['–'] = (.6, [L((0, .5), (.6, .5))])
G['—'] = (1.0, [L((0, .5), (1.0, .5))])
G['_'] = (.7, [L((0, -.12), (.7, -.12))])
G['('] = (.24, [arc(.6, .5, .6, 1.08, 145, 215)])
G[')'] = (.24, [arc(-.36, .5, .6, 1.08, 35, -35)])
G['['] = (.26, [L((.26, C), (0, C), (0, -.3), (.26, -.3))])
G[']'] = (.26, [L((0, C), (.26, C), (.26, -.3), (0, -.3))])
G['/'] = (.6, [L((0, -.2), (.6, C))])
G['\\'] = (.6, [L((0, C), (.6, -.2))])
G['+'] = (.64, [L((0, .55), (.64, .55)), L((.32, .23), (.32, .87))])
G['='] = (.64, [L((0, .72), (.64, .72)), L((0, .38), (.64, .38))])
G['*'] = (.5, [L((.25, 1.4), (.25, .9)), L((.03, 1.28), (.47, 1.02)), L((.47, 1.28), (.03, 1.02))])
G['<'] = (.6, [L((.6, .95), (0, .5), (.6, .05))])
G['>'] = (.6, [L((0, .95), (.6, .5), (0, .05))])
G['#'] = (.8, [L((.26, 0), (.36, C)), L((.52, 0), (.62, C)), L((0, .45), (.8, .45)), L((.04, .98), (.84, .98))])
G['%'] = (.9, [ring(.2, 1.2, .18, .22), L((.82, C), (.08, 0)), ring(.7, .25, .18, .22)])
G['&'] = (.9, [L((.92, 0), (.18, .9)) + arc(.36, 1.12, .2, .28, 220, -40) + [(.06, .48)] + arc(.36, .34, .32, .34, 160, 330) + [(.86, .62)]])
G['@'] = (1.2, [ring(.6, .55, .22, .3, 0), L((.82, .82), (.82, .38)) + arc(.6, .55, .6, .62, -20, 300)])
G['$'] = (.8, [arc(.4, 1.0, .36, .3, 30, 270) + arc(.4, .4, .4, .3, 90, -148), L((.4, F + .1), (.4, -.15))])
G['£'] = (.8, [arc(.5, 1.06, .28, .3, 10, 180) + [(.22, .3)] + arc(.08, .16, .14, .14, 90, 260), L((0, 0), (.8, 0)), L((0, .66), (.54, .66))])
G['€'] = (.9, [arc(.56, F/2, .5, F/2, 45, 315), L((0, .82), (.62, .82)), L((0, .56), (.56, .56))])
G['~'] = (.7, [arc(.17, .5, .17, .12, 180, 0) + arc(.52, .5, .17, .12, 180, 360)])

G['^'] = (.5, [L((0, 1.05), (.25, 1.4), (.5, 1.05))])
G['`'] = (.2, [L((0, 1.45), (.2, 1.2))])
G['|'] = (0, [L((0, 1.5), (0, -.4))])
G['{'] = (.3, [L((.3, 1.5), (.18, 1.42), (.15, .85), (0, .55), (.15, .25), (.18, -.32), (.3, -.4))])
G['}'] = (.3, [L((0, 1.5), (.12, 1.42), (.15, .85), (.3, .55), (.15, .25), (.12, -.32), (0, -.4))])
G['°'] = (.32, [ring(.16, 1.27, .16, .16)])
G['©'] = (1.3, [ring(.65, .72, .65, .72), arc(.7, .72, .3, .34, 45, 315)])
G['®'] = (1.3, [ring(.65, .72, .65, .72), L((.45, .35), (.45, 1.1), (.68, 1.1)) + arc(.68, .92, .18, .18, 90, -90) + [(.45, .74)],
                L((.66, .74), (.9, .35))])
G['™'] = (1.0, [L((0, C), (.4, C)), L((.2, C), (.2, 1.0)), L((.52, 1.0), (.52, C), (.72, 1.15), (.92, C), (.92, 1.0))])
G['½'] = (1.0, [L((0, 1.2), (.15, 1.42), (.15, .75)), L((.85, 1.45), (.15, -.05)),
               arc(.76, .45, .17, .17, 160, -40) + [(.6, 0), (.95, 0)]])
G['¼'] = (1.0, [L((0, 1.2), (.15, 1.42), (.15, .75)), L((.85, 1.45), (.15, -.05)), L((.82, 0), (.82, .62), (.55, .2), (1.0, .2))])
G['¾'] = (1.0, [arc(.16, 1.24, .14, .14, 150, -90) + arc(.16, .95, .16, .16, 90, -150), L((.85, 1.45), (.15, -.05)),
               L((.82, 0), (.82, .62), (.55, .2), (1.0, .2))])
G['±'] = (.64, [L((0, .7), (.64, .7)), L((.32, .38), (.32, 1.02)), L((0, .12), (.64, .12))])
G['÷'] = (.64, [L((0, .55), (.64, .55)), dot(.32, .9), dot(.32, .2)])
G['×'] = (.5, [L((0, .3), (.5, .8)), L((0, .8), (.5, .3))])
G['·'] = (0, [dot(0, .55)])
G['•'] = (.24, [ring(.12, .55, .12, .12)])
G['¡'] = (0, [L((0, .62), (0, -.45)), dot(0, .96)])
G['¿'] = (.64, [[(.64 - x, 1.0 - y) for x, y in G['?'][1][0]], dot(.32, .96)])
G['¢'] = (.62, [arc(.33, .5, .3, .36, 40, 320), L((.33, .98), (.33, .02))])
G['¥'] = (.88, [L((0, C), (.44, .68), (.88, C)), L((.44, .68), (.44, 0)), L((.14, .52), (.74, .52)), L((.14, .28), (.74, .28))])
G['µ'] = (.62, [L((0, 1), (0, DESC)), arc(.31, .4, .31, .4, 180, 360) + [(.62, 1)], L((.62, 1), (.62, 0))])
G['§'] = (.6, [arc(.3, 1.12, .24, .22, 20, 250) + arc(.3, .7, .28, .2, 90, -90) + arc(.3, .3, .24, .22, 110, -160)])

SUBSTITUTE = {'‘': "'", '’': "'", '“': '"', '”': '"', '…': '...'}


def _glyph(ch):
    return G.get(ch)


def supported(ch):
    return ch in ' \n' or all(c in G for c in SUBSTITUTE.get(ch, ch))


# mistakes ----------------------------------------------------------------
CONFUSE = {'a': 'o', 'o': 'a', 'e': 'a', 'i': 'e', 'n': 'm', 'm': 'n', 'u': 'n', 'r': 'n', 's': 'z', 'l': 't', 't': 'l', 'c': 'e',
           'd': 'b', 'b': 'd', 'g': 'q', 'p': 'q', 'v': 'w', 'w': 'v', 'y': 'g', 'h': 'k', 'k': 'h', 'f': 't'}


def _mistake(word, rng):
    """A plausible wrong attempt at `word` (never equal to it)."""
    letters = [i for i, c in enumerate(word) if c.isalpha()]
    if rng.random() < 0.4 and len(letters) >= 3:          # started, then stopped
        return word[:letters[int(rng.integers(1, min(4, len(letters))))] + 1]
    i = letters[int(rng.integers(1, len(letters)))] if len(letters) > 1 else letters[0]
    c = word[i]
    r = CONFUSE.get(c.lower(), 'a' if c.lower() != 'a' else 'o')
    return word[:i] + (r.upper() if c.isupper() else r) + word[i + 1:]


def _plan(paragraph, style):
    """Paragraph -> word items (text, crossed_out)."""
    items = []
    for wi, w in enumerate(paragraph.split()):
        if style.mistakes > 0 and sum(c.isalpha() for c in w) >= 3:
            rng = np.random.default_rng([style.seed & 0xffffffff, zlib.crc32(paragraph.encode('utf-8')), wi, 7])
            if rng.random() < style.mistakes:
                items.append((_mistake(w, rng), True))
        items.append((w, False))
    return items


# layout ------------------------------------------------------------------
def _rng(style, key, line_no):
    return np.random.default_rng([style.seed & 0xffffffff, zlib.crc32(key.encode('utf-8')), line_no])


def _key(items):
    return ' '.join(t + ('~' if c else '') for t, c in items)


def _layout(items, style, rng):
    """Word items of one line -> (strokes as (n, 2) arrays in x-height units, y up; width in units)."""
    mess = max(0.0, 1.0 - style.tidiness)
    space = 0.45*style.word_spacing
    strokes, x = [], 0.0
    for wi, (word, crossed) in enumerate(items):
        if wi:
            x += space*(1 + rng.normal(0, 0.2*mess))
        x_start, w_dy = x, rng.normal(0, 0.05*mess)
        for ch in ''.join(SUBSTITUTE.get(c, c) for c in word):
            g = _glyph(ch)
            if g is None:
                x += space
                continue
            width, parts = g
            dy = w_dy + rng.normal(0, 0.04*mess)
            sy = 1 + rng.normal(0, 0.05*mess)
            sl = rng.normal(0, 0.05*mess)
            for s in parts:
                p = np.array(s, dtype=float)
                y = p[:, 1].copy()
                y = np.where(y > 1, 1 + (y - 1)*style.ascender, np.where(y < 0, y*style.descender, y))
                y = y*sy + dy
                px = x + p[:, 0]*style.width + sl*y
                if mess:
                    px = px + rng.normal(0, 0.012*mess, len(px))
                    y = y + rng.normal(0, 0.012*mess, len(y))
                strokes.append(np.column_stack([px, y]))
            x += width*style.width + GAP + style.letter_spacing
        if crossed:                                     # one untidy line through the wrong word
            a, b = x_start - 0.1, x - GAP - style.letter_spacing + 0.15
            xs = np.linspace(a, b, max(3, int((b - a)/0.5) + 2))
            tilt = rng.normal(0, 0.05)
            strokes.append(np.column_stack([xs, 0.5 + tilt*(xs - a) + rng.normal(0, 0.03, len(xs))]))
        x -= GAP + style.letter_spacing
        x += GAP
    return strokes, max(0.0, x - GAP)


def _line_paths(strokes, style):
    out = []
    for p in strokes:
        q = p.copy()
        q[:, 0] += style.slant*q[:, 1]
        out.append(np.column_stack([q[:, 0]*style.size, -q[:, 1]*style.size]))
    return out


def wrap(text, style):
    """Split text into lines (lists of word items) no wider than style.max_width (mm)."""
    lines = []
    for para in text.split('\n'):
        items = _plan(para, style)
        if not items:
            lines.append([])
            continue
        cur = [items[0]]
        for it in items[1:]:
            trial = cur + [it]
            if _layout(trial, style, _rng(style, _key(trial), 0))[1]*style.size <= style.max_width:
                cur = trial
            else:
                lines.append(cur)
                cur = [it]
        lines.append(cur)
    return lines


def render_lines(text, style=None):
    """Text -> one list of pen paths per line: (n, 2) arrays in mm, x from the left margin, y down, baseline at y = 0."""
    style = style or Style()
    return [_line_paths(_layout(items, style, _rng(style, _key(items), i))[0], style) if items else []
            for i, items in enumerate(wrap(text, style))]


def render(text, style=None):
    """All lines placed on ruled lines: the first baseline is line_height below y = 0."""
    style = style or Style()
    out = []
    for i, line in enumerate(render_lines(text, style)):
        out.extend(p + [0, (i + 1)*style.line_height] for p in line)
    return out


def _label_style(size, style):
    return Style(**dict((style or Style(tidiness=0.95)).as_dict(), size=size, mistakes=0.0))


def text_width(text, size, style=None):
    st = _label_style(size, style)
    return _layout([(w, False) for w in text.split()], st, _rng(st, text, 0))[1]*size


def text_paths(text, x, y, size, anchor='left', style=None):
    """One line at (x, y) = start of the baseline, x-height `size` mm, SVG y-down. Never adds mistakes."""
    st = _label_style(size, style)
    strokes, w = _layout([(w, False) for w in text.split()], st, _rng(st, text, 0))
    if anchor == 'center':
        x -= w*size/2
    elif anchor == 'right':
        x -= w*size
    return [p + [x, y] for p in _line_paths(strokes, st)]
