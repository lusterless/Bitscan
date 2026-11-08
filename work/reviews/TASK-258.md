# TASK-258 REVIEW: unrecognised stored target is "unknown", never All hosts

Reviewer: reviewer-m11, 2026-11-08. Round 1. Low risk, one approval. This closes finding 1 of `work/reviews/TASK-246.md`.

Verdict: APPROVED

**Scope reviewed:** `web/src/components/TargetPicker.tsx` and `web/src/screens/ScheduleForm.tsx` (+25 / −6 against `9371354`).

**Checked against:** #122 (b) (exactly three target forms; `all` only as `true`), REQ-282 (an edit sends only the changed fields), and the lead's ruling of 2026-11-08.

**Reports:**
- `work/reports/TASK-258-impl.md`
- `work/reports/TASK-258-test.md` (PASS, 85/85 affected, App 44/44, plants CHK-M11-439 and -440 red)

## Checks

- **Fails closed now.**
  - `fromTarget` returns All hosts only for `all === true`. Any other unrecognised shape is `kind: "unknown"`.
  - `toTarget` never builds a body from `unknown`; it answers "Choose a target.".
  - On edit, an unknown target is kept: no `target` key is sent. The other changed fields are still sent, and when nothing changed nothing is sent.
  - On create, the form starts at All hosts and can't be unknown. If it ever were, it is refused.
  - The plant that restores the old mapping is red, including the "never `{all: true}`" row.
- **Unchanged paths.**
  - Valid tags and agents targets map as before.
  - A target that also carries `resolved_agents` reads as its requested form.
  - RunScan is unaffected.
- **Plain text.** The new note is static JSX. No API value is rendered beyond the existing text nodes.
- **Re-run (Windows).**
  - `TargetPicker.test.tsx`, `Schedules.test.tsx` and `RunScan.test.tsx`: 85 passed.
  - `eslint` on both files exits 0, and Prettier is clean.

## Findings

1. nit, `TargetPicker.tsx` (the new note): the JSX `<strong>Unknown target</strong> It is kept unless …` renders as "Unknown target It is kept unless you choose one of these forms." with no full stop after the strong text. Adding a period (`Unknown target.`) would fix it. Cosmetic; no change required.
