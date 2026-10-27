# TASK-133 revision 2 REVIEW: setup steps for the TLS certificate, OpenBao and the audit sink

Verdict: APPROVED (final; no conditions left)

Reviewer: reviewer-m6, 2026-10-27. Low risk: docs, plus one tester-owned script. Not a two-approval task.

**Follow-ups after round 1** (tester-m6e, `tests/m6/report.md` "TASK-133 r2b and r2c re-checks", rows CHK-M6-133r2-30..34 with the -r1 re-runs):
- **r2b, the two post-walk edits: PASS.**
  - CHK-M6-133r2-07s-r2b: the lab CA has `keyUsage: critical, Certificate Sign, CRL Sign`, and the chain passes `-x509_strict` and a Python handshake with `VERIFY_X509_STRICT`.
  - CHK-M6-133r2-18-r2b: operations §3 step 1 prints the accessor on a valid token. On a revoked token it prints "no accessor: …", rc 0, with no traceback.
- **r2c, the fix for my nit 1 (the on-host `bao` path in install §5): PASS after r2c-1.**
  - The first version used plain `bao login`, which prints the admin token in its success table (row 33 FAIL).
  - It was corrected to `bao login -no-print` (install §5 L325 sentence, L328).
  - **My condition is met by CHK-M6-133r2-34 PASS.** It ran the L327–L333 block exactly as written under a pty with a fresh non-root admin token, against a fresh OpenBao 2.4.1 TLS server, and showed:
    - block rc 0, with 0 occurrences of the admin token in the terminal output;
    - `~/.vault-token` gone afterwards;
    - the admin token revoked (lookup-self 403, invalid to root);
    - the manager token still renews (200);
    - `vault.token` `root:root 600`, with the §5 token check passing (`Yml0c2Nhbg==`, `604800 True ['bitscan-manager']`, 5 × 403).
  - Also PASS: 31-r1 and 33-r1 (each 1/1), and the static checks 30-r1 (57 blocks, 0 findings; 19 links; `bash -n` 50/50).

Scope (`git diff HEAD --stat`, re-checked after r2c-1: the same 4 files):
- `deploy/runbooks/manager-install.md`: §1 NTP, §1.1–§1.3, §5 token, check and renewal, §10 sink check;
- `deploy/runbooks/manager-operations.md`: §3, §5;
- `README.md` L194 (impl-manager-m6);
- the tester-owned `deploy/tests/check_md_links.py`.

Sources:
- the user request and lead rulings (decisions 2026-10-27, "TASK-133 revision 2", "TASK-133 r2 IMPL done");
- TS §5.3 L1051, §8.1 L1256 and L1259, §8.6 L1310–L1315, §8.7 L1366–L1368;
- `.claude/rules/security-invariants.md` and `.claude/rules/deploy/packaging-and-units.md`.

TEST: PASS (tester-m6e, `work/reports/TASK-133-r2-test.md`; `tests/m6/report.md` CHK-M6-133r2-01..26, then 30..34).
- 29 rows in the first walk: 25 PASS, 1 FAIL → fixed (05, in the test script), 1 recorded, 2 NOT RUN (AppArmor enforcement in WSL; a real manager → sink sign-in).
- The walk ran against OpenBao 2.4.1 in TLS server mode and systemd 255 hosts.
- All 14 commands the implementer was unsure of were resolved on real software.

## Checks

1. **No secret on argv, in an environment variable or on screen.**
   - Every token use goes through stdin: `sed … vault.token | curl -H @-` in the check, the renewal script and ops §3 step 1.
   - Token creation writes through a pipe: `bao token create … -field=token | sudo tee <file>`. sudo logs only the path, since the token is on stdin.
   - The renewal unit gets the token only as `LoadCredential=vault_token:…`.
   - The on-host admin sign-in is `bao login -no-print` at a hidden prompt, never `BAO_TOKEN`, followed by `revoke -self` and the removal of `~/.vault-token`. Row 34 shows 0 occurrences of the admin token.
   - The only `--data` value on argv is the ciphertext of the fixed test string `Yml0c2Nhbg==`, not a secret.
   - Key files are created under `umask 077`, or as empty 0600/0640 files before the copy.

   The tester's argv/env grep over the new blocks found 0, with 2/2 controls. `check_runbook_text.py` reports 0 findings (row 30-r1).
2. **Least privilege.**
   - The policy is `transit/encrypt/bitscan-totp`, `transit/decrypt/bitscan-totp` and `auth/token/renew-self` (each `update`).
   - The token role sets `allowed_policies=bitscan-manager`, `orphan=true`, `token_no_default_policy=true` and `token_period=168h`.
   - `renew-self` lets the token extend only itself. The tester showed it is needed (row 14: 403 without it when there's no `default` policy), and that the five other paths are refused (row 13). The alternative, `renew-accessor`, would be broader.
   - This matches the lead's ruling. TS §8.6 L1312 names only "the manager's vault token", so this invents no setting.
3. **Operator-installed renewal units.**
   - `/usr/local/sbin/bitscan-openbao-renew`, `/etc/systemd/system/bitscan-openbao-renew.{service,timer}` are created by the operator from the runbook. Nothing claims they are in a package or the release.
   - The four released manager units, and every other unit, are unchanged: `deploy/systemd` shows no diff against `HEAD`.
   - The unit is reasonably confined: `DynamicUser=yes`, which implies a read-only system, a private `/tmp` and no new privileges; `curl --proto =https`; and only the token credential plus the root-only, non-secret `manager.env`.
   - Operations §5 removes exactly the three paths install §5 creates (row 26).
4. **No invented manager setting.**
   - `BITSCAN_AUDIT_SINK` is documented exactly as `services/audit/sink_transport.py` L190–L219 parses it: `https://…`, or `syslog+tls://host[:port]` with no path or query and default port 6514 (L24). Credentials in the URL are refused.
   - The runbook's "sends no credentials" and "no client certificate" are true.
   - The outage text matches TS §8.1 L1256 ("an alert fires at once") and the 15-minute refusal of sensitive actions (TS §5.3).
   - `BITSCAN_VAULT_ADDR` and `BITSCAN_TOTP_KEY_REF` are the TS §8.6 names.
5. **The pin method matches the agent.** The §1.1 pipeline (the SHA-256 of the leaf's DER SubjectPublicKeyInfo) is the agent runbook's command. The tester's temporary Go test with the real `NewTLSConfig` accepted its output, and a flipped digit gave `ErrPinMismatch` (row 08). It still prints 64 hex characters with the keyUsage CA (07s-r2b).
6. **The README and the runbooks agree.**
   - README L194 now says what the code does: the token is read once at start-up (`config/startup.py` L167) and never renewed. It points to install §1.2 and §5 and operations §3.
   - The old "only those two paths" claim, which contradicted the new policy, is gone.
   - Links and section citations: `check_md_links.py` OK, 19 links.
   - No other README statement about OpenBao or the sink conflicts.
7. **Spec silence handled as ruled.** The TS doesn't say how the vault token stays valid. The lead took the recommended docs-only action and recorded a product-side renewal as an owner note for a later milestone. That isn't a new spec deviation: no product file, unit or setting changes.
8. **Test file `check_md_links.py` (tester).** No files now gives rc 2, and a missing file or 0 links in total gives rc 1. The four plants are red. This fixes a vacuous pass. The script isn't wired into CI; that's logged for impl-deploy as a later item.
9. **Scope.**
   - 4 files, each changed by its owner, and all named in the lead's ruling.
   - The added lines (about 290, mostly runbook prose and commands) exceed the 200-line guideline. The user asked for these setup steps, and the lead kept the task as one revision. They are docs, walk-tested, so I don't hold the task on size.

## Findings

None blocking, none should-fix.

1. ~~nit~~ **resolved (r2c-1, CHK-M6-133r2-34)**, `deploy/runbooks/manager-install.md` §5, the on-host `bao` path:
   - The workstation path is preferred.
   - The on-host path uses `bao login -no-print`, `revoke -self` and `rm -f ~/.vault-token`.
   - The intermediate version with plain `bao login` (row 33 FAIL) never reached a commit.
2. nit (carried, not this task): wire `check_md_links.py`, `check_runbook_text.py` and `check_runbook_bootstrap.py` into CI over the README and runbooks (impl-deploy, later wave, as logged by the lead).
3. Owner note (for the PR, as the lead recorded): the manager never renews or re-reads its OpenBao token, and the spec is silent on this. A product-side renewal, or a re-read on SIGHUP, is a candidate for a later milestone, and would make the operator timer unnecessary.

## Builder checklist

Added item 17 to `work/reviews/builder-checklist.md`: for a CLI sign-in with a secret, check that the CLI doesn't print the secret back (`bao login -no-print`); a hidden prompt alone isn't enough.
