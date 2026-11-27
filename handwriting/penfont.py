"""
Which single-line font the studio uses for "My font", Labels and the
characters the AI model can't write.

handfont.py is a font drawn from one person's handwriting. It is personal and
is never published, so when it's missing the public print font in
plainfont.py is used instead. Both have the same functions.

On import the chosen font is extended so it can write (nearly) any character
(see charset.py): accented letters are composed from the plain letter plus a
drawn accent, symbols the hand font lacks are borrowed from the print font,
and typographic characters are turned into plain ones before writing.

    from penfont import font
"""
import charset

try:
    import handfont as font
    NAME = getattr(font, 'NAME', 'My font')
    PERSONAL = True
except ImportError:
    import plainfont as font
    NAME = font.NAME
    PERSONAL = False

DEFAULT_SIZE = 2.0          # x-height in mm the Write page starts with

# accented and barred letters worth adding: Latin-1, Latin Extended-A and a few more
_LETTERS = [chr(c) for c in range(0xC0, 0x250)] + list('ȘșȚțẞẼẽỲỳ')


def _extend_plain(pf):
    """plainfont: G[ch] = (width, [strokes as lists of (x, y)])."""
    for ch in _LETTERS:
        if ch in pf.G:
            continue
        sp = charset.split(ch)
        if not sp or sp[0] not in pf.G:
            continue
        width, strokes = pf.G[sp[0]]
        out = charset.compose([[tuple(p[:2]) for p in s] for s in strokes], sp[0], sp[1])
        pf.G[ch] = (width, [[(p[0], p[1]) for p in s] for s in out])


def _extend_hand(hf):
    """handfont: LOWER / UPPER / OTHER tables of [strokes as lists of (x, y[, 'c'])], the first stroke joins."""
    import plainfont as pf
    _extend_plain(pf)
    tables = (hf.LOWER, hf.UPPER, hf.OTHER)
    for ch in _LETTERS:
        if any(ch in t for t in tables):
            continue
        sp = charset.split(ch)
        if not sp:
            continue
        base, marks = sp
        home = next((t for t in tables if base in t), None)
        if home is None:
            continue
        home[ch] = charset.compose(home[base], base, marks)
        if base in hf.JOINS:
            hf.JOINS.add(ch)
    # symbols the hand font doesn't have: borrow the print font's, scaled to the hand font's capitals
    k = hf.CAP/pf.CAP
    for ch, (width, strokes) in pf.G.items():
        if any(ch in t for t in tables) or ch.isalpha() or ch.isdigit():   # ½ ¼ ¾ count as numbers to isalnum
            continue
        hf.OTHER[ch] = [[(x*k, y*k, charset.C) for x, y in s] for s in strokes]


try:
    (_extend_hand if PERSONAL else _extend_plain)(font)
except Exception as e:           # a font that can't be extended still works for plain text
    print('penfont: could not add accents and symbols:', e)


# clean text before writing: typographic characters -> plain ones, unless the font has its own
def _wrap(mod):
    """Make a font write (nearly) any character: clean the text first, keeping what the font can do itself."""
    sup, rl, tp, tw = mod.supported, mod.render_lines, mod.text_paths, mod.text_width
    prep = lambda text: charset.prepare(text, keep=sup)
    mod.prepare = prep
    mod.supported = lambda ch: ch in ' \n' or all(c == ' ' or sup(c) for c in prep(ch))
    mod.render_lines = lambda text, style=None: rl(prep(text), style)
    mod.text_paths = lambda text, x, y, size, anchor='left', style=None: tp(prep(text), x, y, size, anchor, style)
    mod.text_width = lambda text, size, style=None: tw(prep(text), size, style)
    return mod


_wrap(font)
prepare = font.prepare


# fonts people made from their own handwriting (fontimport.py, or drawn in the studio) ---------------------
import json as _json
import os as _os
import types as _types

_HERE = _os.path.dirname(_os.path.abspath(__file__))
FONTS = _os.environ.get('INKPLOT_FONTS') or _os.path.join(_HERE, 'fonts')
_loaded = {}


def _clone_plain(tag):
    """A fresh copy of plainfont's writing code, choosing between versions of a letter as it writes."""
    import plainfont
    with open(plainfont.__file__) as f:
        src = f.read()
    hook = '            g = _glyph(ch)\n'
    if hook not in src:
        raise RuntimeError('plainfont.py changed: cannot attach a handwriting font to it')
    src = src.replace(hook, '            g = _pick(ch, rng)\n')
    mod = _types.ModuleType('userfont_' + tag)
    mod.__file__ = plainfont.__file__
    exec(compile(src, plainfont.__file__, 'exec'), mod.__dict__)
    return mod


def load_user(fid):
    """A font saved in fonts/<fid>.json -> a font module like plainfont (same functions)."""
    import plainfont as pf
    with open(_os.path.join(FONTS, _os.path.basename(fid) + '.json')) as f:
        data = _json.load(f)
    mod = _clone_plain(fid)
    variants = {}
    for ch, vers in data.get('glyphs', {}).items():
        vv = [(float(w), [[(float(x), float(y)) for x, y in s] for s in strokes]) for w, strokes in vers if strokes]
        if vv:
            variants[ch] = vv
    mod.VARIANTS = variants
    mod.G = {ch: vv[0] for ch, vv in variants.items()}
    mod.NAME = data.get('name', fid)
    mod.CAP = float(data.get('cap', 1.45))
    mod.ID = fid

    def _pick(ch, rng, mod=mod):
        vv = mod.VARIANTS.get(ch)
        if not vv:
            return mod.G.get(ch)
        return vv[int(rng.integers(len(vv)))] if len(vv) > 1 else vv[0]
    mod._pick = _pick
    # anything the person didn't write: the print font's version, scaled to their capitals
    k = mod.CAP/pf.CAP
    for ch, (w, strokes) in pf.G.items():
        if ch not in mod.G:
            mod.G[ch] = (w*k, [[(x*k, y*k) for x, y in s] for s in strokes])
    try:
        _extend_plain(mod)                       # accented letters built from the person's own plain letters
    except Exception as e:
        print('penfont: could not add accents to', fid, e)
    return _wrap(mod)


def get(face=None):
    """The font for a style: '' or None = the built-in one (your hand font if present, else the print font)."""
    if not face:
        return font
    path = _os.path.join(FONTS, _os.path.basename(face) + '.json')
    if not _os.path.isfile(path):
        return font
    stamp = _os.path.getmtime(path)
    hit = _loaded.get(face)
    if hit is None or hit[0] != stamp:
        hit = (stamp, load_user(face))
        _loaded[face] = hit
    return hit[1]


def faces():
    """[(id, name)] of every font a style can use, the built-in one first."""
    out = [('', NAME)]
    if _os.path.isdir(FONTS):
        for fn in sorted(_os.listdir(FONTS)):
            if fn.endswith('.json'):
                try:
                    with open(_os.path.join(FONTS, fn)) as f:
                        out.append((fn[:-5], _json.load(f).get('name', fn[:-5])))
                except (OSError, ValueError):
                    pass
    return out
