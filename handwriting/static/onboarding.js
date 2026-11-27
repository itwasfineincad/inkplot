/* InkPlot's Get started guide, shared by the Write, Plotter and Fonts pages.
   Opens by itself the first time the studio runs; the Setup button in the top bar opens it again.
   Progress is saved by the server (GET/POST /setup, handwriting/setup.json). */
(() => {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const api = (path, body) => fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(r => r.json().then(j => { if (!r.ok) throw new Error(j.error || r.statusText); return j; }));
  const onPlotter = location.pathname.startsWith('/plotter');
  let info = null, step = 0;

  const STEPS = [
    { id: 'welcome', title: 'Welcome' },
    { id: 'printer', title: 'Your printer' },
    { id: 'pen', title: 'Your pen' },
    { id: 'settings', title: 'Printer settings' },
    { id: 'calibrate', title: 'Calibrate the pen' },
    { id: 'first', title: 'Your first plot' },
  ];
  const CHECKS = [
    ['monitoring', 'Print monitoring is off', 'On Bambu printers, turn off air-printing detection and first layer inspection in the printer\'s settings. A plot extrudes nothing, so they can pause it halfway.'],
    ['homing', 'I home only with the pen holder off', 'Homing sends the head to places the holder can\'t go. Home from the printer\'s screen, then clip the holder on.'],
    ['paper', 'Paper goes in the back-left corner', 'Left edge against the left side of the bed, top edge against the back, a magnet on each corner. The Plotter page shows where the magnets go.'],
  ];

  function done(id) {
    const s = info.state, c = s.completed || {};
    if (id === 'welcome') return !!c.welcome;
    if (id === 'printer') return !!c.printer;
    if (id === 'pen') return !!c.pen;
    if (id === 'settings') return CHECKS.every(([k]) => (s.checks || {})[k]);
    if (id === 'calibrate') return info.calibrated || !!c.calibrate;
    if (id === 'first') return !!c.first;
    return false;
  }
  const finished = () => !!info.state.done;
  const save = upd => api('/setup', upd).then(r => { info = r; paintButton(); return r; });

  /* ---- the dialog ---- */
  function build() {
    if ($('onb')) return;
    document.body.insertAdjacentHTML('beforeend', `
<dialog id="onb" class="onb" aria-labelledby="onb-title">
  <div class="onb__grid">
    <nav class="onb__steps" aria-label="Setup steps"><p class="onb__kicker">Get started</p><ol id="onb-list"></ol></nav>
    <div class="onb__main">
      <div class="dh"><h2 id="onb-title"></h2><button class="ghost icon" id="onb-x" aria-label="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>
      <div class="db" id="onb-body"></div>
      <div class="onb__foot"><button class="ghost" id="onb-back">Back</button><span class="onb__count" id="onb-count"></span><button class="primary" id="onb-next">Next</button></div>
    </div>
  </div>
</dialog>`);
    $('onb-x').onclick = close;
    $('onb').addEventListener('cancel', e => { e.preventDefault(); close(); });
    $('onb-back').onclick = () => go(step - 1);
    $('onb-next').onclick = next;
  }
  function close() {
    $('onb').close();
    if (!info.state.dismissed && !finished()) save({ dismissed: true, step });
    else save({ step });
  }
  function open(at) {
    build();
    go(at ?? (info.state.step || 0));
    if (!$('onb').open) $('onb').showModal();
  }
  function go(i) {
    step = Math.max(0, Math.min(STEPS.length - 1, i));
    const list = $('onb-list'); list.innerHTML = '';
    STEPS.forEach((s, k) => {
      const li = document.createElement('li');
      li.className = (k === step ? 'on ' : '') + (done(s.id) ? 'ok' : '');
      li.innerHTML = `<button type="button"><span class="n">${done(s.id) ? '✓' : k + 1}</span>${esc(s.title)}</button>`;
      li.querySelector('button').onclick = () => go(k);
      list.appendChild(li);
    });
    $('onb-title').textContent = STEPS[step].title;
    $('onb-count').textContent = `${step + 1} of ${STEPS.length}`;
    $('onb-back').style.visibility = step ? 'visible' : 'hidden';
    $('onb-next').textContent = step === 0 ? 'Start' : step === STEPS.length - 1 ? 'Finish' : 'Next';
    PAGES[STEPS[step].id]($('onb-body'));
    save({ step });
  }
  async function next() {
    const id = STEPS[step].id;
    try {
      if (id === 'welcome') await save({ completed: { welcome: true } });
      if (id === 'printer') {
        await api('/plot/printers', { action: 'use', id: $('onb-printer').value });
        await save({ completed: { printer: true } });
      }
      if (id === 'pen') {
        const pen = parseFloat($('onb-pen').value), pad = parseFloat($('onb-pad').value || '0');
        if (isNaN(pen)) { $('onb-pen').focus(); return; }
        await api('/plot/machine', { set: { pen, surface: isNaN(pad) ? 0 : pad } });
        await save({ completed: { pen: true } });
      }
      if (id === 'first') {
        await save({ completed: { first: true }, done: true });
        $('onb').close();
        return;
      }
    } catch (e) {
      const err = $('onb-err'); if (err) { err.textContent = e.message; err.hidden = false; }
      return;
    }
    go(step + 1);
  }

  /* ---- the steps ---- */
  const PAGES = {
    welcome(b) {
      b.innerHTML = `
<p class="lead">InkPlot turns your 3D printer into a pen plotter that writes letters by hand. Setting it up takes about 15 minutes, plus printing two small calibration files.</p>
<p class="onb__h">You'll need</p>
<ul class="onb__need">
  <li>Your printer, with a pen holder that clips onto the toolhead</li>
  <li>A fine pen or fineliner, 0.3 to 0.5 mm</li>
  <li>A4 paper and four flat magnets about 10 mm across</li>
  <li>A ruler with millimetres</li>
  <li>The printer's SD card</li>
</ul>
<p class="help">You can leave at any point and carry on later from the <b>Setup</b> button at the top.</p>`;
    },
    printer(b) {
      const ps = info.printers.profiles, cur = info.printer.id;
      b.innerHTML = `
<p class="lead">Which printer is the pen holder on? This sets the bed size and where the holder can go without hitting the frame.</p>
<label class="onb__label" for="onb-printer">Printer</label>
<select id="onb-printer">${ps.map(p => `<option value="${esc(p.id)}"${p.id === cur ? ' selected' : ''}>${esc(p.name)}${p.measured ? '' : ' (not measured)'}</option>`).join('')}</select>
<div class="note info" id="onb-pnote"></div>
<p class="help mt">Not on the list? Choose <b>Other printer</b> for now. Later, on the Plotter page under <b>Machine</b>, make your own profile with your bed size and measured limits.</p>
<p class="onb__err c-warn" id="onb-err" hidden></p>`;
      const note = () => {
        const p = ps.find(q => q.id === $('onb-printer').value) || {};
        $('onb-pnote').innerHTML = esc(p.note || '') + (p.measured ? '' : ' <b>Not measured:</b> do a pen-up run before every new layout.');
      };
      $('onb-printer').onchange = note; note();
    },
    pen(b) {
      b.innerHTML = `
<p class="lead">Push the pen through the holder until its tip sits about <b>10 mm below the nozzle tip</b>. It doesn't need to be exact: calibration sets it precisely.</p>
<div class="fields">
  <label for="onb-pen">Pen tip below the nozzle<small>10 works well</small></label><div class="unit"><input type="number" id="onb-pen" step="0.5" min="3" value="${info.pen ?? 10}"><em>mm</em></div>
  <label for="onb-pad">Pad under the paper<small>a thin card helps the pen press evenly; 0 if none</small></label><div class="unit"><input type="number" id="onb-pad" step="0.5" min="0" value="${info.surface ?? 0}"><em>mm</em></div>
</div>
<p class="help mt">If the pen sticks out less than about 7.5 mm, the nozzle passes low over the magnets and InkPlot keeps drawings away from the corners.</p>
<p class="onb__err c-warn" id="onb-err" hidden></p>`;
    },
    settings(b) {
      const ch = info.state.checks || {};
      b.innerHTML = `<p class="lead">Three habits that keep the holder safe. Tick each one when it's done.</p>` +
        CHECKS.map(([k, t, d]) => `<label class="switch onb__check"><input type="checkbox" data-k="${k}"${ch[k] ? ' checked' : ''}><span class="knob"></span><span><b>${esc(t)}</b><small>${esc(d)}</small></span></label>`).join('');
      b.querySelectorAll('input[data-k]').forEach(i => i.onchange = () => save({ checks: { [i.dataset.k]: i.checked } }).then(() => go(step)));
    },
    calibrate(b) {
      const ok = done('calibrate');
      b.innerHTML = `
<p class="lead">The pen sits beside the nozzle, so InkPlot needs to know exactly where. The Calibrate window takes you through four short steps:</p>
<ol class="onb__ol">
  <li>Set the pen height: the bed comes up to the pen and waits while you slide the pen down to touch the paper.</li>
  <li>Print a calibration cross.</li>
  <li>Measure the cross with a ruler and type in the two numbers.</li>
  <li>Print a check cross to confirm it lands where it should.</li>
</ol>
<div class="note ${ok ? 'info' : ''}">${ok ? `<b>✓ Calibrated</b>${info.calibrated_on ? ' on ' + esc(info.calibrated_on) : ''}. Calibrate again whenever you move the pen or re-clip the holder.` : 'Not calibrated yet. InkPlot won\'t save plot files until it is.'}</div>
<div class="row mt"><button class="primary" id="onb-cal">${ok ? 'Calibrate again' : 'Open calibration'}</button>
<label class="switch onb__inline"><input type="checkbox" id="onb-caldone"${(info.state.completed || {}).calibrate ? ' checked' : ''}><span class="knob"></span><span>I've already calibrated</span></label></div>`;
      $('onb-cal').onclick = () => {
        save({ step });
        if (onPlotter && $('cal-open')) { $('onb').close(); $('cal-open').click(); watchCal(); }
        else location.href = '/plotter#calibrate';
      };
      $('onb-caldone').onchange = e => save({ completed: { calibrate: e.target.checked } }).then(() => go(step));
    },
    first(b) {
      b.innerHTML = `
<p class="lead">Start with a short note and a rehearsal with the pen raised.</p>
<ol class="onb__ol">
  <li>On the <b>Write</b> page, type a short note, press <b>Write it now</b>, then <b>Send to Plotter</b>.</li>
  <li>On the <b>Plotter</b> page, press <b>Plot…</b>, choose <b>Pen up (rehearsal)</b> and save it to the SD card.</li>
  <li>Follow the numbered steps it shows. Watch the rehearsal: the pen stays 10 mm up, and nothing should come near a magnet or the frame.</li>
  <li>All clear? Press <b>Plot…</b> again with <b>Draw</b> for the real thing.</li>
</ol>
<div class="row mt">${location.pathname === '/' ? '' : '<a class="btn" href="/">Go to the Write page</a>'}</div>
<p class="help mt">The full guide, with troubleshooting: <a href="https://github.com/itwasfineincad/inkplot/blob/main/docs/GUIDE.md" target="_blank" rel="noopener">InkPlot guide</a>.</p>`;
    },
  };

  /* after calibrating on the Plotter page, come back to the guide */
  function watchCal() {
    const cal = $('cal');
    if (!cal || cal.dataset.onb) return;
    cal.dataset.onb = '1';
    cal.addEventListener('close', async () => {
      info = await api('/setup');
      paintButton();
      if (!finished()) open(4);
    });
  }

  /* ---- the Setup button in the top bar ---- */
  function paintButton() {
    let b = $('onb-open');
    const tools = document.querySelector('.appbar__tools');
    if (!tools) return;
    if (!b) {
      tools.insertAdjacentHTML('afterbegin', '<button class="toggle onb-open" id="onb-open" title="Setup and calibration, step by step">Setup</button>');
      b = $('onb-open');
      b.onclick = () => open();
    }
    const n = STEPS.filter(s => done(s.id)).length;
    b.classList.toggle('pending', !finished());
    b.textContent = finished() ? 'Setup' : `Setup ${n}/${STEPS.length}`;
  }

  async function start() {
    try { info = await api('/setup'); } catch (e) { return; }
    paintButton();
    if (onPlotter && location.hash === '#calibrate') {
      history.replaceState(null, '', location.pathname);
      // wait for the Plotter page to load the machine settings, then open its Calibrate window
      for (let i = 0; i < 50 && !($('calstate') && $('calstate').textContent.trim()); i++) await new Promise(r => setTimeout(r, 200));
      if ($('cal-open')) { $('cal-open').click(); watchCal(); }
      return;
    }
    if (info.first_run || (!finished() && !info.state.dismissed)) open(info.state.step || 0);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
