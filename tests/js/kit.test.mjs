import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

globalThis.window = { PORTAL: { locale: 'en-NZ' } };
globalThis.document = {
  createElement: (tag) => {
    const attrs = {}, handlers = {}, children = [];
    return {
      tagName: tag.toUpperCase(), className: '', handlers, children,
      setAttribute: (k, v) => { attrs[k] = v; },
      getAttribute: (k) => (k in attrs ? attrs[k] : null),
      addEventListener: (type, fn) => { handlers[type] = fn; },
      append: (...kids) => children.push(...kids),
    };
  },
};
const kit = createRequire(import.meta.url)('../../src/static/kit.js');
const { csvText, fmt, h } = kit;

const cell = (v) => csvText([{ key: 'a', label: 'a' }], [{ a: v }]).split('\r\n')[1];

test('csvText guards formula starts', () => {
  for (const c of ['=1+1', '+SUM(A1)', '-cmd', '@x', '\tx', '-2+3', '+1', '-1e3x', '\t=1', '+64211234567', ' =1', ' =1+1', ' -1+1', '＝1+1', '＋1', '－cmd', '＠x']) {
    assert.equal(cell(c), ( /[",\r\n]/.test("'" + c) ? '"' + ("'" + c).replace(/"/g, '""') + '"' : "'" + c));
  }
  assert.equal(csvText([{ key: 'a' }], [{ a: '\rx' }]), 'a\r\n"\'\rx"');
  assert.equal(csvText([{ key: 'a' }], [{ a: '\n=1' }]), 'a\r\n"\'\n=1"');
  assert.equal(cell('=HYPERLINK("http://x","y")'), '"\'=HYPERLINK(""http://x"",""y"")"');
});

test('csvText guards headers', () => {
  assert.equal(csvText([{ key: 'k', label: '=evil' }], []), "'=evil");
});

test('csvText leaves numbers and plain values alone', () => {
  for (const [v, out] of [[-5, '-5'], ['-5', '-5'], ['1.5', '1.5'], ['2e3', '2e3'], [' -5', ' -5'], ['plain', 'plain'], [null, ''], [undefined, ''], [0, '0']]) assert.equal(cell(v), out);
});

test('csvText quoting and row separator', () => {
  assert.equal(cell('a,b'), '"a,b"');
  assert.equal(cell('say "hi"'), '"say ""hi"""');
  assert.equal(csvText([{ key: 'a' }], [{ a: 'a\nb' }]), 'a\r\n"a\nb"');
  assert.equal(csvText([{ key: 'a' }, { key: 'b' }], [{ a: 1, b: 2 }, { a: 3, b: 4 }]), 'a,b\r\n1,2\r\n3,4');
});

test('fmt', () => {
  assert.equal(fmt.num(1234.5), '1,235');
  assert.equal(fmt.num(1234.5, 1), '1,234.5');
  assert.equal(fmt.money(1234), '$1,234');
  assert.equal(fmt.money(-1234.5, 2), '-$1,234.50');
  assert.equal(fmt.compact(1500), '2k');
  assert.equal(fmt.compact(2_500_000), '2.5m');
  assert.equal(fmt.compact(3e9), '3.0b');
  assert.equal(fmt.compact(-1500), '-2k');
  assert.equal(fmt.pct(0.256), '25.6%');
  assert.equal(fmt.date('2024-03-05'), new Date('2024-03-05T00:00:00').toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' }));
  assert.equal(fmt.month('2024-03'), new Date('2024-03-01T00:00:00').toLocaleDateString('en-NZ', { month: 'short', year: 'numeric' }));
  assert.equal(fmt.text('x'), 'x');
});

test('fmt gives an en dash for null, empty and NaN', () => {
  for (const f of [fmt.num, fmt.money, fmt.compact, fmt.pct, fmt.date, fmt.month]) for (const v of [null, '', NaN]) assert.equal(f(v), '–');
  assert.equal(fmt.text(null), '–');
  assert.equal(fmt.text(''), '–');
});

test('h builds elements', () => {
  const fn = () => {};
  const el = h('div', { class: 'x', id: 'i', hidden: true, a: null, b: false, c: undefined, onclick: fn },
    'a<b>', ['x', ['y']], null, false, undefined);
  assert.equal(el.tagName, 'DIV');
  assert.equal(el.className, 'x');
  assert.equal(el.getAttribute('id'), 'i');
  assert.equal(el.getAttribute('hidden'), '');
  for (const k of ['a', 'b', 'c']) assert.equal(el.getAttribute(k), null);
  assert.equal(el.handlers.click, fn);
  assert.deepEqual(el.children, ['a<b>', 'x', 'y']);
});
