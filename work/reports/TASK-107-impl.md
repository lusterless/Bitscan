# TASK-107 IMPL: agent install runbook

This task covers REQ-110. Sources: TS §3.1 (install, uninstall, distribution), §3.2 (steps 1, 5, 6, 8, 9 and Transport), §3.3 (NTP, status, decommission), §8.7 (the manager's `tls.crt` path, upgrade order); #76, #79, #81, #82; the `install.env` ruling (A)–(E) and TASK-100 r1; decisions 2026-10-24 (Ubuntu 22.04 and 24.04, amd64 only). Also the two TASK-096 review notes: (1) the CA file and pin are asked only at low priority, and `dpkg-reconfigure` asks only the token, so the runbook tells an interactive operator with a private CA or a pin to preseed or use `install.env`, and says how to change them later; (2) the preseed declares `bitscan/enrol_token` as `password`.

One review round (docs). No tests were run (that is the tester's job).

## Files

`deploy/runbooks/agent-install.md` is new: 178 lines, LF only. No other file was touched.

## Contents, by REQ-110 item

| REQ-110 item | Section |
| --- | --- |
| SHA-256 check (`sha256sum -c`, from the release page on another origin) | 2 |
| Preseed and install; delete the preseed file | 3a (the TS §3.1 command order: `debconf-set-selections`, `apt install ./…deb`, `rm`) |
| NTP prerequisite | 1 |
| Cloned images (regenerate `/etc/machine-id`) | 1 |
| Optional pinning (`manager_spki_sha256`) or `ca_file` set to the private CA only | 1 (pin computed on the manager from `/etc/bitscan/secrets/tls.crt`; #79: leaf SPKI, 64 hex, in addition to verification; keep the key across renewals), 3 (questions and keys), 7 (changing them later by editing `agent.yaml` as root, which TS §3.1 allows) |
| Re-enrolment (#81) | 7 (`dpkg-reconfigure`, or `install.env` with only `ENROL_TOKEN` plus `dpkg-reconfigure`; held for approval; the agent's own log lines quoted) |
| Uninstall and purge | 8 (#82: agent files only, `/etc/bitscan` removed only when empty; offline after 30 min, decommission after `decommission_after_days`, revoke to cut off at once) |
| 0.x is a pre-release | intro (runner and helper idle, compliance scans report `runner_unavailable`) |

Also: `install.env` described exactly as ruled, (A)–(E) plus r1 (3c); the interactive route and its low-priority limit (3b); one single-use token per host (#76) and the multi-use token settings (1); a table of every fixed `postinst` failure line with its fix and `dpkg --configure` to recover (5); the upgrade (6, manager first).

Quoted texts were checked against the code in the tree: the `postinst` messages (`deploy/debian/postinst`), and the agent lines `enrolment did not complete; the agent stays idle until it is restarted`, `enrolment refused; the host needs a new enrolment token` (`cmd/bitscan-agent/main.go`, `internal/agent/enrol/enrol.go`) and "the host must be re-enrolled" (`internal/agent/loops/run.go`).

## No secrets, no process notes

- Placeholders only: `bse_REPLACE_WITH_THE_ENROLMENT_TOKEN` (not the 43-character token form, so `postinst` would refuse it), `mgr.example`, `<64 hexadecimal characters>`.
- The token is never on a command line: the preseed file and `install.env` are created 0600 with `install` and edited with `sudoedit`.
- `grep -nEi 'debian|arm64|TASK-|REQ-|#[0-9]{2}\b|decisions|tester'` on the file prints nothing.

## Revision 1 (lead ruling "D2 string-typed token preseed", 2026-10-25)

Only `deploy/runbooks/agent-install.md` changed (now 192 lines, LF only). Section 3a gets a warning block after the preseed commands:

- always preseed `bitscan/enrol_token` as `password`, never `string`;
- why: a `string` answer goes to `/var/cache/debconf/config.dat` (readable by every user); the install clears it there, but a copy stays in `/var/cache/debconf/config.dat-old` until debconf's next save;
- how to clear it after the install: `sudo rm -f /var/cache/debconf/config.dat-old`, or one more debconf save by loading the manager URL line again with `debconf-set-selections` (with the operator's own URL);
- treat the token as exposed to local users until then.

No package change (postinst must not edit debconf's private files, per the ruling). The word check from the first round (`grep -nEi 'debian|arm64|TASK-|REQ-|#[0-9]{2}\b|decisions|tester'`) still prints nothing.

For the tester: the D2 check is a string preseed, install, then confirm the token is in `config.dat-old` and gone after each of the two clearing routes.

## For the tester (TP-M4-22)

- Walk-through on a clean Ubuntu 24.04 against the real manager: sections 1 (NTP, pin command on the manager host), 2, 3a (and 3b, 3c on fresh hosts), 4, 5 (plant one failure), 6, 7 (both routes), 8.
- Section 1's pin command assumes the manager's `tls.crt` starts with the leaf certificate.
- Section 4: `enroll.token` disappears only after the manager accepts the enrolment, and `token` and `agent_id` appear then; the approval step needs an admin TOTP session in the manager.

## Revision 2 (reviewer's TASK-100 nit 5; lead 2026-10-25)

Only `deploy/runbooks/agent-install.md` changed (193 lines, LF only). A `ca_file` under `/home`, `/root`, `/run/user` or `/tmp` passes `postinst`'s readability check but is hidden from the agent by `ProtectHome=yes` and `PrivateTmp=yes` in `bitscan-agent.service`, so the agent keeps restarting.

- Section 1, "Private manager CA": copy the CA under `/etc`, readable by every user; do not keep it under `/home`, `/root`, `/run/user` or `/tmp` (the install accepts it, the service cannot see it). The example is now `sudo install -d -m 0755 /etc/bitscan` then `sudo install -m 0644 manager-ca.pem /etc/bitscan/ca.pem`.
- The preseed (3a) and `install.env` (3c) examples now use `/etc/bitscan/ca.pem`.
- Section 5, the CA failure row: "Absolute path under `/etc` …".
- Section 8, purge: a CA at `/etc/bitscan/ca.pem` is kept, so `/etc/bitscan` stays too (postrm removes it only when empty).

The explicit `install -d -m 0755` makes `/etc/bitscan` root:root 0755 whatever the operator's umask (sudo combines it with 022, so `install -D` alone could give 0700, and bitscan could not read the CA). That passes `postinst`'s `/etc/bitscan` check; the package later creates `agent.yaml` there. The word check still prints nothing.

For the tester: in the walk-through, a CA at `/etc/bitscan/ca.pem` installs and the agent starts; purge keeps `/etc/bitscan/ca.pem` and `/etc/bitscan`.

## Revision 3 (TEST FAIL, tester-m4b 2026-10-25: cloned-host step)

Only `deploy/runbooks/agent-install.md` changed (196 lines, LF only; the word check still prints nothing; `bash -n` passes on the new command block).

1. **should-fix, section 1 "Cloned hosts".** `rm -f /etc/machine-id` plus `systemd-machine-id-setup` kept the old id on images where `/var/lib/dbus/machine-id` is a separate regular file: `systemd-machine-id-setup` copies the D-Bus id first. The step now:
   - prints the old id (`cat /etc/machine-id`);
   - removes both copies: `sudo rm -f /etc/machine-id /var/lib/dbus/machine-id`;
   - runs `sudo systemd-machine-id-setup`;
   - restores the stock link if the D-Bus folder exists: `if [ -d /var/lib/dbus ]; then sudo ln -sf /etc/machine-id /var/lib/dbus/machine-id; fi`;
   - checks `cat /etc/machine-id` now differs from the old id.
   The text says why both copies go.
2. **nit, section 4.** The agent swaps `enroll.token` for `agent_id` and `token` at its first enrolment call, while the request may still wait for approval (TS §3.2 step 5, a held re-enrolment returns the `agent_id`). The sentence now says these files do not show that the host is approved; the host is enrolled once an admin approves it (or at once with `auto_approve` and a new machine id).

For the tester: re-run the cloned-host rows on both image layouts (stock link and a separate `/var/lib/dbus/machine-id` file); in both, the id must change and `/var/lib/dbus/machine-id` ends as a link to `/etc/machine-id`.
