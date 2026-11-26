"""
The two ways the studio can write: the AI handwriting model (model_engine) or
a single-line font (penfont: your own hand font if you have one, otherwise
the public print font). Both give the same
thing back: one list of pen paths per line, in mm, x from the left margin, y
down, each line's baseline at y = 0.

The page settings (line spacing, wrap width, mistakes, variation seed) are
shared; the font has its own look settings.
"""
import numpy as np

from penfont import font as handfont
import penfont
import model_engine as me

ENGINES = ('model', 'font')
FONT_KEYS = ('size', 'tidiness', 'slant', 'width', 'ascender', 'descender', 'letter_spacing', 'word_spacing')
FONT_DEFAULTS = {k: getattr(handfont.Style(), k) for k in FONT_KEYS}
FONT_DEFAULTS.update(size=penfont.DEFAULT_SIZE)
# applied by this module after the font has written the lines (not font Style fields), so they work for any font:
#   wander  0 = every line sits on the rule, 1 = lines tilt, float and wave noticeably
#   margin  0 = every line starts exactly at the margin, 1 = the start drifts in and out by a few mm
FONT_EXTRAS = dict(wander=0.0, margin=0.0)
FONT_DEFAULTS.update(FONT_EXTRAS)
FONT_LIMITS = dict(size=(0.8, 6.0), tidiness=(0.0, 1.0), slant=(-0.3, 1.0), width=(0.5, 1.8), ascender=(0.5, 1.6),
                   descender=(0.5, 1.6), letter_spacing=(-0.3, 0.8), word_spacing=(0.6, 3.0), wander=(0.0, 1.0), margin=(0.0, 1.0))


FONT_DEFAULTS['face'] = ''          # which font: '' = the built-in one, else a font made from someone's handwriting


def font_settings(d=None):
    out = dict(FONT_DEFAULTS)
    for k, v in (d or {}).items():
        if k == 'face':
            out['face'] = v if isinstance(v, str) and any(v == f for f, _ in penfont.faces()) else ''
            continue
        if k in FONT_DEFAULTS:
            try:
                lo, hi = FONT_LIMITS[k]
                out[k] = min(hi, max(lo, float(v)))
            except (TypeError, ValueError):
                pass
    return out


def font_of(font=None):
    """The font module a style writes with."""
    return penfont.get(font_settings(font)['face'])


def font_style(style=None, font=None):
    s = me.settings(style)
    look = {k: v for k, v in font_settings(font).items() if k not in FONT_EXTRAS and k != 'face'}
    return font_of(font).Style(**look, line_height=s['line_height'], max_width=s['max_width'],
                               mistakes=s['mistakes'], seed=int(s['seed']))


def wobble(lines, wander, margin, line_height, seed):
    """
    Make lines look hand-placed, the way a person drifts, not random jitter:
      wander: the page has a slope habit (every line leans the same way a
              little); each line's tilt and its height off the rule follow on
              from the line before; the baseline bends in one or two slow,
              smooth curves along the line (no word-by-word jumps).
      margin: where each line starts follows on from the line before, creeping
              slowly inward down the page, with an occasional small step out.
    Lines are lists of (n, 2) arrays in mm (x from the margin, y down, baseline
    0); None or empty lines are kept. Same seed, same result.
    """
    if wander <= 0 and margin <= 0:
        return lines
    page = np.random.default_rng([int(seed) & 0xffffffff, 17])
    habit = page.normal(0, 0.006)                      # mm per mm: this writer's lines tend to rise or fall
    tilt = lift = start = 0.0
    out = []
    for i, line in enumerate(lines):
        if not line:
            out.append(line)
            continue
        rng = np.random.default_rng([int(seed) & 0xffffffff, i, 11])
        span = max(float(p[:, 0].max()) for p in line) or 1.0
        dy = None
        if wander > 0:
            tilt = 0.6*tilt + 0.4*(habit + rng.normal(0, 0.006))
            lift = 0.55*lift + rng.normal(0, 0.07*line_height)
            amp = 0.035*line_height*rng.uniform(0.4, 1.0)
            waves = rng.uniform(0.6, 1.4)                   # about one slow bend along the line
            phase = rng.uniform(0, 2*np.pi)
            t, l = tilt*wander, lift*wander
            dy = lambda x, t=t, l=l, a=amp*wander, w=waves, ph=phase: \
                l + t*x + a*(np.sin(2*np.pi*w*x/span + ph) - np.sin(ph))
        if margin > 0:
            creep = min(0.35*i, 4.0)                        # mm: lines start further in as the page goes on
            start = 0.65*start + 0.35*(creep + rng.normal(0.6, 1.2))
            if rng.random() < 0.12:                         # now and then a line starts a little further out
                start -= abs(rng.normal(0, 1.0))
        dx = start*margin if margin > 0 else 0.0
        out.append([np.column_stack([p[:, 0] + dx, p[:, 1] + (dy(p[:, 0]) if dy else 0.0)]) for p in line])
    return out


_font_cache = {}                       # (text, style) -> lines: wander/margin and repeat previews skip the slow part


def _font_lines(text, st, mod):
    key = (getattr(mod, 'ID', ''), id(mod), text, tuple(sorted(st.as_dict().items())))
    hit = _font_cache.get(key)
    if hit is None:
        hit = mod.render_lines(text, st)
        if len(_font_cache) > 24:
            _font_cache.pop(next(iter(_font_cache)))
        _font_cache[key] = hit
    return [[p.copy() for p in line] for line in hit]


def engine_of(engine):
    return engine if engine in ENGINES else 'model'


def render(text, style=None, engine='model', font=None):
    """-> (lines, missing, skipped): lines of pen paths, how many lines the model still has to write, unsupported characters."""
    if engine_of(engine) == 'font':
        mod = font_of(font)
        skipped = sorted(set(c for c in text if not c.isspace() and not mod.supported(c)))
        st, f = font_style(style, font), font_settings(font)
        lines = wobble(_font_lines(text, st, mod), f['wander'], f['margin'], st.line_height, st.seed)
        return lines, 0, skipped
    s = me.settings(style)
    lines, missing, skipped = me.render(text, style)
    return wobble(lines, s['wander'], s['margin'], s['line_height'], s['seed']), missing, skipped


def generate(text, style=None, engine='model', font=None):
    if engine_of(engine) == 'model':
        me.generate(text, style)
