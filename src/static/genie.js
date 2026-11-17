/* Ask Genie: a chat bar at the bottom of dashboards that have a Genie space in this environment (genie: in dashboard.yml).
 * Questions go to the portal (/api/d/<slug>/genie/...), which asks Genie as the signed-in person. Everything typed or
 * returned is shown as text, never as HTML. See docs/DESIGN.md and docs/AUTHORING.md. */
(() => {
  const cfg = window.PORTAL;
  if (!cfg || !cfg.genie || !cfg.slug || !window.kit || !window.dash) return;
  const { h } = kit;
  const base = `/api/d/${encodeURIComponent(cfg.slug)}/genie`;
  const MAX_Q = 1000, MAX_ITEMS = 20, LIMIT_MS = 5 * 60 * 1000;
  const DONE = new Set(['COMPLETED', 'FAILED', 'CANCELLED', 'QUERY_RESULT_EXPIRED']);
  const WORDS = {
    SUBMITTED: 'Sending your question…', FILTERING_CONTEXT: 'Looking at the data…', FETCHING_METADATA: 'Looking at the data…',
    ASKING_AI: 'Thinking…', PENDING_WAREHOUSE: 'Waiting for the data warehouse to start…', EXECUTING_QUERY: 'Running the query…',
  };
  const BAR_TEXT = 'Ask Genie about this dashboard…';
  let conv = null;      // current conversation id
  let busy = false;     // one question at a time
  let run = 0;          // bumps on New chat, so old polls stop
  let unseen = false;   // an answer arrived while the panel was closed
  const removed = new Set(); // context items the person took out ("key\u0000value")

  /* ---------- layout ---------- */
  const barText = h('span', { class: 'pg-bar-text' }, BAR_TEXT);
  const bar = h('button', { type: 'button', class: 'pg-bar', 'aria-expanded': 'false', 'aria-controls': 'pg-panel', 'aria-label': 'Ask Genie about this dashboard' },
    h('span', { class: 'pg-spark', 'aria-hidden': 'true' }, '✦'), barText);
  const newBtn = h('button', { type: 'button', class: 'pg-hbtn' }, 'New chat');
  const closeBtn = h('button', { type: 'button', class: 'pg-hbtn pg-close', 'aria-label': 'Close Ask Genie' }, '×');
  const log = h('div', { class: 'pg-log', role: 'log', 'aria-label': 'Conversation with Genie' });
  const intro = h('div', { class: 'pg-intro' });
  const ctxBox = h('div', { class: 'pg-context', hidden: true });
  const input = h('textarea', { class: 'pg-input', rows: 1, maxlength: MAX_Q, placeholder: 'Ask a question about this dashboard', 'aria-label': 'Your question for Genie' });
  const send = h('button', { type: 'submit', class: 'pg-send' }, 'Ask');
  const form = h('form', { class: 'pg-form' }, input, send);
  const status = h('p', { class: 'pg-status', role: 'status', 'aria-live': 'polite' });
  const panel = h('section', { class: 'pg-panel', id: 'pg-panel', role: 'dialog', 'aria-modal': 'false', 'aria-labelledby': 'pg-title', hidden: true },
    h('div', { class: 'pg-head' },
      h('div', null, h('h2', { id: 'pg-title' }, 'Ask Genie'),
        h('p', null, 'Answers use your own data access. Genie can make mistakes, so check important numbers against the dashboard.')),
      newBtn, closeBtn),
    intro, log, ctxBox, form, status);
  const root = h('div', { class: 'pg-genie' }, bar, panel);
  document.body.append(root);
  document.documentElement.classList.add('pg-has-genie');

  /* ---------- open / close ---------- */
  function open() {
    root.classList.add('pg-open');
    panel.hidden = false;
    bar.setAttribute('aria-expanded', 'true');
    unseen = false;
    updateBar();
    refreshContext();
    scrollDown();
    input.focus();
  }
  function close() {
    root.classList.remove('pg-open');
    panel.hidden = true;
    bar.setAttribute('aria-expanded', 'false');
    bar.focus();
  }
  const isOpen = () => !panel.hidden;
  function updateBar() {
    barText.textContent = busy ? 'Genie is working on your question…' : unseen ? 'Genie has answered. Open to read it' : BAR_TEXT;
  }
  bar.addEventListener('click', open);
  closeBtn.addEventListener('click', close);
  panel.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); close(); } });
  newBtn.addEventListener('click', () => {
    run++; conv = null; busy = false; removed.clear();
    log.replaceChildren(); status.textContent = 'New chat started.';
    drawIntro(); refreshContext(); updateSend(); updateBar(); input.focus();
  });

  /* ---------- starter questions ---------- */
  function drawIntro() {
    const samples = (cfg.genie.samples || []).slice(0, 5);
    if (log.childElementCount) { intro.replaceChildren(); return; }
    intro.replaceChildren(
      h('p', null, 'Ask in plain English. Genie writes the query, runs it with your access, and shows the SQL it used.'),
      samples.length ? h('div', { class: 'pg-row' }, h('span', { class: 'pg-label' }, 'Try'),
        samples.map((q) => h('button', { type: 'button', class: 'pg-chip', onclick: () => ask(q) }, q))) : null);
  }

  /* ---------- context chips: what is sent with the question ---------- */
  function contextItems() {
    const items = [];
    const p = dash.params();
    for (const k of Object.keys(cfg.params || {})) if (p[k] !== null && p[k] !== undefined && p[k] !== '') items.push({ kind: 'params', key: k, value: String(p[k]) });
    for (const [k, v] of Object.entries(dash.genieContext())) items.push({ kind: 'context', key: k, value: v });
    return items.slice(0, MAX_ITEMS).map((x) => ({ ...x, key: x.key.slice(0, 40), value: x.value.slice(0, 200), id: x.key + '\u0000' + x.value }));
  }
  function refreshContext() {
    const items = contextItems();
    const kept = items.filter((x) => !removed.has(x.id));
    ctxBox.hidden = !items.length;
    ctxBox.replaceChildren(h('div', { class: 'pg-row' },
      h('span', { class: 'pg-label' }, kept.length ? 'Sending with your question' : 'Not sending the dashboard view'),
      kept.map((x) => h('span', { class: 'pg-ctx' }, h('span', { title: `${x.key} = ${x.value}` }, `${x.key} = ${x.value}`),
        h('button', { type: 'button', 'aria-label': `Leave out ${x.key}`, title: 'Leave this out', onclick: () => { removed.add(x.id); refreshContext(); input.focus(); } }, '×'))),
      kept.length < items.length ? h('button', { type: 'button', class: 'pg-link', onclick: () => { removed.clear(); refreshContext(); } }, 'Include all again') : null));
    return kept;
  }
  let rt;
  const soon = () => { if (isOpen()) { clearTimeout(rt); rt = setTimeout(refreshContext, 60); } };
  dash.onData(soon);
  document.addEventListener('click', (e) => { if (!panel.contains(e.target)) soon(); });
  document.addEventListener('change', soon);
  input.addEventListener('focus', soon);

  /* ---------- talking to the portal ---------- */
  async function call(url, body) {
    try {
      const res = await fetch(url, body === undefined ? { credentials: 'same-origin' }
        : { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await res.json().catch(() => ({}));
      if (res.ok) return { ok: true, data };
      const msg = data.error || (typeof data.detail === 'string' ? data.detail : '')
        || (res.status === 401 ? 'Your session has expired. Reload the page.' : res.status === 429 ? 'Genie is busy. Try again in a minute.' : 'Genie isn’t answering right now. Try again in a few minutes.');
      return { ok: false, status: res.status, message: msg };
    } catch (e) {
      return { ok: false, status: 0, message: 'Couldn’t reach the portal. Check your connection and try again.' };
    }
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function scrollDown() { log.scrollTop = log.scrollHeight; }
  function updateSend() { send.disabled = busy; input.setAttribute('aria-busy', String(busy)); }

  form.addEventListener('submit', (e) => { e.preventDefault(); ask(input.value); });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); } });
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(120, input.scrollHeight + 2) + 'px'; });

  async function ask(text) {
    const question = String(text || '').trim();
    if (busy) { status.textContent = 'Genie is still working on the last question.'; return; }
    if (!question) { status.textContent = 'Type a question first.'; input.focus(); return; }
    if (question.length > MAX_Q) { status.textContent = `Keep the question under ${MAX_Q} characters.`; return; }
    if (!isOpen()) open();
    busy = true; updateSend(); updateBar();
    const token = run;
    const kept = refreshContext();
    const params = {}, context = {};
    for (const x of kept) (x.kind === 'params' ? params : context)[x.key] = x.value;
    input.value = ''; input.style.height = '';
    intro.replaceChildren();
    const sent = h('p', { class: 'pg-sent' });
    const answer = h('div', { class: 'pg-a' }, h('p', { class: 'pg-working' }, 'Sending your question…'));
    log.append(h('article', { class: 'pg-turn', 'aria-label': 'Question and answer' }, h('div', { class: 'pg-q' }, question), sent, answer));
    scrollDown();
    status.textContent = 'Sending your question to Genie.';
    const res = await call(`${base}/ask`, { question, conversation_id: conv, context, params });
    if (token !== run) return;
    if (!res.ok) { finish(answer, null, res.message); return; }
    conv = res.data.conversation_id;
    if (res.data.context_sent && kept.length) sent.textContent = 'Sent with: ' + kept.map((x) => `${x.key} = ${x.value}`).join(' · ');
    else if (res.data.context_sent) sent.textContent = 'Sent with the dashboard name only.';
    poll(answer, conv, res.data.message_id, token);
  }

  async function poll(answer, c, m, token) {
    const started = Date.now();
    let delay = 1500, misses = 0, last = '';
    while (token === run) {
      await sleep(delay);
      if (token !== run) return;
      if (Date.now() - started > LIMIT_MS) { finish(answer, null, 'Genie took too long, so the portal stopped waiting. Try a simpler question, or start a new chat.'); return; }
      const res = await call(`${base}/${encodeURIComponent(c)}/${encodeURIComponent(m)}`);
      if (token !== run) return;
      if (!res.ok) {
        if (res.status === 0 && ++misses < 4) { delay = 5000; continue; }
        finish(answer, null, res.message); return;
      }
      misses = 0;
      const st = res.data.status;
      if (DONE.has(st)) { finish(answer, { ...res.data, conversation_id: c, message_id: m }, ''); return; }
      const words = WORDS[st] || 'Working on it…';
      if (words !== last) { last = words; answer.replaceChildren(h('p', { class: 'pg-working' }, words)); status.textContent = words; }
      delay = Math.min(5000, Math.round(delay * 1.4));
    }
  }

  function finish(answer, r, problem) {
    busy = false; updateSend();
    if (!isOpen()) unseen = true;
    updateBar();
    answer.replaceChildren(...(r ? drawAnswer(r) : [h('p', { class: 'pg-error', role: 'alert' }, problem)]));
    status.textContent = r && !r.error ? 'Genie has answered.' : 'Genie couldn’t answer.';
    scrollDown();
    if (isOpen()) input.focus();
  }

  /* ---------- drawing an answer ---------- */
  const isNum = (v) => v !== null && v !== '' && !isNaN(+v);
  /* Genie marks key figures with **bold**. Show that as bold text, built as elements (never parsed as HTML). */
  const rich = (text) => String(text).split(/\*\*([^*\n]+)\*\*/).map((part, i) => (i % 2 ? h('strong', null, part) : part));
  function drawAnswer(r) {
    const out = [];
    if (r.text) out.push(h('p', { class: 'pg-text' }, rich(r.text)));
    if (r.description && r.description !== r.text) out.push(h('p', { class: 'pg-desc' }, r.description));
    if (r.columns && r.columns.length) {
      const columns = r.columns.map((name, i) => {
        const vals = r.rows.map((row) => row[i]).filter((v) => v !== null && v !== '');
        const numeric = vals.length > 0 && vals.every(isNum);
        const dp = numeric && vals.some((v) => !Number.isInteger(+v)) ? 2 : 0;
        return { key: 'c' + i, label: name, align: numeric ? 'right' : null, fmt: numeric ? (v) => kit.fmt.num(v, dp) : null };
      });
      const rows = r.rows.map((row) => Object.fromEntries(row.map((v, i) => ['c' + i, v])));
      const box = h('div', { class: 'pg-table' });
      if (rows.length) kit.table(box, { columns, rows, max: 200, csv: `${cfg.slug}-genie-answer` });
      else box.append(h('p', { class: 'pg-note' }, 'The query returned no rows.'));
      out.push(box);
      if (r.truncated) out.push(h('p', { class: 'pg-note' }, 'Showing the first 200 rows only.'));
    }
    if (r.sql) out.push(h('details', { class: 'pg-sql' }, h('summary', null, 'Show SQL'), h('pre', null, h('code', null, r.sql))));
    if (r.error) out.push(h('p', { class: 'pg-error' }, r.error));
    if (!out.length) out.push(h('p', { class: 'pg-note' }, 'Genie didn’t return an answer. Try rewording the question.'));
    if (r.suggested_questions && r.suggested_questions.length) {
      out.push(h('div', { class: 'pg-row' }, h('span', { class: 'pg-label' }, 'Ask next'),
        r.suggested_questions.map((q) => h('button', { type: 'button', class: 'pg-chip', onclick: () => ask(q) }, q))));
    }
    if (r.status === 'COMPLETED') out.push(feedbackRow(r.conversation_id, r.message_id));
    return out;
  }

  const THUMB = 'M7 10v11H3V10h4zm0 0l4-8c1.7 0 3 1.3 3 3v4h5.2c1.2 0 2.1 1.1 1.9 2.3l-1.4 8c-.2 1-1 1.7-2 1.7H7';
  function thumbIcon(down) {
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    if (down) svg.setAttribute('transform', 'rotate(180)');
    const path = document.createElementNS(ns, 'path'); path.setAttribute('d', THUMB); svg.append(path);
    return svg;
  }
  function feedbackRow(c, m) {
    const note = h('span', { class: 'pg-note', 'aria-live': 'polite' });
    const btn = (rating, label) => h('button', { type: 'button', class: 'pg-thumb', 'aria-label': label, title: label, 'aria-pressed': 'false',
      onclick: async (e) => {
        const b = e.currentTarget;
        const res = await call(`${base}/${encodeURIComponent(c)}/${encodeURIComponent(m)}/feedback`, { rating });
        if (!res.ok) { note.textContent = res.message; return; }
        for (const x of row.querySelectorAll('.pg-thumb')) x.setAttribute('aria-pressed', String(x === b));
        note.textContent = 'Thanks, Genie’s owners will see this.';
      } }, thumbIcon(rating === 'down'));
    const row = h('div', { class: 'pg-row' }, btn('up', 'Good answer'), btn('down', 'Wrong or unhelpful answer'), note);
    return row;
  }

  drawIntro();
  updateSend();
})();
