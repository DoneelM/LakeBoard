"""Never confuse unavailable scanner data or triaged findings with verified clearance."""
from types import SimpleNamespace

import pytest

from scripts.review_app import assess_scan


@pytest.mark.parametrize("status,omitted", [("UNAVAILABLE", 0), ("UNSPECIFIED", 0), ("PARTIAL", 0),
                                           ("NOT_SCANNED", 0), ("CLEAN", 1), ("FINDINGS", 0)])
def test_incomplete_scan_is_not_clear(status, omitted):
    assert assess_scan(status, omitted, [])


def test_completed_scan_with_no_findings():
    assert assess_scan("CLEAN", 0, [], "tracked-sql-rule") is None


def test_tracked_finding_still_counts_after_triage():
    finding = SimpleNamespace(rule_id="tracked-sql-rule", severity="SCAN_FINDING_SEVERITY_ERROR",
                              status="SCAN_FINDING_STATUS_RESOLVED")
    assert assess_scan("FINDINGS", 0, [finding], "tracked-sql-rule")
    assert assess_scan("FINDINGS", 0, [finding]) is None
