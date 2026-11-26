"""
No-go zones for the magnets that hold the paper.

The paper is always A4 portrait pushed into the bed's back-left corner, with a
magnet at each corner. The bed is only 256 mm deep, so the bottom of the
sheet hangs off the front; the bottom two magnets sit on the bed's front
edge, 256 mm down the sheet. Each zone is a square measured in from its
corner; plotcheck keeps the pen out of them while drawing and lifts it over
them when travelling.

    ./magnets              show the zones
    ./magnets size 25      zone size in mm, measured in from each corner (default 20)
    ./magnets height 5     magnet height in mm (default 5); 0 switches the zones off
                           (e.g. when the sheet is clipped or taped to a pad instead)

Saved in magnets.json next to this script.
"""
import json
import os
import sys

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'magnets.json')
PAPER_W = 210.0          # A4 portrait width
ON_BED = 256.0           # how far down the sheet the bed reaches (its front edge)


def load():
    try:
        with open(FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return dict(size=float(d.get('size', 20.0)), height=float(d.get('height', 5.0)),
                diameter=float(d.get('diameter', 10.0)))


def zones(d=None, shift=0.0):
    """
    The four corner zones as (left, top, right, bottom) in mm from the paper's left / top edges.
    shift: how far the sheet's top edge sits in front of the back of the bed (0 = pushed into the
    corner); the front magnets stay on the bed's front edge, which is then that much higher up the sheet.
    """
    d = d or load()
    s, dia = d['size'], d.get('diameter', 10.0)
    front = ON_BED - shift
    # the back magnets sit as far back as they can: when the sheet is moved forward they go partly on the bed
    # behind it (centred on the sheet's back edge, or pushed against the back of the bed), so they only cover
    # a strip along the sheet's back edge; 2 mm extra for placing them by hand
    back = min(s, max(dia - shift, dia/2) + 2.0)
    return [(0, 0, s, back), (PAPER_W - s, 0, PAPER_W, back),
            (0, front - s, s, front), (PAPER_W - s, front - s, PAPER_W, front)]


def show(d):
    if d['height'] <= 0:
        print('Magnet zones are OFF (height 0). Turn them back on with  ./magnets height 5')
        return
    names = ['top-left (bed corner)', 'top-right', 'bottom-left (bed front edge)', 'bottom-right (bed front edge)']
    print('Magnet zones, {:.0f} mm squares, magnets {:.0f} mm tall (mm from the paper\'s left / top edges):'.format(
        d['size'], d['height']))
    for name, (l, t, r, b) in zip(names, zones(d)):
        print('  {:<30} left {:3.0f}-{:3.0f}, top {:3.0f}-{:3.0f}'.format(name, l, r, t, b))
    print('plotcheck keeps the pen 2 mm out of these while drawing and lifts it over them when travelling.')


def main(argv):
    d = load()
    if len(argv) == 2 and argv[0] in ('size', 'height'):
        try:
            d[argv[0]] = float(argv[1])
        except ValueError:
            sys.exit('give a number in mm, e.g.  ./magnets size 25')
        with open(FILE, 'w') as f:
            json.dump(d, f, indent=1)
    elif argv:
        sys.exit(__doc__)
    show(d)


if __name__ == '__main__':
    if '-h' in sys.argv or '--help' in sys.argv:
        print(__doc__)
    else:
        main(sys.argv[1:])
