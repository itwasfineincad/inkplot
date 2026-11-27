"""
Check and fix BambuPlot G-code for an X1E with the UMTS pen holder.

    ./plotcheck bambuplot_X1E_note.gcode

Writes bambuplot_X1E_note_safe.gcode next to it if every check passes,
otherwise explains what to change in BambuPlot and writes nothing.

Checks:
  - no G28 homing (homing with the holder clipped on crashes the toolhead)
  - no G2/G3 arcs (Bambu firmware doesn't run them)
  - pen-down Z is high enough for UMTS (pen tip sits ~17 mm below the nozzle)
  - pen lifts clear of the paper between strokes
  - the nozzle never enters the area where the holder hits the frame

Fix:
  - drops BambuPlot's final "G0 X0 Y0", which parks the nozzle in the front-left
    corner, inside the area where the holder hits the frame

Magnets (A4 portrait in the back-left corner, a magnet at each corner; see ./magnets):
  - refuses drawings that come within 2 mm of a corner zone
  - lifts the pen higher for any travel move that would pass over a zone
    too low to clear it
  Needs the pen offset saved by ./calibrate to know where the pen tip is.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import printers  # noqa: E402

# Where the nozzle may go without the pen holder hitting the frame comes from the printer profile
# (printers.py). For the X1E it was measured by jogging with the holder on (2026-11-20): the pen tip
# can get no closer than 10 mm to the plate's left edge and 30 mm to its front, which with the pen at
# nozzle + (-24.5, -37) puts the nozzle at X >= 34.5, Y >= 67. Those are nozzle positions, so they
# stay right if the pen is re-clipped (the holder doesn't move on the toolhead).
MIN_PEN_DOWN_Z = 12.0   # used when the pen length isn't known: UMTS Stabilo draws around Z 17
MIN_LIFT_MM = 2.0
NOZZLE_FLOOR = 2.5      # never bring the nozzle closer than this to the bed, whatever the pen


def limits(p=None):
    """(SAFE_X, SAFE_Y): the nozzle's safe range in X and Y for the printer in use."""
    p = p or printers.current()
    return tuple(p['safe_x']), tuple(p['safe_y'])


def bed_back(p=None):
    """Bed Y of the back edge, where the paper's top edge sits."""
    return float((p or printers.current())['bed'][1])


def _saved(key, default=None):
    try:
        with open(os.path.join(printers.CONFIG, 'calibration.json')) as f:
            return float(json.load(f)[key])
    except (OSError, ValueError, KeyError, TypeError):
        return default


def pen_length():
    """How far the pen tip sticks out below the nozzle tip (mm), as saved by ./calibrate --pen, or None."""
    return _saved('pen')


def surface():
    """Thickness of the pad under the sheet (mm), as saved by ./calibrate --surface; 0 if none."""
    return _saved('surface', 0.0)


def lowest_allowed_z():
    P, S = pen_length(), surface()
    return S + max(NOZZLE_FLOOR, P - 1.5) if P else MIN_PEN_DOWN_Z + S

MOVE = re.compile(r'^G([0-3])\b(.*)')
AXIS = re.compile(r'([XYZ])(-?\d*\.?\d+)')


def check(lines, profile=None):
    prof = profile or printers.current()
    SAFE_X, SAFE_Y = limits(prof)
    errors, x, y, z = [], None, None, None
    pen_down_z, lift_z, gaps = set(), set(), []
    out_of_area = []
    bounds = [float('inf'), float('inf'), float('-inf'), float('-inf')]
    strokes = 0
    lowered = None        # Z of the last downward move, until we see whether the pen draws after it
    drawing_at = None     # pen-down Z of the stroke being drawn

    for n, raw in enumerate(lines, 1):
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue
        if re.match(r'^G28\b', line):
            errors.append('line {}: G28 homing. In BambuPlot\'s Pen tab, untick "Home all axes (G28) at start" '
                          'and home from the printer screen before clipping on the holder.'.format(n))
            continue
        m = MOVE.match(line)
        if not m:
            why = printers.command_problem(line, prof['maker'])
            if why:
                errors.append('line {}: {}'.format(n, why))
            continue
        if m.group(1) in '23':
            errors.append('line {}: arc move. Untick "Use G2/G3 arc moves" in BambuPlot\'s Pen tab.'.format(n))
            continue
        axes = dict((a, float(v)) for a, v in AXIS.findall(m.group(2)))
        has_xy = 'X' in axes or 'Y' in axes
        if 'Z' in axes and not has_xy:
            prev_z, z = z, axes['Z']
            if prev_z is not None and z < prev_z:
                lowered = z                     # pen down only if it then draws (a G1 sideways move)
            else:
                lowered = None
                if drawing_at is not None and z > drawing_at:
                    gaps.append(z - drawing_at)  # how far the pen lifts after a stroke
                    lift_z.add(z)
                    drawing_at = None
        elif has_xy:
            if m.group(1) == '1' and lowered is not None:
                pen_down_z.add(lowered)
                strokes += 1
                drawing_at = lowered
            lowered = None
        x, y = axes.get('X', x), axes.get('Y', y)
        if 'X' in axes or 'Y' in axes:
            if x is None or y is None:
                continue
            bounds = [min(bounds[0], x), min(bounds[1], y), max(bounds[2], x), max(bounds[3], y)]
            if not (SAFE_X[0] <= x <= SAFE_X[1] and SAFE_Y[0] <= y <= SAFE_Y[1]):
                out_of_area.append((n, x, y))

    P, S = pen_length(), surface()
    if pen_down_z and min(pen_down_z) < lowest_allowed_z():
        if P:
            errors.append('pen-down Z is {:.1f} mm, but the pen touches the paper at about Z {:.1f} (pen {:.1f} mm below the '
                          'nozzle, {:g} mm pad), so this would push it {:.1f} mm into the paper. Set "Z draw" to {:.1f} in '
                          'BambuPlot\'s Pen tab.'.format(min(pen_down_z), S + P, P, S, S + P - min(pen_down_z), S + P - 0.5))
        else:
            errors.append('pen-down Z is {:.1f} mm. With UMTS the pen tip is usually ~17 mm below the nozzle, so this '
                          'could drive the pen into the bed. If your pen sticks out less, measure it and run '
                          './calibrate --pen <mm> so plotcheck knows.'.format(min(pen_down_z)))
    warnings = []
    if P and pen_down_z and max(pen_down_z) > S + P + 0.5:
        warnings.append('pen-down Z {:.1f} is above where your pen touches (about Z {:.1f}), so it may not draw. '
                        'Set "Z draw" to {:.1f}.'.format(max(pen_down_z), S + P, S + P - 0.5))
    if gaps and min(gaps) < MIN_LIFT_MM:
        errors.append('pen only lifts {:.1f} mm between strokes. Set "Z lift" to Z draw + 3.'.format(min(gaps)))
    if out_of_area:
        need_right = max(0.0, SAFE_X[0] - bounds[0])
        need_back = max(0.0, SAFE_Y[0] - bounds[1])
        hint = []
        if need_right:
            hint.append('{:.0f} mm right'.format(need_right + 1))
        if need_back:
            hint.append('{:.0f} mm toward the back (up on the canvas)'.format(need_back + 1))
        if bounds[2] > SAFE_X[1] or bounds[3] > SAFE_Y[1]:
            hint.append('back inside the bed')
        errors.append('{} moves take the nozzle outside the safe area (X {:.0f}-{:.0f}, Y {:.0f}-{:.0f}), e.g. line '
                      '{} goes to X{:.1f} Y{:.1f}. Move the drawing {} in BambuPlot.'
                      .format(len(out_of_area), SAFE_X[0], SAFE_X[1], SAFE_Y[0], SAFE_Y[1],
                              out_of_area[0][0], out_of_area[0][1], out_of_area[0][2],
                              ' and '.join(hint) or 'into the safe area'))

    info = dict(strokes=strokes, bounds=bounds, warnings=warnings,
                pen_down_z=max(pen_down_z) if pen_down_z else None,
                lift_z=min(lift_z) if lift_z else None)
    return errors, info


HERE = os.path.dirname(os.path.abspath(__file__))
DRAW_MARGIN = 2.0         # keep drawing at least this far from a magnet
TRAVEL_MARGIN = 4.0       # treat travel moves this close to a magnet as passing over it


def _load(name):
    try:
        with open(os.path.join(printers.CONFIG, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


SHIFT = re.compile(r'^;\s*paper shift:\s*(-?\d+(?:\.\d+)?)', re.I)


def paper_shift(lines):
    """
    How far in front of the back of the bed the sheet's top edge is, from a
    '; paper shift: N mm' line near the top of the file (the Plotter writes one
    when the sheet isn't pushed right into the corner). 0 if there is none.
    """
    for raw in lines[:60]:
        m = SHIFT.match(raw.strip())
        if m:
            return float(m.group(1))
    return 0.0


def on_paper(lines, shift=None):
    """
    Errors if the pen draws outside the A4 sheet (portrait, in the bed's
    back-left corner), using the pen offset saved by ./calibrate.
    """
    sys.path.insert(0, HERE)
    import magnets
    cal = _load('calibration.json')
    if not cal or 'offset_x' not in cal:
        return []
    ox, oy = cal['offset_x'], cal['offset_y']
    zs = [float(m) for m in re.findall(r'^G1\s+Z(-?[\d.]+)', '\n'.join(lines), re.M)]
    if not zs:
        return []
    z_down = min(zs)
    shift = paper_shift(lines) if shift is None else shift
    back = bed_back()
    width, bottom = magnets.PAPER_W, magnets.on_bed() - shift  # below the bed's front edge the sheet hangs in the air
    over = dict(left=0.0, right=0.0, top=0.0, bottom=0.0)
    x = y = z = None
    for raw in lines:
        m = MOVE.match(raw.split(';', 1)[0].strip())
        if not m:
            continue
        axes = dict((a, float(v)) for a, v in AXIS.findall(m.group(2)))
        if 'Z' in axes and 'X' not in axes and 'Y' not in axes:
            z = axes['Z']
            continue
        nx, ny = axes.get('X', x), axes.get('Y', y)
        if z is not None and z <= z_down + 0.2 and nx is not None and m.group(1) == '1':
            for bx, by in ((x, y), (nx, ny)):
                if bx is None:
                    continue
                px, py = bx + ox, back - shift - (by + oy)  # pen position on the paper
                over['left'] = max(over['left'], -px)
                over['right'] = max(over['right'], px - width)
                over['top'] = max(over['top'], -py)
                over['bottom'] = max(over['bottom'], py - bottom)
        x, y = nx, ny
    where = ['{:.0f} mm past the {} edge'.format(v + 0.5, k) for k, v in over.items() if v > 0.05]
    if not where:
        return []
    fix = {'right': 'left', 'left': 'right', 'top': 'down', 'bottom': 'up'}
    moves = ' and '.join('{:.0f} mm {}'.format(over[k] + 1, fix[k]) for k in over if over[k] > 0.05)
    return ['it draws off the paper: ' + ', '.join(where) + '. Move the drawing ' + moves +
            ' on the BambuPlot canvas, or make it smaller.']


def avoid_magnets(lines, shift=None):
    """
    Returns (lines, hops, errors, note). Keeps the pen, and the nozzle and
    holder when they are low enough to hit, out of the magnet zones at the
    paper's corners, and inserts a higher lift around travel moves that
    would pass over a magnet.
    """
    sys.path.insert(0, HERE)
    import magnets
    mag = magnets.load()
    cal = _load('calibration.json')
    if not cal or 'offset_x' not in cal:
        return lines, 0, ["The pen offset isn't known yet, so the magnet zones at the paper's corners can't be checked. "
                          'Do the calibration first (./calibrate, then ./calibrate a b).'], ''
    ox, oy = cal['offset_x'], cal['offset_y']
    shift = paper_shift(lines) if shift is None else shift
    zones = magnets.zones(mag, shift)
    height = mag['height']
    if height <= 0:
        return lines, 0, [], 'magnet zones off'
    S = surface()                             # magnets sit on the paper, whose top is S above the bed
    back = bed_back()

    def paper(bx, by):                        # bed position -> position on the paper
        return bx, back - shift - by

    def zone_hits(nx0, ny0, nx1, ny1, parts, margin):
        """Zones touched while the nozzle moves (nx0,ny0)->(nx1,ny1); parts: 1 = pen tip, 0 = nozzle,
        in between = the holder."""
        # quick exit: every sampled point lies inside the box spanned by the parts' start and end
        # positions, so if that box misses every zone (with margin) no sample can hit one
        ends = [paper(bx + f*ox, by + f*oy) for f in parts for bx, by in ((nx0, ny0), (nx1, ny1))]
        lo_a, hi_a = min(e[0] for e in ends), max(e[0] for e in ends)
        lo_b, hi_b = min(e[1] for e in ends), max(e[1] for e in ends)
        if not any(hi_a >= l - margin and lo_a <= r + margin and hi_b >= top - margin and lo_b <= bot + margin
                   for l, top, r, bot in zones):
            return set()
        n = max(2, int(((nx1 - nx0)**2 + (ny1 - ny0)**2)**0.5) + 2)
        found = set()
        for k in range(n):
            t = k/(n - 1)
            nx, ny = nx0 + (nx1 - nx0)*t, ny0 + (ny1 - ny0)*t
            for f in parts:
                a, b = paper(nx + f*ox, ny + f*oy)
                for i, (l, top, r, bot) in enumerate(zones):
                    if l - margin <= a <= r + margin and top - margin <= b <= bot + margin:
                        found.add(i)
        return found

    zs = [float(m) for m in re.findall(r'^G1\s+Z(-?[\d.]+)', '\n'.join(lines), re.M)]
    if not zs:
        return lines, 0, [], ''
    z_down = min(zs)
    touch = z_down + 1.0                      # the pen touches at most ~1 mm above pen-down height
    hop = max(touch + height + 3.0, S + height + 3.0)
    PEN = [1.0]
    HOLDER = [0.0, 0.25, 0.5, 0.75]           # nozzle and the holder between nozzle and pen

    out, hops, pen_bad, head_bad = [], 0, set(), set()
    x = y = None
    z = None
    first_travel = True
    for raw in lines:
        line = raw.split(';', 1)[0].strip()
        m = MOVE.match(line)
        if not m:
            out.append(raw)
            continue
        axes = dict((a, float(v)) for a, v in AXIS.findall(m.group(2)))
        if 'Z' in axes and 'X' not in axes and 'Y' not in axes:
            z = axes['Z']
            out.append(raw)
            continue
        nx, ny = axes.get('X', x), axes.get('Y', y)
        pen_down = z is not None and z <= z_down + 0.2
        head_low = z is not None and z - S < height + 2.0      # nozzle / holder low enough to hit a magnet
        if pen_down and x is not None and nx is not None:
            pen_bad |= zone_hits(x, y, nx, ny, PEN, DRAW_MARGIN)
            if head_low:
                head_bad |= zone_hits(x, y, nx, ny, HOLDER, DRAW_MARGIN)
            out.append(raw)
        elif not pen_down and nx is not None:
            pen_clear = (z if z is not None else hop) - touch
            crosses_pen = first_travel or (x is not None and zone_hits(x, y, nx, ny, PEN, TRAVEL_MARGIN))
            crosses_head = first_travel or (x is not None and head_low and zone_hits(x, y, nx, ny, HOLDER, TRAVEL_MARGIN))
            needs = (crosses_pen and pen_clear < height + 2.0) or (crosses_head and head_low)
            if needs and z is not None:
                out += ['G1 Z{:.3f} F600 ; plotcheck: lift over the magnets'.format(hop), raw, 'G1 Z{:.3f} F600'.format(z)]
                hops += 1
            else:
                out.append(raw)
            first_travel = False
        else:
            out.append(raw)
        x, y = nx, ny
    names = ['top-left', 'top-right', 'bottom-left', 'bottom-right']
    errors = []
    for i in sorted(pen_bad):
        l, t, r, b = zones[i]
        errors.append('it draws into the {} magnet zone (left {:.0f}-{:.0f}, top {:.0f}-{:.0f} mm on the paper). '
                      'Move the drawing at least {:.0f} mm away from that corner in BambuPlot.'
                      .format(names[i], l, r, t, b, DRAW_MARGIN))
    for i in sorted(head_bad - pen_bad):
        errors.append('while drawing, the nozzle or pen holder would pass over the {} magnet: with the pen only {:.1f} mm '
                      'below the nozzle, the nozzle is {:.1f} mm above the paper and the magnets are {:.0f} mm tall. '
                      'Move the drawing further from that corner, or push the pen further out of the holder '
                      '(at least {:.0f} mm below the nozzle) and run ./calibrate --pen again.'
                      .format(names[i], (pen_length() or z_down - S + 0.5), z_down - S, height, height + 2.5))
    return out, hops, errors, '4 corner zones of {:.0f} mm, {:.0f} mm tall'.format(mag['size'], height)


# the setup a file was made for ---------------------------------------------------------------
# Every file the studio or ./calibrate writes carries one line like
#   ; inkplot setup: printer=bambu-x1e pen=10 pad=0.5 offset=-24.5,-37
# Its heights and positions are only right for that printer, pen length, pad and pen offset, so a
# file whose stamp doesn't match the setup saved now is refused (save it again instead).
STAMP = re.compile(r'^;\s*ink(?:plot|print) setup:\s*(.*)$', re.I)


def _calibration():
    return _load('calibration.json') or {}


def stamp_line(with_offset=True, profile=None, cal=None):
    """The stamp for a file made now. with_offset=False for files that don't depend on the pen offset."""
    p = profile or printers.current()
    c = _calibration() if cal is None else cal
    parts = ['printer=' + p['id']]
    if c.get('pen') is not None:
        parts.append('pen={:g}'.format(round(float(c['pen']), 2)))
    parts.append('pad={:g}'.format(round(float(c.get('surface', 0.0) or 0.0), 2)))
    if with_offset and 'offset_x' in c and 'offset_y' in c:
        parts.append('offset={:g},{:g}'.format(round(float(c['offset_x']), 2), round(float(c['offset_y']), 2)))
    return '; inkplot setup: ' + ' '.join(parts)


def read_stamp(lines):
    """The setup a file says it was made for, as a dict (printer, pen, pad, offset), or None if it has no stamp."""
    for raw in lines[:80]:
        m = STAMP.match(raw.strip())
        if not m:
            continue
        out = {}
        for k, v in re.findall(r'(\w+)=(\S+)', m.group(1)):
            try:
                if k == 'printer':
                    out[k] = v
                elif k == 'offset':
                    a, b = v.split(',')
                    out[k] = (float(a), float(b))
                elif k in ('pen', 'pad'):
                    out[k] = float(v)
            except ValueError:
                pass
        return out
    return None


def stamp_problems(lines, profile=None, cal=None):
    """
    (problems, stamped): why this file doesn't match the printer, pen, pad and offset saved now.
    A file without a stamp gives no problems and stamped=False (it can't be told either way).
    """
    st = read_stamp(lines)
    if st is None:
        return [], False
    p = profile or printers.current()
    c = _calibration() if cal is None else cal
    out = []
    if 'printer' in st and st['printer'] != p['id']:
        made = printers.get(st['printer'])
        out.append('it was made for the printer profile "{}", but "{}" is chosen now.'.format(
            made['name'] if made else st['printer'], p['name']))
    if 'pen' in st and c.get('pen') is not None and abs(st['pen'] - float(c['pen'])) > 0.01:
        out.append('it was made for the pen sticking out {:g} mm below the nozzle; it is set to {:g} mm now.'.format(
            st['pen'], float(c['pen'])))
    pad = float(c.get('surface', 0.0) or 0.0)
    if 'pad' in st and abs(st['pad'] - pad) > 0.01:
        out.append('it was made for a {:g} mm pad under the paper; the pad is set to {:g} mm now.'.format(st['pad'], pad))
    if 'offset' in st and 'offset_x' in c and 'offset_y' in c:
        ox, oy = float(c['offset_x']), float(c['offset_y'])
        if abs(st['offset'][0] - ox) > 0.01 or abs(st['offset'][1] - oy) > 0.01:
            out.append('it was made for the pen offset X {:g} Y {:g}; the offset is X {:g} Y {:g} now.'.format(
                st['offset'][0], st['offset'][1], round(ox, 2), round(oy, 2)))
    return out, True


DRY_LIFT = 10.0


def main():
    args = [a for a in sys.argv[1:] if a != '--dry']
    dry = '--dry' in sys.argv[1:]
    if len(args) != 1:
        print(__doc__.strip().split('\n\n')[1])
        print('\n    ./plotcheck FILE.gcode --dry   also writes FILE_dry.gcode: the same moves with the pen 10 mm higher')
        sys.exit(2)
    src = args[0]
    with open(src) as f:
        lines = f.read().split('\n')

    # BambuPlot ends with a travel to the front-left corner; drop it
    removed = 0
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and re.match(r'^G0 X0(\.0+)? Y0(\.0+)?\b', lines[-1]):
        lines.pop()
        removed += 1

    prof = printers.current()
    mismatch, stamped = stamp_problems(lines, prof)
    if mismatch:
        print('NOT SAFE for this setup - nothing written:\n')
        for e in mismatch:
            print('  - ' + e)
        print('\nSave the file again from the Plotter (or ./calibrate) so it matches the setup saved now.')
        sys.exit(1)
    errors, info = check(lines, prof)
    if not errors:
        errors += on_paper(lines)
        lines, hops, mag_errors, mag_note = avoid_magnets(lines)
        errors += mag_errors
    if errors:
        print('NOT SAFE for {} - nothing written:\n'.format(prof['name']))
        for e in errors:
            print('  - ' + e)
        sys.exit(1)

    stem, ext = os.path.splitext(src)
    dst = stem + '_safe' + (ext or '.gcode')
    lines.append('; plotcheck: checked for {}; ends here with the pen lifted - remove the holder now'.format(prof['name']))
    with open(dst, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    b = info['bounds']
    print('OK: {}'.format(dst))
    if info['pen_down_z'] is not None:
        print('  {} strokes, pen down at Z{:.1f}, lifted to Z{:.1f}'.format(info['strokes'], info['pen_down_z'], info['lift_z']))
    else:
        print('  the pen never goes down (travel only)')
    print('  nozzle stays within X {:.1f}-{:.1f}, Y {:.1f}-{:.1f}'.format(*[b[0], b[2], b[1], b[3]]))
    print('  printer: {}{}'.format(prof['name'], '' if prof['measured'] else ' (safe area not measured: rehearse pen-up first)'))
    if stamped:
        print('  made for the pen, pad and offset saved now')
    else:
        print('  warning: no "inkplot setup" line, so plotcheck can\'t tell which pen, pad and offset this file was '
              'made for. Files from the Plotter have one; save it again from there to be sure.')
    if removed:
        print('  removed the final move to the front-left corner')
    for w in info.get('warnings', []):
        print('  warning: ' + w)
    print('  magnets: ' + mag_note + ('; lifted the pen over them on {} travel move(s)'.format(hops) if hops else ''))
    if dry:
        def up(line):
            if MOVE.match(line.split(';', 1)[0].strip()):
                return re.sub(r'\bZ(-?[\d.]+)', lambda m: 'Z{:.3f}'.format(float(m.group(1)) + DRY_LIFT), line)
            return line
        dry_path = stem + '_dry' + (ext or '.gcode')
        with open(dry_path, 'w') as f:
            f.write('\n'.join(['; DRY RUN: every height raised {:.0f} mm, the pen never touches the paper'.format(DRY_LIFT)] +
                              [up(l) for l in lines]) + '\n')
        print('\nDry run: {}'.format(dry_path))
        print('  the same moves with the pen {:.0f} mm higher, so it never touches. Print it first and watch.'.format(DRY_LIFT))
    print('\nBefore starting: home from the printer screen with the holder off, move the head to the middle')
    print('of the bed, then clip the holder on.' + ('' if dry else ' First time? Run with --dry for a pen-up rehearsal.'))


if __name__ == '__main__':
    main()
