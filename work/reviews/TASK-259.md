# TASK-259 REVIEW: agent-install.md names the current pre-release `0.2.0~pre2-1`

Reviewer: reviewer-m11, 2026-11-09. Round 1. Low risk (docs), one approval.

Verdict: APPROVED

**Scope reviewed:** `deploy/runbooks/agent-install.md`, L7 and L178 (+2 / −2).

**Reports:**
- `work/reports/TASK-259-impl.md`
- `work/reports/TASK-259-test.md`: PASS. `dpkg --compare-versions` confirms both upgrade paths, and `check_runbook_text.py` reports only its two pre-existing placeholder findings.

## Checks

- L7 now names `0.2.0~pre2-1`, which matches the changelog's top entry and `README.md`.
- L178 now says that `0.1.0-1` and `0.2.0~pre1-1` hosts both upgrade in place. That matches the changelog's "Upgrades 0.1.0-1 and 0.2.0~pre1-1 in place", and the version order holds.
- Every other sentence is unchanged. No new checker finding: the two at L79 and L123 are the known M6 `bse_REPLACE…` placeholders.

## Findings

None.
