"""
The plotter behind the studio's Plotter page: lay out drawings, handwriting,
labels and shapes on the A4 sheet and turn them into G-code for the X1E with
the UMTS pen holder, already checked by plotcheck (nothing to run by hand).

Coordinates are paper mm: x from the paper's left edge, y down from its top
edge. The sheet is A4 portrait pushed into the bed's back-left corner, so the
pen at paper (x, y) is at bed X = x, Y = 256 - y, and the nozzle is at the pen
minus the pen offset found by calibration.

What makes a plot safe, all taken from plotcheck / calibrate / magnets so the
command-line tools and this page always agree:
  - the pen offset, pen length and pad thickness in calibration.json
  - the magnet zones in magnets.json
  - plotcheck's keep-out for the holder (SAFE_X / SAFE_Y, in nozzle positions)
The pen can't reach the top ~37 mm or the bottom of the sheet in one go, so a
sheet can be done in two parts: part A with the sheet as normal, then part B
with the same sheet turned round (top edge to the front, pushed back into the
corner). Whatever doesn't fit in A goes in B. A long text can be flowed over as
many sheets as it needs (pages()).

Anything outside the area the pen may draw is trimmed (and shown in red), then
the finished G-code goes through plotcheck.check, on_paper and avoid_magnets,
exactly like ./plotcheck does. A file is only written if every check passes.
"""
import hashlib
import json
import math
import os
import re
import shutil
import sys
import threading
import time

import numpy as np
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
SYN = os.path.normpath(os.path.join(HERE, '..', 'handwriting-synthesis'))
sys.path.insert(0, HERE)
sys.path.insert(0, SYN)

import calibrate  # noqa: E402
import magnets  # noqa: E402
import plotcheck  # noqa: E402
import printers  # noqa: E402
import svgplot  # noqa: E402

PAPER_W, PAPER_H = magnets.PAPER_W, 297.0
CLIP_EXTRA = 0.5                    # trim this much further inside the limits than plotcheck insists on
SIMPLIFY_MM = 0.05                  # drop points closer together than this
STATE = os.environ.get('PLOTTER_STATE') or os.path.join(HERE, 'plot_state.json')
PLOTS = os.environ.get('INKPLOT_PLOTS') or os.path.join(HERE, 'out', 'plots')     # INKPLOT_PLOTS: another folder (tests)
THUMBS = os.path.join(HERE, 'cache', 'thumbs')
UPLOADS = os.path.join(HERE, 'uploads')
BLUEPRINTS = os.path.normpath(os.path.join(HERE, '..', 'blueprints'))
DRY_LIFT = plotcheck.DRY_LIFT

SETTINGS = dict(pressure=0.5, lift=2.5, draw_speed=1500.0, travel_speed=6000.0, z_speed=600.0,
                dwell_ms=120.0, min_stroke=0.2, join=1.0)
LIMITS = dict(pressure=(0.0, 1.5), lift=(2.0, 15.0), draw_speed=(100.0, 6000.0), travel_speed=(600.0, 24000.0),
              z_speed=(60.0, 3000.0), dwell_ms=(0.0, 2000.0), min_stroke=(0.0, 5.0), join=(0.0, 1.0))

_lock = threading.Lock()


# settings and machine --------------------------------------------------------
def settings(d=None):
    s = dict(SETTINGS)
    for k, v in (d or {}).items():
        if k in SETTINGS:
            try:
                lo, hi = LIMITS[k]
                s[k] = min(hi, max(lo, float(v)))
            except (TypeError, ValueError):
                pass
    return s


def _hull(pts):
    pts = sorted(set((round(x, 6), round(y, 6)) for x, y in pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0])*(b[1] - o[1]) - (a[1] - o[1])*(b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]          # counter-clockwise (in x-right, y-up arithmetic)


def _bbox(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def paper_of(state):
    p = (state or {}).get('paper') or {}
    try:
        w, h = float(p.get('w', PAPER_W)), float(p.get('h', PAPER_H))
    except (TypeError, ValueError):
        w, h = PAPER_W, PAPER_H
    return min(max(w, 150.0), 230.0), min(max(h, 200.0), 320.0)


def two_pass_of(state):
    return bool((state or {}).get('two_pass', True))


def flip(p, W, H):
    """Sheet coordinates <-> coordinates on the bed when the sheet is turned round (part B)."""
    return np.column_stack([W - p[:, 0], H - p[:, 1]])


def shift_of(state):
    """How far forward of the back of the bed the sheet's top edge goes, for part A and part B (mm)."""
    d = (state or {}).get('shift') or {}
    out = []
    for k in ('a', 'b'):
        try:
            out.append(min(max(float(d.get(k, 0) or 0), 0.0), 60.0))
        except (TypeError, ValueError):
            out.append(0.0)
    return tuple(out)


def machine(s=None, paper=(PAPER_W, PAPER_H), two_pass=True, shift=(0.0, 0.0)):
    """
    Everything the page and the planner need to know about the printer, pen and paper.
    shift: (part A, part B) how far the sheet's top edge sits in front of the back of the bed.
    """
    s = settings(s)
    W, H = paper
    shift = (float(shift[0]), float(shift[1]))
    c = calibrate.recall()
    mag = magnets.load()
    prof = printers.current()
    BED = plotcheck.bed_back(prof)
    SAFE_X, SAFE_Y = plotcheck.limits(prof)
    P = c.get('pen')
    S = float(c.get('surface', 0.0) or 0.0)
    has_offset = 'offset_x' in c and 'offset_y' in c
    ox, oy = float(c.get('offset_x', 0.0)), float(c.get('offset_y', 0.0))
    m = dict(calibrated=bool(has_offset and P is not None), has_offset=has_offset, pen=P, surface=S,
             offset_x=ox, offset_y=oy, check=c.get('check'), magnet_size=mag['size'], magnet_height=mag['height'],
             magnet_diameter=mag.get('diameter', 10.0),
             paper=[W, H], two_pass=bool(two_pass), shift=list(shift), bed_front=BED - shift[0], bed=BED,
             bed_w=float(prof['bed'][0]), bed_d=BED, keepout=[SAFE_X[0], SAFE_Y[0]], safe_x=list(SAFE_X), safe_y=list(SAFE_Y),
             cal_nozzle=list(calibrate.cal_point(prof)),
             printer=dict(id=prof['id'], name=prof['name'], maker=prof['maker'], measured=prof['measured'],
                          note=prof.get('note', ''), builtin=prof.get('builtin', False)))
    problems = []
    cal_on = c.get('printer') or printers.DEFAULT     # calibrations from before profiles were made on the X1E
    if has_offset and cal_on and cal_on != prof['id']:
        was = printers.get(cal_on)
        problems.append('The pen was calibrated for "{}". Calibrate again for "{}" (Machine > Calibrate…), '
                        'or switch back.'.format(was['name'] if was else cal_on, prof['name']))
        m['calibrated'] = False
    if P is None:
        problems.append('Enter how far the pen sticks out below the nozzle (Pen card).')
    if not has_offset:
        problems.append('Calibrate the pen offset first (Calibration card).')
    if P is not None:
        top = min(s['pressure'], P - plotcheck.NOZZLE_FLOOR)       # never closer to the bed than plotcheck allows
        if top < s['pressure']:
            problems.append('The pen sticks out only {:.1f} mm, so pressure is limited to {:.1f} mm.'.format(P, max(top, 0)))
        z_draw = round(S + P - max(top, 0.0), 3)
        z_lift = round(z_draw + s['lift'], 3)
        h = mag['height']
        touch = z_draw + 1.0
        hop = max(touch + h + 3.0, S + h + 3.0) if h > 0 else z_lift
        m.update(z_draw=z_draw, z_lift=z_lift, z_hop=round(hop, 3), z_start=round(max(z_lift, hop), 3),
                 head_low=bool(h > 0 and z_draw - S < h + 2.0),
                 pen_for_free_corners=round(h + 2.5, 1) if h > 0 else None)
    else:
        m.update(z_draw=None, z_lift=None, z_hop=None, z_start=None, head_low=False, pen_for_free_corners=None)
    m['problems'] = problems

    lim_a = _limits(m, mag, W, H, shift[0])
    m['lim_a'] = lim_a
    m['reach'], m['banned'], m['zones'] = lim_a['reach'], lim_a['banned'], lim_a['zones']
    m['fit_rects'] = list(lim_a['rects'])
    # part B: the sheet turned round; its limits seen on the sheet itself
    if two_pass:
        lim_b = _limits(m, mag, W, H, shift[1])
        m['lim_b'] = lim_b
        r = lim_b['reach']
        m['reach_b'] = [round(v, 2) for v in (W - r[2], H - r[3], W - r[0], H - r[1])]
        m['banned_b'] = [dict(b, poly=[[round(W - x, 2), round(H - y, 2)] for x, y in b['poly']]) for b in lim_b['banned']]
        m['fit_rects'] += [[round(v, 2) for v in (W - q[2], H - q[3], W - q[0], H - q[1])] for q in lim_b['rects']]
    else:
        m['lim_b'], m['reach_b'], m['banned_b'] = None, None, []
    return m


def _limits(m, mag, W, H, d):
    """
    Where the pen may draw on a sheet lying with its top edge d mm in front of
    the back of the bed (its left edge against the bed's left edge), in the
    sheet's own coordinates: dict(reach, banned, zones, rects).
    """
    ox, oy = m['offset_x'], m['offset_y']
    e = CLIP_EXTRA
    BED = m['bed_d']
    (sx0, sx1), (sy0, sy1) = m['safe_x'], m['safe_y']
    # inside the holder keep-out, and on the part of the sheet that lies on the bed
    reach = [max(0.0, sx0 + ox) + e, max(0.0, BED - d - (sy1 + oy)) + e,
             min(PAPER_W, W, sx1 + ox) - e, min(BED - d, H, BED - d - (sy0 + oy)) - e]
    reach = [round(v, 2) for v in reach]
    zones = magnets.zones(mag, d) if mag['height'] > 0 else []
    banned = []
    g = plotcheck.DRAW_MARGIN + e
    for l, t, r, b in zones:
        rect = [(l - g, t - g), (r + g, t - g), (r + g, b + g), (l - g, b + g)]
        if m['head_low']:
            # the nozzle and holder run from the pen back to the nozzle; when they are low, keep that whole
            # line off the magnet, which bans every pen position within the zone swept along the offset
            rect = rect + [(x + ox, y - oy) for x, y in rect]
        poly = _hull(rect)
        if _overlap(_bbox(poly), reach):
            banned.append(dict(poly=[[round(x, 2), round(y, 2)] for x, y in poly], head=m['head_low']))
    # biggest clear rectangles inside the reach (for "fit to the drawable area")
    rects = [tuple(reach)]
    for bpoly in banned:
        bb = _bbox(bpoly['poly'])
        nxt = []
        for r in rects:
            if not _overlap(r, bb):
                nxt.append(r)
                continue
            for c2 in ((r[0], r[1], r[2], bb[1]), (r[0], bb[3], r[2], r[3]), (r[0], r[1], bb[0], r[3]), (bb[2], r[1], r[2], r[3])):
                if c2[2] - c2[0] > 10 and c2[3] - c2[1] > 10:
                    nxt.append(c2)
        rects = nxt
    return dict(reach=reach, banned=banned, zones=[list(z) for z in zones], rects=[[round(v, 2) for v in r] for r in rects])


def set_machine(d):
    """Save pen / pad / magnet values typed on the page into the files the command-line tools use."""
    upd = {}
    if d.get('pen') not in (None, ''):
        P = float(d['pen'])
        if P - 0.5 < plotcheck.NOZZLE_FLOOR:
            raise ValueError('With the pen only {:g} mm below the nozzle, the nozzle would come within {:.1f} mm of the '
                             'paper. Push the pen further out of the holder (at least {:g} mm).'
                             .format(P, P - 0.5, plotcheck.NOZZLE_FLOOR + 0.5))
        if P > 40:
            raise ValueError('{:g} mm looks too long for the pen. Measure from the nozzle tip to the pen tip.'.format(P))
        upd['pen'] = P
    if d.get('surface') not in (None, ''):
        S = float(d['surface'])
        if not 0 <= S <= 60:
            raise ValueError('The pad under the paper should be between 0 and 60 mm thick.')
        upd['surface'] = S
    for k in ('offset_x', 'offset_y'):
        if d.get(k) not in (None, ''):
            upd[k] = float(d[k])
    if upd:
        calibrate.remember(**upd)
    mag = magnets.load()
    changed = False
    for k in ('magnet_size', 'magnet_height'):
        if d.get(k) not in (None, ''):
            v = float(d[k])
            if k == 'magnet_size' and not 5 <= v <= 60:
                raise ValueError('Magnet zones should be 5-60 mm.')
            if k == 'magnet_height' and not 0 <= v <= 30:
                raise ValueError('Magnet height should be 0-30 mm (0 switches the zones off).')
            mag[k.split('_')[1]] = v
            changed = True
    if changed:
        with open(magnets.FILE, 'w') as f:
            json.dump(mag, f, indent=1)


# sources: what an item is made of ----------------------------------------------
_sources = {}


def library():
    out = []
    for folder, where in ((BLUEPRINTS, 'blueprints'), (UPLOADS, 'uploaded')):
        if os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                if f.lower().endswith('.svg'):
                    out.append(dict(name=f, where=where, title=_title(f)))
    return out


def _title(fname):
    stem = os.path.splitext(fname)[0]
    stem = re.sub(r'^\d+_', '', stem)
    special = dict(spacex='SpaceX', nasa='NASA', csm='CSM', vw='VW', sr71='SR-71', dc3='DC-3', b58='B-58',
                   p51='P-51', c130j='C-130J', mir='Mir', svg='SVG')
    words = [special.get(w.lower(), w if w[:1].isupper() else w.capitalize()) for w in re.split(r'[_\s]+', stem) if w]
    return ' '.join(words)


def svg_file(name):
    name = os.path.basename(name or '')
    for folder in (UPLOADS, BLUEPRINTS):
        p = os.path.join(folder, name)
        if name.lower().endswith('.svg') and os.path.isfile(p):
            return p
    raise ValueError('Drawing not found: ' + name)


def save_upload(name, text):
    name = re.sub(r'[^\w\- .]+', '', os.path.basename(name or 'drawing.svg')).strip() or 'drawing.svg'
    if not name.lower().endswith('.svg'):
        name += '.svg'
    if '<svg' not in text[:5000].lower():
        raise ValueError(name + " doesn't look like an SVG file.")
    os.makedirs(UPLOADS, exist_ok=True)
    with open(os.path.join(UPLOADS, name), 'w', encoding='utf-8') as f:
        f.write(text)
    for k in [k for k in _sources if name in k]:
        _sources.pop(k, None)
    t = os.path.join(THUMBS, name + '.svg')
    if os.path.exists(t):
        os.remove(t)
    return name


def _circle(d, n=None):
    r = d/2.0
    n = n or max(24, min(720, int(math.pi*d/0.4)))
    t = np.linspace(0, 2*math.pi, n + 1)
    return [np.column_stack([r + r*np.cos(t), r + r*np.sin(t)])]


def _writing_lines(src):
    import engines
    args = (src.get('text', ''), src.get('style'), src.get('engine', 'model'), src.get('font'))
    lines, missing, _ = engines.render(*args)
    if missing:                       # the AI model hasn't written these lines yet: write them now (cached afterwards)
        engines.generate(*args)
        lines, missing, _ = engines.render(*args)
        if missing:
            raise ValueError('The AI model couldn\'t write {} line{} of this; try again.'.format(missing, '' if missing == 1 else 's'))
    return lines


def source(src):
    """
    The pen lines an item is made of, in its own units with the top-left of
    everything at (0, 0): dict(paths, groups, w0, h0, baseline, units, lo).
    groups: which line of writing each path belongs to (None for drawings), so
    a line of writing is never split between the two parts of a sheet.
    """
    key = json.dumps(src, sort_keys=True)
    with _lock:
        if key in _sources:
            return _sources[key]
    kind = src.get('kind')
    baseline, groups, units = None, None, 'mm'
    if kind == 'svg':
        paths, _ = svgplot.load(svg_file(src.get('name')))
        if not paths:
            raise ValueError('No lines found in {} (it may be all text or pictures).'.format(src.get('name')))
        units = 'svg'
    elif kind == 'writing':
        import model_engine as me
        lines = _writing_lines(src)
        if src.get('pick'):                        # a page: [[line number, baseline y], ...]
            pick = [(int(i), float(y)) for i, y in src['pick']]
        else:
            lh = me.settings(src.get('style'))['line_height']
            pick = [(i, i*lh) for i in range(len(lines))]
        paths, groups = [], []
        for i, y in pick:
            if 0 <= i < len(lines):
                for p in lines[i] or []:
                    paths.append(p + [0.0, y])
                    groups.append(i)
        baseline = pick[0][1] if pick else 0.0
        if not paths:
            raise ValueError('There is no text to write. Type some on the Write page first.')
    elif kind == 'label':
        import penfont
        handfont = penfont.get(src.get('face'))           # labels can use a font made from someone's handwriting
        size = max(1.0, min(30.0, float(src.get('size', 4.0))))
        style = handfont.Style(tidiness=max(0.0, min(1.0, float(src.get('tidiness', 0.9)))))
        paths, groups = [], []
        for i, t in enumerate((src.get('text') or '').split('\n')):
            if t.strip():
                for p in handfont.text_paths(t, 0.0, i*size*3.0, size, style=style):
                    paths.append(p)
                    groups.append(i)
        baseline = 0.0
        if not paths:
            raise ValueError('Type the label text first.')
    elif kind == 'rect':
        w, h = float(src.get('w', 100)), float(src.get('h', 60))
        paths = [np.array([[0, 0], [w, 0], [w, h], [0, h], [0, 0]], float)]
    elif kind == 'circle':
        paths = _circle(float(src.get('d', 60)))
    elif kind == 'lines':
        n, gap, w = int(src.get('count', 10)), float(src.get('gap', 8)), float(src.get('w', 160))
        paths = [np.array([[0, i*gap], [w, i*gap]], float) if i % 2 == 0 else np.array([[w, i*gap], [0, i*gap]], float)
                 for i in range(max(1, min(200, n)))]
    elif kind == 'calcross':
        paths = [np.array(p, float) for p in calibrate.cross(6.0, 6.0)]
    else:
        raise ValueError('Unknown item type: {}'.format(kind))
    keep = [k for k, p in enumerate(paths) if len(p) > 1]
    paths = [np.asarray(paths[k], float) for k in keep]
    if groups is not None:
        groups = [groups[k] for k in keep]
    allp = np.concatenate(paths)
    lo = allp.min(axis=0)
    w0, h0 = (allp.max(axis=0) - lo).tolist()
    out = dict(paths=[p - lo for p in paths], groups=groups, w0=w0, h0=h0, units=units, lo=lo.tolist(),
               baseline=(baseline - lo[1]) if baseline is not None else None)
    with _lock:
        _sources[key] = out
        while len(_sources) > 60:
            _sources.pop(next(iter(_sources)))
    return out


def preview(src, detail=2500):
    """Light version of a source for drawing on the page: flat [x, y, x, y, ...] lists."""
    s = source(src)
    tol = max(s['w0'], s['h0'], 1e-6)/detail
    flat = []
    for p in _simplify_list(s['paths'], tol):
        flat.append([round(float(v), 3) for v in p.ravel()])
    return dict(w0=s['w0'], h0=s['h0'], baseline=s['baseline'], units=s['units'], count=len(s['paths']), paths=flat)


def warm_thumbs(delay=20.0):
    """Make any missing library pictures in the background, so the Add drawing window opens quickly."""
    time.sleep(delay)
    for d in library():
        try:
            thumb(d['name'])
        except Exception:
            pass


def thumb(name):
    """A small SVG picture of a library drawing (cached on disk)."""
    os.makedirs(THUMBS, exist_ok=True)
    path = os.path.join(THUMBS, os.path.basename(name) + '.svg')
    src_path = svg_file(name)
    if os.path.exists(path) and os.path.getmtime(path) >= os.path.getmtime(src_path):
        with open(path, 'rb') as f:
            return f.read()
    s = source(dict(kind='svg', name=os.path.basename(name)))
    w0, h0 = s['w0'], s['h0']
    k = 200.0/max(w0, h0, 1e-6)
    d = []
    for p in _simplify_list(s['paths'], max(w0, h0)/400.0):
        q = p*k
        d.append('M' + ' '.join('{:.1f} {:.1f}'.format(x, y) for x, y in q))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-4 -4 {:.1f} {:.1f}"><path d="{}" fill="none" '
           'stroke="#26304f" stroke-width="0.7" stroke-linecap="round" stroke-linejoin="round"/></svg>'
           .format(w0*k + 8, h0*k + 8, ' '.join(d)))
    data = svg.encode('utf-8')
    with open(path, 'wb') as f:
        f.write(data)
    return data


# geometry -------------------------------------------------------------------
def _simplify_list(paths, tol, with_index=False):
    """Drop points within `tol` of the previous one (vectorised over all paths at once)."""
    if not paths:
        return ([], []) if with_index else []
    lens = np.array([len(p) for p in paths])
    allp = np.concatenate(paths)
    q = np.floor(allp/tol).astype(np.int64)
    starts = np.zeros(len(allp), bool)
    starts[np.concatenate([[0], np.cumsum(lens)[:-1]])] = True
    ends = np.zeros(len(allp), bool)
    ends[np.cumsum(lens) - 1] = True
    same = np.zeros(len(allp), bool)
    same[1:] = (q[1:] == q[:-1]).all(axis=1)
    keep = starts | ends | ~same
    out, idx = [], []
    cuts = np.cumsum(lens)[:-1]
    for k, (p, kk) in enumerate(zip(np.split(allp, cuts), np.split(keep, cuts))):
        p = p[kk]
        if len(p) > 1:
            out.append(p)
            idx.append(k)
    return (out, idx) if with_index else out


def place(item):
    """An item's paths on the sheet in mm, and which group (line of writing) each belongs to."""
    s = source(item['src'])
    w0, h0 = s['w0'], s['h0']
    w = float(item.get('w') or w0)
    sx = w/w0 if w0 > 1e-9 else 1.0
    h = float(item.get('h') or h0*sx)
    sy = h/h0 if h0 > 1e-9 else sx
    if w0 <= 1e-9:
        sx = sy
    fx = -1.0 if item.get('flip') else 1.0
    th = math.radians(float(item.get('rot', 0.0)))
    c, si = math.cos(th), math.sin(th)
    cx, cy = float(item.get('cx', 105.0)), float(item.get('cy', 130.0))
    lens = [len(p) for p in s['paths']]
    allp = np.concatenate(s['paths'])
    u = (allp[:, 0] - w0/2)*sx*fx
    v = (allp[:, 1] - h0/2)*sy
    out = np.column_stack([cx + u*c - v*si, cy + u*si + v*c])
    return np.split(out, np.cumsum(lens)[:-1]), s['groups']


def _halfplanes(poly):
    """Convex counter-clockwise polygon -> list of (n, c) with inside meaning n.p <= c."""
    hp = []
    for i in range(len(poly)):
        a, b = np.array(poly[i], float), np.array(poly[(i + 1) % len(poly)], float)
        e = b - a
        n = np.array([e[1], -e[0]])
        hp.append((n, float(n @ a)))
    return hp


def _intervals(A, D, hp):
    """For segments A + t*D, t in [0, 1]: the part [t0, t1] inside a convex region (empty when t0 >= t1)."""
    t0 = np.zeros(len(A))
    t1 = np.ones(len(A))
    for n, c in hp:
        num = c - A @ n
        den = D @ n
        with np.errstate(divide='ignore', invalid='ignore'):
            r = num/den
        pos, neg = den > 1e-12, den < -1e-12
        t1 = np.where(pos, np.minimum(t1, r), t1)
        t0 = np.where(neg, np.maximum(t0, r), t0)
        t1 = np.where(~pos & ~neg & (num < 0), -1.0, t1)
    return t0, t1


def _push(lst, src, poly, i):
    if poly is not None and len(poly) > 1:
        lst.append(np.array(poly))
        src.append(i)


def clip(paths, lim):
    """
    Split paths into what lies inside the drawable area (and outside the banned
    polygons) and what doesn't. Returns dict(kept, kept_src, cut, cut_src, ok,
    kept_len, cut_len): *_src give the input path each piece came from, ok[i]
    is True when path i is entirely drawable.
    """
    n = len(paths)
    res = dict(kept=[], kept_src=[], cut=[], cut_src=[], ok=np.ones(n, bool), kept_len=0.0, cut_len=0.0)
    if not n:
        return res
    x0, y0, x1, y1 = lim['reach']
    region = _halfplanes(_hull([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))
    bans = [_halfplanes([tuple(p) for p in b['poly']]) for b in lim['banned']]
    lens = np.array([len(p) for p in paths])
    allp = np.concatenate(paths)
    offs = np.concatenate([[0], np.cumsum(lens)])
    seg_ok = np.ones(len(allp), bool)
    seg_ok[offs[1:] - 1] = False                  # the last point of each path starts no segment
    si = np.flatnonzero(seg_ok)
    A, B = allp[si], allp[si + 1]
    D = B - A
    r0, r1 = _intervals(A, D, region)
    r0, r1 = np.clip(r0, 0, 1), np.clip(r1, 0, 1)
    full = (r0 <= 1e-9) & (r1 >= 1 - 1e-9)
    bint = []
    for hp in bans:
        b0, b1 = _intervals(A, D, hp)
        b0, b1 = np.clip(b0, 0, 1), np.clip(b1, 0, 1)
        hit = b1 > b0 + 1e-12
        full &= ~hit
        bint.append((b0, b1, hit))
    total = float(np.hypot(D[:, 0], D[:, 1]).sum())
    path_of = np.searchsorted(offs, si, side='right') - 1
    bad = np.unique(path_of[~full])
    ok = np.ones(n, bool)
    ok[bad] = False
    kept, kept_src, cut, cut_src = [], [], [], []
    for i in np.flatnonzero(ok):
        kept.append(paths[i])
        kept_src.append(int(i))
    segs_of = {}
    for j in np.flatnonzero(np.isin(path_of, bad)):
        segs_of.setdefault(int(path_of[j]), []).append(int(j))

    def allowed(j):
        lo, hi = float(r0[j]), float(r1[j])
        if hi <= lo + 1e-12:
            return []
        ivs = [(lo, hi)]
        for b0, b1, hit in bint:
            if not hit[j]:
                continue
            c0, c1 = float(b0[j]), float(b1[j])
            nxt = []
            for s0, s1 in ivs:
                if c1 <= s0 or c0 >= s1:
                    nxt.append((s0, s1))
                    continue
                if c0 > s0:
                    nxt.append((s0, c0))
                if c1 < s1:
                    nxt.append((c1, s1))
            ivs = nxt
        return [(s0, s1) for s0, s1 in ivs if s1 - s0 > 1e-9]

    eps = 1e-9
    for pi, segs in segs_of.items():
        cur = cc = None                            # the drawable piece / the cut piece being built
        for j in segs:
            a, d, b = A[j], D[j], B[j]
            if full[j]:
                _push(cut, cut_src, cc, pi)
                cc = None
                if cur is None:
                    cur = [a]
                cur.append(b)
                continue
            pos = 0.0
            for s0, s1 in allowed(j):
                if s0 > pos + eps:                 # a cut piece before this drawable piece
                    _push(kept, kept_src, cur, pi)
                    cur = None
                    if pos <= eps and cc is not None:
                        cc.append(a + d*s0)
                    else:
                        _push(cut, cut_src, cc, pi)
                        cc = [a + d*pos, a + d*s0]
                _push(cut, cut_src, cc, pi)
                cc = None
                if s0 <= eps and cur is not None:
                    cur.append(a + d*s1)
                else:
                    _push(kept, kept_src, cur, pi)
                    cur = [a + d*s0, a + d*s1]
                if s1 < 1 - eps:
                    _push(kept, kept_src, cur, pi)
                    cur = None
                pos = s1
            if pos < 1 - eps:
                _push(kept, kept_src, cur, pi)
                cur = None
                if pos <= eps and cc is not None:
                    cc.append(b)
                else:
                    _push(cut, cut_src, cc, pi)
                    cc = [a + d*pos, b]
        _push(kept, kept_src, cur, pi)
        _push(cut, cut_src, cc, pi)
    cut_len = float(sum(path_length(c) for c in cut))
    res.update(kept=kept, kept_src=kept_src, cut=cut, cut_src=cut_src, ok=ok, kept_len=total - cut_len, cut_len=cut_len)
    return res


def _assign(placed, groups, mach, two_pass):
    """
    Share an item's paths between part A (sheet as normal) and part B (sheet
    turned round). Whole lines of writing / whole strokes go where they fit
    completely, A first; anything that fits neither is split, and what neither
    part can reach is returned as cut. All in sheet coordinates.
    """
    W, H = mach['paper']
    ca = clip(placed, mach['lim_a'])
    if not two_pass:
        return ca['kept'], [], ca['cut']
    cb = clip([flip(p, W, H) for p in placed], mach['lim_b'])
    by = {}
    for k, g in enumerate(groups):
        by.setdefault(g, []).append(k)
    a, b, mixed = [], [], set()
    for g, ks in by.items():
        if ca['ok'][ks].all():
            a += [placed[k] for k in ks]
        elif cb['ok'][ks].all():
            b += [placed[k] for k in ks]
        else:
            mixed.update(ks)
    cut = []
    if mixed:
        a += [p for p, k in zip(ca['kept'], ca['kept_src']) if k in mixed]
        left = [p for p, k in zip(ca['cut'], ca['cut_src']) if k in mixed]
        if left:
            cl = clip([flip(p, W, H) for p in left], mach['lim_b'])
            b += [flip(p, W, H) for p in cl['kept']]
            cut += [flip(p, W, H) for p in cl['cut']]
    return a, b, cut


def _rect_ok(rect, lim):
    """Is an axis-aligned rectangle (sheet as it lies) inside the drawable area and clear of every banned polygon?"""
    r = lim['reach']
    if rect[0] < r[0] or rect[1] < r[1] or rect[2] > r[2] or rect[3] > r[3]:
        return False
    box = [(rect[0], rect[1]), (rect[2], rect[1]), (rect[2], rect[3]), (rect[0], rect[3])]
    return not any(_convex_overlap(box, [tuple(p) for p in b['poly']]) for b in lim['banned'])


def _convex_overlap(P, Q):
    for poly in (P, Q):
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            nx, ny = b[1] - a[1], a[0] - b[0]
            pp = [nx*x + ny*y for x, y in P]
            qq = [nx*x + ny*y for x, y in Q]
            if max(pp) < min(qq) or max(qq) < min(pp):
                return False
    return True


def path_length(p):
    return float(np.hypot(*np.diff(p, axis=0).T).sum()) if len(p) > 1 else 0.0


def order(paths, start):
    """Greedy nearest-neighbour order over both ends of every path (reversing when shorter)."""
    n = len(paths)
    if n < 2:
        return list(paths)
    ends = np.array([p[0] for p in paths] + [p[-1] for p in paths])
    used = np.zeros(n, bool)
    alive = np.arange(2*n)
    tree = cKDTree(ends)
    since = 0
    out, pos = [], np.asarray(start, float)
    for _ in range(n):
        k = 8
        pick = None
        while pick is None:
            kk = min(k, len(alive))
            _, idx = tree.query(pos, k=kk)
            for t in np.atleast_1d(idx):
                e = int(alive[t])
                if not used[e % n]:
                    pick = e
                    break
            if pick is None:
                if kk >= len(alive):
                    break
                k *= 4
        if pick is None:
            break
        i = pick % n
        used[i] = True
        since += 1
        p = paths[i] if pick < n else paths[i][::-1]
        out.append(p)
        pos = p[-1]
        if since > len(alive)//4 and since > 64:             # rebuild the tree without the used ends
            alive = np.array([e for e in range(2*n) if not used[e % n]])
            if len(alive) == 0:
                break
            tree = cKDTree(ends[alive])
            since = 0
    return out


def reading_order(lines):
    """
    Lines of writing as they lie on the sheet -> strokes in reading order: lines
    top to bottom, and inside a line left to right (by where each stroke starts
    on the left), so dots, accents and crossbars follow their own letter. The
    pen keeps the direction each stroke was written in.
    """
    out = []
    for _, _, paths in sorted(lines, key=lambda l: (l[0], l[1])):
        out += sorted(paths, key=lambda p: float(p[:, 0].min()))
    return out


def _text_line(paths):
    """(y, x, paths): where a line of writing sits on the sheet, for reading_order."""
    pts = np.concatenate(paths)
    return (float(np.median(pts[:, 1])), float(pts[:, 0].min()), paths)


def join(paths, tol=0.05):
    """Merge a path into the previous one when it starts where that one ended (no pen lift)."""
    out = []
    for p in paths:
        if out and np.hypot(*(p[0] - out[-1][-1])) <= tol:
            out[-1] = np.vstack([out[-1], p[1:]])
        else:
            out.append(p)
    return out


# planning -----------------------------------------------------------------------
PART_NAMES = dict(a='part 1', b='part 2 (sheet turned round)')


def _key(state):
    c = calibrate.recall()
    blob = json.dumps([state.get('items', []), settings(state.get('settings')), paper_of(state), two_pass_of(state),
                       shift_of(state), c, magnets.load(), printers.current()], sort_keys=True)
    return hashlib.sha1(blob.encode('utf-8')).hexdigest()


_plans = {}          # key -> plan (latest few)
_checks = {}         # key -> check result


def _remember(cache, key, value, keep=6):
    with _lock:
        cache[key] = value
        while len(cache) > keep:
            cache.pop(next(iter(cache)))


def _flat(paths, tol, limit=150000):
    out, n = [], 0
    for p in _simplify_list(paths, tol):
        out.append([round(float(v), 2) for v in p.ravel()])
        n += len(p)
        if n > limit:
            break
    return out


def plan(state):
    """Lay out every visible item of one sheet, share it between the parts, trim it and order the strokes."""
    key = _key(state)
    with _lock:
        if key in _plans:
            return _plans[key]
    s = settings(state.get('settings'))
    W, H = paper_of(state)
    tp = two_pass_of(state)
    mach = machine(s, (W, H), tp, shift_of(state))
    items, parts, problems, warnings = {}, dict(a=[], b=[]), list(mach['problems']), []
    text = dict(a=[], b=[])          # lines of writing, kept whole: written in reading order, not nearest-first
    for it in state.get('items', []):
        iid = str(it.get('id'))
        if it.get('hidden'):
            items[iid] = dict(hidden=True)
            continue
        try:
            raw, groups = place(it)
            is_text = groups is not None
            placed, idx = _simplify_list(raw, SIMPLIFY_MM, with_index=True)
            groups = [groups[k] for k in idx] if groups is not None else list(range(len(placed)))
        except (ValueError, KeyError, RuntimeError) as e:
            items[iid] = dict(error=str(e))
            problems.append('{}: {}'.format(it.get('name') or 'An item', e))
            continue
        if is_text:                      # one line at a time, so each part knows its lines
            a, b, cut = [], [], []
            for g in dict.fromkeys(groups):
                mine = [p for p, gg in zip(placed, groups) if gg == g]
                la_, lb_, lc_ = _assign(mine, [g]*len(mine), mach, tp)
                a += la_
                b += lb_
                cut += lc_
                for k_, got in (('a', la_), ('b', lb_)):
                    if got:
                        text[k_].append(_text_line(got))
        else:
            a, b, cut = _assign(placed, groups, mach, tp)
        la, lb = sum(path_length(p) for p in a), sum(path_length(p) for p in b)
        lc = sum(path_length(p) for p in cut)
        total = la + lb + lc
        items[iid] = dict(length=round(la + lb), part_b=round(lb), cut=round(lc, 1),
                          cut_pct=round(100.0*lc/total, 1) if total > 0 else 0.0, cut_paths=_flat(cut, 0.1, 20000))
        if lc > 0.05:
            warnings.append('{}: {:.0f} mm of line ({:.0f}%) can\'t be reached and will be skipped (shown in red).'
                            .format(it.get('name') or 'An item', lc, max(1, items[iid]['cut_pct'])))
        if not is_text:
            parts['a'] += a
            parts['b'] += b
    min_len = s['min_stroke']
    out_parts, strokes_by_part, dropped = {}, {}, 0
    for k in ('a', 'b'):
        keep = (lambda ps: [p for p in ps if path_length(p) >= min_len]) if min_len > 0 else (lambda ps: list(ps))
        lines = [(y, x, keep(ps)) for y, x, ps in text[k]]
        words = reading_order([l for l in lines if l[2]])             # writing first, line by line, left to right
        rest = keep(parts[k])
        dropped += (len(parts[k]) - len(rest)) + sum(len(ps) for _, _, ps in text[k]) - len(words)
        r = (mach['lim_b'] if k == 'b' and mach['lim_b'] else mach['lim_a'])['reach']
        start = ((r[0] + r[2])/2, (r[1] + r[3])/2)
        if k == 'b':
            start = (W - start[0], H - start[1])
        st = words + order(rest, words[-1][-1] if words else start)    # then drawings, nearest-first
        if s['join'] >= 0.5:
            st = join(st)
        strokes_by_part[k] = st
        if not st:
            continue
        draw = sum(path_length(p) for p in st)
        travel = sum(float(np.hypot(*(q[0] - p[-1]))) for p, q in zip(st[:-1], st[1:]))
        allp = np.concatenate(st)
        out_parts[k] = dict(strokes=len(st), draw_mm=round(draw), travel_mm=round(travel),
                            points=int(len(allp)), seconds=round(_seconds(st, draw, travel, s, mach)),
                            bounds=[round(float(v), 1) for v in (*allp.min(axis=0), *allp.max(axis=0))])
    stats = dict(strokes=sum(p['strokes'] for p in out_parts.values()), draw_mm=sum(p['draw_mm'] for p in out_parts.values()),
                 seconds=sum(p['seconds'] for p in out_parts.values()), dropped=dropped, parts=out_parts)
    if not stats['strokes'] and not problems:
        problems.append('Nothing to plot on this sheet yet: add a drawing, some handwriting or a label.')
    res = dict(key=key, machine=mach, settings=s, items=items, stats=stats, problems=problems, warnings=warnings,
               pass_b=_flat(strokes_by_part['b'], 0.2), _parts=strokes_by_part)
    _remember(_plans, key, res, keep=10)
    return res


def _seconds(strokes, draw, travel, s, mach):
    if not strokes or mach.get('z_lift') is None:
        return 0.0
    z = 2*s['lift']*len(strokes) + 2*(mach['z_start'] - mach['z_draw'])
    pts = sum(len(p) for p in strokes)
    return (draw/(s['draw_speed']/60) + travel/(s['travel_speed']/60) + z/(s['z_speed']/60) +
            len(strokes)*s['dwell_ms']/1000.0 + pts*0.001 + len(strokes)*0.15)


def public(res, with_strokes=False, with_travel=False):
    out = {k: v for k, v in res.items() if not k.startswith('_')}
    if with_strokes:
        out['strokes'] = {k: _flat(st, 0.15, 400000) for k, st in res['_parts'].items()}
    if with_travel:
        out['travel'] = [[round(float(a[-1][0]), 2), round(float(a[-1][1]), 2), round(float(b[0][0]), 2),
                          round(float(b[0][1]), 2)] for st in res['_parts'].values() for a, b in zip(st[:-1], st[1:])]
    return out


# G-code -----------------------------------------------------------------------
def nozzle_xy(p, mach, d=0.0):
    """Pen position (sheet coordinates of the sheet as it lies, top edge d mm in front of the back of the bed) -> nozzle bed coordinates."""
    return p[:, 0] - mach['offset_x'], (mach['bed_d'] - d - p[:, 1]) - mach['offset_y']


def gcode(strokes, mach, s, part='a'):
    W, H = mach['paper']
    d = mach['shift'][1 if part == 'b' else 0]
    if part == 'b':
        strokes = [flip(p, W, H) for p in strokes]
    zf, tf, df = s['z_speed'], s['travel_speed'], s['draw_speed']
    prof = printers.current()
    g = ['; Made by the InkPlot Plotter for {} with a pen holder.'.format(prof['name']),
         plotcheck.stamp_line(),
         '; Pen offset X{:.2f} Y{:.2f} (pen = nozzle + offset), pen {:g} mm below the nozzle, {:g} mm pad.'.format(
             mach['offset_x'], mach['offset_y'], mach['pen'], mach['surface']),
         '; Pen down Z{:.2f}, up Z{:.2f}. Paper: A4 portrait, left edge against the left side of the bed{}.'.format(
             mach['z_draw'], mach['z_lift'], ', TURNED ROUND (top edge at the front)' if part == 'b' else ''),
         '; paper shift: {:g} mm (the sheet\'s top edge is {:g} mm in front of the back edge of the bed, its left edge against the left side)'.format(d, d),
         '; Home from the printer screen BEFORE clipping on the holder. Never home with it attached.',
         'G90', 'G21'] + printers.start_lines(prof) + [
         'G1 Z{:.3f} F{:.0f} ; high enough to clear the magnets'.format(mach['z_start'], zf), 'G4 P120']
    for p in strokes:
        X, Y = nozzle_xy(p, mach, d)
        g.append('G0 X{:.3f} Y{:.3f} F{:.0f}'.format(X[0], Y[0], tf))
        g.append('G1 Z{:.3f} F{:.0f}'.format(mach['z_draw'], zf))
        if s['dwell_ms'] >= 1:
            g.append('G4 P{:.0f}'.format(s['dwell_ms']))
        g.extend('G1 X{:.3f} Y{:.3f} F{:.0f}'.format(x, y, df) for x, y in zip(X[1:], Y[1:]))
        g.append('G1 Z{:.3f} F{:.0f}'.format(mach['z_lift'], zf))
    g.append('G1 Z{:.3f} F{:.0f}'.format(mach['z_lift'] + 10, zf))
    return g + printers.end_lines(prof)


def checked(state):
    """Build the G-code for each part of the sheet and run plotcheck's checks on it. Cached per layout."""
    res = plan(state)
    key = res['key']
    with _lock:
        if key in _checks:
            return _checks[key]
    errors = list(res['problems'])
    parts, gc, hops_all = [], {}, 0
    if not errors:
        mach, s = res['machine'], res['settings']
        two = sum(1 for st in res['_parts'].values() if st) > 1
        for k in ('a', 'b'):
            st = res['_parts'][k]
            if not st:
                continue
            lines = gcode(st, mach, s, k)
            errs, info = plotcheck.check(lines)
            hops = 0
            d = mach['shift'][1 if k == 'b' else 0]
            if not errs:
                errs += plotcheck.on_paper(lines, d)
                lines, hops, mag_errors, _ = plotcheck.avoid_magnets(lines, d)
                errs += mag_errors
            if not errs:
                lines.append('; plotcheck: checked for {} by the Plotter; ends here with the pen lifted - '
                             'remove the holder before homing'.format(mach['printer']['name']))
            seconds = res['stats']['parts'][k]['seconds']
            if hops and mach.get('z_hop'):
                seconds += hops*2*(mach['z_hop'] - mach['z_lift'])/(s['z_speed']/60)
            parts.append(dict(part=k, ok=not errs, errors=errs, warnings=list(info.get('warnings', [])), hops=hops,
                              seconds=round(seconds), strokes=len(st)))
            gc[k] = lines
            hops_all += hops
            errors += [('{}: '.format(PART_NAMES[k].capitalize()) if two else '') + e for e in errs]
    out = dict(key=key, ok=not errors and bool(parts), errors=errors, parts=parts, hops=hops_all,
               seconds=sum(p['seconds'] for p in parts), warnings=[w for p in parts for w in p['warnings']], _gcode=gc)
    _remember(_checks, key, out, keep=8)
    return out


def dry(lines):
    """The same moves with every height raised DRY_LIFT mm: a pen-up rehearsal."""
    up = []
    for line in lines:
        if plotcheck.MOVE.match(line.split(';', 1)[0].strip()):
            line = re.sub(r'\bZ(-?[\d.]+)', lambda m: 'Z{:.3f}'.format(float(m.group(1)) + DRY_LIFT), line)
        up.append(line)
    return ['; PEN-UP REHEARSAL: every height raised {:.0f} mm, the pen never touches the paper'.format(DRY_LIFT)] + up


def outline(res, part='a'):
    """Pen up, well clear of the magnets: trace the rectangle around one part of the drawing, pausing at each corner."""
    mach, s = res['machine'], res['settings']
    b = res['stats']['parts'].get(part, {}).get('bounds')
    if not b:
        raise ValueError('Nothing to trace.')
    x0, y0, x1, y1 = b
    box = np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])
    if part == 'b':
        box = flip(box, *mach['paper'])
    d = mach['shift'][1 if part == 'b' else 0]
    X, Y = nozzle_xy(box, mach, d)
    z = max(mach['z_start'], mach['z_lift'] + 3)
    g = ['; Outline trace: the pen stays up and slowly goes round the drawing', plotcheck.stamp_line(),
         '; paper shift: {:g} mm'.format(d),
         '; Home from the printer screen BEFORE clipping on the holder. Never home with it attached.',
         'G90', 'G21'] + printers.start_lines() + ['G1 Z{:.3f} F{:.0f}'.format(z, s['z_speed']), 'G4 P300']
    for x, y in zip(X, Y):
        g += ['G0 X{:.3f} Y{:.3f} F3000'.format(x, y), 'G4 P1200']
    g += ['G1 Z{:.3f} F{:.0f}'.format(z + 10, s['z_speed'])] + printers.end_lines() + ['; done - remove the holder before homing']
    return g


# a whole page of writing ------------------------------------------------------------
def lined_of(req, W, H):
    """
    The ruled area of lined paper, from the measurements typed on the page:
    first = first line, mm below the top edge; bottom = last line, mm above the
    bottom edge; left = margin line, mm from the left edge; right = where the
    lines end, mm from the right edge; gap = line spacing.
    """
    L = req.get('lined') or {}

    def num(k, default):
        try:
            return float(L[k]) if L.get(k) not in (None, '') else default
        except (TypeError, ValueError):
            return default
    gap = max(3.0, num('gap', float(req.get('gap', 8) or 8)))
    first = num('first', float(req.get('first', 20) or 20))
    last = H - num('bottom', H - float(req.get('last', H - 30) or (H - 30)))
    left = num('left', float(req.get('margin', 15) or 15))
    right = num('right', None)
    return dict(first=first, last=last, left=left, right=right, gap=gap,
                rows=int(max(0, (last - first)//gap + 1)) if last >= first else 0)


def placement(req, ext_top=None, ext_bottom=None):
    """
    Where to put the sheet so the pen can reach every ruled line, and in how
    many parts. The pen can't reach the back ~37 mm of the bed, so if the first
    line is near the top edge the sheet goes that much further forward for part
    1; the bottom lines are written in part 2 with the sheet turned round (and
    moved forward too if they're very close to the bottom edge).
    ext_top / ext_bottom: how far the writing reaches above / below its line (mm).
    """
    s = settings(req.get('settings'))
    W, H = paper_of(req)
    tp = two_pass_of(req)
    L = lined_of(req, W, H)
    if not L['rows']:
        raise ValueError('There are no ruled lines between the first line and the last one: check the measurements.')
    base = machine(s, (W, H), tp)
    if not base['has_offset']:
        raise ValueError('Calibrate the pen offset first, so the paper can be placed where the pen can reach.')
    top0 = base['lim_a']['reach'][1]                      # the nearest the pen gets to the top edge, sheet in the corner
    above = -ext_top if ext_top is not None else 0.92*L['gap']      # tall letters and capitals above the line
    below = ext_bottom if ext_bottom is not None else 0.65*L['gap']    # tails below it
    top_need, bottom_need = L['first'] - above, L['last'] + below
    slack = 1.0                                           # a little room so the tallest letters aren't on the limit
    d_a = float(max(0, math.ceil(top0 - top_need + slack)))
    d_b = float(max(0, math.ceil(top0 - (H - bottom_need) + slack))) if tp else 0.0
    m = machine(s, (W, H), tp, (d_a, d_b))
    ra = m['lim_a']['reach']
    cover = [[ra[1], ra[3]]]
    if tp:
        rb = m['reach_b']
        cover.append([rb[1], rb[3]])
    rows = [L['first'] + k*L['gap'] for k in range(L['rows'])]

    def reachable(y):
        return any(c[0] <= y - above and y + below <= c[1] for c in cover)
    lost = [round(y, 1) for y in rows if not reachable(y)]
    need_b = tp and any(not (ra[1] <= y - above and y + below <= ra[3]) for y in rows)
    right_x = W - L['right'] if L['right'] is not None else None
    # lines whose writing would run into a corner magnet (full-width line, tall letters and tails)
    x1w = min(right_x if right_x is not None else ra[2], ra[2])
    if need_b:
        x1w = min(x1w, m['reach_b'][2])
    x0w, x1w = L['left'] + 1.5, x1w - 3.0          # writing is wrapped a few mm short of the end of the lines
    magnet_rows = []
    for y in rows:
        rect = [x0w - 0.3, y - above - 0.3, x1w + 0.3, y + below + 0.3]
        in_a = ra[1] <= rect[1] and rect[3] <= ra[3]
        in_b = tp and m['reach_b'][1] <= rect[1] and rect[3] <= m['reach_b'][3]
        ok = (in_a and _rect_ok(rect, m['lim_a'])) or (
            in_b and _rect_ok([W - rect[2], H - rect[3], W - rect[0], H - rect[1]], m['lim_b']))
        if not ok and (in_a or in_b):
            magnet_rows.append(round(y, 1))
    warnings = []
    if magnet_rows:
        warnings.append('The line{} at {} mm {} too close to a corner magnet: tall letters or tails would come within '
                        '{:g} mm of it, so {} left empty. To use {}, move that magnet in from the corner a little and make '
                        'the corner zones smaller in the Magnets card.'.format(
                            '' if len(magnet_rows) == 1 else 's', ', '.join('{:g}'.format(y) for y in magnet_rows),
                            'is' if len(magnet_rows) == 1 else 'are', plotcheck.DRAW_MARGIN,
                            'it is' if len(magnet_rows) == 1 else 'they are', 'it' if len(magnet_rows) == 1 else 'them'))
    if lost:
        warnings.append('{} ruled line{} can\'t be reached ({} mm from the top){}.'.format(
            len(lost), '' if len(lost) == 1 else 's', ', '.join('{:g}'.format(y) for y in lost[:6]) + ('…' if len(lost) > 6 else ''),
            '' if tp else '; turn on "Turn the sheet round" to reach the bottom ones'))
    if L['left'] + 1 < ra[0]:
        warnings.append('The margin is only {:g} mm from the left edge; the pen can\'t get closer than {:.0f} mm.'.format(L['left'], ra[0]))
    if right_x is not None and need_b and right_x > m['reach_b'][2] + 1:
        warnings.append('The lines end only {:g} mm from the right edge; with the sheet turned round the pen can\'t get '
                        'closer than {:.0f} mm, so the writing will stop a little short there.'.format(L['right'], W - m['reach_b'][2]))

    def where(d, turned):
        edge = 'bottom edge (now at the back)' if turned else 'top edge'
        if d <= 0:
            return 'push it right into the back-left corner of the bed, {} against the back.'.format(edge)
        return ('put its left edge against the left side of the bed and slide it forward until its {} is {:g} mm in front of '
                'the back edge of the bed. Measure at both ends so it sits square.'.format(edge, d))
    steps = ['Part 1: sheet the normal way round (top edge towards the back): ' + where(d_a, False)]
    if need_b:
        steps.append('Part 2: take the sheet out and turn it round so its top edge is towards the front, then ' + where(d_b, True))
    dia = magnets.load().get('diameter', 10.0)

    def magnet_step(d, part):
        if d >= dia/2:
            back = 'one at each back corner, centred on the sheet\'s back edge: half on the sheet, half on the bed behind it'
        elif d > 0:
            back = 'one at each back corner, pushed against the back of the bed so it overlaps the sheet\'s edge'
        else:
            back = 'one on each of the sheet\'s back corners'
        return 'Magnets{}: {}; two more on the front edge of the bed.'.format(part, back)
    if need_b and d_b != d_a:
        steps.append(magnet_step(d_a, ' for part 1'))
        steps.append(magnet_step(d_b, ' for part 2'))
    else:
        steps.append(magnet_step(d_a, ''))
    why = []
    if d_a > 0:
        why.append('The pen can\'t reach the back {:.0f} mm of the bed and your first line is {:g} mm from the top, so the '
                   'sheet goes {:g} mm forward.'.format(top0, L['first'], d_a))
    if need_b:
        why.append('The bottom lines are out of reach with the sheet that way round, so they are written after turning it.')
    return dict(shift=dict(a=d_a, b=d_b if need_b else 0.0), two_parts=bool(need_b), steps=steps, why=why,
                warnings=warnings, rows=len(rows), lost=lost, magnet_rows=magnet_rows, lined=L)


def pages(req):
    """
    Flow the Write page's text onto the ruled lines, sheet after sheet, with the
    sheet placed (and turned) as placement() says. A line goes on the next ruled
    line where the pen can write all of it; lines it can't reach are left empty.
    Returns dict(sheets=[dict(items=[...])], shift, placement, ...).

    after_y: carry on below writing already on the first sheet (its lowest ink, mm
    from the top): the first sheet returned only holds what goes under it, and may
    be empty. keep_shift: the sheet positions already in use ({'a', 'b'}); the new
    writing never asks for less, so earlier writing stays where it was planned.
    """
    import engines
    import model_engine as me
    W, H = paper_of(req)
    L = lined_of(req, W, H)
    style = dict(me.settings(req.get('style')))
    margin = L['left'] + 1.5
    # wrap between the margin and the line ends, and no further right than the pen reaches in either part
    first_go = placement(req)
    m0 = machine(settings(req.get('settings')), (W, H), two_pass_of(req), (first_go['shift']['a'], first_go['shift']['b']))
    right_x = m0['lim_a']['reach'][2]
    if first_go['two_parts']:
        right_x = min(right_x, m0['reach_b'][2])
    if L['right'] is not None:
        right_x = min(right_x, W - L['right'])
    if L['right'] is not None or right_x - margin < style['max_width']:
        style['max_width'] = max(30.0, right_x - margin - 6.0)    # wrapped lines can run a few mm past the wrap width
    src = dict(kind='writing', text=req.get('text', ''), style=style,
               engine=engines.engine_of(req.get('engine')), font=engines.font_settings(req.get('font')))
    if not src['text'].strip():
        raise ValueError('There is no text to write. Type some on the Write page first.')
    lines, missing, _ = engines.render(src['text'], style, src['engine'], src['font'])
    if missing:                                    # new line breaks: let the AI model write those lines now
        engines.generate(src['text'], style, src['engine'], src['font'])
        lines, missing, _ = engines.render(src['text'], style, src['engine'], src['font'])
        if missing:
            raise ValueError('The AI model couldn\'t write {} line(s); try again.'.format(missing))
    ext = []
    for line in lines:
        if not line:
            ext.append(None)
            continue
        pts = np.concatenate(line)
        ext.append((float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())))
    real = [e for e in ext if e]
    if not real:
        raise ValueError('There is no text to write.')
    plc = placement(req, min(e[1] for e in real), max(e[3] for e in real))
    keep = req.get('keep_shift') or {}
    for k in ('a', 'b'):
        try:
            plc['shift'][k] = max(plc['shift'][k], float(keep.get(k) or 0))
        except (TypeError, ValueError):
            pass
    s = settings(req.get('settings'))
    tp = two_pass_of(req)
    mach = machine(s, (W, H), tp, (plc['shift']['a'], plc['shift']['b']))
    rows = [L['first'] + k*L['gap'] for k in range(L['rows'])]

    def fits(e, y):
        rect = [margin + e[0] - 0.3, y + e[1] - 0.3, margin + e[2] + 0.3, y + e[3] + 0.3]
        if _rect_ok(rect, mach['lim_a']):
            return True
        return bool(tp and mach['lim_b']) and _rect_ok([W - rect[2], H - rect[3], W - rect[0], H - rect[1]], mach['lim_b'])

    sheets, cur, r = [], [], 0
    after = req.get('after_y')
    carry_on = after is not None
    if carry_on:            # start on the next ruled line below the earlier writing's lowest ink (tall letters may
        while r < len(rows) and rows[r] < float(after) + 1.0:    # reach up between the lines, as on real lined paper)
            r += 1
    for li, e in enumerate(ext):
        if e is None:
            if cur and r < len(rows):
                r += 1                                 # a blank line between paragraphs
            continue
        while True:
            if r >= len(rows):
                if not cur and carry_on and not sheets:   # no room left under the earlier writing: next sheet
                    sheets.append([])
                    r = 0
                    carry_on = False
                    continue
                if not cur:
                    raise ValueError('A line of writing doesn\'t fit on any ruled line the pen can reach (it is '
                                     '{:.0f} mm wide from a {:.0f} mm margin). Check where the lines end, or make the '
                                     'writing smaller on the Write page.'.format(e[2] - e[0], margin))
                sheets.append(cur)
                cur, r = [], 0
                continue
            if fits(e, rows[r]):
                cur.append((li, rows[r]))
                r += 1
                break
            r += 1
    if cur:
        sheets.append(cur)
    out = []
    stamp = int(time.time()*1000)
    label = (req.get('style_name') or '').strip() or 'Writing'
    for k, picks in enumerate(sheets):
        if not picks:
            out.append(dict(items=[]))
            continue
        y0 = picks[0][1]
        sub = dict(src, pick=[[li, round(y - y0, 3)] for li, y in picks])
        g = source(sub)
        lo = g['lo']
        out.append(dict(items=[dict(id='p{}_{}'.format(stamp, k), src=sub, rot=0, lock=True,
                                    name='{}, page {} of {}'.format(label, k + 1, len(sheets)),
                                    w=g['w0'], h=g['h0'], cx=margin + lo[0] + g['w0']/2, cy=y0 + lo[1] + g['h0']/2)]))
    used = [y for picks in sheets for _, y in picks]
    # ruled lines a full-width line of writing can't use, and why
    above, below = -min(e[1] for e in real), max(e[3] for e in real)
    blocked = []
    for y in rows:
        if not fits((0.0, -above, style['max_width'], below), y):
            ra = mach['lim_a']['reach']
            rb = mach['reach_b'] if (tp and mach['reach_b']) else None
            vertical = (ra[1] <= y - above and y + below <= ra[3]) or (rb and rb[1] <= y - above and y + below <= rb[3])
            blocked.append(dict(y=round(y, 1), why='magnet' if vertical else 'reach'))
    return dict(sheets=out, lines=len(real), shift=plc['shift'], placement=plc, wrap=style['max_width'], blocked=blocked,
                skipped_rows=sorted(set(rows) - set(used))[:40],
                first_row=min(used) if used else None, last_row=max(used) if used else None)


# saving --------------------------------------------------------------------------
MAC = sys.platform == 'darwin'


def mount_roots():
    """Folders where removable disks appear: /Volumes on macOS; /media and /run/media on Linux."""
    if MAC:
        return ['/Volumes']
    user = os.environ.get('USER') or os.path.basename(os.path.expanduser('~'))
    return [os.path.join('/media', user), os.path.join('/run/media', user), '/media', '/mnt']


def on_removable(folder):
    folder = os.path.realpath(folder)
    return any(folder.startswith(os.path.realpath(r) + os.sep) for r in mount_roots())


def volumes():
    """Mounted disks a file could go to (e.g. the printer's microSD card)."""
    out, seen = [], set()
    for root in mount_roots():
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for n in names:
            p = os.path.join(root, n)
            if p in seen or n in seen:
                continue
            seen.update((p, n))
            v = _volume(p, n)
            if v:
                out.append(v)
    return out


def _volume(p, n):
    """One mounted disk, or None if it isn't somewhere a plot file can go."""
    if not os.path.ismount(p) or os.path.realpath(p) == '/' or n.startswith('.') or 'TimeMachine' in n:
        return None
    if not os.access(p, os.W_OK):
        return None
    try:
        total = shutil.disk_usage(p).total
    except OSError:
        return None
    try:
        top = os.listdir(p)
    except OSError:
        top = []
    # a card that has been in the Bambu printer has its timelapse folder, or G-code files on it
    printer = 'timelapse' in top or any(f.lower().endswith('.gcode') and not f.startswith('.') for f in top)
    return dict(name=n, path=p, gb=round(total/1e9, 1), card=total < 300e9, printer=printer)


def _dest_dir(dest):
    if not dest or dest == 'plots':
        os.makedirs(PLOTS, exist_ok=True)
        return PLOTS
    if dest == 'downloads':
        return os.path.expanduser('~/Downloads')
    for v in volumes():
        if v['name'] == dest:
            return v['path']
    raise ValueError('That disk ({}) is no longer connected.'.format(dest))


def safe_name(name, default='plot'):
    n = re.sub(r'[^\w\- ]+', '', name or '').strip().replace(' ', '_')
    return n or default


def write_file(dest, filename, lines):
    folder = _dest_dir(dest)
    path = os.path.join(folder, filename)
    on_card = on_removable(folder)
    # on a card write straight to the file: a temporary name would leave a stray entry the printer lists
    tmp = path if on_card else path + '.part'
    with open(tmp, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    if tmp != path:
        os.replace(tmp, path)
    if on_card:
        _no_mac_extras(path)
    return path


def _no_mac_extras(path):
    """
    macOS keeps extra file information in a hidden "._name" file next to the
    file on SD cards (FAT / exFAT). The printer lists those as files that do
    nothing, so strip the extra information and remove the hidden file.
    """
    if MAC:
        import subprocess
        subprocess.run(['xattr', '-c', path], capture_output=True)
    shadow = os.path.join(os.path.dirname(path), '._' + os.path.basename(path))
    if os.path.isfile(shadow):
        os.remove(shadow)


# folders and files macOS adds to a card that the printer shows as junk
MAC_DIRS = ('.Trashes', '.Spotlight-V100', '.fseventsd', '.TemporaryItems', '.DocumentRevisions-V100')
MAC_FILES = ('.DS_Store', '.apdisk', '.VolumeIcon.icns', '._.Trashes', '._.DS_Store')


def card_junk(dest):
    """What macOS has left on a card: (list of paths, total bytes, gcode files sitting in the card's Trash)."""
    folder = _dest_dir(dest)
    if not on_removable(folder):
        raise ValueError('Choose the SD card under "Save to" first.')
    found, size, trashed = [], 0, []
    for name in os.listdir(folder):
        p = os.path.join(folder, name)
        if name in MAC_DIRS and os.path.isdir(p):
            found.append(p)
            for root, _, files in os.walk(p):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        size += os.path.getsize(fp)
                    except OSError:
                        pass
                    if name == '.Trashes' and f.lower().endswith('.gcode') and not f.startswith('._'):
                        trashed.append(f)
        elif name in MAC_FILES or name.startswith('._'):
            found.append(p)
            try:
                size += os.path.getsize(p)
            except OSError:
                pass
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in MAC_DIRS]
        if root == folder:
            continue
        for f in files:
            if f.startswith('._') or f == '.DS_Store':
                found.append(os.path.join(root, f))
    return found, size, trashed


def eject_card(dest):
    """Eject a card so it can be pulled out safely (pulling it without ejecting can leave it unreadable)."""
    import subprocess
    folder = _dest_dir(dest)
    if not on_removable(folder):
        raise ValueError('Choose the SD card under "Save to" first.')
    if MAC:
        r = subprocess.run(['diskutil', 'eject', folder], capture_output=True, text=True, timeout=60)
    else:
        r = _eject_linux(folder, subprocess)
    if r.returncode != 0:
        raise ValueError('The card could not be ejected: {}. Close any Finder window or file using it, then try again.'
                         .format((r.stderr or r.stdout).strip() or 'it is busy'))
    return dict(ok=True, card=os.path.basename(folder))


def _eject_linux(folder, subprocess):
    """Unmount (and power off where possible) a card on Linux: udisksctl, then gio, then umount."""
    subprocess.run(['sync'], capture_output=True)
    dev = subprocess.run(['findmnt', '-n', '-o', 'SOURCE', '--target', folder], capture_output=True, text=True).stdout.strip()
    tries = []
    if dev and shutil.which('udisksctl'):
        tries.append(['udisksctl', 'unmount', '-b', dev])
    if shutil.which('gio'):
        tries.append(['gio', 'mount', '-u', folder])
    tries.append(['umount', folder])
    r = None
    for cmd in tries:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            if dev and cmd[0] == 'udisksctl':
                subprocess.run(['udisksctl', 'power-off', '-b', dev], capture_output=True, text=True, timeout=60)
            break
    return r


def reveal(path):
    """Show a file in Finder (macOS) or open its folder in the file manager (Linux)."""
    import subprocess
    if MAC:
        subprocess.run(['open', '-R', path] if os.path.isfile(path) else ['open', path])
    else:
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        subprocess.Popen(['xdg-open', folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def clean_card(dest, really=False):
    """List (or, with really=True, delete) the hidden macOS files on the card. Your own files are never touched."""
    found, size, trashed = card_junk(dest)
    info = dict(count=len(found), kb=round(size/1024), names=sorted(set(os.path.basename(p) for p in found))[:30],
                trashed=sorted(trashed)[:30], card=dest)
    if really:
        removed = 0
        for p in found:
            _remove(p)
            if not os.path.lexists(p):
                removed += 1
        for root, _, files in os.walk(_dest_dir(dest)):
            for f in files:
                if f.lower().endswith('.gcode'):
                    subprocess_xattr_clear(os.path.join(root, f))
        info['removed'] = removed
        info['left'] = sorted(os.path.basename(p) for p in found if os.path.lexists(p))
    return info


def card_files(dest):
    """
    Every G-code file in the chosen folder or card, and whether it still matches the printer, pen, pad and
    offset saved now: [dict(file, ok, stamped, problems)]. Out-of-date files must be saved again.
    """
    folder = _dest_dir(dest)
    out = []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith('.gcode') or name.startswith('.'):
            continue
        try:
            with open(os.path.join(folder, name), errors='replace') as f:
                head = [next(f, '') for _ in range(80)]
        except OSError:
            continue
        problems, stamped = plotcheck.stamp_problems(head)
        out.append(dict(file=name, ok=stamped and not problems, stamped=stamped, problems=problems))
    return dict(folder=folder, files=out, old=sum(1 for f in out if not f['ok']))


def printer_list():
    cur = printers.current()['id']
    return dict(current=cur, profiles=printers.all_profiles())


def printer_action(req):
    """Choose, save or delete a printer profile from the Machine tab."""
    act = req.get('action')
    if act == 'use':
        printers.use(req.get('id'))
    elif act == 'save':
        p = printers.save(req.get('profile') or {})
        if req.get('use', True):
            printers.use(p['id'])
    elif act == 'delete':
        printers.delete(req.get('id'))
    elif act != 'list':
        raise ValueError('Unknown printer action')
    return printer_list()


def _remove(p):
    """Delete a file or folder. macOS deletes a "._" twin by itself when its file goes, so missing files are fine."""
    for _ in range(3):
        if not os.path.lexists(p):
            return
        if os.path.isdir(p) and not os.path.islink(p):
            for root, dirs, files in os.walk(p, topdown=False):
                for f in files:
                    try:
                        os.remove(os.path.join(root, f))
                    except FileNotFoundError:
                        pass
                    except OSError:
                        pass
                for d in dirs:
                    try:
                        os.rmdir(os.path.join(root, d))
                    except OSError:
                        pass
            try:
                os.rmdir(p)
            except OSError:
                pass
        else:
            try:
                os.remove(p)
            except OSError:
                pass


def subprocess_xattr_clear(path):
    if MAC:
        import subprocess
        subprocess.run(['xattr', '-c', path], capture_output=True)


def export(state, kind, dest, part='a', suffix='', title=None):
    """One part of one sheet. kind: plot, rehearsal or outline. Raises ValueError with the reasons if it isn't safe."""
    res = checked(state)
    if not res['ok']:
        raise ValueError('Not safe to plot yet:\n- ' + '\n- '.join(res['errors']))
    if part not in res['_gcode']:
        raise ValueError('There is nothing in {} of this sheet.'.format(PART_NAMES.get(part, part)))
    name = safe_name(state.get('name')) + (suffix or '')
    head = ['; ' + (title or name)]
    if kind == 'plot':
        lines, fname = head + res['_gcode'][part], name + '.gcode'
    elif kind == 'rehearsal':
        lines, fname = head + dry(res['_gcode'][part]), name + '_rehearsal.gcode'
    elif kind == 'outline':
        lines, fname = head + outline(plan(state), part), name + '_outline.gcode'
    else:
        raise ValueError('Unknown file type ' + str(kind))
    mismatch, _ = plotcheck.stamp_problems(lines)
    if mismatch:
        raise ValueError('The setup changed while saving:\n- ' + '\n- '.join(mismatch))
    if kind != 'plot':
        errs, _ = plotcheck.check(lines)
        if errs:
            raise ValueError('The {} file failed its check:\n- {}'.format(kind, '\n- '.join(errs)))
    seconds = next((p['seconds'] for p in res['parts'] if p['part'] == part), 0)
    return dict(path=write_file(dest, fname, lines), file=fname, seconds=seconds)


def sheet_state(req, k):
    sheets = req.get('sheets') or []
    return dict(items=(sheets[k] or {}).get('items', []), settings=req.get('settings'), name=req.get('name'),
                paper=req.get('paper'), two_pass=req.get('two_pass', True), shift=req.get('shift'))


def jobs(req):
    """Every part of every sheet, in printing order: [(sheet index, part, state, check)]."""
    out = []
    for k in range(len(req.get('sheets') or [])):
        st = sheet_state(req, k)
        if not any(not it.get('hidden') for it in st['items']):
            continue
        res = checked(st)
        if not res['ok']:
            raise ValueError('Sheet {} isn\'t safe to plot yet:\n- {}'.format(k + 1, '\n- '.join(res['errors'])))
        for p in res['parts']:
            out.append((k, p['part'], st, p))
    if not out:
        raise ValueError('Nothing to plot yet.')
    return out


def job_suffix(n_jobs, sheet, part):
    return '' if n_jobs == 1 else '_{}{}'.format(sheet + 1, part)


def export_all(req, kind, dest):
    js = jobs(req)
    files = []
    for k, part, st, p in js:
        title = '{} - sheet {}, {}'.format(safe_name(req.get('name')), k + 1, PART_NAMES[part])
        r = export(st, kind, dest, part, job_suffix(len(js), k, part), title)
        files.append(dict(r, sheet=k + 1, part=part))
    return dict(files=files)


# calibration ------------------------------------------------------------------------
def calibration_file(step, dest, s=None, a=None, b=None):
    """Write a calibration file. step: pen_set, cross, cross_air, measured (a, b), check, landed (a, b)."""
    s = settings(s)
    mach = machine(s)
    if mach['pen'] is None:
        raise ValueError('Enter how far the pen sticks out below the nozzle first.')
    zd, zl = mach['z_draw'], mach['z_lift']
    if step == 'pen_set':
        # bring the paper up to exactly where the pen tip belongs, under the pen, and wait while the pen is set
        P, S = mach['pen'], mach['surface']
        touch = S + P
        x, y = calibrate.cal_point()
        BED = mach['bed_d']
        where = ''
        if mach['has_offset']:
            where = ' The pen tip is over the paper about {:.0f} mm from the left edge and {:.0f} mm from the top.'.format(
                x + mach['offset_x'], BED - (y + mach['offset_y']))
        lines = ['; Set the pen height: the paper comes up to {:g} mm below the nozzle tip and waits 4 minutes.{}'.format(P, where),
                 '; 1. Home from the printer screen with the holder OFF. Put the sheet{} in the back-left corner, magnets on.'
                 .format(' (on its {:g} mm pad)'.format(S) if S else ''),
                 '; 2. Clip the holder on with the pen pulled UP: it must stick out less than {:g} mm.'.format(P),
                 '; 3. Print this. While it waits, loosen the pen, slide it down until the tip just touches the paper, tighten it.',
                 '; 4. After 4 minutes the bed drops {:g} mm and it ends.'.format(10),
                 plotcheck.stamp_line(with_offset=False),
                 'G90', 'G21'] + printers.start_lines() + [
                 'G1 Z{:.3f} F600 ; well clear first'.format(max(30.0, touch + 15)),
                 'G0 X{:.3f} Y{:.3f} F3000 ; pen over the middle of the sheet, away from the magnets'.format(x, y),
                 'G1 Z{:.3f} F600'.format(touch + 5),
                 'G1 Z{:.3f} F120 ; slowly: the paper is now {:g} mm below the nozzle tip'.format(touch, P),
                 'M400'] + ['G4 P60000 ; waiting while you set the pen'] * 4 + [
                 'G1 Z{:.3f} F600 ; done - the paper moves away from the pen'.format(touch + 10)] + printers.end_lines()
        fname = 'set_pen_height.gcode'
        info = dict(touch=touch)
    elif step == 'check':
        if not mach['has_offset']:
            raise ValueError('Do the calibration cross first.')
        cx, cy = calibrate.cal_point()
        ox, oy, (ca, cb), nozzle = calibrate.from_measurement(cx + mach['offset_x'],
                                                              mach['bed_d'] - cy - mach['offset_y'])
        lines = calibrate.gcode(nozzle, 'Check cross: should land {} mm from the left edge, {} mm from the top edge'
                                .format(ca, cb), zd, zl, with_offset=True)
        calibrate.remember(check=[ca, cb])
        fname = 'calibration_check.gcode'
        info = dict(check=[ca, cb])
    elif step in ('cross', 'cross_air'):
        lift = 15.0 if step == 'cross_air' else 0.0
        cx, cy = calibrate.cal_point()
        lines = calibrate.gcode(calibrate.cross(cx, cy), 'Calibration cross: nozzle at X{:.0f} Y{:.0f}'.format(cx, cy),
                                zd + lift, zl + lift)
        fname = 'calibration_cross{}.gcode'.format('_air' if lift else '')
        info = {}
    elif step == 'measured':
        a, b = float(a), float(b)
        if not (0 < a < PAPER_W and 0 < b < PAPER_H):
            raise ValueError('Those numbers are off the sheet: measure in mm from the paper\'s left and top edges.')
        ox, oy, (ca, cb), nozzle = calibrate.from_measurement(a, b)
        new = dict(calibrate.recall(), offset_x=ox, offset_y=oy)
        lines = calibrate.gcode(nozzle, 'Check cross: should land {} mm from the left edge, {} mm from the top edge'
                                .format(ca, cb), zd, zl)
        lines[1] = plotcheck.stamp_line(cal=new)          # stamped with the offset it is about to save
        errs, _ = plotcheck.check(lines)
        if errs:
            raise ValueError('The check cross failed its safety check:\n- ' + '\n- '.join(errs))
        calibrate.remember(offset_x=ox, offset_y=oy, check=[ca, cb])
        fname = 'calibration_check.gcode'
        info = dict(offset_x=ox, offset_y=oy, check=[ca, cb])
    elif step == 'landed':
        c = calibrate.recall()
        if 'check' not in c or 'offset_x' not in c:
            raise ValueError('Do the calibration cross first.')
        da, db = float(a) - c['check'][0], float(b) - c['check'][1]
        ox, oy = c['offset_x'] + da, c['offset_y'] - db
        calibrate.remember(offset_x=ox, offset_y=oy)
        return dict(offset_x=ox, offset_y=oy, moved=[round(da, 2), round(db, 2)])
    else:
        raise ValueError('Unknown calibration step')
    errs, _ = plotcheck.check(lines)
    if errs:
        raise ValueError('Not safe:\n- ' + '\n- '.join(errs))
    return dict(info, path=write_file(dest, fname, lines), file=fname)


# state on disk ----------------------------------------------------------------------
def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(d):
    tmp = STATE + '.part'
    with open(tmp, 'w') as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, STATE)


def add_item(src, name):
    """Add an item to the sheet shown on the Plotter page (used by the Write page's 'Send to plotter')."""
    st = load_state()
    sheets = st.get('sheets') or [dict(items=st.get('items', []))]
    k = min(max(int(st.get('sheet', 0) or 0), 0), len(sheets) - 1)
    iid = 'i{}'.format(int(time.time()*1000))
    sheets[k].setdefault('items', []).append(dict(id=iid, src=src, name=name, new=True))
    st.update(sheets=sheets, sheet=k, selected=iid)
    st.pop('items', None)
    save_state(st)
    return iid
