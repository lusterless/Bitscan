# TASK-258 TEST: an unrecognised stored target is "unknown", never All hosts

Verdict: **PASS**

Tester: tester-m11w, 2026-11-08. Worktree `Bitscan-m11`, uncommitted IMPL (`work/reports/TASK-258-impl.md`; reviewer-m11 nit 1 on TASK-256/249, done because it fails open). L, from `web/`.
Expected values: #122 (b) (exactly the three forms; `all` is the value `true` only); the lead's ruling 2026-11-08 (an edit must not widen a target it does not recognise). This closes my TASK-249 note.

## Tests added (tester-owned)

| File | Added | File total |
| --- | --- | --- |
| `web/src/components/TargetPicker.test.tsx` | 11 | 48/48 |
| `web/src/screens/Schedules.test.tsx` | 3 | 20/20 |

## Runs

| Run | Command (from `web/`) | Result |
| --- | --- | --- |
| TASK-258 and affected files | `npx vitest run src/components/TargetPicker.test.tsx src/screens/Schedules.test.tsx src/screens/RunScan.test.tsx` | **85/85**, 0 failed, 0 skipped |
| Shell (mounts Schedules and Run scan) | `npx vitest run src/app/App.test.tsx` | 44/44 |
| G12–G14 | lint, typecheck, format:check | all exit 0 |

## Coverage

- `fromTarget` gives `unknown` for each of these, and `toTarget` then answers "Choose a target.", never a body: `{}`, `{all: "true"}`, `{all: false}`, `{all: 1}`, `{tags: "db"}`, `{agents: [1, 2]}`, `{agents: "<uuid>"}`, `{foo: 1}`, `{resolved_agents: [...]}`.
- `{all: true}` is still All hosts. A target that also has `resolved_agents` still reads as its requested form; the earlier test is unchanged and green.
- The picker shows "Unknown target" in a `<strong>`, with no radio checked. Choosing All hosts replaces it.
- The schedule list shows "Unknown target".
- Editing a schedule whose stored target is unrecognised:
  - another change sends `{cron}` only, with no `target` key;
  - no change shows "Nothing has changed." and sends nothing;
  - choosing a form sends `{target: {tags: ["db"]}}`.

## Plants (throwaway copy `%TEMP%\m11w-mut-258`; clean copy 68/68 first; removed afterwards)

| Plant | Change | Red |
| --- | --- | --- |
| CHK-M11-439 (main's plant) | `fromTarget` returns `ALL_HOSTS` for an unrecognised target | 12 failed / 68, including "another change sends no target key (never {all: true})" |
| CHK-M11-440 (tester extra) | ScheduleForm ignores `keep`, so an unknown target is passed to `toTarget` | 2 failed / 68: the edit is refused and no PATCH is sent |

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| TASK-258 (CHK-M11-274 extended) | `npx vitest run src/components/TargetPicker.test.tsx` | PASS | 48/48 |
| TASK-258 (CHK-M11-269 extended) | `npx vitest run src/screens/Schedules.test.tsx` | PASS | 20/20 |
| TASK-258 affected | RunScan, App | PASS | 17/17, 44/44 |
| CHK-M11-439 | plant | PASS (red as required) | 12 failed / 68 |
| CHK-M11-440 | plant | PASS (red as required) | 2 failed / 68 |

## r1 re-run (2026-11-08): punctuation only

The r1 change (reviewer nit): a full stop now follows `<strong>Unknown target</strong>`, outside the `<strong>` (`TargetPicker.tsx` L179). The `<strong>` text is still exactly "Unknown target". No behaviour changes and no test was edited.

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| TASK-258 r1 | `npx vitest run src/components/TargetPicker.test.tsx src/screens/Schedules.test.tsx` | PASS | 68/68 (48 + 20), 0 failed, 0 skipped |
| TASK-258 r1 gates | lint, typecheck, format:check | PASS | all exit 0 |

Verdict r1: **PASS**.
