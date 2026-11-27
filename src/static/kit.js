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

  /* ---- Motion: numbers count up and charts draw in when their values change, never on a plain redraw (resize),
   * and never for people who ask for less motion. ---- */
  const still = () => typeof matchMedia !== 'function' || typeof requestAnimationFrame !== 'function'
    || matchMedia('(prefers-reduced-motion: reduce)').matches;
  const SEP = (() => {
    try {
      const parts = new Intl.NumberFormat(LOCALE).formatToParts(12345.6);
      return { g: (parts.find((p) => p.type === 'group') || {}).value || ',', d: (parts.find((p) => p.type === 'decimal') || {}).value || '.' };
    } catch (e) { return { g: ',', d: '.' }; }
  })();
  const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const NUM_RE = new RegExp(`\\d{1,3}(?:${reEsc(SEP.g)}\\d{3})+(?:${reEsc(SEP.d)}\\d+)?|\\d+(?:${reEsc(SEP.d)}\\d+)?`, 'g');
  /* The one number in a formatted value ("$25.2m", "1,137,325", "21.5%"), so it can count up. null when there is no
   * number, more than one ("1992–1997") or a word before it ("Jan 2016"): those are shown as they are. */
  function numberIn(text) {
    const s = String(text ?? '');
    const all = s.match(NUM_RE) || [];
    if (all.length !== 1) return null;
    const at = s.search(NUM_RE), raw = all[0];
    const pre = s.slice(0, at);
    if (/\p{L}/u.test(pre)) return null;
    const [whole, frac = ''] = raw.split(SEP.d);
    return { pre, post: s.slice(at + raw.length), value: +(whole.split(SEP.g).join('') + (frac ? '.' + frac : '')), dp: frac.length, group: raw.includes(SEP.g) };
  }
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  /* Sets node's text to `text`, counting its number up from `from` (a number) when there is motion. */
  function countUp(node, text, from) {
    const n = numberIn(text);
    if (node.__kitAnim) cancelAnimationFrame(node.__kitAnim);
    if (!n || from === null || from === undefined || from === n.value || still()) { node.textContent = text; return; }
    const show = (v) => n.pre + v.toLocaleString(LOCALE, { minimumFractionDigits: n.dp, maximumFractionDigits: n.dp, useGrouping: n.group }) + n.post;
    const t0 = performance.now(), ms = 900;
    const step = (now) => {
      const t = Math.min(1, (now - t0) / ms);
      node.textContent = t < 1 ? show(from + (n.value - from) * ease(t)) : text;
      node.__kitAnim = t < 1 ? requestAnimationFrame(step) : null;
    };
    node.__kitAnim = requestAnimationFrame(step);
  }

  /* Small trend line for a tile: values in order, oldest first. */
  function spark(values) {
    const v = (values || []).map(num).filter((x) => x !== null);
    if (v.length < 2) return null;
    const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
    const pts = v.map((x, i) => [(i / (v.length - 1)) * 100, 26 - ((x - lo) / span) * 22]);
    const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(2) + ',' + p[1].toFixed(2)).join('');
    const svg = d3.create('svg').attr('class', 'kit-spark').attr('viewBox', '0 0 100 28').attr('preserveAspectRatio', 'none').attr('aria-hidden', 'true');
    svg.append('path').attr('class', 'kit-spark-area').attr('d', d + 'L100,28L0,28Z');
    svg.append('path').attr('class', 'kit-spark-line').attr('d', d);
    return svg.node();
  }

  /* KPI tiles. items: [{label, value, note, tone: 'ok' | 'warn' | 'bad', spark: [numbers]}]
   * value is already formatted; its number counts up when it changes. spark draws a small trend under the value. */
  function tiles(el, items) {
    el = mount(el);
    el.classList.add('kit-tiles');
    const before = el.__kitTiles || new Map();
    const same = el.children.length === items.length && items.every((t, i) => el.children[i].dataset.label === String(t.label));
    if (!same) el.replaceChildren(...items.map((t) => h('div', { class: 'kit-tile kit-enter', 'data-label': t.label },
      h('span', { class: 'kit-tile-label' }, t.label), h('strong', { class: 'kit-tile-value' }))));
    const now = new Map();
    items.forEach((t, i) => {
      const tile = el.children[i];
      tile.className = 'kit-tile' + (same ? '' : ' kit-enter') + (t.tone ? ' kit-' + t.tone : '') + (t.spark ? ' kit-has-spark' : '');
      const value = tile.querySelector('.kit-tile-value');
      const prev = before.has(t.label) ? before.get(t.label) : 0;
      const n = numberIn(t.value);
      if (value.dataset.text !== String(t.value)) countUp(value, t.value, prev);
      value.dataset.text = String(t.value);
      now.set(t.label, n ? n.value : null);
      for (const old of tile.querySelectorAll('.kit-tile-note, .kit-spark')) old.remove();
      if (t.note) tile.append(h('span', { class: 'kit-tile-note' }, t.note));
      const s = t.spark ? spark(t.spark) : null;
      if (s) tile.append(s);
    });
    el.__kitTiles = now;
  }

  /* A floating tooltip inside `host` (charts use it on hover). Returns {show(x, y, ...content), hide()}; x and y are
   * pixels from the host's top-left corner. Content is elements or text, never HTML. */
  function tip(host) {
    host = mount(host);
    host.classList.add('kit-tip-host');
    let box = host.querySelector(':scope > .kit-tip');
    if (!box) { box = h('div', { class: 'kit-tip', role: 'tooltip', hidden: true }); host.append(box); }
    return {
      show(x, y, ...content) {
        box.replaceChildren(...content.flat().filter((c) => c !== null && c !== undefined));
        box.hidden = false;
        const W = host.clientWidth, bw = box.offsetWidth, bh = box.offsetHeight;
        const left = x + 14 + bw > W ? Math.max(0, x - 14 - bw) : x + 14;
        box.style.left = left + 'px';
        box.style.top = Math.max(0, y - bh - 10) + 'px';
      },
      hide() { box.hidden = true; },
    };
  }

  /* Headline for the top of a page: the one thing the data says. opts: {eyebrow, title, body, tone: 'ok' | 'warn' | 'bad',
   * stats: [{value, label}]}. Write it from the data on the page, so it is true for whatever the filters show. */
  function insight(el, opts) {
    el = mount(el);
    el.className = 'kit-insight' + (opts.tone ? ' kit-' + opts.tone : '');
    el.replaceChildren(
      h('div', { class: 'kit-insight-text' },
        opts.eyebrow ? h('span', { class: 'kit-insight-eyebrow' }, opts.eyebrow) : null,
        h('strong', { class: 'kit-insight-title' }, opts.title),
        opts.body ? h('p', null, opts.body) : null),
      opts.stats && opts.stats.length ? h('div', { class: 'kit-insight-stats' }, opts.stats.map((s) =>
        h('div', null, h('strong', null, s.value), h('span', null, s.label)))) : null);
  }

  // Cells whose first character, or first non-whitespace character, is = + - @ TAB CR LF or full-width ＝＋－＠ get a ' prefix so Excel won't run them as formulas (xlsx.py _set_text forces text for the same reason).
  const formulaStart = /^[=+\-@\t\r\n＝＋－＠]/;
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

  /* Horizontal bar chart. opts: {rows, label: 'key', value: 'key', fmt, max: 15, color(row)}. Bars grow from their
   * last width when the values change. */
  function bars(el, opts) {
    el = mount(el);
    const rows = opts.rows.slice().sort((a, b) => (num(b[opts.value]) || 0) - (num(a[opts.value]) || 0)).slice(0, opts.max || 15);
    const top = Math.max(1, ...rows.map((r) => Math.abs(num(r[opts.value]) || 0)));
    const f = opts.fmt || fmt.num;
    const before = el.__kitBars || new Map(), now = new Map(), grow = [];
    el.replaceChildren(h('div', { class: 'kit-bars', role: 'list' }, rows.map((r, i) => {
      const key = String(r[opts.label]), pct = (100 * Math.abs(num(r[opts.value]) || 0) / top);
      const start = still() ? pct : before.has(key) ? before.get(key) : 0;
      const colour = opts.color && opts.color(r);
      const fill = h('span', { class: 'kit-bar-fill' + (colour ? '' : ' kit-bar-brand'), style: `width:${start.toFixed(1)}%;${colour ? 'background:' + colour : ''};transition-delay:${Math.min(i, 12) * 30}ms` });
      now.set(key, pct);
      if (start !== pct) grow.push([fill, pct]);
      return h('div', { class: 'kit-bar', role: 'listitem' },
        h('span', { class: 'kit-bar-label', title: r[opts.label] }, fmt.text(r[opts.label])),
        h('span', { class: 'kit-bar-track' }, fill),
        h('span', { class: 'kit-bar-value' }, f(r[opts.value])));
    })));
    el.__kitBars = now;
    if (grow.length) requestAnimationFrame(() => requestAnimationFrame(() => { for (const [fill, pct] of grow) fill.style.width = pct.toFixed(1) + '%'; }));
  }

  /* Line chart (d3). opts: {rows, x: 'key', series: [{key, label, color, dash: true}], fmt, height: 240, label,
   *   xType: 'time' (ISO date or yyyy-MM, the default) | 'number', xFmt(v) for number axes,
   *   area: true (shade under the lines; the default for one series),
   *   band: {low: 'key', high: 'key', label} (a shaded range, e.g. a typical day),
   *   marks: [{x, label, note}] (labelled events on the x axis),
   *   spans: [{from, to, label}] (shaded stretches of the x axis, e.g. a closure),
   *   tip(row) -> extra tooltip lines (text)}.
   * Hover shows every series' value at the nearest x. Lines draw in when the data changes. */
  let uid = 0;
  function line(el, opts) {
    el = mount(el);
    const W = Math.max(320, el.clientWidth || 640), H = opts.height || 240;
    const marks = opts.marks || [];
    const m = { t: marks.length ? 30 : 12, r: 24, b: 28, l: 52 };  // room for the last date label
    const numeric = opts.xType === 'number';
    const monthly = !numeric && opts.rows.every((r) => String(r[opts.x]).length === 7);
    // Local time, as d3's ticks: 'yyyy-MM' and 'yyyy-MM-dd' at midnight, 'yyyy-MM-dd HH:mm' at that hour.
    const hourly = !numeric && opts.rows.some((r) => String(r[opts.x]).length > 10);
    const parse = numeric ? (v) => num(v) : (v) => {
      const s = String(v);
      return s.length > 10 ? new Date(s.slice(0, 16).replace(' ', 'T') + ':00') : new Date((s.length === 7 ? s + '-01' : s.slice(0, 10)) + 'T00:00:00');
    };
    const rows = opts.rows.slice().sort((a, b) => parse(a[opts.x]) - parse(b[opts.x]));
    const xs = rows.map((r) => parse(r[opts.x]));
    const band = opts.band;
    const all = opts.series.flatMap((s) => rows.map((r) => num(r[s.key]) || 0))
      .concat(band ? rows.flatMap((r) => [num(r[band.low]), num(r[band.high])]).filter((v) => v !== null) : []);
    const x = (numeric ? d3.scaleLinear() : d3.scaleTime()).domain(d3.extent(xs)).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([Math.min(0, d3.min(all) || 0), d3.max(all) || 1]).nice().range([H - m.b, m.t]);
    const yf = opts.fmt || fmt.compact;
    const colourOf = (s, i) => s.color || dash.colors[i % dash.colors.length];
    const svg = d3.create('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('class', 'kit-chart').attr('role', 'img').attr('aria-label', opts.label || 'Line chart');
    const xFmt = numeric ? (opts.xFmt || ((v) => fmt.num(v))) : (d) => d.toLocaleDateString(LOCALE, monthly ? { month: 'short', year: '2-digit' } : { day: 'numeric', month: 'short' });
    if (numeric) {
      svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(Math.max(2, Math.floor((W - m.l - m.r) / 64))).tickFormat(xFmt).tickSizeOuter(0));
    } else {
      // One date label per ~64px, written in the portal's locale, so the labels never run together.
      // Space labels by the months covered, not the row count: a series with missing months spans more than its rows.
      const months = monthly ? d3.timeMonth.count(...d3.extent(xs)) + 1 : xs.length;
      const ticks = Math.max(2, Math.min(months, Math.floor((W - m.l - m.r) / 64)));
      const days = Math.max(1, Math.ceil((x.domain()[1] - x.domain()[0]) / 864e5 / ticks));  // days between labels
      const every = monthly ? d3.timeMonth.every(Math.max(1, Math.ceil(months / ticks)))
        : days <= 1 ? d3.timeDay : days <= 2 ? d3.timeDay.every(2) : days <= 8 ? d3.timeMonday
          : days <= 20 ? d3.timeMonday.every(2) : d3.timeMonth.every(Math.ceil(days / 30));
      svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(every).tickFormat(xFmt).tickSizeOuter(0));
    }
    svg.append('g').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat((v) => yf(v)).tickSize(-(W - m.l - m.r))).call((g) => g.select('.domain').remove());
    const px = (r) => x(parse(r[opts.x]));
    if (band) {
      const ok = rows.filter((r) => num(r[band.low]) !== null && num(r[band.high]) !== null);
      svg.append('path').attr('class', 'kit-band').attr('d', d3.area().x(px).y0((r) => y(num(r[band.low]))).y1((r) => y(num(r[band.high]))).curve(d3.curveMonotoneX)(ok));
    }
    for (const sp of opts.spans || []) {
      const a = Math.max(m.l, x(parse(sp.from))), b = Math.min(W - m.r, x(parse(sp.to)));
      if (!(b > a)) continue;
      const g = svg.append('g').attr('class', 'kit-span');
      g.append('rect').attr('x', a).attr('width', b - a).attr('y', m.t).attr('height', H - m.t - m.b);
      if (sp.label) g.append('text').attr('x', (a + b) / 2).attr('y', m.t + 13).attr('text-anchor', 'middle').text(sp.label);
    }
    for (const mk of marks) {
      const at = x(parse(mk.x));
      if (!(at >= m.l && at <= W - m.r)) continue;
      const g = svg.append('g').attr('class', 'kit-mark');
      g.append('line').attr('x1', at).attr('x2', at).attr('y1', m.t - 6).attr('y2', H - m.b);
      const text = g.append('text').attr('x', at).attr('y', 12).attr('text-anchor', at > W - 90 ? 'end' : at < m.l + 60 ? 'start' : 'middle').text(mk.label);
      if (mk.note) g.append('title').text(mk.note);
      text.attr('class', 'kit-mark-label');
    }
    const shade = opts.area ?? opts.series.length === 1;
    const lines = [];
    opts.series.forEach((s, i) => {
      const c = colourOf(s, i);
      const ok = rows.filter((r) => num(r[s.key]) !== null);
      if (shade && !s.dash) {
        const id = `kit-grad-${++uid}`;
        const grad = svg.append('defs').append('linearGradient').attr('id', id).attr('x1', 0).attr('x2', 0).attr('y1', 0).attr('y2', 1);
        grad.append('stop').attr('offset', '0%').attr('stop-color', c).attr('stop-opacity', 0.32);
        grad.append('stop').attr('offset', '100%').attr('stop-color', c).attr('stop-opacity', 0);
        svg.append('path').attr('class', 'kit-area').attr('fill', `url(#${id})`)
          .attr('d', d3.area().x(px).y0(y(Math.max(0, y.domain()[0]))).y1((r) => y(num(r[s.key]))).curve(d3.curveMonotoneX)(ok));
      }
      lines.push(svg.append('path').attr('class', 'kit-line' + (s.dash ? ' kit-line-dash' : '')).attr('fill', 'none').attr('stroke', c).attr('stroke-width', s.dash ? 1.5 : 2.25)
        .attr('d', d3.line().x(px).y((r) => y(num(r[s.key]))).curve(d3.curveMonotoneX)(ok)).node());
    });
    // Hover: a guide line and a dot per series at the nearest x, with the values in a tooltip.
    const guide = svg.append('line').attr('class', 'kit-guide').attr('y1', m.t).attr('y2', H - m.b).style('display', 'none');
    const dots = opts.series.map((s, i) => svg.append('circle').attr('r', 4).attr('class', 'kit-dot').attr('fill', colourOf(s, i)).style('display', 'none'));
    const legend = h('div', { class: 'kit-legend' }, opts.series.map((s, i) => h('span', null, h('i', { class: s.dash ? 'kit-legend-dash' : null, style: `background:${colourOf(s, i)}` }), s.label || s.key)),
      band && band.label ? h('span', null, h('i', { class: 'kit-legend-band' }), band.label) : null);
    el.replaceChildren(svg.node(), opts.series.length > 1 || band ? legend : '');
    const t = tip(el);
    const bis = d3.bisector((d) => d).center;
    svg.append('rect').attr('class', 'kit-hit').attr('x', m.l).attr('y', m.t).attr('width', W - m.l - m.r).attr('height', H - m.t - m.b)
      .on('pointermove', (ev) => {
        if (!rows.length) return;
        const [mx] = d3.pointer(ev);
        const i = bis(xs, x.invert(mx)), r = rows[i], at = x(xs[i]);
        guide.attr('x1', at).attr('x2', at).style('display', null);
        opts.series.forEach((s, k) => { const v = num(r[s.key]); dots[k].attr('cx', at).attr('cy', v === null ? -99 : y(v)).style('display', v === null ? 'none' : null); });
        const scale = (el.querySelector('svg').getBoundingClientRect().width || W) / W;
        const head = numeric ? xFmt(xs[i]) : monthly ? fmt.month(r[opts.x])
          : hourly ? xs[i].toLocaleString(LOCALE, { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
            : xs[i].toLocaleDateString(LOCALE, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
        t.show(at * scale, (d3.min(opts.series, (s) => y(num(r[s.key]) ?? y.domain()[1])) || m.t) * scale,
          h('strong', null, head),
          opts.series.map((s, k) => h('div', { class: 'kit-tip-row' }, h('i', { style: `background:${colourOf(s, k)}` }), h('span', null, s.label || s.key), h('b', null, yf(r[s.key])))),
          band && band.label && num(r[band.low]) !== null ? h('div', { class: 'kit-tip-row kit-tip-muted' }, h('i', { class: 'kit-legend-band' }), h('span', null, band.label), h('b', null, `${yf(r[band.low])}–${yf(r[band.high])}`)) : null,
          (opts.tip ? [].concat(opts.tip(r) || []) : []).map((line) => h('div', { class: 'kit-tip-note' }, line)));
      })
      .on('pointerleave', () => { guide.style('display', 'none'); dots.forEach((d) => d.style('display', 'none')); t.hide(); });
    // Draw in, once per new set of values: a resize redraws without it.
    const sig = rows.length + '|' + opts.series.map((s) => d3.sum(rows, (r) => num(r[s.key]) || 0)).join(',') + '|' + xs[0] + '|' + xs[xs.length - 1];
    if (el.__kitLineSig !== sig && !still()) {
      for (const p of lines) {
        const len = p.getTotalLength ? p.getTotalLength() : 0;
        if (!len || p.classList.contains('kit-line-dash')) continue;
        p.style.strokeDasharray = `${len} ${len}`;
        p.style.strokeDashoffset = String(len);
        p.getBoundingClientRect();
        p.style.transition = 'stroke-dashoffset 1.1s cubic-bezier(.2,.7,.2,1)';
        p.style.strokeDashoffset = '0';
        p.addEventListener('transitionend', () => { p.style.strokeDasharray = ''; p.style.transition = ''; }, { once: true });
      }
      el.querySelectorAll('.kit-area, .kit-band').forEach((a) => a.classList.add('kit-fade'));
    }
    el.__kitLineSig = sig;
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

  window.kit = { num, fmt, h, ready, filters, tiles, table, csv, csvText, xlsx, bars, line, map, colour, isoDate, daysAgo, tip, insight, spark, numberIn };
  if (typeof module !== 'undefined' && module.exports) module.exports = window.kit;  // lets Node tests require this file
})();
