---
name: handwriting-font
description: Make a single-line pen-plotter font from someone's own handwriting for InkPrint (this project's handwriting studio), and coach the person through it step by step. Use this whenever the user wants the plotter to write "in my handwriting", wants to turn a scan or photo of their writing into a font, wants to draw their letters on screen, has a Calligraphr / FontCrafter / iFontMaker / FontForge .ttf or .otf they want to plot, has a single-line SVG font (Inkscape Hershey Text, Custom Stroke Font), or asks why an ordinary handwriting font plots as double lines. Also use it when a font they made looks wrong (missing letters, broken strokes, wrong size) and needs fixing.
---

# Handwriting fonts for InkPrint

A pen plotter draws the *path the pen travels*. Ordinary fonts (including every handwriting font from
Calligraphr, FontCrafter and similar sites) store the *outline* of each letter, so a plotter draws each
stroke twice, as a hollow double line. InkPrint needs a **single-line font**: one line down the middle of
every stroke. No mainstream tool makes a single-line font from handwriting, so InkPrint does it itself,
three ways. All three save the same kind of font and show up in the same places.

| Route | Best for | What the person does | Quality |
|---|---|---|---|
| **Draw it** (Fonts page) | Mouse, trackpad or drawing tablet users; quick start | Draws each character in a box on screen | Exactly the strokes they draw |
| **Scan a template** | Real pen-on-paper handwriting | Prints a template, writes in it, scans or photographs it | Their real pen strokes, traced to the centre line |
| **Import a font file** | Someone who already made a font elsewhere | Uploads the .ttf / .otf / .svg | Good; outline fonts are traced to centre lines |

Everything lives in `handwriting/`: the page is `fonts.html` (served at http://127.0.0.1:8765/fonts while
the studio runs), the work is done by `fontimport.py`, and fonts are saved to `handwriting/fonts/<id>.json`.
Read `references/how-it-works.md` only if you need to debug or change the importer itself.

## How to talk the person through it

Most people who use InkPrint are not programmers.
Give one step at a time, exact numbers (100% scale, 300 dpi), and say what they should see. Don't mention
JSON, skeletons or homographies. Ask which route suits them if it isn't obvious; if they have a scanner or
a phone and want their *real* handwriting, recommend the template. If they just want to try it, drawing on
screen takes ten minutes.

Their handwriting font is personal: it lets anyone write in their hand. Say once that it stays on their
Mac (`handwriting/fonts/` is git-ignored) and should not be shared or committed.

### Route 1: draw it on screen

1. Start the studio (double-click `handwriting/My Handwriting.command`) and open the **Fonts** tab.
2. Click **New font** and type a name, e.g. "Jo's hand".
3. In each box, write the character so it **sits on the solid line**. Small letters (a, c, e, n, o…) reach
   the **dashed line**; tall letters and capitals go above it, tails (g, j, p, y) below.
4. Lowercase letters have **two boxes**. Draw them a little differently: InkPrint mixes the two so repeated
   letters don't look stamped.
5. ⌘Z undoes the last stroke; hover a box and click × to clear it.
6. Click **Save font**, then type something in **Try it** to check it.

Anything they don't draw is written in the built-in font, so they can start with just the lowercase
letters. A drawing tablet or an iPad used as a tablet (Sidecar) gives the most natural result; a trackpad
works but letters come out stiffer.

### Route 2: scan a template (their real handwriting)

1. On the **Fonts** tab click **Download the template**, or make it yourself:
   `cd handwriting && ~/.venvs/handwriting-synthesis/bin/python fontimport.py template ~/Desktop/template.pdf`
2. Print it at **100% / actual size** (not "fit to page").
3. Write each character in its box with a **dark pen**: black or dark blue, 0.4–0.7 mm. Pencil and light
   colours don't scan. Sit letters on the solid line, small letters up to the dashed line, keep inside the
   box, and write lowercase twice (the template has two sets).
4. Scan at **300 dpi**, or photograph the page flat, in even light, straight from above, with **all four
   black corner squares** in the picture. PNG, JPG, PDF and iPhone photos (HEIC) all work. On an iPhone,
   Notes > Scan Documents also works well (it flattens the page); AirDrop the result to the Mac.
5. On the **Fonts** tab click **Upload the scan…**, or run:
   `~/.venvs/handwriting-synthesis/bin/python fontimport.py scan path/to/scan.jpg --name "Jo's hand"`
6. The result lists **empty boxes** and characters **not in it**. Then check it by eye (next section).

### Route 3: import a font made with another tool

- **Calligraphr** (free plan: 75 characters), **FontCrafter**, **iFontMaker**, **FontForge**: download the
  **.ttf** or **.otf**, then **Import a font file…** on the Fonts tab, or
  `fontimport.py font MyHand.ttf --name "Jo's hand"`. The outlines are traced down to their centre lines.
  Before importing, glance at the font's own name (fontTools `name` table, IDs 1 and 4). If it is a font
  that ships with macOS or someone else's font rather than one they made, say so and ask: it won't be
  their handwriting, and it must never go into the public release.
  A font file has one shape per letter, so repeated letters look identical; the scan template (two of
  each small letter) gives more natural variety.
  Bold, even-width fonts trace best; very thin hairlines or heavily textured fonts trace badly.
- **Single-line SVG fonts** (Inkscape's Hershey Text, or the Custom Stroke Font extension) are already pen
  lines: `fontimport.py svgfont MyStrokes.svg --name "..."` or the same button.

## Check the font before anyone plots with it

Always look at it. Draw a sample and read the picture:

```bash
cd handwriting && ~/.venvs/handwriting-synthesis/bin/python fontimport.py preview <font id> /tmp/font.png
```

(use the scratchpad instead of /tmp when you have one; `--text "..."` draws your own sample). The
preview is upright, as the letters were written. Look for, and fix:

- **Letters missing or replaced by print letters**: the box was empty, too faint, or outside the box. Ask
  them to redraw just those letters on the Fonts tab (open the font, redraw the boxes, Save), or rescan.
- **Broken letters / extra bits**: smudges, a pen that skipped, or a crossing that traced oddly. Redraw
  that letter on the Fonts tab; it replaces only that letter.
- **Wrong size relationships** (capitals tiny, small letters huge): the small letters didn't reach the
  dashed line consistently. The font's size is measured from a, c, e, m, n, o, r, s, u, v, w, x, z.
- **Dots missing on i, j, !, ?**: the dot was too small or faint; redraw it a bit bigger.

`fontimport.py list` shows every font and how many characters it has. A font with fewer than about 40
characters will lean heavily on the built-in font.

## Using the font

Tell them about **Slant**: the Write page's font settings lean letters forward by default (Slant 0.42,
about 23°), made for the built-in hand. Someone who writes upright should set **Look > Slant** to **0**
before saving the style.

- **Write page**: switch the text box to the font mode (the second button beside "Text"), open **Look** and
  choose it under **Font**. Then **Save style** so it can be picked in the Plotter.
- **Plotter**: Add > Handwriting or Page of writing, choose the saved style; labels have their own **Font**
  list in the Selected panel.
- Plots made with it go through the same safety checks as everything else; nothing about the printer
  changes.

## When something fails

| Message | What to tell them |
|---|---|
| Could not read that picture / iPhone photo | Export it from Preview as JPEG (File > Export) and upload that. |
| Couldn't find all four black squares | Rescan or rephotograph the whole page so all four corner squares show, nothing covering them. |
| No small letters came out | The pen is too light or the scan too dark; use a black pen and scan at 300 dpi in colour. |
| That SVG has no `<font>` in it | It's a drawing, not an SVG font; use the drawing in the Plotter (Upload SVG) instead. |
| Use a scan, a .ttf / .otf font, or a single-line .svg font | Wrong file type, e.g. .woff; convert it to .ttf first. |

To delete a font: Fonts tab > Delete (click twice), or `fontimport.py delete <id>`.
