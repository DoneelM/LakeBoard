/* Portal runtime: the Claude Dashboard `dash` API, backed by /api/d/<slug>/data/<id>.
 * Datasets load lazily on first dash.data(id). Rows arrive as strings (like a CSV), so pages convert numbers.
 * Pages written as Claude Dashboard artifacts (`page: artifact`, decision 0011) get the artifact's behaviour where
 * it differs from LakeBoard's own pages: `ARTIFACT` below. static/artifact.js mounts and runs such a page. */
/* LakeBoard data runtime: the documented `dash` API, backed by /api/d/<slug>/data/<id>.
 * Datasets load lazily on first dash.data(id). Rows arrive as strings (like a CSV), so pages convert numbers. */
(() => {
  const cfg = window.PORTAL;
  const ARTIFACT = cfg.page === 'artifact';
  const sets = {}; // id -> {status, data, columns, message, refreshing, key, fetchedAt}
  const calcs = {}; // id -> {inputs, fn, title, description, memo}
  const loaders = {}; // source id -> {description, fn}
  const subs = [];
  let params = { ...cfg.params };
  let queued = false;
  let genieContext = null; // page function describing its current view, for Ask Genie

  const keyFor = (id) => JSON.stringify((cfg.datasets[id].params || []).map((p) => params[p] ?? null));

  function notify() {
    if (queued) return;
    queued = true;
    setTimeout(() => {  // not requestAnimationFrame: it never fires in background tabs
      queued = false;
      stamp();
      fresh.update();
      for (const fn of subs) {
        try { fn(); } catch (e) { console.error('dashboard callback failed', e); }
      }
      draws.runAll();
    }, 0);
  }

  // The state a mark shows for one dataset or calc id: what data-dash-source-state is set to.
  function markState(id) {
    if (calcs[id]) {
      const v = calcValue(id);
      if (v.status === 'error') return 'error';
      if (v.status === 'loading') return 'loading';
      return v.status === 'ok' && Array.isArray(v.data) && !v.data.length ? 'empty' : null;
    }
    const s = sets[id];
    if (!s) return null;
    if (s.status === 'error') return 'error';
    if (s.status === 'loading') return 'loading';
    if (s.refreshing) return 'refreshing';
    if (s.stale) return 'stale';
    return s.status === 'ok' && !s.data.length ? 'empty' : null;
  }

  function stamp() {
    const order = ['error', 'loading', 'refreshing', 'stale', 'empty'];
    for (const el of document.querySelectorAll('[data-source]')) {
      const ids = el.getAttribute('data-source').split(/\s+/).filter((x) => cfg.datasets[x] || calcs[x]);
      const st = ids.map(markState);
      const state = order.find((x) => st.includes(x)) || null;
      if (state) el.setAttribute('data-dash-source-state', state); else el.removeAttribute('data-dash-source-state');
    }
    const root = document.getElementById('dash-root');
    const all = Object.values(sets);
    const rs = all.some((s) => s.status === 'error') ? 'error' : all.some((s) => s.status === 'loading') ? 'loading' : null;
    if (rs) root.setAttribute('data-dash-state', rs); else root.removeAttribute('data-dash-state');
  }

  async function load(id, mode = 'load') {
    const s = sets[id] || (sets[id] = { status: 'loading', data: [], columns: [], message: '', refreshing: false });
    const request = Symbol(id);
    s.request = request;
    s.key = keyFor(id);
    const had = s.status === 'ok' || (s.stale && s.data.length);
    if (s.status === 'ok') s.refreshing = true; else s.status = 'loading';
    notify();
    const qs = new URLSearchParams();
    for (const p of cfg.datasets[id].params || []) if (params[p] != null && params[p] !== '') qs.set(p, params[p]);
    if (mode === 'force') qs.set('refresh', '1');
    const headers = mode === 'check' && s.etag ? { 'If-None-Match': s.etag } : {};
    let accessDenied = false;
    try {
      const res = await fetch(`/api/d/${encodeURIComponent(cfg.slug)}/data/${encodeURIComponent(id)}?${qs}`,
        { credentials: 'same-origin', headers });
      if (s.request !== request) return; // a newer filter or refresh superseded this request
      if (res.status === 304) return 'unchanged';
      const body = await res.json().catch(() => ({ error: res.statusText }));
      if (s.request !== request) return;
      if (!res.ok) {
        accessDenied = res.status === 403;
        throw new Error(body.error || body.detail || res.statusText);
      }
      const cols = body.columns;
      s.data = body.rows.map((r) => { const o = {}; for (let i = 0; i < cols.length; i++) o[cols[i]] = r[i]; return o; });
      s.data.columns = cols;
      s.columns = cols;
      s.cut = !!body.cut;
      s.fetchedAt = body.fetched_at;
      s.queryStartedAt = body.query_started_at;
      s.etag = res.headers.get('ETag');
      s.expiresAt = body.expires_at;
      s.cache = body.cache || cfg.datasets[id].cache;
      s.snapshot = !!body.snapshot;
      s.dataThrough = body.data_through || null;
      s.status = 'ok';
      s.stale = false;
      s.message = '';
      return 'updated';
    } catch (e) {
      if (s.request !== request) return;
      // An artifact keeps showing the last good data when a refresh fails ("stale"); LakeBoard pages show the error.
      if (ARTIFACT && had && mode !== 'load' && !accessDenied) { s.status = 'ok'; s.stale = true; } else s.status = 'error';
      if (accessDenied) { s.data = []; s.columns = []; s.fetchedAt = null; s.stale = false; }
      s.message = String(e.message || e);
      console.error(`dataset ${id} failed:`, s.message);
      return 'failed';
    } finally {
      if (s.request === request) s.refreshing = false;
      notify();
    }
  }

  let refreshPending = false;
  let refreshStatusTimer;

  async function refreshLoaded(force) {
    if (refreshPending) return;
    const loaded = Object.entries(sets).filter(([, s]) => s.status !== 'loading' && !s.refreshing);
    if (!loaded.length) return;
    const status = document.getElementById('pn-refresh-status');
    const buttons = document.querySelectorAll('.pn-refresh');
    const targets = loaded.map(([id, s]) => [id, s.request]);
    refreshPending = true;
    clearTimeout(refreshStatusTimer);
    buttons.forEach((button) => { button.disabled = true; });
    if (status) status.textContent = force ? 'Refreshing…' : 'Checking sources…';
    try {
      let checks = {};
      if (!force) {
        const qs = new URLSearchParams(loaded.map(([id]) => ['check', id]));
        try {
          const res = await fetch(`/api/d/${encodeURIComponent(cfg.slug)}/sources?${qs}`, { credentials: 'same-origin' });
          if (res.ok) checks = (await res.json()).checks || {};
        } catch (e) { console.warn('Refresh could not verify source changes', e); }
      }
      if (status) status.textContent = 'Refreshing…';
      const results = await Promise.all(targets.map(([id, request]) => {
        const s = sets[id];
        if (s.request !== request) return; // the filter changed while the source check was running
        const sourceAt = checks[id];
        const unchanged = s.status === 'ok' && !s.stale && s.etag && Number.isFinite(s.queryStartedAt)
          && Number.isFinite(sourceAt) && sourceAt < s.queryStartedAt;
        return load(id, unchanged ? 'check' : 'force');
      }));
      const counts = ['updated', 'unchanged', 'failed'].map((label) => {
        const count = results.filter((result) => result === label).length;
        return count ? `${count} ${label}` : '';
      }).filter(Boolean);
      if (status) status.textContent = counts.join(' · ');
      refreshStatusTimer = setTimeout(() => { if (status) status.textContent = ''; }, 6000);
    } finally {
      refreshPending = false;
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  let paramsRead = 0; // counts dash.params() calls, so a calc knows whether it depends on the filters

  /* A calc reruns only when one of its inputs changes, or a filter changes and its fn called dash.params(). */
  function calcValue(id) {
    const c = calcs[id];
    const empty = ARTIFACT ? null : [];
    const inputs = (c.inputs || []).map((i) => dash.data(i));
    const bad = inputs.find((x) => x.status !== 'ok');
    if (bad) return { status: bad.status, data: empty, columns: [], message: bad.message, refreshing: false };
    const datas = inputs.map((x) => x.data);
    const pkey = JSON.stringify(params);
    const m = c.memo;
    if (m && m.datas.length === datas.length && m.datas.every((d, i) => d === datas[i]) && (!m.usesParams || m.pkey === pkey)) {
      return m.value;
    }
    const before = paramsRead;
    let value;
    try {
      const out = c.fn(...datas);
      const columns = (out && out.columns) || (Array.isArray(out) && out[0] && typeof out[0] === 'object' ? Object.keys(out[0]) : []);
      if (Array.isArray(out) && !out.columns) out.columns = columns;
      value = { status: 'ok', data: out, columns, message: '', refreshing: inputs.some((x) => x.refreshing), meta: {} };
    } catch (e) {
      console.error(`calc ${id} failed`, e);
      value = { status: 'error', data: empty, columns: [], message: String(e.message || e), refreshing: false };
    }
    c.memo = { datas, pkey, usesParams: paramsRead !== before, value };
    return value;
  }

  /* dash.loader(id, {fn}): in an artifact it turns a source's raw answer into rows. LakeBoard sources are SQL and
   * already rows, so fn gets those rows, and its return is used when it is an array. */
  function applyLoader(id, s) {
    const l = loaders[id];
    if (!l || typeof l.fn !== 'function' || s.status !== 'ok') return { data: s.data, columns: s.columns };
    if (l.memo && l.memo.raw === s.data) return l.memo.out;
    let out = { data: s.data, columns: s.columns };
    try {
      const r = l.fn(s.data);
      if (Array.isArray(r)) {
        const columns = r.columns || (r[0] && typeof r[0] === 'object' ? Object.keys(r[0]) : []);
        if (!r.columns) r.columns = columns;
        out = { data: r, columns };
      }
    } catch (e) { console.error(`loader ${id} failed`, e); out = { error: String(e.message || e) }; }
    l.memo = { raw: s.data, out };
    return out;
  }

  /* ---- Drawings: dash.draw(name, fn | {mount, update, unmount}) runs on every element with data-draw="name"
   * once the page's scripts have run, then on any data, filter or page-width change and when that element's own
   * width changes. Not inside another drawing, and not while the element (or a parent) has the hidden attribute. */
  const draws = (() => {
    const fns = {}; // name -> fn or {mount, update, unmount}
    const mounted = new Map(); // element -> {name, made}
    const widths = new WeakMap(); // element -> last width drawn at
    let ready = false;
    let queuedAll = false;
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver((entries) => {
      for (const e of entries) {
        const w = Math.round(e.target.getBoundingClientRect().width);
        if (widths.has(e.target) && widths.get(e.target) !== w) runOne(e.target);
      }
    }) : null;
    const observed = new WeakSet();

    const skip = (el) => !el.isConnected || (el.parentElement && el.parentElement.closest('[data-draw]')) || el.closest('[hidden]');

    function drop(el) {
      const st = mounted.get(el);
      mounted.delete(el);
      const spec = st && fns[st.name];
      if (spec && typeof spec === 'object' && typeof spec.unmount === 'function') {
        try { spec.unmount(el, st.made); } catch (e) { console.error(`drawing ${st.name}: unmount failed`, e); }
      }
    }

    function runOne(el) {
      if (!ready) return;
      const name = el.getAttribute('data-draw');
      const spec = fns[name];
      if (!spec || skip(el)) return;
      if (ro && !observed.has(el)) { ro.observe(el); observed.add(el); }
      widths.set(el, Math.round(el.getBoundingClientRect().width));
      if (typeof spec === 'function') {
        try { spec(el); } catch (e) { console.error(`drawing ${name} failed`, e); }
        return;
      }
      let st = mounted.get(el);
      if (st && st.name !== name) { drop(el); st = null; }
      try {
        if (!st) {
          el.replaceChildren();
          st = { name, made: typeof spec.mount === 'function' ? spec.mount(el) : undefined };
          mounted.set(el, st);
        }
        if (typeof spec.update === 'function') spec.update(el, st.made);
      } catch (e) {
        console.error(`drawing ${name} failed`, e);
        if (mounted.has(el)) drop(el);  // mount runs again next time
      }
    }

    function run(name) {
      if (!ready) return;
      for (const [el] of mounted) if (!el.isConnected) drop(el);
      const sel = name == null ? '[data-draw]' : `[data-draw="${CSS.escape(name)}"]`;
      for (const el of document.querySelectorAll(sel)) runOne(el);
    }

    function runAll() { if (ready && Object.keys(fns).length) run(null); }

    function soon() {  // several triggers at once draw once
      if (queuedAll) return;
      queuedAll = true;
      setTimeout(() => { queuedAll = false; runAll(); }, 0);
    }

    function start() {
      if (ready) return;
      ready = true;
      const root = document.getElementById('dash-root') || document.body;
      new MutationObserver((list) => {
        let again = false;
        for (const m of list) {
          if (m.type === 'attributes') {
            // hidden came on or off outside any drawing: drawings under it may now run (or must wait)
            const t = m.target;
            if (m.oldValue === t.getAttribute('hidden') || (t.parentElement && t.parentElement.closest('[data-draw]'))) continue;
            if (t.matches('[data-draw]') || t.querySelector('[data-draw]')) again = true;
          } else {
            for (const n of m.removedNodes) {
              if (n.nodeType !== 1) continue;
              for (const [el] of mounted) if (!el.isConnected && (n === el || n.contains(el))) drop(el);
            }
            for (const n of m.addedNodes) {  // drawings added by the page (not by another drawing)
              if (n.nodeType !== 1 || (n.parentElement && n.parentElement.closest('[data-draw]'))) continue;
              if (n.matches('[data-draw]') || n.querySelector('[data-draw]')) again = true;
            }
          }
        }
        if (again) soon();
      }).observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ['hidden'], attributeOldValue: true });
      runAll();
    }

    return {
      define(name, spec) {
        const old = fns[name];
        if (old && old !== spec) for (const [el, st] of mounted) if (st.name === name) drop(el);
        fns[name] = spec;
        run(name);
      },
      run, runAll, start,
    };
  })();

  /* ---- Freshness label beside "Refresh data": how old the data on screen is, how it is cached, and whether the
   * source tables changed since (GET /api/d/<slug>/sources, Unity Catalog metadata). See docs/OPERATIONS.md. */
  // dash.js loads in <head>, before the title bar exists, so this is set up on the first update after it does.
  let freshUi = null;
  const fresh = { update() { if (!freshUi) freshUi = makeFresh(); if (freshUi) freshUi.update(); } };
  function makeFresh() {
    const btn = document.getElementById('pn-fresh');
    const panel = document.getElementById('pn-fresh-panel');
    if (!btn || !panel || !cfg.slug) return null;
    const long = btn.querySelector('.pn-fresh-long');
    const short = btn.querySelector('.pn-fresh-short');
    const TZ = (() => { try { new Intl.DateTimeFormat('en', { timeZone: cfg.tz }); return cfg.tz || 'UTC'; } catch (e) { return 'UTC'; } })();  // warm.timezone
    const LOCALE = cfg.locale || undefined;
    const timeFmt = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, hour: 'numeric', minute: '2-digit', hour12: true });
    const dayFmt = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short' });
    const keyFmt = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' });
    let sources = null;      // dataset id -> {source_note, tables, source_updated_at, live, partial, no_source, static}, from /sources
    let sourcesAsked = false;
    const openTables = new Map();  // explicit open/closed choices survive periodic panel rendering

    const when = (sec) => {  // "10:42 am", or "Mon 16 Nov, 10:42 am" when not today (portal time zone)
      const d = new Date(sec * 1000);
      const t = timeFmt.format(d).replace(/\s+/g, ' ');
      return keyFmt.format(d) === keyFmt.format(new Date()) ? t : `${dayFmt.format(d)}, ${t}`;
    };
    const ago = (sec) => {
      const m = Math.floor((Date.now() / 1000 - sec) / 60);
      if (m < 1) return 'just now';
      if (m < 60) return `${m} min ago`;
      const h = Math.floor(m / 60);
      if (h < 24) return `${h} h ago`;
      const days = Math.floor(h / 24);
      return `${days} day${days === 1 ? '' : 's'} ago`;
    };
    const list = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);
    const KIND = {
      user: () => 'Your own copy',
      shared: () => 'Shared with everyone',
      warm: () => (cfg.warm_times && cfg.warm_times.length
        ? `Shared, pre-loaded at ${list(cfg.warm_times)} on weekdays` : 'Shared with everyone'),
      app: () => 'Shared, read by the portal',
      snapshot: () => 'Snapshot preview: rows saved on this computer, not live data',
    };
    const loaded = () => Object.entries(sets).filter(([, s]) => s.status === 'ok' && s.fetchedAt);

    function state() {
      const all = Object.values(sets);
      if (!all.length) return null;
      const ok = loaded();
      // The OLDEST fetch time, so the label never overstates how fresh the page is.
      const oldest = ok.length ? Math.min(...ok.map(([, s]) => s.fetchedAt)) : null;
      let cue = null; // 'same' | 'newer' | 'static' | null (unknown)
      if (sources && ok.length) {
        const src = ok.map(([id, s]) => ({ s, at: sources[id] ? sources[id].source_updated_at : null,
          none: !!(sources[id] && sources[id].no_source),     // reads no table, so it can't have changed
          static: !!(sources[id] && sources[id].static) }));  // reads only data that never changes
        const timed = src.filter((x) => !x.none && !x.static);
        if (timed.some((x) => x.at != null && x.at > x.s.fetchedAt)) cue = 'newer';
        else if (timed.length && timed.every((x) => x.at != null) && Math.max(...timed.map((x) => x.at)) < oldest) cue = 'same';
        else if (!timed.length && src.some((x) => x.static)) cue = 'static';
      }
      // Some source is read live (federated): "unchanged" can only speak for the tracked tables.
      const live = !!sources && ok.some(([id]) => sources[id] && sources[id].live);
      return { busy: all.some((s) => s.status === 'loading' || s.refreshing), loading: all.some((s) => s.status === 'loading'),
        failed: all.some((s) => s.status === 'error' || s.stale), oldest, cue, live, snapshot: ok.some(([, s]) => s.snapshot) };
    }

    function label() {
      const st = state();
      if (!st) { btn.hidden = true; return; }
      btn.hidden = false;
      let l, sh, cue = null;
      if (st.busy) { l = st.loading ? 'Loading…' : 'Refreshing…'; sh = l; }
      else if (st.failed) { l = 'Some data didn’t load'; sh = 'Data problem'; }
      else if (st.oldest) {
        l = `Data as of ${when(st.oldest)} · ${ago(st.oldest)}`;
        sh = ago(st.oldest);
        cue = st.cue;
        if (cue === 'same') { l += st.live ? ' · tracked sources unchanged' : ' · source unchanged'; sh += ' ✓'; }  // phone: a tick
        if (cue === 'newer') { l += ' · newer data available'; sh += ' • new'; }
        if (cue === 'static') { l += ' · source never changes'; sh += ' ✓'; }
      } else { l = 'Loading…'; sh = l; }
      if (st.snapshot && !st.busy) { l += ' · snapshot preview'; sh += ' · snapshot'; }  // local preview of todo data
      btn.classList.toggle('pn-fresh-newer', cue === 'newer');
      btn.classList.toggle('pn-fresh-bad', !st.busy && st.failed);
      long.textContent = l;
      short.textContent = sh;
      btn.setAttribute('aria-label', `${l}. Show details`);
    }

    const el = (tag, cls, text) => {
      const e = document.createElement(tag);
      if (cls) e.className = cls;
      if (text != null) e.textContent = text;
      return e;
    };

    const tableKind = (t, fetchedAt) => {
      if (t.kind === 'managed' && t.updated_at != null) {
        const base = `changed ${ago(t.updated_at)} (${when(t.updated_at)})`;
        return t.updated_at > fetchedAt ? `${base}, ${window.LakeBoardSourceGroups.span(t.updated_at - fetchedAt)} after your data` : base;
      }
      if (t.kind === 'live') return t.via ? `live (${t.via})` : 'live, federated';
      if (t.kind === 'external') return 'external, change time not tracked';
      if (t.kind === 'none') return 'reads no table';
      if (t.kind === 'static') return 'never changes (static catalog)';
      return 'change time unavailable';
    };

    function render() {
      const st = state();
      const rows = loaded();
      panel.replaceChildren(el('h2', 'pn-fresh-h', 'How fresh this data is'));
      if (!rows.length) panel.append(el('p', 'pn-fresh-note', 'No data has loaded on this page yet.'));
      for (const [id, s] of rows) {
        const meta = cfg.datasets[id] || {};
        const box = el('section', 'pn-fresh-item');
        const dl = el('dl');
        const add = (k, v) => dl.append(el('dt', null, k), el('dd', null, v));
        add('As of', `${when(s.fetchedAt)} (${ago(s.fetchedAt)})`);
        if (s.dataThrough) add('Data through', s.dataThrough);
        if (s.expiresAt) add('Kept until', when(s.expiresAt));
        add('Type', (KIND[s.cache || meta.cache] || KIND.user)());
        if (meta.source) add('Source', meta.source);
        const src = sources && sources[id];
        const tables = (src && src.tables) || [];
        if (src && src.source_updated_at != null) {
          const at = src.source_updated_at;
          add('Source last changed', `${ago(at)} (${when(at)})${at > s.fetchedAt ? ', after this data was fetched' : ''}`);
        } else if (src && src.static) {
          add('Source last changed', 'Never: this data doesn’t change');
        } else if (src && src.no_source) {
          add('Source last changed', 'No source table (generated in the query)');
        } else if (src && src.live && tables.every((t) => t.kind === 'live')) {
          add('Source last changed', 'Live source — always current when fetched');
        } else add('Source last changed', sources ? 'Source change time unavailable' : 'Checking…');
        box.append(el('h3', null, meta.title || id), dl);
        if (src && src.source_updated_at != null && (src.live || src.partial)) {
          box.append(el('p', 'pn-fresh-note', 'Some sources are read live or aren’t tracked; the time shown covers the tracked tables only.'));
        }
        if (tables.length) {
          const groups = window.LakeBoardSourceGroups.groupSourceTables(tables, s.fetchedAt);
          const det = el('details', 'pn-fresh-tables');
          det.open = openTables.has(id) ? openTables.get(id) : groups.changed.length > 0;
          // Initialization can emit toggle too; only remember an actual change from the rendered state.
          let renderedOpen = det.open;
          det.addEventListener('toggle', () => {
            if (det.open !== renderedOpen) openTables.set(id, det.open);
            renderedOpen = det.open;
          });
          det.append(el('summary', null, `Source tables (${tables.length})${groups.changed.length ? ` · ${groups.changed.length} changed since your data` : ''}`));
          for (const [key, title] of [['changed', 'Changed since your data'], ['unchanged', 'Unchanged'], ['untracked', 'Live or not tracked']]) {
            if (!groups[key].length) continue;
            det.append(el('h4', 'pn-fresh-group', `${title} (${groups[key].length})`));
            const ul = el('ul');
            for (const t of groups[key]) {
              const li = el('li', key === 'changed' ? 'pn-fresh-changed' : '');
              li.append(el('span', 'pn-fresh-tname', t.name), document.createTextNode(` — ${tableKind(t, s.fetchedAt)}`));
              if (key === 'changed') li.append(el('strong', 'pn-fresh-tag', 'new since your data'));
              ul.append(li);
            }
            det.append(ul);
          }
          box.append(det);
        }
        panel.append(box);
      }
      for (const [id, s] of Object.entries(sets)) {
        if (s.stale) panel.append(el('p', 'pn-fresh-note pn-fresh-err', `${(cfg.datasets[id] || {}).title || id} didn’t refresh, so it shows the last data: ${s.message}`));
        if (s.status === 'error') panel.append(el('p', 'pn-fresh-note pn-fresh-err', `${(cfg.datasets[id] || {}).title || id} didn’t load: ${s.message}`));
      }
      if (st && !st.busy && st.cue === 'same') {
        panel.append(el('p', 'pn-fresh-note', st.live
          ? 'No tracked source table has changed since this data was fetched. Live sources are read afresh on every fetch, so Refresh may still bring newer figures from them.'
          : 'The latest source metadata shows no writes since this data was fetched.'));
      }
      if (st && !st.busy && st.cue === 'static') {
        panel.append(el('p', 'pn-fresh-note', 'These source tables contain fixed data.'));
      }
      if (st && !st.busy && st.cue === 'newer') {
        panel.append(el('p', 'pn-fresh-note pn-fresh-accent', 'A source table has changed since this data was fetched. Refresh data to see it.'));
      }
      panel.append(el('p', 'pn-fresh-foot', 'Refresh data checks for source changes. Refresh all re-runs the loaded queries.'));
    }

    const isOpen = () => btn.getAttribute('aria-expanded') === 'true';
    function open(v, focusBack) {
      btn.setAttribute('aria-expanded', String(v));
      panel.hidden = !v;
      if (v) { render(); panel.focus(); } else if (focusBack) btn.focus();
    }
    btn.addEventListener('click', () => open(!isOpen()));
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && isOpen()) open(false, true); });
    document.addEventListener('click', (e) => {
      if (isOpen() && !panel.contains(e.target) && !btn.contains(e.target)) open(false);
    });

    async function loadSources() {
      try {
        const res = await fetch(`/api/d/${encodeURIComponent(cfg.slug)}/sources`, { credentials: 'same-origin' });
        if (!res.ok) return;
        sources = (await res.json()).datasets || {};
        update();
      } catch (e) { console.warn('source change times unavailable', e); }
    }

    function update() {
      label();
      if (isOpen()) render();
      if (!sourcesAsked && loaded().length) {  // once after the first data arrives, then every 5 minutes while visible
        sourcesAsked = true;
        loadSources();
        setInterval(() => { if (!document.hidden) loadSources(); }, 5 * 60 * 1000);
      }
    }
    setInterval(() => { label(); if (isOpen()) render(); }, 60 * 1000);  // keeps "12 min ago" current
    return { update };
  }

  const dash = {
    /* Series colours: --chart-1 .. --chart-8 from the theme in shell.css (read once, when the page loads). */
    colors: (() => {
      if (ARTIFACT) return [1, 2, 3, 4, 5, 6, 7, 8].map((i) => `var(--chart-${i})`);  // artifacts get CSS var() strings
      const fallback = ['#6366F1', '#0EA5E9', '#94A3B8', '#F59E0B', '#10B981', '#64748B', '#EF4444', '#A78BFA'];
      try {
        const css = getComputedStyle(document.documentElement);
        return fallback.map((c, i) => css.getPropertyValue(`--chart-${i + 1}`).trim() || c);
      } catch (e) { return fallback; }
    })(),
    data(id) {
      if (calcs[id]) return calcValue(id);
      if (!cfg.datasets[id]) return { status: 'missing', data: [], columns: [], message: `Unknown dataset ${id}`, refreshing: false, truncated: false, meta: {} };
      if (cfg.datasets[id].allowed === false) {  // artifacts know no 'forbidden' status: there it is an error
        return { status: ARTIFACT ? 'error' : 'forbidden', data: [], columns: [], message: 'No access to this section', refreshing: false, truncated: false, meta: {} };
      }
      if (!sets[id]) load(id);
      const s = sets[id];
      const v = applyLoader(id, s);
      if (v.error) return { status: 'error', data: [], columns: [], message: v.error, refreshing: false, truncated: false, meta: {} };
      return { status: s.status, data: v.data, rows: v.data, columns: v.columns, message: s.message, refreshing: s.refreshing,
        cut: s.cut, truncated: !!s.cut, fetchedAt: s.fetchedAt,
        meta: ARTIFACT ? { fetchedAt: s.fetchedAt, cache: s.cache, snapshot: !!s.snapshot, stale: !!s.stale } : [] };
    },
    onData(fn) { subs.push(fn); try { fn(); } catch (e) { console.error('dashboard callback failed', e); } },
    params: () => { paramsRead++; return { ...params }; },
    env: cfg.env || 'prod',
    allowed: (id) => !!cfg.datasets[id] && cfg.datasets[id].allowed !== false,
    setParams(upd) {
      const changed = Object.keys(upd).filter((k) => params[k] !== upd[k]);
      params = { ...params, ...upd };
      for (const id of Object.keys(sets)) if (sets[id].key !== keyFor(id)) load(id);
      if (changed.length) notify();
    },
    resetParams() { dash.setParams({ ...cfg.params }); },
    calc(id, spec) { calcs[id] = { ...(spec || {}), inputs: (spec && spec.inputs) || [] }; notify(); },
    loader(id, spec) { loaders[id] = { ...(spec || {}) }; if (sets[id]) notify(); },
    /* dash.draw(name, fn) or dash.draw(name, {mount, update, unmount}); dash.draw(name) reruns it. */
    draw(name, spec) {
      if (spec === undefined) { draws.run(String(name)); return; }
      draws.define(String(name), spec);
    },
    setLink(name) { history.replaceState(null, '', name ? `#${name}` : location.pathname + location.search); },
    refresh(id) { if (sets[id]) load(id, 'force'); },
    refreshChanged() { return refreshLoaded(false); },
    refreshAll() { return refreshLoaded(true); },
    /* Ask Genie: dash.genieContext(() => ({ Period: 'Year to date', Region: 'North' })) tells Genie what the
     * page is showing (filters that never reach SQL). Called with no argument it returns the current pairs. */
    genieContext(fn) {
      if (arguments.length) { genieContext = typeof fn === 'function' ? fn : null; return undefined; }
      if (!genieContext) return {};
      try {
        const out = {}, v = genieContext() || {};
        for (const [k, x] of Object.entries(v)) if (x !== null && x !== undefined && x !== '' && typeof x !== 'object') out[String(k)] = String(x);
        return out;
      } catch (e) { console.error('genieContext failed', e); return {}; }
    },
  };
  window.dash = dash;
  /* Drawings start once the page's scripts have run: after static/artifact.js has mounted an artifact page, or once
   * the document is parsed for a LakeBoard page. */
  if (ARTIFACT) dash._artifactReady = () => { draws.start(); notify(); };
  else if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => draws.start());
  else draws.start();
  let rt;
  addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(notify, 150); });
})();
