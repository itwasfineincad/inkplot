# InkPrint

InkPrint turns a 3D printer with a clip-on pen holder into a pen plotter for handwriting. Type a letter, and an AI handwriting model (or a single-line font) writes it out. Lay it out on A4 with line drawings and labels, then save G-code that has already passed a set of safety checks.

It was built for a **Bambu Lab X1E** with a **UMTS pen holder** and runs entirely on your Mac. Nothing is uploaded anywhere.

Made by [It Was Fine In CAD](https://github.com/itwasfineincad).

> **Safety first.** A wrong move can drive the pen holder into the printer's frame or the bed magnets. InkPrint never homes the printer, keeps the nozzle inside a measured safe area and checks every file before saving it, but those limits were measured on one machine. Measure your own (see *Your printer* below), and print the **Pen up** rehearsal of every new job before the real one.

## What it does

- **Write page**: an AI model writes your text in one of 13 handwriting styles, with sliders for neatness, slant, letter size, joined-up writing and occasional crossed-out mistakes. Each line is written several times and the most readable version is kept. A single-line font gives instant results. Save any mix of settings as a **handwriting style** and use several styles on one page.
- **Plotter page**: place handwriting, line drawings (25 are included), uploaded SVGs, labels, frames, circles and ruled lines on the sheet. Drag, resize and rotate them; anything the pen can't reach is shown in red.
- **Writing on lined paper**: measure your paper's lines and InkPrint works out where to put the sheet so the writing lands on them.
- **Whole pages**: the bottom of an A4 sheet is out of reach, so lines near the bottom are written in a second part with the sheet turned round. Print jobs come with step-by-step instructions.
- **Fonts page**: make a font from your own handwriting (see below).
- **Preview**: watch a simulation of the pen, nozzle and holder before you print.
- **Checked G-code**: every file passes `plotcheck` (safe area, pen height, magnet zones, no homing, no arcs) before it is written. Save it to a folder or straight to the printer's SD card.

## Install

You need macOS and Python 3.11: with [Homebrew](https://brew.sh), run `brew install python@3.11` (a Python 3.11 installed with `uv` works too). About 2 GB of free disk space is needed for TensorFlow and the model.

1. Download this repository (**Code > Download ZIP**, then unzip it) or clone it:
   `git clone https://github.com/itwasfineincad/inkprint.git`
2. Double-click **Install InkPrint.command**. It makes a Python environment in `~/.venvs/handwriting-synthesis`, installs TensorFlow and the other libraries, and downloads the handwriting model. This takes a few minutes the first time.
3. Double-click **handwriting/My Handwriting.command**. The studio opens in your browser at `http://127.0.0.1:8765`.

The AI model loads in the background; the first piece of writing takes a little longer.

## Before your first plot

1. **Calibrate.** On the Plotter page open **Calibration > Calibrate** and follow the four steps: set the pen length, draw a calibration cross, measure it, and print a check cross. Do this again whenever you move the pen in the holder.
2. **Turn off the printer's print monitoring** (spaghetti detection, air-printing detection, first layer inspection). The printer extrudes nothing while plotting, and these checks can pause it mid-plot.
3. **Home with the holder off**, then clip it on. Never home, resume or stop a print with the holder on.
4. Print the **Pen up** version of a job first and watch it.

## Your printer

The machine model lives in `handwriting-synthesis/plotcheck.py` (safe area for the nozzle, `SAFE_X` and `SAFE_Y`), `handwriting-synthesis/magnets.py` (magnet sizes) and `handwriting-synthesis/calibration.json` (pen length, pad under the paper, pen offset). The defaults are for an X1E with a 256 x 256 mm bed, A4 paper in the back-left corner and the pen 24.5 mm left of and 37 mm in front of the nozzle. Other printers need these values measured and changed.

Check any G-code file on its own:

```bash
handwriting-synthesis/plotcheck path/to/file.gcode
```

## Your own handwriting as a font

A pen plotter needs a **single-line** font: one line down the middle of each stroke. Ordinary fonts, including handwriting fonts from Calligraphr or FontCrafter, store outlines, so a plotter draws every stroke twice. The **Fonts** page makes single-line fonts three ways:

- **Draw it**: draw each letter in a box with a mouse, trackpad or drawing tablet.
- **Scan a template**: click **Download the template**, print it at 100%, write each letter in its box with a dark pen, then scan it or photograph it (all four black corner squares must show). **Upload the scan…** turns it into a font. PNG, JPG, PDF and iPhone photos work.
- **Import a font file**: a .ttf or .otf (traced down to its centre lines) or a single-line SVG font (Inkscape Hershey Text).

Then pick the font on the Write page (font mode, **Look > Font**), set **Slant** to 0 if you write upright, and **Save style** to use it on the Plotter page. Fonts are saved in `handwriting/fonts/`, which is in `.gitignore`: your handwriting stays on your Mac.

If you use [Claude Code](https://claude.com/claude-code), the `handwriting-font` skill in `.claude/skills/` walks you through it.

## Files

```
handwriting/            the studio: server, Write and Plotter pages, plotter engine, fonts
handwriting-synthesis/  safety checker, calibration and magnet tools; the AI model is installed here
blueprints/             line drawings to plot, with credits
setup/                  installer and the patch applied to the AI model
```

## Licence

InkPrint's own code is free for noncommercial use under the [PolyForm Noncommercial License 1.0.0](LICENSE). The AI model, the Geist font and the drawings keep their own licences; see [THIRD_PARTY.md](THIRD_PARTY.md).
