"""
Printer profiles: everything InkPlot needs to know about the printer the pen
holder is clipped to.

A profile gives, in mm:
  bed      [width, depth]: the sheet's left edge goes against the bed's left side (X 0) and its top
           edge against the back of the bed (Y = depth)
  safe_x   [min, max] and safe_y [min, max]: where the NOZZLE may go without the pen holder hitting
           the frame (measure it on your printer with the holder on, by jogging slowly)
  cal      [x, y]: where the nozzle goes for the calibration cross
  maker    'bambu' or 'other'. Bambu profiles get Bambu's own G-code (BAMBU_START); no other printer
           gets it, and Bambu-only commands are refused in other profiles.
  start / end: extra G-code lines for the start and end of every file (optional; checked, see
           command_problem)
  measured True when the safe area was measured on a real printer, not guessed.

Built-in profiles are below. Profiles people make are kept in printers.json next to
this file (or in $INKPLOT_CONFIG), together with which profile is in use.

    python printers.py        list the profiles and show the one in use
    python printers.py use ID
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.environ.get('INKPLOT_CONFIG') or HERE
FILE = os.path.join(CONFIG, 'printers.json')
DEFAULT = 'bambu-x1e'

# Bambu Studio writes "M981 S1 P20000 ;open spaghetti detector" at the start of every print and
# "M981 S0 P20000 ; close spaghetti detector" at the end (src/libslic3r/GCode.cpp in
# github.com/bambulab/BambuStudio). A pen extrudes nothing, which the camera's failure detection
# can mistake for a failed print and pause it, so InkPlot's Bambu files close it at the start.
BAMBU_START = ['M981 S0 P20000 ; Bambu: spaghetti detector off (the same line Bambu Studio uses to close it)']

_X1E = dict(bed=[256.0, 256.0], safe_x=[34.5, 256.0], safe_y=[67.0, 256.0], cal=[128.0, 180.0])
BUILTIN = [
    dict(_X1E, id='bambu-x1e', name='Bambu Lab X1E', maker='bambu', measured=True,
         note='Measured on an X1E with the UMTS pen holder.'),
    dict(_X1E, id='bambu-x1', name='Bambu Lab X1 / X1 Carbon', maker='bambu', measured=False,
         note='Same frame and toolhead as the X1E; limits copied from it.'),
    dict(_X1E, id='bambu-p1', name='Bambu Lab P1S / P1P', maker='bambu', measured=False,
         note='Same bed and a similar toolhead to the X1E; limits copied from it.'),
    dict(id='bambu-a1', name='Bambu Lab A1', maker='bambu', measured=False,
         bed=[256.0, 256.0], safe_x=[40.0, 256.0], safe_y=[70.0, 256.0], cal=[128.0, 180.0],
         note='A guess: the A1 toolhead differs from the X1E. Measure, then make your own profile.'),
    dict(id='bambu-a1mini', name='Bambu Lab A1 mini', maker='bambu', measured=False,
         bed=[180.0, 180.0], safe_x=[40.0, 180.0], safe_y=[70.0, 180.0], cal=[95.0, 130.0],
         note='A guess. The bed is narrower than A4: use smaller paper or let it overhang. Measure, then make '
              'your own profile.'),
    dict(id='other', name='Other printer (Marlin, Klipper, Prusa…)', maker='other', measured=False,
         bed=[220.0, 220.0], safe_x=[40.0, 220.0], safe_y=[70.0, 220.0], cal=[110.0, 150.0],
         note='A starting point for any other printer. Make your own profile with your bed size and safe area.'),
]
for _p in BUILTIN:
    _p.update(builtin=True, start=[], end=[])

MAKERS = ('bambu', 'other')


# what extra G-code lines may do ------------------------------------------------------------
# Commands only Bambu firmware understands (camera, lidar, AMS, Bambu's status codes)
BAMBU_ONLY = re.compile(r'^M(9[6-9]\d|100\d|62\d)(\.\d+)?$')
HEATERS = {'M104', 'M109', 'M140', 'M190', 'M141', 'M191'}
# commands that move the head, change the machine's position, limits or stored settings
REFUSED = {'M48', 'M92', 'M125', 'M206', 'M211', 'M290', 'M401', 'M402', 'M428', 'M500', 'M501', 'M502',
           'M600', 'M701', 'M702', 'M851'}
ALLOWED_G = {'G4', 'G21', 'G90'}


def command_problem(line, maker):
    """
    Why a non-move line may not go in a file for this kind of printer, or None if it may.
    Moves (G0/G1) are checked separately by plotcheck; this covers everything else.
    """
    code = line.split(';', 1)[0].strip()
    if not code:
        return None
    word = code.split()[0].upper()
    if word.startswith('T'):
        return '{}: tool changes move the head, so they are not allowed.'.format(word)
    m = re.match(r'^([GM])(\d+)(?:\.(\d+))?$', word)
    if not m:
        return '"{}" is not a G-code command InkPlot knows.'.format(word)
    base = m.group(1) + str(int(m.group(2)))
    if m.group(1) == 'G':
        if base in ('G0', 'G1', 'G2', 'G3', 'G28'):
            return None                      # moves, arcs and homing: plotcheck explains those itself
        if base in ALLOWED_G:
            return None
        if base == 'G91':
            return 'G91 (relative moves) would make every move land somewhere else.'
        if base == 'G92':
            return 'G92 changes where the printer thinks the head is, so the safe area would no longer match.'
        if base == 'G29':
            return 'G29 (bed levelling) moves the head all over the bed and would crash the pen holder.'
        return '{} is not allowed: the only G-codes InkPlot uses are moves (G0/G1), pauses (G4), G21 and G90.'.format(base)
    norm = base + ('.' + m.group(3) if m.group(3) else '')
    if BAMBU_ONLY.match(norm) and maker != 'bambu':
        return '{} is a Bambu Lab command; it only goes in profiles for Bambu printers.'.format(norm)
    if base in HEATERS:
        s = re.search(r'\bS(-?\d*\.?\d+)', code[len(word):], re.I)
        if s and float(s.group(1)) > 0:
            return '{} would heat the {}: a pen needs no heat, and a hot nozzle can melt the holder.'.format(
                base, 'bed' if base in ('M140', 'M190') else 'chamber' if base in ('M141', 'M191') else 'nozzle')
        return None
    if base in REFUSED:
        return '{} moves the head or changes the printer\'s stored settings, so it is not allowed.'.format(base)
    return None


# profiles --------------------------------------------------------------------------------
def _read():
    try:
        with open(FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d):
    tmp = FILE + '.part'
    with open(tmp, 'w') as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, FILE)


def custom():
    out = []
    for p in _read().get('custom') or []:
        try:
            out.append(clean(p, keep_id=True))
        except (ValueError, TypeError, KeyError):
            continue
    return out


def all_profiles():
    return [dict(p) for p in BUILTIN] + custom()


def get(pid):
    for p in all_profiles():
        if p['id'] == pid:
            return p
    return None


def current():
    """The profile in use (the X1E if none was chosen, or the chosen one has gone)."""
    return get(_read().get('current') or DEFAULT) or get(DEFAULT)


def use(pid):
    p = get(pid)
    if not p:
        raise ValueError('There is no printer profile called "{}".'.format(pid))
    d = _read()
    d['current'] = p['id']
    _write(d)
    return p


def _num(v, what):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError('{} must be a number in mm.'.format(what))
    if x != x or x in (float('inf'), float('-inf')):
        raise ValueError('{} must be a number in mm.'.format(what))
    return round(x, 2)


def _pair(v, what):
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError('{} needs two numbers.'.format(what))
    return [_num(v[0], what), _num(v[1], what)]


def _lines(v, maker, where):
    if isinstance(v, str):
        v = v.split('\n')
    out = []
    for raw in v or []:
        line = str(raw).rstrip()
        if not line.strip():
            continue
        if len(line) > 160:
            raise ValueError('A {} G-code line is too long (160 characters at most).'.format(where))
        if re.match(r'^\s*G[0-3]\b', line.split(';', 1)[0].strip(), re.I) or re.match(r'^\s*G28\b', line, re.I):
            raise ValueError('{} G-code: "{}" moves the head. The Plotter makes every move itself, so extra lines '
                             'may only set things up (M-codes, G4 pauses, comments).'.format(where.capitalize(), line.strip()))
        why = command_problem(line, maker)
        if why:
            raise ValueError('{} G-code: {}'.format(where.capitalize(), why))
        out.append(line)
    if len(out) > 30:
        raise ValueError('Keep the {} G-code to 30 lines or fewer.'.format(where))
    return out


def _slug(name):
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:30]
    s = s or 'printer'
    return s if s.startswith('my-') else 'my-' + s


def clean(p, keep_id=False):
    """Check a profile someone typed in and return it tidied up. Raises ValueError with a plain reason."""
    name = re.sub(r'\s+', ' ', str(p.get('name') or '')).strip()[:50]
    if not name:
        raise ValueError('Give the printer profile a name.')
    maker = p.get('maker') if p.get('maker') in MAKERS else 'other'
    bed = _pair(p.get('bed'), 'Bed size')
    if not (80 <= bed[0] <= 1000 and 80 <= bed[1] <= 1000):
        raise ValueError('The bed should be between 80 and 1000 mm each way.')
    sx, sy = _pair(p.get('safe_x'), 'Safe area X'), _pair(p.get('safe_y'), 'Safe area Y')
    for (lo, hi), size, axis in ((sx, bed[0], 'X'), (sy, bed[1], 'Y')):
        if not 0 <= lo < hi <= size:
            raise ValueError('The safe area in {axis} must lie on the bed: 0 to {size:g} mm, the smaller number first.'
                             .format(axis=axis, size=size))
        if hi - lo < 40:
            raise ValueError('The safe area in {} is under 40 mm: that leaves no room to draw.'.format(axis))
    cal = _pair(p.get('cal') or [(sx[0] + sx[1])/2, (sy[0] + sy[1])/2], 'Calibration spot')
    if not (sx[0] + 10 <= cal[0] <= sx[1] - 10 and sy[0] + 10 <= cal[1] <= sy[1] - 10):
        raise ValueError('Put the calibration spot inside the safe area, at least 10 mm from its edges '
                         '(X {:g}-{:g}, Y {:g}-{:g}).'.format(sx[0] + 10, sx[1] - 10, sy[0] + 10, sy[1] - 10))
    out = dict(name=name, maker=maker, bed=bed, safe_x=sx, safe_y=sy, cal=cal,
               start=_lines(p.get('start'), maker, 'start'), end=_lines(p.get('end'), maker, 'end'),
               measured=bool(p.get('measured')), note=str(p.get('note') or '').strip()[:300], builtin=False)
    pid = str(p.get('id') or '')
    out['id'] = pid if keep_id and pid.startswith('my-') else ''
    return out


def save(p):
    """Add or replace a profile someone made (built-in ones can't be changed). Returns it."""
    prof = clean(p)
    d = _read()
    mine = [q for q in d.get('custom') or [] if isinstance(q, dict)]
    pid = str(p.get('id') or '')
    if any(b['id'] == pid for b in BUILTIN):
        pid = ''                               # editing a built-in makes a new profile
    if not pid or not any(q.get('id') == pid for q in mine):
        taken = {q.get('id') for q in mine} | {b['id'] for b in BUILTIN}
        base = _slug(prof['name'])
        pid, n = base, 2
        while pid in taken:
            pid, n = '{}-{}'.format(base, n), n + 1
    if any(q.get('name', '').lower() == prof['name'].lower() and q.get('id') != pid for q in mine) or \
            any(b['name'].lower() == prof['name'].lower() for b in BUILTIN):
        raise ValueError('There is already a profile called "{}". Pick another name.'.format(prof['name']))
    prof['id'] = pid
    mine = [q for q in mine if q.get('id') != pid] + [prof]
    d['custom'] = mine
    _write(d)
    return prof


def delete(pid):
    d = _read()
    mine = [q for q in d.get('custom') or [] if isinstance(q, dict)]
    if not any(q.get('id') == pid for q in mine):
        raise ValueError('Only profiles you made can be deleted.')
    d['custom'] = [q for q in mine if q.get('id') != pid]
    if d.get('current') == pid:
        d['current'] = DEFAULT
    _write(d)


def start_lines(p=None):
    p = p or current()
    return (BAMBU_START if p['maker'] == 'bambu' else []) + list(p.get('start') or [])


def end_lines(p=None):
    p = p or current()
    return list(p.get('end') or [])


def main(argv):
    if len(argv) == 2 and argv[0] == 'use':
        p = use(argv[1])
        print('Now using: {} ({})'.format(p['name'], p['id']))
        return
    if argv:
        sys.exit(__doc__)
    cur = current()['id']
    for p in all_profiles():
        print('{} {:<16} {:<42} bed {:g} x {:g}, nozzle X {:g}-{:g}, Y {:g}-{:g}{}'.format(
            '*' if p['id'] == cur else ' ', p['id'], p['name'], p['bed'][0], p['bed'][1], p['safe_x'][0], p['safe_x'][1],
            p['safe_y'][0], p['safe_y'][1], '' if p['measured'] else '  (not measured)'))


if __name__ == '__main__':
    main(sys.argv[1:])
