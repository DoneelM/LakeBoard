/* LakeBoard data runtime: the documented `dash` API, backed by /api/d/<slug>/data/<id>.
 * Datasets load lazily on first dash.data(id). Rows arrive as strings (like a CSV), so pages convert numbers. */
(() => {
  const cfg = window.PORTAL;
  const sets = {}; // id -> {status, data, columns, message, refreshing, key, fetchedAt}
  const calcs = {};
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
    }, 0);
  }

  function stamp() {
    for (const el of document.querySelectorAll('[data-source]')) {
      const ids = el.getAttribute('data-source').split(/\s+/).filter((x) => cfg.datasets[x]);
      const st = ids.map((x) => sets[x]).filter(Boolean);
      const state = st.some((s) => s.status === 'error') ? 'error' : st.some((s) => s.status === 'loading') ? 'loading'
        : st.some((s) => s.refreshing) ? 'refreshing' : null;
      if (state) el.setAttribute('data-dash-source-state', state); else el.removeAttribute('data-dash-source-state');
    }
    const root = document.getElementById('dash-root');
    const all = Object.values(sets);
    const rs = all.some((s) => s.status === 'error') ? 'error' : all.some((s) => s.status === 'loading') ? 'loading' : null;
    if (rs) root.setAttribute('data-dash-state', rs); else root.removeAttribute('data-dash-state');
  }

  async function load(id, refresh = false) {
    const s = sets[id] || (sets[id] = { status: 'loading', data: [], columns: [], message: '', refreshing: false });
    const key = keyFor(id);
    s.key = key;
    if (s.status === 'ok') s.refreshing = true; else s.status = 'loading';
    notify();
    const qs = new URLSearchParams();
    for (const p of cfg.datasets[id].params || []) if (params[p] != null && params[p] !== '') qs.set(p, params[p]);
    if (refresh) qs.set('refresh', '1');
    try {
      const res = await fetch(`/api/d/${encodeURIComponent(cfg.slug)}/data/${encodeURIComponent(id)}?${qs}`, { credentials: 'same-origin' });
      const body = await res.json().catch(() => ({ error: res.statusText }));
      if (s.key !== key) return; // a newer filter superseded this request
      if (!res.ok) throw new Error(body.error || body.detail || res.statusText);
      const cols = body.columns;
      s.data = body.rows.map((r) => { const o = {}; for (let i = 0; i < cols.length; i++) o[cols[i]] = r[i]; return o; });
      s.data.columns = cols;
      s.columns = cols;
      s.cut = !!body.cut;
      s.fetchedAt = body.fetched_at;
      s.expiresAt = body.expires_at;
      s.cache = body.cache || cfg.datasets[id].cache;
      s.status = 'ok';
      s.message = '';
    } catch (e) {
      if (s.key !== key) return;
      s.status = 'error';
      s.message = String(e.message || e);
      console.error(`dataset ${id} failed:`, s.message);
    } finally {
      if (s.key === key) s.refreshing = false;
      notify();
    }
  }

  function calcValue(id) {
    const c = calcs[id];
    const inputs = c.inputs.map((i) => dash.data(i));
    const bad = inputs.find((x) => x.status !== 'ok');
    if (bad) return { status: bad.status, data: [], message: bad.message };
    try { return { status: 'ok', data: c.fn(...inputs.map((x) => x.data)) }; }
    catch (e) { return { status: 'error', data: [], message: String(e) }; }
  }

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
    const openTables = new Set();  // datasets whose "Source tables" list is open in the panel

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
        failed: all.some((s) => s.status === 'error'), oldest, cue, live };
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

    const tableKind = (t) => {
      if (t.kind === 'managed' && t.updated_at != null) return `changed ${ago(t.updated_at)} (${when(t.updated_at)})`;
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
        if (tables.length) {  // each table and what is known about it, folded away by default
          const det = el('details', 'pn-fresh-tables');
          det.open = openTables.has(id);  // the panel re-renders every minute; keep what the reader opened
          det.addEventListener('toggle', () => { if (det.open) openTables.add(id); else openTables.delete(id); });
          det.append(el('summary', null, `Source tables (${tables.length})`));
          const ul = el('ul');
          for (const t of tables) {
            const li = el('li');
            li.append(el('span', 'pn-fresh-tname', t.name), document.createTextNode(` — ${tableKind(t)}`));
            ul.append(li);
          }
          det.append(ul);
          box.append(det);
        }
        panel.append(box);
      }
      for (const [id, s] of Object.entries(sets)) {
        if (s.status === 'error') panel.append(el('p', 'pn-fresh-note pn-fresh-err', `${(cfg.datasets[id] || {}).title || id} didn’t load: ${s.message}`));
      }
      if (st && !st.busy && st.cue === 'same') {
        panel.append(el('p', 'pn-fresh-note', st.live
          ? 'No tracked source table has changed since this data was fetched. Live sources are read afresh on every fetch, so Refresh may still bring newer figures from them.'
          : 'No source table has changed since this data was fetched, so Refresh won’t show anything new.'));
      }
      if (st && !st.busy && st.cue === 'static') {
        panel.append(el('p', 'pn-fresh-note', 'These sources never change, so Refresh won’t show anything new.'));
      }
      if (st && !st.busy && st.cue === 'newer') {
        panel.append(el('p', 'pn-fresh-note pn-fresh-accent', 'A source table has changed since this data was fetched. Refresh data to see it.'));
      }
      panel.append(el('p', 'pn-fresh-foot', 'Refresh data re-runs these queries now. For shared data, everyone sees the new result.'));
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
      const fallback = ['#6366F1', '#0EA5E9', '#94A3B8', '#F59E0B', '#10B981', '#64748B', '#EF4444', '#A78BFA'];
      try {
        const css = getComputedStyle(document.documentElement);
        return fallback.map((c, i) => css.getPropertyValue(`--chart-${i + 1}`).trim() || c);
      } catch (e) { return fallback; }
    })(),
    data(id) {
      if (calcs[id]) return calcValue(id);
      if (!cfg.datasets[id]) return { status: 'missing', data: [], columns: [], message: `Unknown dataset ${id}` };
      if (cfg.datasets[id].allowed === false) return { status: 'forbidden', data: [], columns: [], message: 'No access to this section' };
      if (!sets[id]) load(id);
      const s = sets[id];
      return { status: s.status, data: s.data, rows: s.data, columns: s.columns, message: s.message, refreshing: s.refreshing,
        cut: s.cut, fetchedAt: s.fetchedAt, meta: [] };
    },
    onData(fn) { subs.push(fn); try { fn(); } catch (e) { console.error('dashboard callback failed', e); } },
    params: () => ({ ...params }),
    env: cfg.env || 'prod',
    allowed: (id) => !!cfg.datasets[id] && cfg.datasets[id].allowed !== false,
    setParams(upd) {
      const changed = Object.keys(upd).filter((k) => params[k] !== upd[k]);
      params = { ...params, ...upd };
      for (const id of Object.keys(sets)) if (sets[id].key !== keyFor(id)) load(id);
      if (changed.length) notify();
    },
    resetParams() { dash.setParams({ ...cfg.params }); },
    calc(id, spec) { calcs[id] = spec; },
    loader() {},
    setLink(name) { history.replaceState(null, '', name ? `#${name}` : location.pathname + location.search); },
    refresh(id) { if (sets[id]) load(id, true); },
    refreshAll() { for (const id of Object.keys(sets)) load(id, true); },
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
  let rt;
  addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(notify, 150); });
})();
