"""
The AI handwriting model (../handwriting-synthesis) as the studio's engine.

The model invents every pen stroke, so it never writes the same line twice.
To keep results reproducible, every generated line is cached on disk
(cache/), keyed by its text and the settings that change the strokes
(writer, neatness, readability checks, seed). Same key -> same strokes.
Shuffle changes the seed, which asks the model for a new version.

Alongside the strokes the model reports which character it was writing at
each pen step. That is used to:
  - write capital Q, X and Z, which the model was never trained on: Q is the
    model's own O plus a tail; for X and Z the model writes K or L in that
    spot (so the word flows naturally), that letter is rubbed out and the
    hand-drawn font's X or Z is drawn in its place, sized and slanted to match;
  - cross out mistakes exactly over the wrong word.

Settings that only reshape the strokes (slant, width, letter size, line
spacing, wandering off the rule) are applied afterwards, so they update
instantly without regenerating.
"""
import hashlib
import json
import os
import sys
import threading
import zlib

import numpy as np

import charset

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.normpath(os.path.join(HERE, '..', 'handwriting-synthesis'))
CACHE = os.path.join(HERE, 'cache')

DEFAULTS = dict(
    writer=9,           # built-in writer the model imitates (9 is the default; 2 is the most joined-up)
    neatness=0.75,      # model bias: higher = tidier, lower = looser (and more scribbles)
    attempts=6,         # versions written per line; the most readable is kept
    letter_size=2.3,    # average character width in mm
    slant=0.35,
    width=1.3,          # letter width multiplier (writer 9 writes narrow, so it is widened)
    line_height=8.0,    # mm between ruled lines
    max_width=180.0,    # mm; longer lines wrap
    wander=0.4,         # 0 = every line sits on the rule, 1 = lines drift noticeably (engines.wobble)
    margin=0.0,         # 0 = every line starts at the margin, 1 = the start drifts by a few mm (engines.wobble)
    joins=0.7,          # 0 = letters as the model wrote them, 1 = join every letter it can (cursive)
    small=0.7,          # height of small letters (a, e, n...) relative to how the writer wrote them; tall letters keep their height
    mistakes=0.0,       # chance a word gets a crossed-out wrong attempt first
    seed=0,
)

# capitals the model has no slot for -> what it writes in their place
STAND_IN = {'Q': 'O', 'X': 'K', 'Z': 'L'}

_lock = threading.Lock()
_ready = threading.Event()
_error = None
_mh = None              # my_hand module, once loaded
progress = dict(phase='loading', done=0, total=0)


def settings(d=None):
    s = dict(DEFAULTS)
    for k, v in (d or {}).items():
        if k in DEFAULTS:
            try:
                s[k] = int(v) if isinstance(DEFAULTS[k], int) else float(v)
            except (TypeError, ValueError):
                pass
    return s


# loading -------------------------------------------------------------------
def load():
    """Load TensorFlow and the model (takes a few seconds). Safe to call more than once."""
    global _mh, _error
    with _lock:
        if _ready.is_set():
            return
        try:
            os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')
            os.chdir(MODEL_DIR)                       # the model reads checkpoints/ and styles/ relative paths
            if MODEL_DIR not in sys.path:
                sys.path.insert(0, MODEL_DIR)
            import my_hand
            my_hand._get_hand()
            _mh = my_hand
            progress.update(phase='ready', done=0, total=0)
            _ready.set()
        except Exception as e:                        # shown in the UI
            _error = '{}: {}'.format(type(e).__name__, e)
            progress.update(phase='error')


def load_in_background():
    threading.Thread(target=load, daemon=True).start()


def status():
    return dict(progress, ready=_ready.is_set(), error=_error)


# text -> lines ---------------------------------------------------------------
_ALPHA = None


def _alpha():
    """The characters the model itself can write."""
    global _ALPHA
    if _ALPHA is None:
        if MODEL_DIR not in sys.path:
            sys.path.insert(0, MODEL_DIR)
        import drawing
        _ALPHA = frozenset(drawing.alphabet) - {'\x00'}
    return _ALPHA


def _font():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    from penfont import font
    return font


def _model_char(c):
    """What the model writes for c (always one character), or None if c can't be written at all.
    Q, X, Z: a stand-in it later turns into the real letter; accented letters: the plain letter (the accent is
    drawn on afterwards); other symbols: a stand-in letter whose place the font fills."""
    a = _alpha()
    if c in a:
        return c
    if c in STAND_IN:
        return STAND_IN[c]
    sp = charset.split(c)
    if sp and (sp[0] in a or sp[0] in STAND_IN):
        return _model_char(sp[0])
    if c.strip() and _font().supported(c):
        return ' '                     # the model leaves a gap; the font writes the symbol into it
    return None


def _clean(text):
    text = charset.prepare(text, keep=lambda c: c in _alpha())
    out, skipped = [], set()
    for c in text:
        if c == '\n' or _model_char(c) is not None:
            out.append(c)
        else:
            skipped.add(c)
    return ''.join(out), sorted(skipped)


_CONFUSE = {'a': 'o', 'o': 'a', 'e': 'a', 'i': 'e', 'n': 'm', 'm': 'n', 'u': 'n', 'r': 'n', 's': 'z', 'l': 't', 't': 'l',
            'c': 'e', 'd': 'b', 'b': 'd', 'g': 'q', 'p': 'q', 'v': 'w', 'w': 'v', 'y': 'g', 'h': 'k', 'k': 'h', 'f': 't'}


def _wrong(word, rng):
    """A believable wrong first attempt at `word`."""
    letters = [i for i, c in enumerate(word) if c.isalpha()]
    kind = rng.choice(['wrong', 'wrong', 'start', 'start', 'swap', 'double'])
    if kind == 'start' and len(letters) >= 3:
        k = int(rng.integers(2, min(4, len(letters)) + 1)) if len(letters) > 3 else 2
        out = word[:letters[k - 1] + 1]
        if rng.random() < 0.5:
            out = out[:-1] + _CONFUSE.get(out[-1].lower(), 'e')
        return out
    i = letters[int(rng.integers(1, len(letters)))]
    if kind == 'swap' and i + 1 < len(word) and word[i + 1].isalpha() and word[i] != word[i + 1]:
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if kind == 'double':
        return word[:i + 1] + word[i] + word[i + 1:]
    c = word[i]
    r = _CONFUSE.get(c.lower(), 'a' if c.lower() != 'a' else 'o')
    return word[:i] + (r.upper() if c.isupper() else r) + word[i + 1:]


def plan(text, s):
    """
    Text -> list of lines; each line is a list of (word, cross) where cross is
    None or how that wrong attempt is crossed out ('strike', 'double', 'scribble').
    """
    text, skipped = _clean(text)
    # letters are scaled to letter_size on average; leave a little slack for wide lines
    chars_per_line = max(8, int(s['max_width']/(s['letter_size']*1.05)))
    lines = []
    for para in text.split('\n'):
        words = para.split()
        if not words:
            lines.append([])
            continue
        items = []
        for wi, w in enumerate(words):
            if s['mistakes'] > 0 and sum(c.isalpha() for c in w) >= 3:
                rng = np.random.default_rng([s['seed'] & 0xffffffff, zlib.crc32(para.encode('utf-8')), wi, 7])
                if rng.random() < s['mistakes']:
                    cross = str(rng.choice(['strike', 'strike', 'double', 'scribble', 'scribble']))
                    items.append((_wrong(w, rng), cross))
            items.append((w, None))
        cur, n = [], 0
        for it in items:
            add = len(it[0]) + (1 if cur else 0)
            if cur and n + add > chars_per_line:
                lines.append(cur)
                cur, n = [], 0
                add = len(it[0])
            cur.append(it)
            n += add
        if cur:
            lines.append(cur)
    while lines and not lines[-1]:
        lines.pop()
    return lines, skipped


def _line_text(items):
    return ' '.join(w for w, _ in items)


def _model_text(t):
    """What the model is asked to write: same length as t, with stand-ins (see _model_char)."""
    return ''.join(_model_char(c) or ' ' for c in t)


def _key(line, s):
    raw = json.dumps([_model_text(line), s['writer'], round(s['neatness'], 3), s['attempts'], s['seed']])
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def _cached(key):
    path = os.path.join(CACHE, key + '.npy')
    return np.load(path) if os.path.exists(path) else None


# generation -------------------------------------------------------------------
def _sample(lines, bias, writer):
    """
    Like Hand._sample, but also returns, for every pen step, the index of the
    character in the line the model was writing at that moment.
    """
    import drawing
    hand = _mh._get_hand()
    n = len(lines)
    x_prime = np.zeros([n, 1200, 3])
    x_prime_len = np.zeros([n])
    chars = np.zeros([n, 120])
    chars_len = np.zeros([n])
    x_p = np.load('styles/style-{}-strokes.npy'.format(writer))
    c_p = np.load('styles/style-{}-chars.npy'.format(writer)).tobytes().decode('utf-8')
    prefix = len(c_p) + 1                                  # writer's sample text + a space, then our line
    for i, line in enumerate(lines):
        enc = np.array(drawing.encode_ascii(c_p + ' ' + line))
        x_prime[i, :len(x_p), :] = x_p
        x_prime_len[i] = len(x_p)
        chars[i, :len(enc)] = enc
        chars_len[i] = len(enc)
    samples, where = hand.nn.session.run(
        [hand.nn.sampled_sequence, hand.nn.sampled_chars],
        feed_dict={
            hand.nn.prime: True,
            hand.nn.x_prime: x_prime,
            hand.nn.x_prime_len: x_prime_len,
            hand.nn.num_samples: n,
            hand.nn.sample_tsteps: 40*max(len(l) for l in lines),
            hand.nn.c: chars,
            hand.nn.c_len: chars_len,
            hand.nn.bias: [bias]*n,
        })
    out = []
    for sample, w in zip(samples, where):
        keep = ~np.all(sample == 0.0, axis=1)
        out.append(np.column_stack([sample[keep], w[keep] - prefix]))
    return out


PHRASE = 26             # the model is written a few words at a time: it rarely loses its place in short runs
RETRY_BELOW = 0.8       # readability under this gets another round of tries


def _phrases(items):
    """Split a line's words into short phrases: list of (first, last+1) word indexes."""
    out, start, n = [], 0, 0
    for i, (w, _) in enumerate(items):
        add = len(w) + (1 if i > start else 0)
        if i > start and n + add > PHRASE:
            out.append((start, i))
            start, n = i, len(w)
        else:
            n += add
    out.append((start, len(items)))
    return out


def _phrase_texts(items):
    """(phrase text, char offset in the line) for each phrase."""
    words = [w for w, _ in items]
    res = []
    for a, b in _phrases(items):
        res.append((' '.join(words[a:b]), sum(len(w) + 1 for w in words[:a])))
    return res


def generate(text, d):
    """
    Write every phrase that isn't cached yet, one line at a time: each line is
    saved to the cache as soon as it is done, so the page can show it while the
    next one is written. Blocking; progress is reported in `progress`
    (line = the line being written, lines = how many need writing, lines_done).
    """
    s = settings(d)
    lines, _ = plan(text, s)
    todo, seen = [], set()
    for items in lines:
        group = []
        for ph, _ in (_phrase_texts(items) if items else []):
            mt = _model_text(ph)
            if _cached(_key(ph, s)) is None and mt not in seen:
                group.append(mt)
                seen.add(mt)
        if group:
            todo.append(group)
    if not todo:
        return 0
    load()
    if not _ready.is_set():
        raise RuntimeError(_error or 'the model is not loaded')
    os.makedirs(CACHE, exist_ok=True)
    with _lock:
        n = s['attempts']
        for li, group in enumerate(todo):
            best = {}
            rounds = [group]
            for r in range(2):
                part = rounds[-1]
                if not part:
                    break
                progress.update(phase='writing', done=0, total=len(part), round=r + 1,
                                line=li + 1, lines=len(todo), lines_done=li)
                samples = _sample([t for t in part for _ in range(n)], s['neatness'], s['writer'])
                progress.update(phase='checking', done=0, total=len(part))
                for i, t in enumerate(part):
                    for c in samples[i*n:(i + 1)*n]:
                        sc = _mh._readability(c[:, :3], t, s['slant'], s['width']) if n > 1 or r else 1.0
                        if t not in best or sc > best[t][0]:
                            best[t] = (sc, c)
                    progress.update(done=i + 1)
                rounds.append([t for t in part if best[t][0] < RETRY_BELOW])
            for t, (sc, c) in best.items():               # this line is finished: save it now
                np.save(os.path.join(CACHE, _key(t, s) + '.npy'), c)
            progress.update(lines_done=li + 1)
        progress.update(phase='ready', done=0, total=0, round=0, line=0, lines=0, lines_done=0)
    return sum(len(g) for g in todo)


# layout -----------------------------------------------------------------------
def _word_chars(items):
    """Character range [a, b) of each word in the line text."""
    out, pos = [], 0
    for w, _ in items:
        out.append((pos, pos + len(w)))
        pos += len(w) + 1
    return out


def _words_x(strokes, idx, items, char_mm):
    """
    x-range (mm) of each word. With the model's character positions (idx) this
    is exact; for older cached lines without them, word boundaries are
    estimated from the letters and snapped to gaps in the ink.
    """
    xs = np.concatenate([p[:, 0] for p in strokes])
    if idx is not None:
        ix = np.concatenate(idx)
        out = []
        for a, b in _word_chars(items):
            m = (ix >= a) & (ix < b)
            out.append((float(xs[m].min()), float(xs[m].max())) if m.any() else None)
        known = [o for o in out if o]
        if known:
            # a word the attention skipped: put it between its neighbours
            for i, o in enumerate(out):
                if o is None:
                    left = next((out[j][1] for j in range(i - 1, -1, -1) if out[j]), known[0][0])
                    right = next((out[j][0] for j in range(i + 1, len(out)) if out[j]), left + char_mm*len(items[i][0]))
                    out[i] = (left, max(right, left + char_mm))
            return out

    spans = sorted((float(p[:, 0].min()), float(p[:, 0].max())) for p in strokes)
    clusters = []
    for a, b in spans:
        if clusters and a < clusters[-1][1] + 0.55*char_mm:
            clusters[-1][1] = max(clusters[-1][1], b)
        else:
            clusters.append([a, b])
    gaps = [(clusters[i][1] + clusters[i + 1][0])/2 for i in range(len(clusters) - 1)]
    text = _line_text(items)
    lo_all, hi_all = clusters[0][0], clusters[-1][1]
    expect = [(lo_all + (hi_all - lo_all)*a/len(text), lo_all + (hi_all - lo_all)*b/len(text)) for a, b in _word_chars(items)]
    cuts = []
    for i in range(len(items) - 1):
        guess = (expect[i][1] + expect[i + 1][0])/2
        near = [g for g in gaps if abs(g - guess) < 1.6*char_mm and (not cuts or g > cuts[-1])]
        cuts.append(min(near, key=lambda g: abs(g - guess)) if near else max(guess, cuts[-1] + 0.1 if cuts else guess))
    out = []
    for i in range(len(items)):
        lo = cuts[i - 1] if i else -np.inf
        hi = cuts[i] if i < len(cuts) else np.inf
        inside = xs[(xs > lo) & (xs < hi)]
        out.append((float(inside.min()), float(inside.max())) if len(inside) else expect[i])
    return out


def _smooth(p):
    """Light Chaikin smoothing so added strokes look hand-drawn rather than polygonal."""
    for _ in range(2):
        q = [p[0]]
        for a, b in zip(p[:-1], p[1:]):
            q += [0.75*a + 0.25*b, 0.25*a + 0.75*b]
        q.append(p[-1])
        p = np.array(q)
    return p


def _cross_out(x0, x1, top, kind, rng):
    """Untidy crossing-out strokes (mm, y down, baseline 0, x-height `top` above it, negative)."""
    h = top
    out = []
    if kind in ('strike', 'double'):
        rows = [0.5] if kind == 'strike' else [0.72, 0.3]
        for k, f in enumerate(rows):
            tilt = rng.normal(0, 0.05)
            a, b = x0 - rng.uniform(0.3, 1.2), x1 + rng.uniform(0.3, 1.3)
            xs = np.linspace(a, b, max(3, int((b - a)/2.0) + 2))
            pts = np.array([(x, h*f + tilt*(x - a) + rng.normal(0, 0.15*abs(h))) for x in xs])
            out.append(pts if k % 2 == 0 else pts[::-1])
    else:
        a, b = x0 - 0.4, x1 + 0.5
        xs = np.linspace(a, b, max(4, int((b - a)/(0.33*abs(h) + 0.3))))
        there = [(x + rng.normal(0, .1), (h*1.1 if j % 2 == 0 else -h*0.05) + rng.normal(0, .1*abs(h))) for j, x in enumerate(xs)]
        back = [(x + 0.3 + rng.normal(0, .12), (h*0.1 if j % 2 == 0 else h*0.95) + rng.normal(0, .1*abs(h)))
                for j, x in enumerate(xs[::-1])]
        out.append(np.array(there + back))
    return [_smooth(p) for p in out]


def _font_letter(ch, cap_mm, slant):
    """A capital from the hand-drawn font, cap_mm tall, as paths (mm, y down, baseline 0, starting at x=0)."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    from penfont import font as handfont
    size = cap_mm/handfont.CAP
    paths = handfont.text_paths(ch, 0, 0, size, style=handfont.Style(tidiness=0.75, slant=slant))
    x0 = min(p[:, 0].min() for p in paths)
    return [p - [x0, 0] for p in paths]


def _accent(strokes, idx, k, ch, s, rng):
    """Draw the accent (or the bar) of letter k over the plain letter the model wrote. In place."""
    base, marks = charset.split(ch)
    mine = [p for p, i in zip(strokes, idx) if (i == k).all()]
    pts = [p[i == k] for p, i in zip(strokes, idx) if (i == k).any()]
    if not pts or sum(len(p) for p in pts) < 3:
        return
    xh = 0.85*s['letter_size']                                  # about the x-height in mm
    if base in 'ij' and mine:                                   # the dot makes way for the accent
        drop = [p for p in mine if p[:, 1].max() < -1.12*xh and np.ptp(p[:, 1]) < 0.45*xh]
        if drop and len(drop) < len(mine):
            keep = [(p, i) for p, i in zip(strokes, idx) if not any(p is d for d in drop)]
            strokes[:], idx[:] = [p for p, _ in keep], [i for _, i in keep]
            pts = [p[i == k] for p, i in zip(strokes, idx) if (i == k).any()]
    up = [[(x, -y) for x, y in p] for p in pts]                  # y up, as charset expects
    jit = lambda n: rng.normal(0, 0.04, n)
    new = charset.compose(up, base, marks, unit=xh, jitter=jit, size=0.75)[len(up):]
    for st in new:
        p = np.array([(q[0], -q[1]) for q in st], dtype=float)
        if len(p) > 2 and not any(len(q) > 2 for q in st):     # smooth curved marks (tilde, ring, cedilla)
            p = _smooth(p)
        strokes.append(p)
        idx.append(np.full(len(p), k))


def _special_letters(strokes, idx, t, s, rng):
    """Turn the model's stand-ins into the real characters: Q, X, Z, accented letters and symbols. In place."""
    alpha = _alpha()
    for k, ch in enumerate(t):
        if ch in alpha or ch == ' ':
            continue
        if ch not in STAND_IN and charset.split(ch) and _model_char(ch) == _model_char(charset.split(ch)[0]):
            if (base := charset.split(ch)[0]) in STAND_IN and base != 'Q':
                pass                                             # an accented X or Z: the font letter below has it
            else:
                _accent(strokes, idx, k, ch, s, rng)
                continue
        pts = np.concatenate(strokes)
        ix = np.concatenate(idx)
        cap = float(np.clip(np.percentile(-pts[:, 1], 97), 1.2*s['letter_size'], 3.5*s['letter_size']))
        if ch == 'Q':
            o = pts[ix == k]
            if len(o) < 4:
                continue
            x0, x1 = o[:, 0].min(), o[:, 0].max()
            top, bot = o[:, 1].min(), o[:, 1].max()
            w, h = x1 - x0, bot - top
            tail = np.array([(x0 + 0.5*w, bot - 0.32*h), (x0 + 0.72*w, bot - 0.08*h + rng.normal(0, 0.03*h)),
                             (x1 + 0.08*w, bot + 0.1*h), (x1 + 0.32*w, bot + 0.16*h)])
            strokes.append(_smooth(tail))
            idx.append(np.full(len(strokes[-1]), k))
        else:
            # rub out the stand-in letter the model wrote here, remembering where it was
            gone = pts[ix == k]
            kept_s, kept_i = [], []
            for p, i in zip(strokes, idx):
                keep = i != k
                if keep.all():
                    kept_s.append(p)
                    kept_i.append(i)
                    continue
                for run in np.split(np.arange(len(p)), np.where(np.diff(keep.astype(int)) != 0)[0] + 1):
                    if keep[run[0]] and len(run) > 1:
                        kept_s.append(p[run])
                        kept_i.append(i[run])
            strokes[:], idx[:] = kept_s, kept_i
            pts = np.concatenate(strokes)
            ix = np.concatenate(idx)
            glyph = _font_letter(ch, cap, s['slant'] + 0.12)
            gw = max(p[:, 0].max() for p in glyph)
            if len(gone) >= 3:
                left = float(gone[:, 0].min())
                room = float(gone[:, 0].max()) - left
            else:                                        # the model skipped it: use the space before the next letter
                before, after = pts[(ix >= 0) & (ix < k)], pts[ix > k]
                left = float(before[:, 0].max()) + 0.25*cap if len(before) else 0.0
                room = (float(after[:, 0].min()) - 0.15*cap - left) if len(after) else gw
            if room < gw:                                 # make room: push the rest of the line along
                for p, i in zip(strokes, idx):
                    p[i > k, 0] += gw - room
            else:
                left += (room - gw)/2
            for p in glyph:
                strokes.append(p + [left, 0])
                idx.append(np.full(len(p), k))


def _join_letters(strokes, idx, spans, items, s, t):
    """
    Make the writing more cursive: inside a word, when one stroke ends near
    the baseline and the next letter starts shortly after it, draw the
    connecting hairline and merge them into one pen-down stroke. Dots,
    crossbars and anything far apart are left alone.
    """
    if s['joins'] <= 0 or len(strokes) < 2:
        return strokes, idx
    char_mm = s['letter_size']
    ys = np.concatenate([p[:, 1] for p in strokes])
    xh = max(0.2, -float(np.percentile(ys, 30)))       # x-height in mm
    reach = s['joins']*1.6*char_mm

    def word_of(p):
        c = p[:, 0].mean()
        for j, (a, b) in enumerate(spans):
            if a - 0.2 <= c <= b + 0.2:
                return j
        return -1

    def is_mark(p):                                    # i-dots, t-bars, short ticks
        length = float(np.hypot(*np.diff(p, axis=0).T).sum())
        return length < 0.9*char_mm or (np.ptp(p[:, 1]) < 0.35*xh and p[:, 1].mean() < -0.9*xh)

    out_s, out_i = [strokes[0]], [idx[0] if idx is not None else None]
    for k in range(1, len(strokes)):
        a, b = out_s[-1], strokes[k]
        ia = out_i[-1]
        ib = idx[k] if idx is not None else None
        (ax, ay), (bx, by) = a[-1], b[0]
        from_capital = ia is not None and 0 <= ia[-1] < len(t) and t[ia[-1]].isupper()
        ok = (word_of(a) == word_of(b) != -1 and not is_mark(a) and not is_mark(b) and not from_capital
              and 0 < bx - ax < reach                      # next letter starts just to the right
              and ay > -0.45*xh                           # previous letter ends near the baseline
              and -1.15*xh < by < 0.4*xh)                 # next starts in the body, not atop a tall letter
        if ok:
            # a garland connector that dips slightly before rising into the next letter
            mid = ((ax + bx)/2, max(ay, min(by, 0.0)) + 0.12*xh)
            link = _smooth(np.array([(ax, ay), mid, (bx, by)]))[1:-1]
            out_s[-1] = np.vstack([a, link, b])
            if ia is not None:
                out_i[-1] = np.concatenate([ia, np.full(len(link), ia[-1]), ib])
        else:
            out_s.append(b)
            out_i.append(ib)
    return out_s, (out_i if idx is not None else None)


def _shrink_small_letters(strokes, f):
    """
    Make the small letters (the x-height band) smaller by f while tall letters,
    capitals and tails keep their full reach: heights above the x-height are
    re-spread so the tallest point stays where it was. Works in place.
    """
    if abs(f - 1) < 1e-3 or not strokes:
        return
    h = -np.concatenate([p[:, 1] for p in strokes])     # height above the baseline
    xh = float(np.percentile(h, 70))
    top = float(np.percentile(h, 99.5))
    if xh <= 0 or top <= xh*1.2:
        return
    g = (top - xh*f)/(top - xh)
    for p in strokes:
        hh = -p[:, 1]
        p[:, 1] = -np.where(hh <= 0, hh, np.where(hh <= xh, hh*f, xh*f + (hh - xh)*g))


def _phrase_coords(off, s):
    coords = _mh._line_coords(off[:, :3], s['slant'], s['width'])
    coords[:, :2] *= s['letter_size']/_mh._UNITS_PER_CHAR
    coords[:, 0] -= coords[:, 0].min()
    baseline = np.percentile(coords[:, 1], 15)
    coords[:, 1] = baseline - coords[:, 1]
    return coords


def render(text, d):
    """
    Lines as pen paths in mm (x from the margin, y down, each line's baseline at 0),
    using cached strokes only. Returns (lines, missing_count, skipped_chars).
    """
    s = settings(d)
    lines, skipped = plan(text, s)
    if _mh is None and any(lines):
        load()
    out, missing = [], 0
    char_mm = s['letter_size']
    # writers differ in how wide they write; scale so the average letter is letter_size wide
    chars = width = 0.0
    for items in lines:
        for ph, _ in (_phrase_texts(items) if items else []):
            off = _cached(_key(ph, s))
            if off is not None:
                c = _phrase_coords(off, s)
                chars += len(ph)
                width += float(np.ptp(c[:, 0]))
    fit = float(np.clip(chars*char_mm/width, 0.6, 1.6)) if width else 1.0
    for li, items in enumerate(lines):
        t = _line_text(items)
        if not t:
            out.append([])
            continue
        rng = np.random.default_rng([s['seed'] & 0xffffffff, zlib.crc32(t.encode('utf-8')), li, 3])
        strokes, idx, x_at, has_idx, ok = [], [], 0.0, True, True
        for ph, at in _phrase_texts(items):
            off = _cached(_key(ph, s))
            if off is None:
                ok = False
                break
            where = off[:, 3].astype(int) if off.shape[1] > 3 else np.full(len(off), -2)
            has_idx &= off.shape[1] > 3
            coords = _phrase_coords(off, s)
            coords[:, :2] *= fit
            cut = np.where(coords[:, 2] == 1)[0] + 1
            pieces = [(p[:, :2].copy(), w) for p, w in zip(np.split(coords, cut), np.split(where, cut)) if len(p) > 1]
            if off.shape[1] > 3:
                # drop stray strokes made entirely before the first letter or after the last
                pieces = [(p, w) for p, w in pieces if ((w >= 0) & (w < len(ph))).any()] or pieces
            # some writers dab the pen before starting: drop a tiny mark left of everything else
            if len(pieces) > 1:
                p0 = pieces[0][0]
                rest = min(float(p[:, 0].min()) for p, _ in pieces[1:])
                if np.hypot(*np.diff(p0, axis=0).T).sum() < 0.35*char_mm and p0[:, 0].max() < rest - 0.2*char_mm:
                    pieces = pieces[1:]
            if not pieces:
                continue
            shift = min(float(p[:, 0].min()) for p, _ in pieces)
            pieces = [(p - [shift, 0], w) for p, w in pieces]
            for p, w in pieces:
                strokes.append(p + [x_at, 0])
                idx.append(np.where(w >= 0, w + at, w))
            x_at = max(float(p[:, 0].max()) for p in strokes) + char_mm*(1.05 + rng.normal(0, 0.12))
        if not ok:
            missing += 1
            out.append(None)
            continue
        if not strokes:
            out.append([])
            continue
        if not has_idx:
            idx = None
        _shrink_small_letters(strokes, s['small'])

        if idx is not None and any(c not in _alpha() and c != ' ' for c in t):
            _special_letters(strokes, idx, t, s, rng)
        spans = _words_x(strokes, idx, items, char_mm)
        strokes, idx = _join_letters(strokes, idx, spans, items, s, t)
        # mistakes: cross out the wrong attempts
        if any(c for _, c in items):
            ys = np.concatenate([p[:, 1] for p in strokes])
            top = float(np.percentile(ys, 30))          # roughly the x-height (negative, y down)
            for (x0, x1), (w, cross) in zip(spans, items):
                if cross:
                    strokes += _cross_out(x0, x1, top, cross, rng)
        # wander and margin are applied by engines.wobble(), the same for the model and the font
        out.append(strokes)
    return out, missing, skipped
