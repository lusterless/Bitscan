# TASK-259 IMPL: agent-install.md names the current pre-release `0.2.0~pre2-1`

Implementer: impl-deploy, 2026-11-08. Follow-up to TASK-253 (REQ-289, REQ-290; PD-50 (a)), assigned by the lead after the TASK-254 hand-off. Only `deploy/runbooks/agent-install.md` changed.

## Change (+2 / −2)

- L7: "**Pre-release `0.2.0~pre1-1`** (not a supported release) runs compliance jobs." becomes "**Pre-release `0.2.0~pre2-1`** …". The rest of the sentence is unchanged: it still describes the compliance pre-release.
- L178 (section 6, Upgrade): "A `0.1.0-1` host upgrades to the pre-release `0.2.0~pre1-1` the same way, since it sorts above `0.1.0-1`." becomes "A `0.1.0-1` or `0.2.0~pre1-1` host upgrades to the pre-release `0.2.0~pre2-1` the same way, since it sorts above both." The upgrade path is kept. The `0.2.0~pre1-1` source matches the changelog entry's "Upgrades 0.1.0-1 and 0.2.0~pre1-1 in place".

Now agrees with `deploy/debian/changelog` (top entry `0.2.0~pre2-1`) and `README.md` L16.

## How to check

- `python -I deploy/tests/check_runbook_text.py deploy/runbooks/agent-install.md` → `FAIL 1 files, 17 sh blocks, 2 findings`: the same two known findings as before the change (L79 and L123, the `bse_REPLACE_WITH_THE_ENROLMENT_TOKEN` placeholders), so nothing is new.
- `grep -n 'pre1\|pre2' deploy/runbooks/agent-install.md`: only L7 and L178. L178 still holds `0.1.0~pre1-1 sorts below 0.1.0-1` (unchanged).
- Version order, for the walk (WSL): `dpkg --compare-versions 0.1.0-1 lt 0.2.0~pre2-1 && dpkg --compare-versions 0.2.0~pre1-1 lt 0.2.0~pre2-1`.

## Builder checklist

Docs only. Items 11 and 12 hold (no secret, no client text); the rest don't apply.
