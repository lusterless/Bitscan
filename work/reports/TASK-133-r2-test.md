# TASK-133 revision 2: test verdict

**Current verdict (after r2c-1): PASS.**
- r2b passes.
- r2c failed once: `bao login` printed the admin token in clear (CHK-M6-133r2-33).
- impl-deploy's r2c-1 changed L328 to `bao login -no-print` and the sentence at L325. With that, the re-runs 31-r1 and 33-r1 and the reviewer's confirming row 34 pass, each 1/1:
  - 0 occurrences of the admin token on the terminal;
  - `~/.vault-token` gone afterwards, and the admin token revoked;
  - the manager token unaffected, `vault.token` `root:root 600`, and the §5 check passing.
- The static checks pass again (30-r1).
- Re-check rows: `tests/m6/report.md`, "TASK-133 r2b and r2c re-checks", CHK-M6-133r2-30 to -34.

(The r2c table below was written before r2c-1; row 33's FAIL is now closed by 33-r1 and 34.)

| Re-check | Result | Evidence |
| --- | --- | --- |
| Static, after r2b and r2c (30) | PASS | `check_runbook_text` 57 blocks, 0 findings; links 19 OK; `bash -n` 50/50 |
| 07s: lab CA with keyUsage (r2b) | PASS | CA `Certificate Sign, CRL Sign` critical; `-x509_strict` OK (manager, sink and openbao leaves, with host name); Python strict handshake TLSv1.3 OK; wrong-host control red |
| 18 step 1: empty-input guard (r2b) | PASS | Valid token: the accessor alone, rc 0. Revoked: stdout `no accessor: the old token is no longer valid`, stderr `curl: (22) … 403`, rc 0, 0 tracebacks |
| 31: `bao login` prompts hidden, writes `~/.vault-token` (r2c) | PASS | `Token (will be hidden):`, no echo; `~/.vault-token` 600 = the admin token |
| 32: L327 block leaves no usable admin token (r2c) | PASS | `~/.vault-token` gone; admin token 403 / invalid; manager token still 200; L337 check passes in full |
| 33: admin token shown on screen (r2c) | **FAIL** | `bao login` prints `token <ADMIN-TOKEN>` in its table (1 occurrence); `bao login -no-print` gives 0 occurrences, the same prompt, and still writes `~/.vault-token` |

## Original r2 verdict (before r2b and r2c)

**Verdict: PASS.** Every runbook command walked works as written. One correction is recommended (non-blocking) and there is one cosmetic nit. Both are now done in r2b and re-checked above. Tester: tester-m6e, 2026-10-27. Worktree `Bitscan-m6`, branch `m6-release`, nothing committed.

Scope: `deploy/runbooks/manager-install.md` §1, §1.1–§1.3, §5 and §10; `deploy/runbooks/manager-operations.md` §3 and §5; `README.md` L194 (impl-manager-m6). Rows: [`tests/m6/report.md`, section "TASK-133 r2"](../../tests/m6/report.md), CHK-M6-133r2-01 to -26.

## Totals

- **29 rows: 25 PASS, 1 FAIL → fixed, 1 recorded, 2 NOT RUN.**
  - 18 and 24 each include one NOT RUN sub-step.
  - The FAIL (05) is in a test script, not in the runbooks.
- `bash -n`: 56/57 blocks passed, 0 errors, 0 skipped. Runbooks 50/50; the one failure is README L159's documented `<venv>` placeholder, which the repo gate substitutes on purpose.
- `go test -run TestM6eRunbookPin` (temporary file, deleted): 1/1 passed.

## Environment

- WSL Ubuntu-24.04 with Docker. Light-step memory floor of 2,000 MB (main); free memory was 2,011–3,097 MB at each container start.
- `openbao/openbao:2.4.1@sha256:597f62847dd382382056a1d6704d50465908c2040038c4611832a23269a67112` in **server mode with TLS** (lab certificate from §1.1's `issue`), not dev mode.
- Manager and sink hosts are `m6b-mgrhost` (Ubuntu 24.04, systemd 255 as PID 1).
- Every block was run as `admin` from the runbook text. The only stand-ins were `sudoedit` → `sudo tee` with the same text, and `y` answered to apt's prompt.
- Containers `m6e-*` are removed.

## Commands run

- **Static (W):**
  - `python -I deploy/tests/check_runbook_text.py` on the 2 runbooks and README: `OK 3 files, 57 sh blocks, 0 findings`.
  - `check_md_links.py README.md deploy/runbooks/*.md`: `OK 19 relative links`.
  - `check_runbook_bootstrap.py`: OK.
  - Own `bash -n` per block: as in Totals.
  - Argv/env secret grep over the 19 new blocks: 0 secrets, controls 2/2.
- **Walk (L):**
  - §1.1 lab CA, the `issue` helper, the checks and the pin.
  - §1.2 CA trust and the admin block (by a non-root admin).
  - §5 first block, certificate copy, `bao token create … | sudo tee`, the token check, and the renewal script, units and timer (`systemd-analyze verify`, start, enable).
  - Operations §3, steps 1–4.
  - §1.3 rsyslog receiver: install, conf, `-N1`, `ss`, `s_client`.
  - Frames through the manager's own `SyslogTlsTransport`, then the §10 grep.
  - §1 NTP.

## The implementer's 14 unsure commands

| # | Result | Row |
| --- | --- | --- |
| 1 role parameters; a non-root admin creates orphan tokens | Confirmed. The read-back matches, and a non-root admin with only role paths runs the whole block. | 10, 11 |
| 2 `token create -role … -field=token` | Confirmed. Policies are exactly `["bitscan-manager"]`, the token is orphan and periodic, and only the token is printed (no trailing newline). | 11, 12 |
| 3 renew-self needs the policy line without `default` | Confirmed: 403 without the line, 200 with `default`. | 14 |
| 4 `604800 True ['bitscan-manager']` | Confirmed. Periodic beyond the max TTL (20 s twin past a 60 s cap). | 12, 13 |
| 5 five refused paths → 403 | Confirmed, all five. | 13 |
| 6 `curl -H @-` with and without a trailing newline | Confirmed, both (curl 8.5.0). | 13 |
| 7 "only root tokens an unlimited lifetime" | Confirmed. Non-root tokens get 768 h even with `-ttl=0`; root-policy tokens get 0. | 12 |
| 8 units verify; `EnvironmentFile` + `DynamicUser`; credentials and env seen | Confirmed. Verify prints nothing, TTL reset to 604799, and the token appears 0 times in the journal. The failure path is as documented. | 16, 17 |
| 9 `global()` / `maxMessageSize` from `rsyslog.d`, `MaxFrameSize`, ruleset order | Confirmed. `-N1` is clean; 20 kB frames stay whole, and the control without the line splits them at 8 k. | 19, 22 |
| 10 AppArmor allows `/etc/rsyslog.d/tls/*` | Profile text allows `/etc/rsyslog.d/** r`. **Enforcement NOT RUN**: WSL has AppArmor off. | 23 |
| 11 octet-counted frames land; grep matches despite the BOM | Confirmed. §10's grep printed 4 (two pairs). | 21 |
| 12 `s_client -brief` prints `Verification: OK` | Confirmed; wrong-name control red. | 20 |
| 13 `-noenc` gives a `CA:TRUE` CA; the leaf is accepted by Go, Python and curl | Confirmed (Go pin handshake, Python 3.12 sink transport, curl to OpenBao). **Recommended correction** below. | 07, 07s, 08, 21 |
| 14 `set-ntp` error text | `Failed to set ntp: NTP not supported` contains the quoted text. The timesyncd fallback can't run in a container (`ConditionVirtualization=!container`). | 24 |

Also confirmed: the pin command's output equals what the agent computes (the real `NewTLSConfig` accepts it and a flipped digit gives `ErrPinMismatch`, row 08). The orphan claim holds: revoking the creating admin token leaves the manager token valid (row 15; found through my own harness error, recorded). Operations §3: after step 4 the old token gets 403 and the new one 200 (row 18). Operations §5's remove paths equal those created in install §5, and README L194 is consistent (row 26).

## Recommended correction (impl-deploy, non-blocking)

Row 07s, `manager-install.md` §1.1, the lab CA line. Ubuntu's `v3_ca` gives the CA no keyUsage, so `openssl verify -x509_strict` fails with `error 92 … CA cert does not include key usage extension`. Python ≥ 3.13 turns strict mode on by default, and RFC 5280 requires keyUsage on CA certificates. The v1 stack (Python 3.12, Go, curl, rsyslog) accepts it, so this is not a FAIL. The fix, which I verified OK under `-x509_strict`:

```sh
(umask 077 && openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -noenc \
    -keyout manager-ca.key -out manager-ca.pem -days 1825 -subj "/CN=Bitscan lab CA" \
    -addext "keyUsage=critical,keyCertSign,cRLSign")
```

## Nit

Operations §3 step 1 on an expired or revoked token prints the documented `403` followed by a Python traceback (row 18). This is cosmetic, and the text already tells the reader what a 403 means.

## Test-file finding (main's extra check, rows 05 / 05-fix)

- `deploy/tests/check_md_links.py` passed with no arguments (`OK 0 relative links checked`, rc 0).
- No workflow, `e2e/m6` script or `deploy/tests` script calls it, so no current CI gate was vacuous. None of the three runbook text checks is wired into CI; main is logging that for impl-deploy.
- I fixed the script:
  - no files → rc 2;
  - a missing path, or 0 links in total → rc 1.
- Plants (no args, unmatched glob, empty `nullglob` glob, a 0-link file) are all red. The broken-anchor control is red, and the real run is OK with 19 links.

## NOT RUN

- Row 23: AppArmor enforcement (the WSL kernel has AppArmor off).
- Row 25: a real manager with `BITSCAN_AUDIT_SINK=syslog+tls://…` signing in. There is no built wheel, and it needs PostgreSQL; row 21 covers the manager's own transport into the receiver instead.
- Sub-steps:
  - `systemctl restart bitscan-manager` in operations §3 step 3 (no manager installed on the walk host, row 18);
  - the timesyncd fallback (row 24).
