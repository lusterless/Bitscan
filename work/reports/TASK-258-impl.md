# TASK-258 IMPL: unrecognised stored target is "unknown", never All hosts

Owner: impl-web. Worktree `Bitscan-m11`, branch `m11-results`. Not committed.
This is reviewer-m11's nit 1 on TASK-256/249 (`work/reviews/TASK-246.md`), done now because it fails open (the lead, 2026-11-08). Nits 2 (500 profiles) and 3 (`007`) stay follow-ups and are not touched.

## Files (+25 / −6)

- `web/src/components/TargetPicker.tsx`:
  - `TargetValue.kind` gains `"unknown"`.
  - `fromTarget` returns `ALL_HOSTS` only for `all: true`. Any target that is none of the three forms becomes `{kind: "unknown"}`. Examples: `{}`, `{all: "true"}`, `{tags: "db"}`, `{foo: 1}`.
  - `toTarget` answers the fixed text "Choose a target." for `unknown` and never builds a body from it.
  - `TargetPicker` shows "**Unknown target**" (a `<strong>`) followed by "It is kept unless you choose one of these forms.". No radio is checked. Choosing a radio replaces the unknown value with that form.
  - `describeTarget` is unchanged and already gives "Unknown target".
- `web/src/screens/ScheduleForm.tsx`:
  - **Edit:** if the target is still `unknown`, the PATCH carries **no `target` key**. The other changed fields still go, and if nothing else changed the form shows "Nothing has changed." and sends nothing. Once the user chooses a form, that target is validated and sent as before.
  - **Create:** the form starts at All hosts and so can never be `unknown`. If it were, `toTarget` would refuse it with "Choose a target.", so a new schedule always needs a real form.

Unchanged:
- A stored target that also carries `resolved_agents` still reads as its requested form, because only `tags`, `agents` and `all` are looked at. This keeps the existing `TargetPicker.test.tsx` case.
- RunScan starts at All hosts and is unaffected.

## Checks run (from `web/`)

`npm run typecheck`, `npm run lint` and `npm run format:check` pass. No vitest run.

## Plant for the tester

Make `fromTarget` return `ALL_HOSTS` again for an unrecognised target. The "edit of an unknown-target schedule sends no `target`" row must go red, because the PATCH would then carry `target: {all: true}`.

## r1 (reviewer nit, `work/reviews/TASK-258.md`)

- A full stop now follows the `<strong>Unknown target</strong>` element, so the note reads "Unknown target. It is kept unless you choose one of these forms.". This is a punctuation-only change in `web/src/components/TargetPicker.tsx`, with no change in behaviour.
- The `<strong>` text is still exactly "Unknown target", so no test row needs updating. These assertions match it: `TargetPicker.test.tsx` L362–L371 (`getByText("Unknown target")`, tag `STRONG`) and `Schedules.test.tsx` L501 and L512 (`toContain` / `getByText`). No test asserts the full sentence.
- typecheck, lint and format:check pass. Re-run: `TargetPicker.test.tsx` and `Schedules.test.tsx`.
