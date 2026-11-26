/* Pure source ordering, shared by the freshness panel and its Node tests. */
(() => {
  // Untracked sources: live ones first (always current), then external, fixed, unknown, and "reads no table".
  const UNTRACKED_RANK = { live: 0, external: 1, static: 2, unknown: 3, none: 4 };
  const untrackedRank = (t) => (t.kind in UNTRACKED_RANK ? UNTRACKED_RANK[t.kind] : UNTRACKED_RANK.unknown);

  function groupSourceTables(tables, fetchedAt) {
    const groups = { changed: [], unchanged: [], untracked: [] };
    for (const table of tables) {
      const timed = table.kind === 'managed' && Number.isFinite(table.updated_at);
      const bucket = timed && Number.isFinite(fetchedAt)
        ? (table.updated_at > fetchedAt ? 'changed' : 'unchanged') : 'untracked';
      groups[bucket].push(table);
    }
    const newestFirst = (a, b) => b.updated_at - a.updated_at || a.name.localeCompare(b.name);
    groups.changed.sort(newestFirst);
    groups.unchanged.sort(newestFirst);  // the most recently written unchanged table is the next likely to change
    groups.untracked.sort((a, b) => untrackedRank(a) - untrackedRank(b) || a.name.localeCompare(b.name));
    return groups;
  }

  // A length of time in seconds, for "N after your data": "under a minute", "22 min", "3 h", "2 days".
  function span(sec) {
    const m = Math.floor(sec / 60);
    if (m < 1) return 'under a minute';
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} h`;
    const d = Math.floor(h / 24);
    return `${d} day${d === 1 ? '' : 's'}`;
  }

  const api = { groupSourceTables, span };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else window.LakeBoardSourceGroups = api;
})();
