"""
Find the pen offset for the UMTS holder on the X1E (the numbers BambuPlot
calls Tool offset X / Y), and the right pen heights, without crashing.

First time only, make sure nothing can hit:
  A. ./calibrate --air
     Writes calibration_cross_air.gcode: the same moves as the calibration
     cross but with the pen 15 mm above the paper. Run it once WITHOUT the
     holder (checks the printer does nothing unexpected, like homing), then
     once WITH the holder (checks nothing touches).
  B. Measure how far the pen tip sticks out below the nozzle (P, in mm), then
     ./calibrate --z-test P            e.g.  ./calibrate --z-test 17
     Writes pen_height_test.gcode: a row of short dashes, each 0.5 mm lower,
     starting 2 mm above the paper. The first dash with ink shows the height
     where the pen touches; it prints the pen-down / pen-up heights to use.

Step 1:   ./calibrate
          Writes calibration_cross.gcode: the nozzle goes to X128 Y180 and
          the pen draws a cross in a circle wherever it sits beside it.
          Print it on paper pushed into the bed's back-left corner, then
          measure to the centre of the circle:
            a = mm from the paper's LEFT edge
            b = mm from the paper's TOP edge

Step 2:   ./calibrate a b          e.g.  ./calibrate 98 106
          Prints the Tool offset X / Y for BambuPlot and writes
          calibration_check.gcode, which draws a cross where it should now
          land (it tells you where), so you can confirm it with a ruler.

Step 3 (only if the check cross is more than ~1 mm out):
          ./calibrate --landed A B
          where A, B are measured to the check circle's centre the same way.
          Prints the corrected Tool offset X / Y.

Options:  --pen P                    how far the pen tip sticks out below the nozzle tip (mm)
          --surface S                thickness of anything under the sheet, e.g. a pad of paper (mm)
                                     Both are remembered. Pen down = S + P - 0.5, pen up = S + P + 3.
          --z-draw Z  --z-lift Z     or give the pen heights directly
          --out DIR                  where to write the files (default: this folder)
"""
import argparse
import json
import math
import os
import sys

import plotcheck

CAL_X, CAL_Y = 128.0, 180.0      # where the nozzle goes for the calibration cross
BED_BACK = 256.0                 # bed Y of the back edge, where the paper's top edge sits
PAPER_W, PAPER_H = 210.0, 297.0  # A4 portrait
MEMORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'calibration.json')


def recall():
    try:
        return json.load(open(MEMORY))
    except (OSError, ValueError):
        return {}


def remember(**kw):
    """Merge values into calibration.json (pen length, offset, check spot)."""
    try:
        mem = json.load(open(MEMORY))
    except (OSError, ValueError):
        mem = {}
    mem.update(kw)
    json.dump(mem, open(MEMORY, 'w'), indent=1)


def cross(cx, cy, size=6.0, ring=2.5):
    """A + with a small circle round its centre, as polylines."""
    circle = [(cx + ring*math.cos(t*2*math.pi/36), cy + ring*math.sin(t*2*math.pi/36)) for t in range(37)]
    return [[(cx - size, cy), (cx + size, cy)], [(cx, cy - size), (cx, cy + size)], circle]


def gcode(paths, title, z_draw, z_lift):
    g = ['; ' + title,
         '; Home from the printer screen BEFORE clipping on the holder. Never home with it attached.',
         'G90', 'G21', 'G1 Z{:.3f} F600 ; high enough to pass over the magnets'.format(z_lift + 6), 'G4 P120']
    for k, path in enumerate(paths):
        g.append('G0 X{:.3f} Y{:.3f} F6000'.format(*path[0]))
        if k == 0:
            g.append('G1 Z{:.3f} F600'.format(z_lift))
        g += ['G1 Z{:.3f} F600'.format(z_draw), 'G4 P120']
        g += ['G1 X{:.3f} Y{:.3f} F1500'.format(x, y) for x, y in path[1:]]
        g.append('G1 Z{:.3f} F600'.format(z_lift))
    g += ['G1 Z{:.3f} F600'.format(z_lift + 10), '; done - pen lifted; take the holder off before homing']
    return g


def from_measurement(a, b):
    """
    Calibration cross measured a mm from the paper's left edge and b mm from its
    top edge -> (offset_x, offset_y, (ca, cb), nozzle_paths): the pen offset, a
    round-numbered spot in the middle of what the pen can reach on the paper, and
    the nozzle paths for a check cross there.
    """
    ox = a - CAL_X                      # pen x on the bed is a (paper's left edge = bed X0)
    oy = (BED_BACK - b) - CAL_Y         # pen y on the bed is 256 - b (paper's top edge = back of the bed)
    x0 = max(plotcheck.SAFE_X[0] + ox, 0) + 15
    x1 = min(plotcheck.SAFE_X[1] + ox, PAPER_W) - 15
    y0 = max(BED_BACK - (plotcheck.SAFE_Y[1] + oy), 0) + 15
    y1 = min(BED_BACK - (plotcheck.SAFE_Y[0] + oy), PAPER_H) - 15
    ca, cb = round((x0 + x1)/2/5)*5, round((y0 + y1)/2/5)*5
    return ox, oy, (ca, cb), cross(ca - ox, BED_BACK - cb - oy)


def save(path, lines):
    errors, _ = plotcheck.check(lines)
    if errors:
        print('NOT SAFE - nothing written:')
        for e in errors:
            print('  - ' + e)
        sys.exit(1)
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('a', nargs='?', type=float, help="mm from the paper's left edge to the circle centre")
    ap.add_argument('b', nargs='?', type=float, help="mm from the paper's top edge to the circle centre")
    ap.add_argument('--pen', type=float, metavar='P',
                    help='mm the pen tip sticks out below the nozzle tip; sets pen down P-0.5, pen up P+3')
    ap.add_argument('--surface', type=float, metavar='S',
                    help='mm of material under the sheet (a pad of paper); raises every height by S')
    ap.add_argument('--z-draw', type=float)
    ap.add_argument('--z-lift', type=float)
    ap.add_argument('--out', default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument('--landed', nargs=2, type=float, metavar=('A', 'B'),
                    help='where the check circle actually landed (from the left edge, from the top edge)')
    ap.add_argument('--air', action='store_true', help='the calibration cross with the pen 15 mm above the paper')
    ap.add_argument('--z-test', type=float, metavar='P',
                    help='pen height test; P = how far the pen tip sticks out below the nozzle, in mm')
    args = ap.parse_args()
    mem = recall()
    if args.surface is not None:
        if args.surface < 0:
            ap.error('the pad thickness can\'t be negative')
        remember(surface=args.surface)
    if args.pen is not None:
        if args.pen - 0.5 < plotcheck.NOZZLE_FLOOR:
            ap.error('with the pen only {} mm below the nozzle, the nozzle would come within {:.1f} mm of the paper. '
                     'Push the pen further out of the holder.'.format(args.pen, args.pen - 0.5))
        remember(pen=args.pen)                       # plotcheck uses it for its height limits
    S = args.surface if args.surface is not None else float(mem.get('surface', 0.0))
    P = args.pen if args.pen is not None else mem.get('pen')
    if args.z_draw is None:
        args.z_draw = round(S + P - 0.5, 2) if P is not None else 18.0 + S
    if args.z_lift is None:
        args.z_lift = round(S + P + 3, 2) if P is not None else args.z_draw + 3
    if P is not None and args.z_test is None:
        import magnets
        h = magnets.load()['height']
        if h > 0 and P - 0.5 < h + 2:
            print('NOTE: with the pen {} mm below the nozzle, the nozzle is only {:.1f} mm above the paper while drawing,\n'
                  '      and the magnets are {:.0f} mm tall. plotcheck will stop drawings that would take the nozzle or\n'
                  '      holder over a magnet. For more freedom, push the pen out to at least {:.0f} mm.\n'
                  .format(P, P - 0.5, h, h + 2.5))

    if args.z_test is not None:
        P = args.z_test
        heights = [round(S + P + 2.0 - 0.5*k, 2) for k in range(8)]      # touch+2 ... touch-1.5
        if heights[-1] - S < plotcheck.NOZZLE_FLOOR:
            ap.error('P = {} looks too small: the pen would be driven into the bed. Measure again '
                     '(with UMTS it is usually about 17 mm).'.format(P))
        lift = S + P + 5
        g = ['; Pen height test: one dash at each height, left to right: ' + ', '.join('Z{}'.format(z) for z in heights),
             '; Home from the printer screen BEFORE clipping on the holder. Never home with it attached.',
             'G90', 'G21', 'G1 Z{:.3f} F600'.format(lift), 'G4 P120']
        for k, z in enumerate(heights):
            x = 100 + 9*k
            g += ['G0 X{:.3f} Y{:.3f} F6000'.format(x, CAL_Y), 'G1 Z{:.3f} F300'.format(z), 'G4 P300',
                  'G1 X{:.3f} Y{:.3f} F600'.format(x + 6, CAL_Y), 'G1 Z{:.3f} F600'.format(lift)]
        g += ['G1 Z{:.3f} F600'.format(lift + 10), '; done - pen lifted; take the holder off before homing']
        path = os.path.join(args.out, 'pen_height_test.gcode')
        save(path, g)
        print('Wrote ' + path)
        print('\nIt draws 8 short dashes from left to right, each 0.5 mm lower:')
        for k, z in enumerate(heights):
            print('    dash {}:  Z {:5.1f}   ({})'.format(k + 1, z, 'pen {:+.1f} mm from touching'.format(z - S - P)))
        print('\nThe first dash with ink is where the pen touches (call that height T). Then use')
        print('    pen down Z = T - 0.5    (presses lightly into the spring)')
        print('    pen up Z   = T + 3')
        print('for example:  ./calibrate --z-draw <pen down> --z-lift <pen up>')
        print('and the same numbers in BambuPlot (Z draw / Z lift).')
        print('If no dash has ink, your P was too small: run it again with P 2 mm larger.')
        return

    if args.air:
        args.z_draw += 15
        args.z_lift += 15

    if args.landed:
        try:
            mem = json.load(open(MEMORY))
        except (OSError, ValueError):
            ap.error('run ./calibrate a b first')
        da, db = args.landed[0] - mem['check'][0], args.landed[1] - mem['check'][1]
        ox, oy = mem['offset_x'] + da, mem['offset_y'] - db
        remember(offset_x=ox, offset_y=oy)
        print('It landed {:.1f} mm {} and {:.1f} mm {} than planned. Corrected offset:'.format(
            abs(da), 'further right' if da > 0 else 'further left', abs(db), 'lower' if db > 0 else 'higher'))
        print('    Tool offset X = {:.1f}'.format(ox))
        print('    Tool offset Y = {:.1f}'.format(oy))
        return

    if args.a is None:
        path = os.path.join(args.out, 'calibration_cross_air.gcode' if args.air else 'calibration_cross.gcode')
        save(path, gcode(cross(CAL_X, CAL_Y), 'Calibration cross: nozzle at X{:.0f} Y{:.0f}'.format(CAL_X, CAL_Y),
                         args.z_draw, args.z_lift))
        print('Wrote ' + path)
        if args.air:
            print('Pen stays 15 mm above the paper (Z {:.0f} / {:.0f}). Run it once WITHOUT the holder, then once WITH it,'.format(
                args.z_draw, args.z_lift))
            print('watching with a hand near pause. Nothing should touch the paper or anything else.')
            return
        print('Pen down Z {:.1f}, pen up Z {:.1f}  (pen {} mm below the nozzle, {:g} mm pad under the sheet).'.format(
            args.z_draw, args.z_lift, P if P is not None else '?', S))
        print("""
1. Home the printer from its screen, THEN clip on the holder.
2. Push a sheet into the bed's back-left corner and hold it with flat magnets.
3. Print calibration_cross.gcode from the microSD card.
4. Measure to the centre of the circle it draws:
     a = mm from the paper's LEFT edge
     b = mm from the paper's TOP edge
5. Run:  ./calibrate a b""")
        return

    if args.b is None:
        ap.error('give both measurements: ./calibrate a b')
    ox, oy, (ca, cb), nozzle = from_measurement(args.a, args.b)
    print('Pen offset found.  In BambuPlot\'s Pen tab enter:')
    print('    Z draw = {:.1f}    Z lift = {:.1f}'.format(args.z_draw, args.z_lift))
    print('    Tool offset X = {:.1f}'.format(ox))
    print('    Tool offset Y = {:.1f}'.format(oy))
    side = '{:.0f} mm {}'.format(abs(ox), 'left of' if ox < 0 else 'right of')
    depth = '{:.0f} mm {}'.format(abs(oy), 'in front of' if oy < 0 else 'behind')
    print('    (the pen sits {} and {} the nozzle)'.format(side, depth))

    path = os.path.join(args.out, 'calibration_check.gcode')
    save(path, gcode(nozzle, 'Check cross: should land {} mm from the left edge, {} mm from the top edge'.format(ca, cb),
                     args.z_draw, args.z_lift))
    remember(offset_x=ox, offset_y=oy, check=[ca, cb])
    print('\nWrote ' + path)
    print('Print it on paper in the same corner. The circle centre should be:')
    print('    {} mm from the paper\'s left edge'.format(ca))
    print('    {} mm from the paper\'s top edge'.format(cb))
    print('If it is more than about 1 mm out, measure where it landed and run:')
    print('    ./calibrate --landed <from left edge> <from top edge>')
    print('\nIn BambuPlot, with the paper in that corner:')
    print('    ruler X = distance from the paper\'s left edge')
    print('    ruler Y = 256 - distance from the paper\'s top edge')


if __name__ == '__main__':
    main()
