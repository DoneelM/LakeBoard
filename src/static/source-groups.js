/* Pure source ordering, shared by the freshness panel and its Node tests. */
(() => {
  function groupSourceTables(tables, fetchedAt) {
    const groups = { changed: [], unchanged: [], untracked: [] };
    for (const table of tables) {
      const timed = table.kind === 'managed' && Number.isFinite(table.updated_at);
      const bucket = timed && Number.isFinite(fetchedAt)
        ? (table.updated_at > fetchedAt ? 'changed' : 'unchanged') : 'untracked';
      groups[bucket].push(table);
    }
    groups.changed.sort((a, b) => b.updated_at - a.updated_at || a.name.localeCompare(b.name));
    groups.unchanged.sort((a, b) => a.name.localeCompare(b.name));
    groups.untracked.sort((a, b) => a.name.localeCompare(b.name));
    return groups;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { groupSourceTables };
  else window.LakeBoardSourceGroups = { groupSourceTables };
})();
