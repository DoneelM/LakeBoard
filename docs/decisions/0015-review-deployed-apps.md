# 0015. Review deployed apps

- **Status:** Accepted
- **Date:** 2026-11-18

## Context

A successful deploy can have an unavailable scan or a dashboard that fails after it loads. A source change
can also alter response times, while the app reports healthy.

## Decision

Use `scripts/review_app.py` to check LakeBoard health and the security scan for the active deployment with an
explicit workspace profile. Unavailable or incomplete scans remain unverified. A tracked rule must be absent
from a completed scan regardless of its triage state. The operator also checks changed dashboards as a viewer,
reviews Insights for the relevant time window and records any recommendation alongside the release.

## Why

Checking live behavior, scanner coverage and system metrics separately makes it clear which evidence supports
each conclusion. The check is read-only and works without changing workspace permissions or creating a service.

## Limitations

The operator reads system metrics in the workspace UI. CI runs static checks and tests, while this review
requires a deployed app and suitable access. A sparse metrics window cannot establish performance under load.

## Links

- [Deployment review](../OPERATIONS.md#review-a-deployment)
- [Promotion workflow](../PROMOTION.md#the-steps-for-one-change)
