# How InkPlot's handwriting fonts work (for debugging or changing them)

## Files

- `handwriting/fontimport.py` — template, scan reader, font-file tracer, SVG-font reader, preview, CLI.
- `handwriting/fonts.html` — the Fonts page (draw grid, upload, import, list, try it).
- `handwriting/penfont.py` — `get(face)` loads a saved font as a font module; `faces()` lists them.
- `handwriting/engines.py` — the font settings carry `face` ('' = built-in); `font_of()` picks the module.
- `handwriting/handwriting_ui.py` — routes: GET /fonts (page), /fonts/list, /fonts/get?id=, /fonts/template.pdf;
  POST /fonts/import {name, filename, data (base64 data URL)}, /fonts/draw {name, glyphs, keep_from, source},
  /fonts/delete {id}.

## Font file format (`handwriting/fonts/<id>.json`)

```
{ "id": "jos-hand", "name": "Jo's hand", "made": "2026-11-25", "source": "scan|drawn|edited|font file ...|single-line SVG font",
  "cap": 1.45,               # capital height in x-heights
  "x_height_mm": 6.0,        # scan only: how big they wrote
  "glyphs": { "a": [ [width, [ [[x, y], ...], ... ]], [width, strokes] ], ... } }
```

Units: x-height = 1, baseline = 0, y up, each version starting at x = 0 (the same units as plainfont.py's
`G` table). A character can have several versions; the writer picks one at random per occurrence.

## How a saved font becomes writing

`penfont.load_user()` runs a fresh copy of plainfont.py's code with its glyph table replaced and its glyph
lookup swapped for one that picks between versions (`_pick(ch, rng)`). Characters the font lacks are
borrowed from the print font, scaled to the font's capital height; accented letters are composed from the
font's own plain letters (charset.py). The result is wrapped like the built-in fonts (typographic
characters cleaned first). It is cached and reloaded when the file changes.

## Scan reader (`from_scan`)

1. Load as grey (PIL). PDFs are rendered at about 300 dpi with macOS `qlmanage` (sips as a fallback);
   iPhone HEIC photos are converted to JPEG with `sips` (the venv's Pillow can't read HEIC).
2. Find the four black corner squares: dark connected blobs that are square, solid, about 6 mm, nearest
   each image corner (`find_marks`).
3. Homography from template mm to picture pixels; each cell resampled at 0.08 mm per pixel.
4. Ink = darker than an Otsu threshold (capped at 0.62). The printed guides and labels are light enough to
   fall outside it. A 0.9 mm border and the label corner are ignored.
5. Thin the ink to a one-pixel centre line (Zhang–Suen), trace it into pieces between ends and junctions
   (diagonal links only where no side link exists, otherwise staircases look like junctions), drop short
   whiskers, join pieces that carry straight on through a junction, smooth, simplify (RDP 0.05 mm).
   Blobs with no line through them, and lines under 0.3 mm, become dots.
6. `normalise()`: x-height = median top of the short lowercase letters; everything scaled to x-height
   units, each version shifted to start at x = 0.

Template geometry is in the constants at the top of fontimport.py (MARKS, GRID_X0/Y0, CELL_W/H, BASE, XH,
CHARS). Change them together; the template and the reader share them.

## Font-file tracer (`from_outline_font`)

matplotlib's TextPath gives each glyph's outline; it is filled even-odd on a 0.1 mm grid at a 40 mm em and
traced with the same centre-line code. fontTools' cmap limits the characters to the ones the font has.

## Draw grid

Cells are 96 x 160 px: baseline at 102 px, x-height guide 36 px above it (= 1 unit), x origin at 10 px.
Strokes are sent in font units; saving an edited font sends `keep_from` so characters the grid doesn't
show (accents in an imported font) are kept.

## Testing without a real scan

Draw plainfont's glyphs into the template PNG with PIL (dark lines 0.5 mm wide, x-height 6 mm, baseline at
BASE), rotate it a couple of degrees and shrink it, save as JPG, then `fontimport.py scan`. The preview
should match plainfont, dots included.
