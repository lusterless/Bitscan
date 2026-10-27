# TASK-133 IMPL: manager install runbook

Implementer: impl-deploy. REQ-138, REQ-140 (also REQ-146 to REQ-148 through the installed host). Plan: `work/plans/TASK-133.md` §2–§3, §6. Spec: TS §8.7 L1343–L1348 and the units L1350–L1480, §8.6, §5.2 Bootstrap L1016–L1033, §5.3 L1048–L1049, §8.2 L1264, §3.1 L165 (release-page check). Answers: #6 (install half), #46, #90, #91, #93, and the lead's ruling on the database CA (below).

## Files

| File | Change |
| --- | --- |
| `deploy/runbooks/manager-install.md` | **New** (256 lines). No other file changed. |

The runbook was written against TASK-129's acceptance criteria (`work/tasks.md` L1303), not its report: `bitscan_manager-0.1.0-py3-none-any.whl`, the `bitscan-manager` entry point. The release file names come from `work/plans/TASK-135.md` §3: `bitscan-manager-0.1.0-requirements.txt`, the four unit files, and `SHA256SUMS` copied from the release notes.

## Sections (plan §3 order)

1. Before you start: Ubuntu 24.04 amd64 only (#6); NTP; the name, certificate and key; OpenBao Transit with an encrypt/decrypt-only policy (README "OpenBao"); the audit sink (`https://` preferred, or `syslog+tls://`).
2. Release check: `sha256sum -c --ignore-missing SHA256SUMS`, with the text copied from the release page and never the attached asset (#91).
3. PostgreSQL:
   - Install `postgresql-16 postgresql-16-debversion python3.12 python3.12-venv`, then `SHOW ssl` → `on`.
   - **The Bootstrap block**, then `sudo -u postgres psql -X -v ON_ERROR_STOP=1 < bitscan-bootstrap.sql`.
   - Passwords with `\password <role>` at the psql prompt (#46).
   - Four `pg_hba.conf` lines above every other line: `local` reject, `hostnossl` reject, `hostssl bitscan … 127.0.0.1/32 scram-sha-256`, then `host all` reject, all for the three roles. Then reload, check `pg_hba_file_rules` for errors, and the `sslmode=disable` refusal check for each role.
   - The variant for a database on another host.
4. User (`adduser --system --group --no-create-home --home /nonexistent --shell /usr/sbin/nologin`) and the four `/var/lib/bitscan` folders (plan §2), created before the first start (plan §6).
5. `/etc/bitscan` (0755) and `secrets/` (0700). `manager.env` and all six secret files are created empty at 0600 with `install … /dev/null` before any content, then written with `sudoedit`, or with `cp` onto the existing file for the certificate and key. `manager.env` holds only `BITSCAN_VAULT_ADDR`, `BITSCAN_TOTP_KEY_REF`, `BITSCAN_AUDIT_SINK` and the optional pair. The runbook warns never to set `BITSCAN_*_FILE` there, because an `EnvironmentFile=` value overrides the unit's `Environment=` value.
6. Venv `/opt/bitscan-manager`, then `pip --require-hashes --only-binary :all:` for the lock and `--no-deps --no-index` for the wheel. Then `ln -sfn` to `/usr/bin/bitscan-manager`, `--help`, and a `find -perm /022` check. An offline variant (`pip download` on another 24.04 amd64 host).
7. The units: `install -m 0644` into `/etc/systemd/system/`, `daemon-reload`, then `systemd-analyze verify` on the four files, which must print nothing. No edits and no drop-ins.
8. `systemctl start bitscan-manager-migrate`, the journal (head revision), one `bitscan-manager-maintain.service` run, `enable --now` of the timer, and `list-timers`.
9. `enable --now bitscan-manager`, then `/readyz` → `{"status":"ok"}` (the body is compact, as `api/health.py` returns it), and what a 503's `detail` means.
10. `sudo bitscan-manager users create-admin alice` (password prompted twice), sign-in, TOTP enrolment in the UI (the Confirm step returns a TOTP-verified session, `auth/totp_enrol.py`), then enrolment tokens and the agent runbook.
11. Install check in operator terms: `User`, the four Cap values 0 and `NoNewPrivs` 1, a `find -printf` of owners and modes, `sudo -u bitscan-manager cat migrate.dsn` → `Permission denied`, and `cmp` of each unit file against the release copy.

## Database CA: pending owner (#97)

The spec has no `sslrootcert` and no CA path. The lead ruled on 2026-10-26:
- (a) **Approved:** a database on the manager host uses `host=127.0.0.1 … sslmode=require`. This is the M6-e2e setup, and the runbook's main path.
- (b) **Pending owner (#97):** for a database on another host, `sslmode=verify-full sslrootcert=/etc/bitscan/postgres-ca.pem`, with the CA at `root:root` 0644, outside `secrets/`. The runbook says why libpq's default `~/.postgresql/root.crt` can't work: the user has no home, `ProtectHome=yes`, and migrate and maintain run as `DynamicUser`. `sslrootcert=system` is not used. This adds one path that isn't in the plan §2 layout. If the owner decides otherwise, only the "Database on another host" paragraphs of sections 3 and 5 change.

## Checks run here

- **Bootstrap:** the fenced block was inserted from the bytes of TS lines 1018–1033 (opening fence through closing fence) and compared afterwards: identical, 16 lines, LF only. It is the runbook's only ```` ```sql ```` block.
- All 17 ```` ```sh ```` blocks pass `bash -n`. The first run caught a `<name>` placeholder, now `alice` with a note.
- No secret on a command line: the only `PGPASSWORD` occurrence is the warning. Passwords appear only as `<password>` inside DSN lines typed in `sudoedit`, and the `psql` refusal check carries no password. No task id, REQ, CHK or `#nn` in the runbook.
- Builder checklist: items 1–14 concern manager code, SQL and Go, so none applies. Item 11 holds in spirit: no token or DSN is printed or logged by any step.
- Not run (no Ubuntu host for me): the walk itself, `systemd-analyze verify`, and the PostgreSQL steps.

## Notes for the tester (TP-M6-03)

- The Bootstrap check: extract the ```` ```sql ```` block (fences included) and compare it to TS L1018–L1033.
- Unit verbatim: the runbook installs the release copies of `deploy/systemd/bitscan-manager*`. I didn't change those files.
- `sha256sum --ignore-missing` relies on GNU coreutils ≥ 8.28 ("no file was verified"). Ubuntu 24.04 has 9.4.
- The `pg_hba.conf` `local … reject` line also refuses the three roles over the Unix socket, so every non-TLS path for them is refused, not only TCP.
- The OpenBao and sink steps run against your test doubles (#93). The runbook names only their prerequisites.
- `manager-operations.md` (TASK-134) is referenced by name in the introduction.

## r1 (TEST FAIL from tester-m6b: CHK-M6-044, CHK-M6-050)

Only `deploy/runbooks/manager-install.md` changed (256 → 265 lines).

- **F1 (§3):** `sudo apt update` now comes before `sudo apt install …` in the same block. A fresh host's package lists are empty.
- **F2 (§9):** the single `curl` after `enable --now` is now a retry loop. It tries `curl -sS --cacert manager-ca.pem https://mgr.example:8443/readyz` up to 10 times, a second apart, and stops at the first HTTP answer. `curl` exits 0 on an HTTP answer without `--fail`, so a 503 body that names the failed check is still printed. If it never answers, it prints `readyz: no answer after 10 tries; see sudo journalctl -u bitscan-manager` to stderr, and `curl -sS` has already shown the last `curl: (7)`. One sentence says why the loop is there. I didn't use `curl --retry`: it also retries 503 and can print the body more than once to stdout.
- **N1 (§8):** added `sudo journalctl -u bitscan-manager-maintain -n 5 --no-pager` after the maintenance run. The text now says `created <name>` / `nothing to do` goes to the unit's journal, which that line shows.
- **N2 (§5):** a one-line warning above the first block: run it only on a fresh host, because on an installed host it empties `manager.env` and every secret file.

Checks run here (r1):
- All 17 ```` ```sh ```` blocks pass `bash -n` (dedented where nested). LF only.
- The Bootstrap block still matches TS L1018–L1033 byte for byte (`diff` against `sed -n '1018,1033p'`: identical).
- No secret on any command line. The new lines carry no password, DSN or token.
- Not run: the walk on an Ubuntu host (the tester re-runs CHK-M6-044 and CHK-M6-050).
