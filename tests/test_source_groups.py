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
];
const g = groupSourceTables(tables,100);
assert.deepEqual(g.changed.map(t=>t.name), ['newest','new']);
assert.deepEqual(g.unchanged.map(t=>t.name), ['equal','older']);
assert.deepEqual(g.untracked.map(t=>t.name), ['live','static','unknown']);
assert.equal(groupSourceTables(tables,200).changed.length,0);
assert.equal(groupSourceTables(tables,null).untracked.length,7);
assert.equal(tables[0].name,'older');
""", str(source)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
