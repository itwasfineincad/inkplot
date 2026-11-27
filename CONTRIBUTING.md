# Contributing to InkPlot

Thanks for trying it. Here's how to help.

## Report a problem

[Open an issue](https://github.com/itwasfineincad/inkplot/issues/new/choose) and pick "Something went wrong".
Say which printer and printer profile you used (Plotter > Machine > Printer), your computer (macOS or Linux),
and what you saw. If a plot went wrong, attach the `.gcode` file, or the first 20 lines of it: they record the
setup it was made for.

## Measure a printer

Only the Bambu Lab X1E has been measured. If you have another printer, its numbers are the most useful thing you
can send:

1. In InkPlot, go to Plotter > Machine > New profile….
2. Measure where the nozzle can safely go with your pen holder on (the steps are in the profile window and in
   the [guide](docs/GUIDE.md#12-other-printers)).
3. Do a pen-up run and an outline run, then a real plot.
4. Open an issue with "Printer profile" and paste the numbers, the pen holder you used and how the plot went.

## Change the code

- Fork the repo and make your change on a branch.
- Test on a separate copy of the studio, not your real one:
  `PLOTTER_STATE=/tmp/test_state.json INKPLOT_CONFIG=/tmp/cfg INKPLOT_PLOTS=/tmp/plots python handwriting_ui.py 8766 --no-browser`
- Every G-code file must still go through `plotcheck` before it's written. Don't add G28 (homing), arcs or any
  move outside the profile's safe area.
- Check any file you make with `handwriting-synthesis/plotcheck FILE.gcode`.
- Keep the app's wording short and plain.

By contributing, you agree your changes are shared under the same licence as InkPlot
([PolyForm Noncommercial 1.0.0](LICENSE)).
