"""
InkPlot, the handwriting studio: type text and have it written by the AI
handwriting model or by a single-line font (the Write page), then lay it
out with drawings and labels and make checked G-code for the printer (the
Plotter page, see plotjob.py).

    ~/.venvs/handwriting-synthesis/bin/python handwriting_ui.py

Starts a small server on this Mac only (127.0.0.1) and opens the page in your
browser. Close the terminal window (or press Ctrl+C) to quit.

Generated lines are cached in cache/, so the same text and settings always
give the same writing. Settings are remembered in ui_settings.json; saved
files go to out/.
"""
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser

import numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import engines  # noqa: E402
import export  # noqa: E402
import fontimport  # noqa: E402
import penfont  # noqa: E402
from penfont import font as handfont  # noqa: E402
import model_engine as me  # noqa: E402
import plotjob  # noqa: E402
from urllib.parse import unquote  # noqa: E402

APP_NAME = 'InkPlot'
OUT = os.path.join(HERE, 'out')
SETTINGS = os.path.join(HERE, 'ui_settings.json')
PAGE = os.path.join(HERE, 'ui.html')
PLOT_PAGE = os.path.join(HERE, 'plot.html')
FONTS_PAGE = os.path.join(HERE, 'fonts.html')
STYLES = os.path.join(HERE, 'styles.json')     # saved handwriting styles, shared by the Write page and the Plotter
STATIC = os.path.join(HERE, 'static')          # fonts and the icon, served under /static/
STATIC_TYPES = {'.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.png': 'image/png', '.css': 'text/css; charset=utf-8'}


def _d(path, dy):
    return 'M' + ' L'.join('{:.2f},{:.2f}'.format(x, y + dy) for x, y in path)


def render_response(text, style, engine='model', font=None):
    s = me.settings(style)
    lines, missing, skipped = engines.render(text, s, engine, font)
    out, strokes, max_x = [], 0, 0.0
    for i, line in enumerate(lines):
        if line is None:
            out.append(None)
            continue
        out.append([_d(p, (i + 1)*s['line_height']) for p in line])
        strokes += len(line)
        for p in line:
            max_x = max(max_x, float(p[:, 0].max()))
    return dict(lines=out, missing=missing, skipped=skipped, line_height=s['line_height'],
                ink_width=max_x, strokes=strokes, status=me.status(), engine=engines.engine_of(engine))


def load_styles():
    try:
        with open(STYLES) as f:
            data = json.load(f)
        return [s for s in data if isinstance(s, dict) and s.get('name')]
    except (OSError, ValueError):
        return []


def clean_style(d):
    """One saved handwriting style: a name, which engine writes it, and that engine's settings."""
    name = re.sub(r'\s+', ' ', str(d.get('name') or '')).strip()[:40]
    if not name:
        raise ValueError('Give the style a name.')
    return dict(name=name, engine=engines.engine_of(d.get('engine')), style=me.settings(d.get('style')),
                font=engines.font_settings(d.get('font')))


def save_styles(styles):
    tmp = STYLES + '.part'
    with open(tmp, 'w') as f:
        json.dump(styles, f, indent=1, ensure_ascii=False)
    os.replace(tmp, STYLES)


def _name(req, default):
    return re.sub(r'[^\w\- ]+', '', req.get('name') or '').strip() or default


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, ctype='application/json', code=200):
        data = body if isinstance(body, bytes) else json.dumps(body).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(n) or b'{}')

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            with open(PAGE, 'rb') as f:
                self._send(f.read(), 'text/html; charset=utf-8')
        elif self.path == '/settings':
            try:
                with open(SETTINGS) as f:
                    self._send(json.load(f))
            except (OSError, ValueError):
                self._send({})
        elif self.path == '/defaults':
            self._send(dict(style=me.DEFAULTS, font=engines.FONT_DEFAULTS, font_name=penfont.NAME, app=APP_NAME,
                            faces=[dict(id=f, name=n) for f, n in penfont.faces()]))
        elif self.path == '/status':
            self._send(me.status())
        elif self.path == '/styles':
            self._send(load_styles())
        elif self.path.split('?', 1)[0] in ('/fonts', '/fonts/'):
            with open(FONTS_PAGE, 'rb') as f:
                self._send(f.read(), 'text/html; charset=utf-8')
        elif self.path == '/fonts/list':
            self._send(dict(fonts=fontimport.list_fonts(), builtin=penfont.NAME))
        elif self.path.startswith('/fonts/get?id='):
            fid = os.path.basename(unquote(self.path.split('=', 1)[1]))
            path = os.path.join(fontimport.FONTS, fid + '.json')
            if not os.path.isfile(path):
                return self._send({'error': 'No font called ' + fid}, code=404)
            with open(path, 'rb') as f:
                self._send(f.read())
        elif self.path == '/fonts/template.pdf':
            path = os.path.join(HERE, 'cache', 'handwriting-template.pdf')
            if not os.path.isfile(path) or os.path.getmtime(path) < os.path.getmtime(fontimport.__file__):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                fontimport.make_template(path)
            with open(path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Disposition', 'attachment; filename="InkPlot handwriting template.pdf"')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path.startswith('/static/') or self.path == '/favicon.ico':
            self.static_get('icon.svg' if self.path == '/favicon.ico' else unquote(self.path[len('/static/'):]))
        elif self.path.startswith('/plot'):
            try:
                self.plot_get(self.path)
            except (ValueError, RuntimeError, KeyError) as e:
                self._send({'error': str(e)}, code=400)
        else:
            self._send({'error': 'not found'}, code=404)

    def static_get(self, name):
        path = os.path.realpath(os.path.join(STATIC, name))
        ctype = STATIC_TYPES.get(os.path.splitext(path)[1])
        if not ctype or not path.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(path):
            return self._send({'error': 'not found'}, code=404)
        with open(path, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'max-age=86400' if path.endswith('.woff2') else 'no-cache')
        self.end_headers()
        self.wfile.write(data)

    def plot_get(self, path):
        if path in ('/plotter', '/plotter/'):
            with open(PLOT_PAGE, 'rb') as f:
                self._send(f.read(), 'text/html; charset=utf-8')
        elif path == '/plot/state':
            self._send(plotjob.load_state())
        elif path == '/plot/library':
            self._send(plotjob.library())
        elif path.startswith('/plot/thumb/'):
            self._send(plotjob.thumb(unquote(path[len('/plot/thumb/'):])), 'image/svg+xml')
        elif path == '/plot/volumes':
            self._send(plotjob.volumes())
        elif path == '/plot/printers':
            self._send(plotjob.printer_list())
        elif path == '/plot/write':
            try:
                with open(SETTINGS) as f:
                    saved = json.load(f)
            except (OSError, ValueError):
                saved = {}
            self._send(dict(text=saved.get('text', ''), style=me.settings(saved.get('style')),
                            engine=engines.engine_of(saved.get('engine')), font=engines.font_settings(saved.get('font'))))
        else:
            self._send({'error': 'not found'}, code=404)

    def plot_post(self, path, req):
        st = req.get('state') or {}
        if path == '/plot/state':
            plotjob.save_state(req)
            self._send({'ok': True})
        elif path == '/plot/source':
            self._send(plotjob.preview(req.get('src') or {}))
        elif path == '/plot/upload':
            name = plotjob.save_upload(req.get('name'), req.get('svg') or '')
            self._send(dict(name=name, library=plotjob.library()))
        elif path == '/plot/plan':
            self._send(plotjob.public(plotjob.plan(st), bool(req.get('strokes')), bool(req.get('travel'))))
        elif path == '/plot/check':
            res = plotjob.checked(st)
            self._send({k: v for k, v in res.items() if not k.startswith('_')})
        elif path == '/plot/export':
            self._send(plotjob.export(st, req.get('kind', 'plot'), req.get('dest'), req.get('part', 'a'),
                                      req.get('suffix', ''), req.get('title')))
        elif path == '/plot/export_all':
            self._send(plotjob.export_all(req.get('all') or {}, req.get('kind', 'plot'), req.get('dest')))
        elif path == '/plot/eject':
            self._send(plotjob.eject_card(req.get('dest')))
        elif path == '/plot/clean':
            self._send(plotjob.clean_card(req.get('dest'), bool(req.get('really'))))
        elif path == '/plot/placement':
            self._send(plotjob.placement(req))
        elif path == '/plot/pages':
            self._send(plotjob.pages(req))
        elif path == '/plot/machine':
            plotjob.set_machine(req.get('set') or {})
            self._send(plotjob.machine(req.get('settings')))
        elif path == '/plot/printers':
            out = plotjob.printer_action(req)
            out['machine'] = plotjob.machine(req.get('settings'))
            self._send(out)
        elif path == '/plot/cardfiles':
            self._send(plotjob.card_files(req.get('dest')))
        elif path == '/plot/calibrate':
            self._send(plotjob.calibration_file(req.get('step'), req.get('dest'), req.get('settings'),
                                                req.get('a'), req.get('b')))
        elif path == '/plot/add':
            text = (req.get('text') or '').strip()
            if not text:
                raise ValueError('Type something to write first.')
            words = text.split()
            iid = plotjob.add_item(dict(kind='writing', text=req.get('text'), style=me.settings(req.get('style')),
                                        engine=engines.engine_of(req.get('engine')),
                                        font=engines.font_settings(req.get('font'))),
                                   (str(req.get('style_name') or '').strip()[:40] or 'Writing') + ': ' +
                                   ' '.join(words[:4]) + ('…' if len(words) > 4 else ''))
            self._send(dict(id=iid))
        elif path == '/plot/reveal':
            target = os.path.realpath(req.get('path') or '')
            allowed = [os.path.realpath(plotjob.PLOTS), os.path.realpath(os.path.expanduser('~/Downloads'))] + \
                [os.path.realpath(r) for r in plotjob.mount_roots()]
            if not any(target.startswith(a + os.sep) for a in allowed) or not os.path.exists(target):
                raise ValueError('Can only show saved plot files.')
            plotjob.reveal(target)
            self._send({'ok': True})
        else:
            self._send({'error': 'not found'}, code=404)

    def fonts_post(self, path, req):
        import base64
        import tempfile
        name = re.sub(r'\s+', ' ', str(req.get('name') or '')).strip()[:40]
        if path == '/fonts/import':
            if not name:
                raise ValueError('Give the font a name.')
            fname = os.path.basename(str(req.get('filename') or 'file'))
            data = base64.b64decode(str(req.get('data') or '').split(',')[-1])
            if not data:
                raise ValueError('The file was empty.')
            tmp = os.path.join(tempfile.mkdtemp(), fname)
            with open(tmp, 'wb') as f:
                f.write(data)
            report = {}
            fid = fontimport.import_file(tmp, name, report)
            self._send(dict(id=fid, name=name, report=report))
        elif path == '/fonts/draw':
            if not name:
                raise ValueError('Give the font a name.')
            glyphs = {}
            for ch, vers in (req.get('glyphs') or {}).items():
                if not isinstance(ch, str) or len(ch) != 1:
                    continue
                vv = []
                for strokes in vers or []:
                    st = [np.array(s, float) for s in strokes if isinstance(s, list) and len(s) > 1]
                    if st:
                        vv.append(st)
                if vv:
                    glyphs[ch] = vv
            if not glyphs:
                raise ValueError('Draw some letters first.')
            keep = os.path.join(fontimport.FONTS, os.path.basename(str(req.get('keep_from') or '')) + '.json')
            if req.get('keep_from') and os.path.isfile(keep):       # editing a font: keep the letters the grid doesn't show
                with open(keep) as f:
                    old = json.load(f).get('glyphs', {})
                for ch, vers in old.items():
                    if ch not in glyphs:
                        glyphs[ch] = [[np.array(s, float) for s in strokes] for _, strokes in vers]
            font = fontimport.normalise(glyphs, req.get('source') or 'drawn')
            fid = fontimport.save(font, name)
            self._send(dict(id=fid, name=name, glyphs=len(glyphs)))
        elif path == '/fonts/delete':
            fontimport.delete(str(req.get('id') or ''))
            self._send(dict(fonts=fontimport.list_fonts()))
        else:
            self._send({'error': 'not found'}, code=404)

    def do_POST(self):
        try:
            req = self._body()
            if self.path.startswith('/plot/'):
                return self.plot_post(self.path, req)
            if self.path.startswith('/fonts/'):
                return self.fonts_post(self.path, req)
            if self.path in ('/styles', '/styles/delete'):
                name = re.sub(r'\s+', ' ', str(req.get('name') or '')).strip().lower()
                styles = [s for s in load_styles() if s['name'].lower() != name]
                if self.path == '/styles':
                    new = clean_style(req)
                    styles.append(new)
                    styles.sort(key=lambda s: s['name'].lower())
                save_styles(styles)
                return self._send(styles)
            text, style = req.get('text', ''), req.get('style')
            engine, font = req.get('engine', 'model'), req.get('font')
            if self.path == '/render':
                self._send(render_response(text, style, engine, font))
            elif self.path == '/generate':
                engines.generate(text, style, engine, font)
                self._send(render_response(text, style, engine, font))
            elif self.path == '/logo':
                paths = handfont.text_paths(APP_NAME, 0, 0, 6, style=handfont.Style(tidiness=1))
                self._send(dict(paths=[_d(p, 0) for p in paths]))
            elif self.path == '/settings':
                with open(SETTINGS, 'w') as f:
                    json.dump(req, f, indent=2, ensure_ascii=False)
                self._send({'ok': True})
            elif self.path == '/save':
                s = me.settings(style)
                lines, missing, _ = engines.render(text, s, engine, font)
                if missing:
                    raise ValueError('{} line(s) are not written yet. Wait for the writing to finish, or press Write it now.'.format(missing))
                os.makedirs(OUT, exist_ok=True)
                files = export.save(os.path.join(OUT, _name(req, 'handwriting') + '.svg'), lines, s['line_height'],
                                    dict(text=text, style=s), split=bool(req.get('split', True)))
                self._send({'files': [dict(name=os.path.basename(p), offset=o) for p, o in files]})
            elif self.path == '/reveal':
                name = os.path.basename(req.get('name', ''))
                target = os.path.join(OUT, name)
                plotjob.reveal(target if name and os.path.exists(target) else OUT)
                self._send({'ok': True})
            else:
                self._send({'error': 'not found'}, code=404)
        except (ValueError, RuntimeError, KeyError) as e:
            self._send({'error': str(e)}, code=400)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # the browser hung up mid-reply (a reload, a page change, a newer preview replacing an older one): harmless
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def main():
    port = next((int(a) for a in sys.argv[1:] if a.isdigit()), 0)
    for p in ([port] if port else range(8765, 8800)):
        try:
            server = Server(('127.0.0.1', p), Handler)
            break
        except OSError:
            continue
    else:
        sys.exit('no free port')
    me.load_in_background()
    threading.Thread(target=plotjob.warm_thumbs, daemon=True).start()
    url = 'http://127.0.0.1:{}/'.format(server.server_address[1])
    print('Handwriting studio running at ' + url)
    print('Close this window or press Ctrl+C to quit.')
    if '--no-browser' not in sys.argv:
        threading.Timer(0.4, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
