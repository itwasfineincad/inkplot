# InkPlot

Turn a 3D printer into a pen plotter that writes letters in realistic handwriting, including your own.

<!-- Replace this picture with a short GIF or video of the printer writing (docs/images/writing.gif). -->
![InkPlot's Plotter page: a handwritten note and a Porsche line drawing laid out on an A4 sheet, marked safe to plot](docs/images/plotter.png)

## Install

macOS or Linux, about 2 GB free. Paste this into Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/itwasfineincad/inkplot/main/setup/get.sh | bash
```

It puts InkPlot in `~/InkPlot` and fetches Python 3.11 if you don't have it. Run the same line again to update.

To start it, double-click `handwriting/My Handwriting.command` on a Mac, or pick InkPlot in the app menu on
Linux (or run `inkplot`). It opens in your browser. Before your first plot, choose your printer and calibrate the
pen under Plotter > Machine, then use Plot… and do a pen-up run first. The [guide](docs/GUIDE.md) walks through
every step.

## What you get

You type a letter and an AI model writes it out in one of 13 hands, or in a single-line font. You can make that
font from your own handwriting: draw the letters on screen, fill in a printed template and scan it, or import a
font file.

On the Plotter page you lay the writing out on A4 with line drawings, your own SVGs, labels, frames and ruled
lines. Anything the pen can't reach shows in red. Long letters flow over as many sheets as they need, and the
bottom of each sheet is written after you turn it round, because the pen can't reach it in one go. If you write
on lined paper, InkPlot works out where to put the sheet so the writing lands on the lines.

When you press Plot…, you pick the pages, choose a pen-up rehearsal or the real thing, and save straight to the
printer's SD card. You then get numbered steps for each file: where the paper goes and which file to print.

Every file is checked before it's saved. It never homes the printer, keeps the nozzle inside the safe area,
keeps the pen on the paper and away from the magnets, and records the pen, pad and printer it was made for, so
an old file is refused once you change any of them.

| Write | Fonts |
|---|---|
| ![The Write page with AI handwriting on ruled paper](docs/images/write.png) | ![The Fonts page with boxes to draw each letter](docs/images/fonts.png) |

## What's tested

It was built and measured on a Bambu Lab X1E with the UMTS pen holder, and that's the only printer it has
plotted on. The X1, X1 Carbon, P1S and P1P profiles copy the X1E's numbers. The A1, A1 mini and "other printer"
profiles are guesses. On any of those, measure your printer first ([Other printers](docs/GUIDE.md#12-other-printers))
and do a pen-up run before you plot. The installer has been tested on macOS (Apple silicon) and Ubuntu 24.04 (ARM).

A wrong move can drive the pen holder into the frame or a magnet. InkPlot checks every file, but it can only
check against the numbers you give it.

## Help and feedback

Found a problem or got it working on another printer? [Open an issue](https://github.com/itwasfineincad/inkplot/issues/new/choose)
and say which printer and profile you used. Measurements for the untested printers are the most useful thing
you can send. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Files

```
handwriting/            the studio: server, Write, Plotter and Fonts pages, plotter engine, fonts
handwriting-synthesis/  safety checker, calibration, magnet and printer-profile tools; the AI model goes here
blueprints/             line drawings to plot, with credits
setup/                  get.sh (one-command install), install.sh and the patch applied to the AI model
inkplot                 starts the studio
docs/                   the guide and its pictures
.claude/skills/         a Claude Code skill that coaches you through making a handwriting font
```

Check any G-code file on its own: `handwriting-synthesis/plotcheck path/to/file.gcode`

## Licence

InkPlot's own code is free for noncommercial use under the [PolyForm Noncommercial License 1.0.0](LICENSE):
use it, change it and share it, but don't sell it. The AI handwriting model, the Geist font and the drawings
keep their own licences; see [THIRD_PARTY.md](THIRD_PARTY.md). Made by [It Was Fine In CAD](https://github.com/itwasfineincad).
