"""Run the actual pure JavaScript source grouping helper, without a frontend toolchain."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_source_groups_compare_each_fetch_time_and_sort_changed_first():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the JavaScript unit test")
    source = Path(__file__).resolve().parents[1] / "src/static/source-groups.js"
    result = subprocess.run([node, "-e", """
const assert = require('node:assert/strict');
const {groupSourceTables} = require(process.argv[1]);
const tables = [
 {name:'older', kind:'managed', updated_at:90},
 {name:'live', kind:'live', updated_at:300},
 {name:'new', kind:'managed', updated_at:150},
 {name:'newest', kind:'managed', updated_at:200},
 {name:'equal', kind:'managed', updated_at:100},
 {name:'unknown', kind:'unknown', updated_at:null},
 {name:'static', kind:'static', updated_at:null},
 {name:'none', kind:'none', updated_at:null},
 {name:'ext', kind:'external', updated_at:null},
];
const g = groupSourceTables(tables,100);
assert.deepEqual(g.changed.map(t=>t.name), ['newest','new']);
assert.deepEqual(g.unchanged.map(t=>t.name), ['equal','older']);  // newest first
assert.deepEqual(g.untracked.map(t=>t.name), ['live','ext','static','unknown','none']);  // by kind, then name
assert.equal(groupSourceTables(tables,200).changed.length,0);
assert.equal(groupSourceTables(tables,null).untracked.length,9);
assert.equal(tables[0].name,'older');
""", str(source)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_span_says_how_long_after_your_data_a_table_changed():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the JavaScript unit test")
    source = Path(__file__).resolve().parents[1] / "src/static/source-groups.js"
    result = subprocess.run([node, "-e", """
const assert = require('node:assert/strict');
const {span} = require(process.argv[1]);
assert.equal(span(30), 'under a minute');
assert.equal(span(22 * 60), '22 min');
assert.equal(span(3 * 3600 + 59), '3 h');
assert.equal(span(86400), '1 day');
assert.equal(span(2 * 86400 + 5), '2 days');
""", str(source)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
