# TASK-124 REVIEW: package search screen

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (package search UI). Not a two-approval task.

Scope reviewed (`work/reports/TASK-124-impl.md`):
- `web/src/screens/PackageSearch.tsx` (new);
- `web/src/api/schema.d.ts`, re-generated with no diff.

Sources:
- REQ-129, REQ-132, REQ-136;
- TS §7.1 and §7.3 L1223;
- #86 (a) and (b);
- the lead's ruling of 2026-10-25 (the drill-down carries the active filters).

TEST: PASS (tester-m5, 2026-10-25).
- 20/20 tests pass, and the plants are red.
- The drill-down was tested against the lead's ruling, plus the `agent_id` carry.
- The whole web suite passes 320/320.

## Checks
1. **Spec (REQ-129).**
   - (1) The form sends only the parameters that are filled in, typed through the generated operation query.
   - `version_op` is disabled and never sent without a version.
   - `q` together with `name` is refused locally, and the server checks again.
   - `status=any` is sent only when chosen.
   - (2) `group_by=package` results are nested by name, in response order (#86 (b)).
   - (3) A version click asks for `name`, `version` and `arch` with no `group_by`. A host link opens `#/hosts/<agent_id>`.
   - (5) Paging uses the returned cursors, and a new query starts at page 1.
   - A 400 shows its `detail` as text.
2. **Lead ruling.**
   - The drill-down carries `status`, `os`, `tag` and `host`, so the host list matches `host_count`.
   - It also carries `agent_id`. That is not in the ruling's list, but the ruling's stated aim needs it, and impl-web told the lead. I accept it.
   - `q` and `version_op` are correctly not carried, because the exact name and version replace them.
3. **REQ-132 and REQ-129 (4).** Every value is a text node.
   - There is no raw-HTML insertion, `style=`, raw `fetch` or storage.
   - The three item shapes are told apart with type guards, not casts.
4. **REQ-136 and G16.** The package paths are in the generated client, and re-generating it gives no diff.
5. **Re-run by the reviewer (Windows).** `npm run lint`, `npm run typecheck` and `npm run format:check` pass.
6. **Scope.** 1 hand-written file of about 315 lines (380 with TASK-125's additions). The lead accepted it as one task (decisions 2026-10-25).

## Findings
None.
