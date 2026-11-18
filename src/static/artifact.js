/* Runs a Claude Dashboard artifact page (`page: artifact` in dashboard.yml; decision 0011).
 *
 * The server sends the page untouched inside <template id="dash-artifact">, so nothing in it loads or runs early.
 * This script does what the artifact host does:
 *   1. drops what the artifact host drops: module scripts, iframe, object, base, on…= attributes; a form is
 *      unwrapped (its contents stay, the form element goes);
 *   2. points files named by bare name (src="app.js", href="theme.css") at /d/<slug>/assets/<name>;
 *   3. mounts the page in #dash-root, waits for its stylesheets, then runs its scripts in order, each in its own
 *      function scope (anything shared goes on window);
 *   4. starts the drawings (dash.draw).
 * Only same-origin files are fetched; the Content-Security-Policy blocks anything else anyway. */
(() => {
  const cfg = window.PORTAL || {};
  if (cfg.page !== 'artifact') return;
  const tpl = document.getElementById('dash-artifact');
  const root = document.getElementById('dash-root');
  const assets = new Set(cfg.assets || []);
  const base = `/d/${encodeURIComponent(cfg.slug)}/assets/`;
  const CLASSIC = new Set(['', 'text/javascript', 'application/javascript', 'text/ecmascript', 'application/ecmascript']);

  /* A bare file name (optionally ./name, ?query or #hash) that is in assets/ -> its URL, else null. */
  function assetUrl(ref) {
    const m = /^(?:\.\/)?([A-Za-z0-9][A-Za-z0-9._-]*)([?#].*)?$/.exec((ref || '').trim());
    return m && assets.has(m[1]) ? base + encodeURIComponent(m[1]) + (m[2] || '') : null;
  }

  function prepare(frag) {
    for (const el of frag.querySelectorAll('script[type="module" i], iframe, object, base')) el.remove();
    for (const form of frag.querySelectorAll('form')) form.replaceWith(...form.childNodes);
    for (const el of frag.querySelectorAll('*')) {
      for (const a of [...el.attributes]) if (/^on/i.test(a.name)) el.removeAttribute(a.name);
    }
    const attrs = [['link', 'href'], ['img', 'src'], ['source', 'src'], ['video', 'src'], ['video', 'poster'],
      ['audio', 'src'], ['image', 'href'], ['use', 'href'], ['input', 'src']];
    for (const [tag, attr] of attrs) {
      for (const el of frag.querySelectorAll(`${tag}[${attr}]`)) {
        const url = assetUrl(el.getAttribute(attr));
        if (url) el.setAttribute(attr, url);
      }
    }
    // Scripts come out of the page and run one by one below, so their order and scope are under our control.
    const scripts = [];
    for (const s of frag.querySelectorAll('script')) {
      const type = (s.getAttribute('type') || '').trim().toLowerCase();
      if (!CLASSIC.has(type)) continue;  // data blocks (application/json, text/plain …) stay as they are
      scripts.push({ src: s.getAttribute('src'), text: s.textContent });
      s.remove();
    }
    return scripts;
  }

  function stylesheetsLoaded() {
    const links = [...root.querySelectorAll('link[rel~="stylesheet" i]')].filter((l) => !l.sheet);
    return Promise.race([
      Promise.all(links.map((l) => new Promise((ok) => { l.addEventListener('load', ok); l.addEventListener('error', ok); }))),
      new Promise((ok) => setTimeout(ok, 3000)),  // never hold the page for a slow or missing stylesheet
    ]);
  }

  async function source(s, i) {
    if (!s.src) return { text: s.text, name: `index.html (script ${i + 1})` };
    const url = assetUrl(s.src) || s.src;
    let abs;
    try { abs = new URL(url, location.href); } catch (e) { abs = null; }
    if (!abs || abs.origin !== location.origin) {
      console.warn(`artifact: skipped ${s.src}; only files in assets/ and this portal can be loaded`);
      return null;
    }
    const res = await fetch(abs, { credentials: 'same-origin' });
    if (!res.ok) { console.error(`artifact: couldn't load ${s.src} (${res.status})`); return null; }
    return { text: await res.text(), name: abs.pathname };
  }

  function run({ text, name }) {
    const el = document.createElement('script');
    // Its own scope, like the artifact host: top-level const/let/function stay inside; `this` is window.
    el.textContent = `(function () {\n${text}\n}).call(window);\n//# sourceURL=${encodeURI(name)}`;
    document.body.append(el);  // inline scripts run as soon as they are inserted
    el.remove();
  }

  async function mount() {
    if (!tpl || !root) return;
    const frag = tpl.content.cloneNode(true);
    const scripts = prepare(frag);
    tpl.replaceWith(frag);
    await stylesheetsLoaded();
    // Fetch in parallel, run strictly in page order.
    const texts = scripts.map((s, i) => source(s, i).catch((e) => { console.error(`artifact: couldn't load ${s.src}`, e); return null; }));
    for (const t of texts) {
      const code = await t;
      if (code) run(code);
    }
    if (window.dash && typeof window.dash._artifactReady === 'function') window.dash._artifactReady();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
