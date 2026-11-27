# Approvals

One line per PR review pass. A new commit means a new head SHA and a new line.

| PR | Head SHA | Who passed | When (NZ time) | Result |
|----|----------|------------|----------------|--------|
| #40 | 79ab426 | Iron Man (code review) | 2026-11-27 14:55 NZDT | REQUEST CHANGES |
| #40 | acea68c | Iron Man (code review) | 2026-11-27 14:58 NZDT | APPROVE (pending Doneel's approve.py re-run) |
| #40 | 56aedce | Iron Man (code review) | 2026-11-27 15:03 NZDT | APPROVE. Decision 0018: (1) shared SQL is viewer-independent (no current_user(), row filters or masks); (2) the page loads nothing external (only the portal's own kit and dataset API, no map/tiles, no external URLs) and builds DOM as text (no innerHTML). Pending Doneel's approve.py on this exact SHA. |
| #40 | 56aedce | Iron Man (code review) | 2026-11-27 15:03 NZDT | APPROVE (bands.sql NULL fix; pending Doneel's approve.py re-run) |
| #40 | 56aedce | Wolverine (security) | 2026-11-27 15:11 NZDT | PASS (security; Info only) |
