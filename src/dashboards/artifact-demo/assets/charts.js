// Chart helpers for the Artifact Demo page. Loaded by <script src="charts.js"> and run in its own scope,
// so only what is put on window is shared with the page script.
const fmt = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });

// Shows loading / error / empty in el and returns false until every result is ready.
function ready(el, ...results) {
  const bad = results.find((r) => r.status !== 'ok');
  if (bad) {
    el.replaceChildren();
    const p = document.createElement('p');
    p.className = bad.status === 'loading' ? 'dash-skeleton ad-state' : 'ad-state ad-state-error';
    p.textContent = bad.status === 'loading' ? 'Loading…' : `Couldn't load this data: ${bad.message || bad.status}`;
    el.append(p);
    return false;
  }
  if (results.some((r) => !r.data || !r.data.length)) {
    el.replaceChildren();
    const p = document.createElement('p');
    p.className = 'ad-state';
    p.textContent = 'No data for this selection.';
    el.append(p);
    return false;
  }
  return true;
}

// Lines over x, one per series; the selected series is drawn in colour, the rest muted.
function lines(el, { series, x, y, selected, yFormat = fmt.format }) {
  const width = Math.max(280, el.clientWidth);
  const height = 260;
  const m = { top: 12, right: 96, bottom: 26, left: 52 };
  const all = series.flatMap((s) => s.points);
  const xs = d3.scaleLinear().domain(d3.extent(all, (p) => p[x])).range([m.left, width - m.right]);
  const ys = d3.scaleLinear().domain(d3.extent(all, (p) => p[y])).nice().range([height - m.bottom, m.top]);
  const svg = d3.create('svg').attr('viewBox', `0 0 ${width} ${height}`).attr('width', width).attr('height', height)
    .attr('class', 'ad-svg').attr('role', 'img').attr('aria-label', 'Revenue by year, one line per region');
  svg.append('g').attr('transform', `translate(0,${height - m.bottom})`)
    .call(d3.axisBottom(xs).ticks(Math.min(6, width / 80)).tickFormat(d3.format('d')).tickSizeOuter(0));
  svg.append('g').attr('transform', `translate(${m.left},0)`)
    .call(d3.axisLeft(ys).ticks(5).tickFormat(yFormat).tickSize(-(width - m.left - m.right)))
    .call((g) => g.select('.domain').remove());
  const line = d3.line().x((p) => xs(p[x])).y((p) => ys(p[y]));
  const order = [...series].sort((a, b) => (a.key === selected) - (b.key === selected));  // selected on top
  for (const s of order) {
    const on = !selected || s.key === selected;
    const colour = on ? dash.colors[series.indexOf(s) % dash.colors.length] : 'var(--cds-chart-muted)';
    svg.append('path').datum(s.points).attr('fill', 'none').style('stroke', colour)
      .attr('stroke-width', on ? 2.5 : 1.5).attr('d', line);
    const last = s.points[s.points.length - 1];
    svg.append('text').attr('x', xs(last[x]) + 6).attr('y', ys(last[y])).attr('dy', '0.35em')
      .attr('class', on ? 'ad-label ad-label-on' : 'ad-label').text(s.key);
  }
  el.replaceChildren(svg.node());
}

// Ranked horizontal bars, one per row.
function bars(el, { rows, label, value, format = fmt.format }) {
  const width = Math.max(260, el.clientWidth);
  const rowH = 30;
  const m = { left: 104, right: 56 };
  const height = rows.length * rowH;
  const xs = d3.scaleLinear().domain([0, d3.max(rows, (r) => r[value]) || 1]).range([0, width - m.left - m.right]);
  const svg = d3.create('svg').attr('viewBox', `0 0 ${width} ${height}`).attr('width', width).attr('height', height)
    .attr('class', 'ad-svg').attr('role', 'img').attr('aria-label', 'Revenue by market segment');
  const g = svg.selectAll('g').data(rows).join('g').attr('transform', (r, i) => `translate(0,${i * rowH})`);
  g.append('text').attr('x', m.left - 8).attr('y', rowH / 2).attr('dy', '0.35em').attr('text-anchor', 'end')
    .attr('class', 'ad-label ad-label-on').text((r) => r[label]);
  g.append('rect').attr('x', m.left).attr('y', 6).attr('height', rowH - 12).attr('width', (r) => xs(r[value]))
    .style('fill', dash.colors[0]);
  g.append('text').attr('x', (r) => m.left + xs(r[value]) + 6).attr('y', rowH / 2).attr('dy', '0.35em')
    .attr('class', 'ad-label').text((r) => format(r[value]));
  el.replaceChildren(svg.node());
}

window.AdCharts = { fmt, ready, lines, bars };
