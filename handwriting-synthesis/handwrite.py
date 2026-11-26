"""
Turn text into an SVG in AI handwriting, ready for BambuPlot.

    ./handwrite "Dear Alex, thanks for the lovely gift!" -o out/thanks.svg
    ./handwrite -f message.txt -o out/card.svg --line-height 7

Each newline in the text starts a new line; long lines are wrapped.
"""
import argparse
import os
import sys
import textwrap

import drawing

# characters the model can't draw -> closest thing it can
SUBSTITUTES = {
    'Q': 'q', 'X': 'x', 'Z': 'z',
    '‘': "'", '’': "'", '“': '"', '”': '"',
    '–': '-', '—': '-', '…': '...',
    '&': 'and', '/': '-', '\t': ' ',
}


def clean(text):
    allowed = set(drawing.alphabet)
    out, dropped = [], set()
    for ch in text:
        ch = SUBSTITUTES.get(ch, ch)
        for c in ch:
            if c in allowed or c == '\n':
                out.append(c)
            else:
                dropped.add(c)
    if dropped:
        print('warning: skipped unsupported characters: ' + ' '.join(sorted(dropped)), file=sys.stderr)
    return ''.join(out)


def to_lines(text, wrap):
    lines = []
    for para in text.split('\n'):
        para = ' '.join(para.split())
        lines.extend(textwrap.wrap(para, wrap) if para else [''])
    while lines and not lines[-1]:
        lines.pop()
    return lines


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('text', nargs='?', help='text to write (or use -f)')
    p.add_argument('-f', '--file', help='read text from a file')
    p.add_argument('-o', '--output', default='out/handwriting.svg', help='output SVG (default: %(default)s)')
    p.add_argument('--line-height', type=float, default=8.0,
                   help='line spacing in mm (default: %(default)s, standard ruled paper)')
    p.add_argument('--letter-size', type=float, default=2.3,
                   help='average width of a character in mm (default: %(default)s)')
    p.add_argument('--wrap', type=int, default=60, help='max characters per line (default: %(default)s, max 75)')
    p.add_argument('--attempts', type=int, default=6, help='versions generated per line; best is kept (default: %(default)s)')
    p.add_argument('--bias', type=float, help='neatness; higher is tidier (default 0.75)')
    p.add_argument('--slant', type=float, help='forward lean (default 0.35)')
    p.add_argument('--width', type=float, dest='x_scale', help='letter width multiplier (default 0.7)')
    p.add_argument('--style', type=int, help='built-in writer 0-12 (default 11)')
    args = p.parse_args()

    if args.file:
        with open(args.file) as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        p.error('give some text or -f FILE')

    lines = to_lines(clean(text), min(args.wrap, drawing.MAX_CHAR_LEN))
    if not any(lines):
        p.error('no text to write')

    overrides = {k: v for k, v in dict(bias=args.bias, slant=args.slant, x_scale=args.x_scale,
                                       style=args.style).items() if v is not None}

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    print('Writing {} line(s)...'.format(len(lines)))

    from my_hand import write_plotter_svg  # slow import (TensorFlow), so after arg checks
    written = write_plotter_svg(args.output, lines, line_height_mm=args.line_height,
                               char_width_mm=args.letter_size, attempts=args.attempts, **overrides)

    print()
    for path, rows in written:
        print('Saved {}  ({} lines)'.format(path, rows))
    print('\nIn BambuPlot: Image tab -> drop in the SVG -> "Vector outlines" -> Convert & add to bed.')
    print("It comes in at real size; move it, but don't resize it.")
    print('The top edge of its box is the ruled line above your first line of text.')
    if len(written) > 1:
        print('Each file continues where the last stopped. Put the top edge of each one this far below the first:')
        down = 0
        for path, rows in written:
            print('  {:>5.0f} mm  {}'.format(down, os.path.basename(path)))
            down += rows*args.line_height


if __name__ == '__main__':
    main()
