# TASK-258 REVIEW: unrecognised stored target is "unknown", never All hosts

Reviewer: reviewer-m11, 2026-11-08. Round 2 (r1). Low risk, one approval. This closes finding 1 of `work/reviews/TASK-246.md`.

Verdict: APPROVED

## Round 2 (r1)

- **Change:** r1 adds the full stop after the strong text: `<strong>Unknown target</strong>. It is kept unless you choose one of these forms.` (`TargetPicker.tsx:179`).
- **Nothing else changed.** The tester re-ran `TargetPicker` and `Schedules`: 68/68, gates green.
- Round 1 finding 1 is resolved. No new findings.

## Round 1

**Scope reviewed:** `web/src/components/TargetPicker.tsx` and `web/src/screens/ScheduleForm.tsx`, +25 / −6 against `9371354`.

**Checked against:**
- #122 (b): exactly three target forms; `all` only as `true`.
- REQ-282: an edit sends only the changed fields.
- The lead's ruling of 2026-11-08.

**Reports:**
- `work/reports/TASK-258-impl.md`
- `work/reports/TASK-258-test.md`: PASS, 85/85 affected, App 44/44, plants CHK-M11-439 and -440 red.

### Checks

- **Fails closed:**
  - `fromTarget` returns All hosts only for `all === true`. Any other unrecognised shape is `kind: "unknown"`.
  - `toTarget` never builds a body from `unknown`.
  - On edit, an unknown target is kept: no `target` key is sent. The other changed fields are still sent, and when nothing changed, nothing is sent.
  - On create, the target can never be unknown.
  - The plant that restores the old mapping is red, including the "never `{all: true}`" row.
- **Unchanged paths:**
  - Valid tags and agents targets map as before.
  - A target that also carries `resolved_agents` reads as its requested form.
  - RunScan is unaffected.
- **Plain text:** the new note is static JSX.
- **Re-run (Windows):**
  - `TargetPicker.test.tsx`, `Schedules.test.tsx` and `RunScan.test.tsx`: 85 passed.
  - `eslint` on both files exits 0, and Prettier is clean.

### Findings

1. nit, resolved in r1, `TargetPicker.tsx`: the note had no full stop after "Unknown target".
