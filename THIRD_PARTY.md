# Third-party parts

| Part | Where | Licence |
|---|---|---|
| Handwriting model ([sjvasquez/handwriting-synthesis](https://github.com/sjvasquez/handwriting-synthesis)) | Downloaded by `setup/install.sh` into `handwriting-synthesis/`, not stored in this repository. `setup/model.patch` holds our changes (TensorFlow 2 support, slant and width options, the model returns the characters it wrote). | The original repository has no licence file. Check its terms before you redistribute the model. |
| Geist font by Vercel | `handwriting/static/fonts/` | SIL Open Font License 1.1 (`OFL.txt` next to the files) |
| Line drawings | `blueprints/` | Public domain, CC0 or CC BY-SA, listed per file in `blueprints/CREDITS.md` |
| Python libraries (TensorFlow, NumPy, SciPy, matplotlib, svgelements, Pillow, fontTools; ocrmac on macOS, pillow-heif on Linux) | Installed by `setup/install.sh` | Their own licences |
| Python 3.11 via [uv](https://github.com/astral-sh/uv), only when no Python 3.11 is found | Downloaded by `setup/install.sh` | MIT or Apache 2.0 |
