# TASK-080 REVIEW: README user guide for M3

Reviewer: reviewer. Date: 2026-10-23. REQ-090. Spec: TS §3.2 L181 (enrolment tokens), §6.1 (agent routes), §8.6 L1317–L1327 (runtime settings); #37 (the first `bse_` token through the API with a TOTP session, no CLI); decisions 2026-10-20 (docs ownership; no `bse_` CLI). Ruling (`work/decisions.md`, 2026-10-23, REQ-090 (1)): the tester runs the live walk-through of every README request against a real `serve` in WSL as a TASK-080 TEST addition and records each actual answer; the reviewer checks the README against the code, the tested behaviour and that transcript. Inputs:
- `work/reports/TASK-080-impl.md`, including revision 1 (the four pre-review nits plus the TASK-083 id rule);
- `work/reports/TASK-080-test.md` (README scan, CHK-M3-295);
- tester-f's live walk-through `tests/m3/readme-walk-080.md` (CHK-M3-296): 158 rows, 107 requests, against a real `bitscan-manager serve` with PostgreSQL 16 in WSL, as root and as `bstester`. Every row matches the README, with 0 deviations. The test is `manager/tests/test_readme_walk_linux.py`.

File reviewed: `README.md` (the M3 additions plus the TASK-078 r1 audit-log lines).

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **REQ-090 (1), every documented request behaves as written.** I read the walk-through transcript row by row. All 158 rows say "yes". They cover:
  - health, `create-admin`, the restricted session and TOTP enrolment;
  - the README's two `curl` steps (sign-in with TOTP, then `POST /enrollment-tokens` with the README's body);
  - an admin `bsk_` refused with 403 `totp_session_required`;
  - defaults and range refusals;
  - list, read and revoke of tokens (no token or hash in lists);
  - enrolment held and auto-approved;
  - approve and reject, including a re-enrolment and twin requests;
  - heartbeat, pull, inventory with every `job_id` class, the 10-minute window, 400, 413 and 422;
  - rotation: early 403 plus alert, inside the window, the lost-response retry, the 24 h 429, `token_expired`;
  - the machine-id mismatch, including the held re-enrolment case;
  - tags, revoke, settings at bounds and refusals;
  - the audit-log re-verification: 42 items, 0 mismatched, links intact;
  - metrics with a viewer API token;
  - the scheduler and sweep behaviour.
- **Against the code (my pre-review, then revision 1).**
  - The `row_hash` recipe matches `compute_row_hash`.
  - The `curl` bodies match `LoginRequest` and `CreateToken`.
  - The settings table matches `INT_RANGES` and TS §8.6.
  - The agent route table is exactly TS §6.1.
  - The rotation, limits, body-cap, `job_id`, 400/413/422 and scheduler texts match TASK-059/063/057/060/065/068/071/074/075/082/083.
  - Revision 1 adds:
    - the inventory 400 cases;
    - "a held re-enrolment's new token is not revoked on a mismatch";
    - the failed and completed versus other `job_id` classes;
    - `--cacert`;
    - the hyphenated-id rule.
- **REQ-090 (2).** The README holds no task, REQ, CHK, PD or open-question ids (`grep` is clean), and only placeholders such as `<password>`, `<code>`, `<session token>` and `manager.example` stand in for secrets.
- **Security invariants.** The README offers no way to disable inventory, run a command or bypass the TOTP session. It states that API tokens are refused for enrolment tokens, approvals, revoke and `PATCH /settings`.

## Findings

None block approval. tester-f's three notes are completeness gaps, not deviations:

1. **nit**, `README.md:301` (Token rotation). The overlap sentence omits that **rotating** with the old token after the new one was first used is reuse even inside the 10 minutes (#62): both tokens are revoked and `token_reuse` is raised. Suggested addition: "Calling rotate with the old token once the new one has been used counts as reuse, even within the 10 minutes."
2. **nit**, `README.md:252` (Approve). After an approved re-enrolment, the old token gets 401 `unauthorized`, because its hash is no longer known, rather than `token_revoked`. "That ends the old token" is accurate. Optionally name the 401.
3. **nit**, `README.md` (Enrolment requests or Approving enrolments). An operator calling approve or reject gets 403 `totp_session_required`, because the TOTP-session dependency refuses before the role is reported. That is not `forbidden`. It is optional to state.

These can go into the next touch of `README.md` (M4 or M5). They need not reopen this task.

## Revision 2 (2026-10-23)

Verdict for revision 2: APPROVED.

- **Nit 1 is resolved.** `README.md:301` now adds: "A rotation with the old token after the new one has been used, even within those 10 minutes, counts as reuse: both tokens are revoked and an alert is raised." This matches `services/enrolment/rotation.py` (the previous-token path with `prev_token_expires_at` set) and #62, as tested in TASK-075 (CHK-M3-344).
- **Nothing else changed.** The text scan for task, REQ, CHK, PD and question ids still prints nothing. The lead ruled that no re-test is needed beyond the gate's text scan.
- **Nits 2 and 3 remain open**: the 401 `unauthorized` for the old token after an approved re-enrolment, and the operator's 403 `totp_session_required` on approve. Neither blocks approval; `main` decides when they go in.
