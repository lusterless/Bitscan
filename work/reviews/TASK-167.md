# TASK-167 REVIEW: README, the M7 user guide

Verdict: APPROVED (revision 2)

Reviewer: reviewer-m7, 2026-10-28. REQ-184. Low risk (docs): one review round.

Scope reviewed: `README.md` only, per `work/reports/TASK-167-impl.md` including "Revision 1" and "Revision 2".
- A new "Policies" section.
- The intro's route list and server commands updated.
- The Web UI "Pages by role" table and page bullets updated (r1).
- The N1 wording of the 503 bullet (r2).

TEST: PASS on round 2 (`work/reports/TASK-167-test.md`, tester-m7w).
- Round 1 FAILED on F1: no UI path for rebuild, and the pages table still listed only the M5 pages. r1 fixed both.
- Round 2: 66/66 static rows, comparing routes, field lists, enums, statuses and CLI statements with `openapi.json` and the code. 22/22 relative links resolve.
- r2 is a one-line wording change, so the lead ruled no re-test. I checked the line myself (below).
- The live WSL walk (CHK-M7-305, REQ-184 acceptance (1)) has moved to the M7 gate (lead).

Spec read: TS §4.1–§4.3, §4.6, §6.2 L1084, L1100–L1107, §8.7 L1347; SR §1.1, §4.1, §4.2; #100 (d), #102 (b), #107; the TASK-159 carry (hard links); my TASK-162–164 note (the stored-but-not-recorded 503).

## Checks
1. **REQ-184 coverage.**
   - The `.bit` format in brief, linking SR.
   - Loading through the server folder (watcher, start-up, name rules, "don't hard-link files into the bits folder", rename in place, BIT007, byte order).
   - Upload by UI or by an admin `bsk_` with `curl -F`.
   - What an import does, including the audit-sink entry size.
   - Status and the override.
   - Delete: TOTP session, API token refused, sink gate.
   - Rebuild by UI, API and `sudo bitscan-manager bits rebuild`, with its folder rule, output lines and exit codes.
   - Import history.
2. **Accuracy.** Every route, field list, enum, status and role statement matches the code as built, per the tester's walk and my own reading of the diff. Upload is admin by session or API token (TS L1084), delete and rebuild need a TOTP session, and the CLI reads the DSN only from its file.
3. **No secrets or process notes.** The curl uses a `<token>` placeholder. There are no task ids, check ids, open-question references or `work/` paths.
4. **Revision 2 (N1), `README.md:364`.** The 503 bullet now reads: "A 503 after an upload means the policy may already be live. Check the policy list or the import history before you upload it again. After "The import was stored but its record could not be written.", check the policy list (its version and imported time); this case has no import-history row."
   - The quoted text is the route's `_NOT_RECORDED` (`api/user/policy_import.py:46`).
   - That case writes no `bit_import` row (`policy_import.py:164-166`), so pointing only at the policy list is now correct.
   - Nothing else changed.

## Findings
None.

1. Closed (r2): the tester's N1, the 503 advice that pointed at the import history for a case with no history row.
