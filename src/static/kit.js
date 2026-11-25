/* Page kit: the shared building blocks for dashboard pages (formatting, filters, tiles, tables, CSV, charts, maps).
 * Pages should use these instead of hand-writing their own, so every dashboard looks and behaves the same.
 * Reference with examples: docs/AUTHORING.md. */
(() => {
  const LOCALE = (window.PORTAL && window.PORTAL.locale) || undefined;  // locale: in src/environments.yml
  const num = (v) => (v === null || v === undefined || v === '' || isNaN(+v) ? null : +v);
  const dash0 = '–';

  const fmt = {
    num: (v, dp = 0) => (num(v) === null ? dash0 : num(v).toLocaleString(LOCALE, { minimumFractionDigits: dp, maximumFractionDigits: dp })),
    money: (v, dp = 0) => (num(v) === null ? dash0 : (num(v) < 0 ? '-$' : '$') + Math.abs(num(v)).toLocaleString(LOCALE, { minimumFractionDigits: dp, maximumFractionDigits: dp })),
    compact: (v) => {
      const n = num(v);
      if (n === null) return dash0;
      const a = Math.abs(n);
      const s = a >= 1e9 ? (a / 1e9).toFixed(1) + 'b' : a >= 1e6 ? (a / 1e6).toFixed(1) + 'm' : a >= 1e3 ? (a / 1e3).toFixed(0) + 'k' : a.toFixed(0);
      return (n < 0 ? '-' : '') + s;
    },
    pct: (v, dp = 1) => (num(v) === null ? dash0 : (num(v) * 100).toFixed(dp) + '%'),
    date: (v) => { const d = v ? new Date(String(v).slice(0, 10) + 'T00:00:00') : null; return d && !isNaN(d) ? d.toLocaleDateString(LOCALE, { day: 'numeric', month: 'short', year: 'numeric' }) : dash0; },
    month: (v) => { const d = v ? new Date(String(v).slice(0, 7) + '-01T00:00:00') : null; return d && !isNaN(d) ? d.toLocaleDateString(LOCALE, { month: 'short', year: 'numeric' }) : dash0; },
    text: (v) => (v === null || v === undefined || v === '' ? dash0 : String(v)),
  };

  /* h('div', {class: 'x', onclick: fn}, 'text', child) -> element. Text is always set as text, never as HTML. */
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'class') el.className = v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid.nodeType ? kid : String(kid));
    return el;
  }
  const mount = (el) => (typeof el === 'string' ? document.querySelector(el) : el);
  const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const daysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return isoDate(d); };

  /* Shows a loading or error message in `el` unless every dataset is ready. Returns true when ready. */
  function ready(el, ...datasets) {
    el = mount(el);
    const bad = datasets.find((d) => d.status !== 'ok');
    if (!bad) { el.querySelector(':scope > .kit-state')?.remove(); return true; }
    const msg = bad.status === 'loading' ? 'Loading…' : bad.status === 'forbidden' ? 'You don’t have access to this section.' : 'Couldn’t load this data: ' + (bad.message || bad.status);
    el.replaceChildren(h('div', { class: 'kit-state kit-state-' + bad.status, role: bad.status === 'error' ? 'alert' : 'status' }, msg));
    return false;
  }

  /* Filter bar. specs: [{id, label, type: 'select' | 'multi' | 'date' | 'search', options: [..] | [{value, label}], value, all: 'All'}]
   * Returns {values(), set(id, value), options(id, list)}; onChange(values, changedId) runs on every change. */
  function filters(el, specs, onChange) {
    el = mount(el);
    el.classList.add('kit-filters');
    const state = {}; const inputs = {};
    const fire = (id) => onChange && onChange({ ...state }, id);
    const fill = (spec, list) => {
      const sel = inputs[spec.id];
      const opts = (list || []).map((o) => (o !== null && typeof o === 'object' ? o : { value: o, label: o }));
      const keep = spec.type === 'multi' ? new Set(state[spec.id] || []) : state[spec.id];
      sel.replaceChildren(...(spec.type === 'select' && spec.all !== false ? [h('option', { value: '' }, spec.all || 'All')] : []),
        ...opts.map((o) => h('option', { value: o.value }, o.label)));
      if (spec.type === 'multi') { for (const o of sel.options) o.selected = keep.has(o.value); state[spec.id] = [...sel.selectedOptions].map((o) => o.value); }
      else { sel.value = opts.some((o) => String(o.value) === String(keep)) ? keep : ''; state[spec.id] = sel.value; }
    };
    for (const spec of specs) {
      let input;
      if (spec.type === 'date') input = h('input', { type: 'date', value: spec.value || '', min: spec.min, max: spec.max });
      else if (spec.type === 'search') input = h('input', { type: 'search', placeholder: spec.placeholder || 'Search', value: spec.value || '' });
      else input = h('select', { multiple: spec.type === 'multi', size: spec.type === 'multi' ? spec.size || 4 : null });
      input.id = 'kit-f-' + spec.id;
      inputs[spec.id] = input;
      state[spec.id] = spec.type === 'multi' ? spec.value || [] : spec.value ?? '';
      if (input.tagName === 'SELECT') fill(spec, spec.options);
      input.addEventListener(spec.type === 'search' ? 'input' : 'change', () => {
        state[spec.id] = spec.type === 'multi' ? [...input.selectedOptions].map((o) => o.value) : input.value;
        fire(spec.id);
      });
      el.append(h('label', { class: 'kit-filter', for: input.id }, h('span', null, spec.label), input));
    }
    return {
      values: () => ({ ...state }),
      set(id, value) { state[id] = value; const i = inputs[id]; if (i.multiple) for (const o of i.options) o.selected = value.includes(o.value); else i.value = value; },
      options(id, list) { fill(specs.find((s) => s.id === id), list); },
    };
  }

  /* KPI tiles. items: [{label, value, note, tone: 'ok' | 'warn' | 'bad'}] (value already formatted). */
  function tiles(el, items) {
    el = mount(el);
    el.classList.add('kit-tiles');
    el.replaceChildren(...items.map((t) => h('div', { class: 'kit-tile' + (t.tone ? ' kit-' + t.tone : '') },
      h('span', { class: 'kit-tile-label' }, t.label), h('strong', null, t.value), t.note ? h('span', { class: 'kit-tile-note' }, t.note) : null)));
  }

  // Cells whose first character, or first non-whitespace character, is = + - @ TAB CR or full-width ＝＋－＠ get a ' prefix so Excel won't run them as formulas (xlsx.py _set_text forces text for the same reason).
  const formulaStart = /^[=+\-@\t\r＝＋－＠]/;
  const plainNumber = /^-?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i;
  const esc = (v) => {
    let s = v === null || v === undefined ? '' : String(v);
    if (typeof v !== 'number') {
      const probed = s.replace(/^\s+/, '');
      if ((formulaStart.test(s) || formulaStart.test(probed)) && !plainNumber.test(probed)) s = "'" + s;
    }
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const csvText = (columns, rows) => [columns.map((c) => esc(c.label || c.key)).join(','), ...rows.map((r) => columns.map((c) => esc(r[c.key])).join(','))].join('\r\n');

  function csv(name, columns, rows) {
    const text = csvText(columns, rows);
    const url = URL.createObjectURL(new Blob(['﻿' + text], { type: 'text/csv' }));
    const a = h('a', { href: url, download: String(name ?? 'export').replace(/\.csv$/i, '') + '.csv' });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  /* Sortable table. opts: {columns: [{key, label, fmt(value), render(row), align: 'right', link: true}], rows, max: 500, csv: 'file-name',
   * onRow(row), empty: 'No rows'}. Click a heading to sort. */
  function table(el, opts) {
    el = mount(el);
    const max = opts.max || 500;
    let sort = opts.sort || null; // {key, dir}
    const draw = () => {
      let rows = opts.rows.slice();
      if (sort) {
        const k = sort.key, dir = sort.dir === 'desc' ? -1 : 1;
        rows.sort((a, b) => { const x = num(a[k]), y = num(b[k]); return dir * (x !== null && y !== null ? x - y : String(a[k] ?? '').localeCompare(String(b[k] ?? ''), LOCALE)); });
      }
      const head = h('tr', null, opts.columns.map((c) => h('th', { class: c.align === 'right' ? 'kit-r' : null, scope: 'col', 'aria-sort': sort && sort.key === c.key ? (sort.dir === 'desc' ? 'descending' : 'ascending') : null },
        h('button', { type: 'button', onclick: () => { sort = { key: c.key, dir: sort && sort.key === c.key && sort.dir === 'asc' ? 'desc' : 'asc' }; draw(); } }, c.label || c.key))));
      const cell = (c, r) => {
        const v = c.render ? c.render(r) : c.fmt ? c.fmt(r[c.key]) : fmt.text(r[c.key]);
        if (c.link && r[c.key]) return h('a', { href: r[c.key], target: '_blank', rel: 'noopener noreferrer' }, c.linkText || 'Open');
        return v;
      };
      const body = rows.slice(0, max).map((r) => h('tr', { class: opts.onRow ? 'kit-click' : null, tabindex: opts.onRow ? 0 : null, onclick: opts.onRow ? () => opts.onRow(r) : null,
        onkeydown: opts.onRow ? (e) => { if (e.key === 'Enter') opts.onRow(r); } : null }, opts.columns.map((c) => h('td', { class: c.align === 'right' ? 'kit-r' : null }, cell(c, r)))));
      const foot = h('div', { class: 'kit-table-foot' },
        h('span', null, rows.length ? `${fmt.num(Math.min(rows.length, max))} of ${fmt.num(rows.length)} rows` : opts.empty || 'No rows'),
        opts.csv && rows.length ? h('button', { type: 'button', class: 'kit-btn', onclick: () => csv(opts.csv, opts.columns, rows) }, 'Download CSV') : null);
      el.replaceChildren(h('div', { class: 'kit-table-wrap' }, h('table', { class: 'kit-table' }, h('thead', null, head), h('tbody', null, body))), foot);
    };
    draw();
  }

  /* Horizontal bar chart. opts: {rows, label: 'key', value: 'key', fmt, max: 15, color} */
  function bars(el, opts) {
    el = mount(el);
    const rows = opts.rows.slice().sort((a, b) => (num(b[opts.value]) || 0) - (num(a[opts.value]) || 0)).slice(0, opts.max || 15);
    const top = Math.max(1, ...rows.map((r) => Math.abs(num(r[opts.value]) || 0)));
    const f = opts.fmt || fmt.num;
    el.replaceChildren(h('div', { class: 'kit-bars', role: 'list' }, rows.map((r) => h('div', { class: 'kit-bar', role: 'listitem' },
      h('span', { class: 'kit-bar-label', title: r[opts.label] }, fmt.text(r[opts.label])),
      h('span', { class: 'kit-bar-track' }, h('span', { class: 'kit-bar-fill', style: `width:${(100 * Math.abs(num(r[opts.value]) || 0) / top).toFixed(1)}%;background:${(opts.color && opts.color(r)) || 'var(--brand)'}` })),
      h('span', { class: 'kit-bar-value' }, f(r[opts.value]))))));
  }

  /* Line chart over time (d3). opts: {rows, x: 'key' (ISO date or yyyy-MM), series: [{key, label}], fmt, height: 240} */
  function line(el, opts) {
    el = mount(el);
    const W = Math.max(320, el.clientWidth || 640), H = opts.height || 240, m = { t: 12, r: 12, b: 28, l: 52 };
    const monthly = opts.rows.every((r) => String(r[opts.x]).length === 7);
    const parse = (v) => new Date((String(v).length === 7 ? v + '-01' : String(v).slice(0, 10)) + 'T00:00:00');  // local midnight, as d3's ticks
    const xs = opts.rows.map((r) => parse(r[opts.x]));
    const all = opts.series.flatMap((s) => opts.rows.map((r) => num(r[s.key]) || 0));
    const x = d3.scaleTime().domain(d3.extent(xs)).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([Math.min(0, d3.min(all) || 0), d3.max(all) || 1]).nice().range([H - m.b, m.t]);
    const svg = d3.create('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('class', 'kit-chart').attr('role', 'img').attr('aria-label', opts.label || 'Line chart');
    // One date label per ~64px, written in the portal's locale, so the labels never run together.
    // Space labels by the months covered, not the row count: a series with missing months spans more than its rows.
    const months = monthly ? d3.timeMonth.count(...d3.extent(xs)) + 1 : xs.length;
    const ticks = Math.max(2, Math.min(months, Math.floor((W - m.l - m.r) / 64)));
    const tickFmt = (d) => d.toLocaleDateString(LOCALE, monthly ? { month: 'short', year: '2-digit' } : { day: 'numeric', month: 'short' });
    const days = Math.max(1, Math.ceil((x.domain()[1] - x.domain()[0]) / 864e5 / ticks));  // days between labels
    const every = monthly ? d3.timeMonth.every(Math.max(1, Math.ceil(months / ticks)))
      : days <= 1 ? d3.timeDay : days <= 2 ? d3.timeDay.every(2) : days <= 8 ? d3.timeMonday
        : days <= 20 ? d3.timeMonday.every(2) : d3.timeMonth.every(Math.ceil(days / 30));
    svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(every).tickFormat(tickFmt).tickSizeOuter(0));
    svg.append('g').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat((v) => (opts.fmt || fmt.compact)(v)).tickSize(-(W - m.l - m.r))).call((g) => g.select('.domain').remove());
    opts.series.forEach((s, i) => {
      svg.append('path').attr('fill', 'none').attr('stroke', s.color || dash.colors[i % dash.colors.length]).attr('stroke-width', 2)
        .attr('d', d3.line().x((r) => x(parse(r[opts.x]))).y((r) => y(num(r[s.key]) || 0))(opts.rows));
    });
    const legend = h('div', { class: 'kit-legend' }, opts.series.map((s, i) => h('span', null, h('i', { style: `background:${s.color || dash.colors[i % dash.colors.length]}` }), s.label || s.key)));
    el.replaceChildren(svg.node(), opts.series.length > 1 ? legend : '');
  }

  /* n distinct colours for categories (routes, vehicles, …). Stable for a given index. */
  const BASE = ['#4ADE80', '#3FA9F5', '#F5A623', '#E0559B', '#9B7BFF', '#2ED3C6', '#FF6B57', '#FFD84D', '#7FB7FF', '#B8E986',
    '#FF9FD0', '#00B894', '#D980FA', '#FDA7DF', '#12CBC4', '#ED4C67', '#F79F1F', '#A3CB38', '#1289A7', '#C4E538'];
  /* A theme colour from shell.css, for libraries (Leaflet) that need a real colour rather than var(--x). */
  const themeColour = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  const colour = (i) => (i < BASE.length ? BASE[i] : `hsl(${(i * 137.508) % 360} ${i % 2 ? 70 : 85}% ${i % 3 ? 62 : 72}%)`);

  /* Point map (needs `libs: [leaflet]` in dashboard.yml). opts: {dark: true, onClick(point), tooltip(point) -> text}
   * Returns {set(points, {fit, lines}), map}. A point is {lat, lon, color, label, ...your fields}: with a `label`
   * (a stop number, say) it is drawn as a numbered pin. lines: [{path: [[lat, lon], …], color}] draws routes. */
  function map(el, opts = {}) {
    el = mount(el);
    if (!window.L) { el.textContent = 'Map library is missing: add `libs: [leaflet]` to dashboard.yml'; return null; }
    el.classList.add('kit-map');
    el.classList.toggle('kit-map-dark', opts.dark !== false);
    const m = L.map(el, { preferCanvas: true, zoomControl: true, attributionControl: true }).setView([20, 0], 2);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors', referrerPolicy: 'strict-origin-when-cross-origin' }).addTo(m);
    const renderer = L.canvas({ padding: 0.3 });
    const routes = L.layerGroup().addTo(m);
    const group = L.featureGroup().addTo(m);
    const tip = L.tooltip({ direction: 'top', offset: [0, -6], className: 'kit-map-tip' });
    group.on('mouseover', (e) => { if (opts.tooltip) { tip.setLatLng(e.latlng).setContent(h('div', null, opts.tooltip(e.layer.point)).outerHTML).addTo(m); } });
    group.on('mouseout', () => tip.remove());
    group.on('click', (e) => opts.onClick && opts.onClick(e.layer.point));
    // Frame the map only once its box has a size. A map drawn in the same moment its section appears can still
    // measure 0 x 0, and framing then leaves it zoomed out to the whole world.
    let pending = null;
    const frame = () => {
      m.invalidateSize({ animate: false });
      const size = m.getSize();
      if (!pending || !size.x || !size.y) return;
      m.fitBounds(pending, { maxZoom: 15 });
      pending = null;
    };
    if (window.ResizeObserver) new ResizeObserver(frame).observe(el);
    addEventListener('resize', frame);
    return {
      map: m,
      set(points, { fit = true, lines = [] } = {}) {
        group.clearLayers();
        routes.clearLayers();
        for (const ln of lines) if (ln.path && ln.path.length > 1) routes.addLayer(L.polyline(ln.path, { color: ln.color || themeColour('--brand', '#4F46E5'), weight: 3, opacity: 0.85, interactive: false }));
        for (const p of points) {
          const pin = p.label === undefined || p.label === null ? null
            : L.divIcon({ className: 'kit-map-pin', iconSize: [26, 26], html: h('span', { style: `background:${p.color || themeColour('--brand', '#4F46E5')}` }, String(p.label)).outerHTML });
          const mk = pin ? L.marker([p.lat, p.lon], { icon: pin, keyboard: false })
            : L.circleMarker([p.lat, p.lon], { renderer, radius: opts.radius || 5, weight: 1, color: 'rgba(0,0,0,.55)', fillColor: p.color || themeColour('--chart-1', '#6366F1'), fillOpacity: 0.9 });
          mk.point = p;
          group.addLayer(mk);
        }
        if (fit && points.length) {
          // Frame the bulk of the points (2nd to 98th percentile) so a few far-away stops don't shrink the view.
          const q = (key, f) => { const v = points.map((p) => p[key]).sort((a, b) => a - b); return v[Math.min(v.length - 1, Math.floor(f * v.length))]; };
          const trim = points.length > 50 ? [0.02, 0.98] : [0, 1];
          pending = L.latLngBounds([q('lat', trim[0]), q('lon', trim[0])], [q('lat', trim[1]), q('lon', trim[1])]).pad(0.12);
        }
        frame();
        setTimeout(frame, 0);
      },
    };
  }

  /* Excel download, for files people edit and print. sheets: [{name, columns: [{key, label, width, link}], rows, landscape}].
   * The portal builds the file from these rows (bold header, wrapped text, A4 landscape, fitted to one page wide). */
  async function xlsx(name, sheets) {
    const res = await fetch('/api/xlsx', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, sheets }) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Could not create the Excel file');
    const url = URL.createObjectURL(await res.blob());
    const a = h('a', { href: url, download: String(name ?? 'export').replace(/\.xlsx$/i, '') + '.xlsx' });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  window.kit = { num, fmt, h, ready, filters, tiles, table, csv, csvText, xlsx, bars, line, map, colour, isoDate, daysAgo };
  if (typeof module !== 'undefined' && module.exports) module.exports = window.kit;  // lets Node tests require this file
})();
