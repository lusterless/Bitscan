# M6 end-to-end plan: environment, Wave 0 network check, sequence, stop rule

Owner of this plan: planner. Owner of every script, image, certificate and report it describes: tester (`e2e/m6/`, `deploy/tests/`, `tests/m6/`). REQs: REQ-146 to REQ-149 (and the host REQ-140 checks re-used). Open questions: #93 (environment), #94 (alerts), #95 (idle cost). VM facts: `work/m6-vms.md` and decisions 2026-10-25/26.

## 1. Environment (#93, recommended answer)

| Piece | Choice | Why |
| --- | --- | --- |
| Manager host | A fresh systemd-enabled `ubuntu:24.04` container in WSL (as the M4 `m4b-sysd-u24` images), privileged, `-p 127.0.0.1:18443:8443` (behind the Windows portproxy `172.31.0.1:8443 → 127.0.0.1:18443`; nothing in WSL may bind 8443, decisions 2026-10-26), installed **only** by following `deploy/runbooks/manager-install.md` (TASK-133). Thrown away after the run. | Disposable like a `clean` checkpoint; leaves the shared WSL distro unchanged; exercises the real install, the verbatim units and `LoadCredential=`. |
| Fallback manager host | The WSL distro itself (root, systemd), same runbook, if `LoadCredential=` or `DynamicUser=` cannot run inside the container. The tester records the reason and asks `main` first (it changes the shared distro). | Same network path (the manager listens on WSL `127.0.0.1:18443`, behind the portproxy, in both cases). |
| PostgreSQL | PostgreSQL 16 and `postgresql-16-debversion` from the Ubuntu 24.04 archive, inside the manager host, `ssl = on` (the archive's default certificate), DSNs with `host=127.0.0.1 … sslmode=require` (a Unix-socket DSN would not use TLS). | What the runbook documents; TLS-only per TS §5.3 L1049. |
| OpenBao | The tester's Transit fake (`manager/tests/fake_vault.py`), run as its own process on `127.0.0.1` inside the manager host with its own test certificate. | OpenBao is outside Bitscan; installing a real one needs a download the user has not approved. The runbook's OpenBao step is walked with the fake and recorded as such. |
| Audit sink | The tester's HTTPS sink (`manager/tests/fake_sink.py`), same way; it records every entry it receives with its arrival time. | REQ-147 (5) reads alert delivery from it. |
| TLS | A test CA made for this run (never committed). Manager leaf with SAN `DNS:bitscan-mgr.test` and `IP:172.31.0.1`. Agents: `ca_file=/etc/bitscan/ca.pem` (the runbook's path; under `/etc`, as TASK-107 r2 requires). u2404 also sets `manager_spki_sha256` (the leaf's SPKI SHA-256); u2204 does not. | Both TS §3.2 Transport options, one per host. |
| Name | `bitscan-mgr.test` → `172.31.0.1` (the Default Switch address, where the portproxy listens; re-checked at W0) in each VM's `/etc/hosts`, written over SSH after the restore; agents use `https://bitscan-mgr.test:8443`. | Mirrored WSL's own address is not reachable from the VMs (decisions 2026-10-26). 172.31.0.1 can change after a Windows reboot; then the portproxy, the firewall rule and the certificate change with it. |
| Agents | `bitscan-u2204`, `bitscan-u2404` restored from `clean`; files copied with Windows `scp` (or `scp.exe` through WSL interop). | WSL has no route to the VMs (decisions 2026-10-26). |
| Approval | Through the API with an admin TOTP-verified session (#93 (f)); the UI approval path is proven by M5 tests and the user's CHK-M5-305 walk. An optional, non-gating user step may approve one host in the browser. | Automatable overnight; no browser automation (PD-28 (f)). |
| Enrolment tokens | One single-use `bse_` per host (`max_uses` 1, no CIDRs, no auto-approve), created with the TOTP session. | The agent runbook's advice (#76); the source address the manager sees for NATed VMs is unknown until Wave 0, so CIDRs are not used. |

## 2. Wave 0: the network check (TP-M6-01)

Runs first. Its result is recorded in `tests/m6/report.md` (CHK-M6-001 to -019) and sent to `main`.

1. `Get-VM bitscan-u*`; restore `clean` on both; start them; find each IP from the static MAC (`Get-NetNeighbor`, `work/m6-vms.md`); record the IPs and the Default Switch address (expected `172.31.0.1`).
2. Tester → VM: SSH from Git Bash and through `ssh.exe` from WSL; `cloud-init status --wait` is `done`; `stat -fc %T /sys/fs/cgroup` is `cgroup2fs`; `timedatectl` shows a synchronised clock. `scp` a 10 MB file to each VM and compare SHA-256.
3. Write the `bitscan-mgr.test` line into each VM's `/etc/hosts`; copy the test CA to `/etc/bitscan-netcheck/ca.pem` (outside `/etc/bitscan`, removed after).
4. **Listener A:** a TLS listener in the WSL distro on `127.0.0.1:18443` (reached from the VMs through the portproxy on `172.31.0.1:8443`) with the test manager certificate that answers one fixed body (for example `openssl s_server -accept 8443 -www`, or a few lines of Python `ssl` + `http.server` in `e2e/m6/netcheck.sh`). From each VM: `curl --cacert … https://bitscan-mgr.test:8443/` returns the body (handshake, name check and one GET).
5. **Listener B:** the same listener inside a container published with `-p 127.0.0.1:18443:8443` (the path the end-to-end run uses). Same check from each VM.
6. Control: from each VM, TCP to `bitscan-mgr.test:8444` (nothing listening): record "refused" or "timeout" (diagnostic only).
7. From each VM, `apt-get update` reaches the Ubuntu archive (needed for the small test packages in §4).
8. Stop the listeners; shut the VMs down (they are restored again at the start of TP-M6-10).

**PASS** when steps 2, 4 or 5, and 7 pass on both VMs. Step 5 is what the planned environment needs; if only step 4 passes, the run uses the fallback manager host of §1 (ask `main` first).

**If the listener cannot be started** (the auto-mode safety check blocked it on 2026-10-26): report NOT RUN with the exact refusal and stop; do not work around it. The lead resumes it in a session where a local listener is allowed.

**FAIL → stop rule.** If no listener is reachable from a VM, TP-M6-10 to TP-M6-13 and gates G50 to G52 stop and wait for the user (decisions 2026-10-26 (4)). Nothing else stops: every TASK and TP-M6-02 to -09 continue. The tester records what failed (the step, the address, the error, a `tcpdump` on the WSL side if it can be run) and lists the options of §6 for the user. **Not allowed overnight:** an SSH reverse tunnel, `netsh interface portproxy`, a firewall or Hyper-V firewall change, a `.wslconfig` change, a new VM.

## 3. Preparation (after W0 PASS and TASK-133 TEST PASS)

1. Build the release candidate on the M6 head with the release build commands (`work/plans/TASK-135.md` §2; if TASK-135 is not yet TEST PASS, with `deploy/debian/build-deb.sh` and the TASK-129 wheel command). Write `SHA256SUMS`. Record every hash; the gate checks that the `.deb` tested here has the SHA-256 the release build produces (reproducible, G39).
2. Install the manager host by the runbook (TP-M6-03 already did this once; this is a fresh one), start the two test doubles, create the first admin, enrol TOTP, sign in with a TOTP-verified session, create a viewer `bsk_` for metrics and an admin `bsk_` for the REQ-148 (4) refusals.
3. Create one single-use `bse_` per host.

## 4. Sequence (TP-M6-10 to TP-M6-13)

Total wall time about 3.5 hours, most of it the u2204 session's stale-inventory window (2 × the minimum 3,600 s interval). One VM runs at a time (decisions 2026-10-26, "W4 runs one VM at a time"): u2404 session 1, then the u2204 session; u2404 session 2 on the same disk is the one overlap, alongside u2204's stale window (two 1 GB VMs for about 40 min, user speed-up, decisions 2026-10-26). Before each `Start-VM` the preflight re-checks Windows free memory against 2000 MB (one 1 GB VM, decisions 2026-10-26); below it, W4 stops and waits for the user, as before. Times are approximate wall-clock minutes from the start of that session's phase A (session 2: from its `Start-VM`).

**Phase A, once per VM, at the start of u2404 session 1 and of the u2204 session (0–25 min): REQ-146 (1)–(8), REQ-148 (5)–(7).** REQ-146 (7)'s two-host checks (one `bash` row per VM, `os=ubuntu:22.04` only u2204, `group_by=host` with both) are read in u2204's phase A, when u2404's inventory is still stored.
1. Restore `clean`, boot, IP lookup, the W0 quick re-check (steps 2, 5), `/etc/hosts`, copy the CA to `/etc/bitscan/ca.pem`, the RC `.deb` and `SHA256SUMS`.
2. `sha256sum -c` (and the one-byte-altered copy fails).
3. Preseed (`password` type for the token; u2204 without pin, u2404 with pin), `apt install ./bitscan-agent_0.1.0-1_amd64.deb`, delete the preseed file. Unit, mode, debconf and canary checks.
4. Held request listed (fields of REQ-146 (4)); approve; `online`; three heartbeat intervals; first inventory; `os_info` and packages against the VM (`uname -r`, `nproc`, `/proc/meminfo`, `ip -j addr`, `dpkg-query -W`).
5. Package search rows, `os` filter, `group_by=host`, a `version_op` query cross-checked with `dpkg --compare-versions` on the VM, CSV equals JSON.
6. `apt-get install -y tree` on u2204 and `jq` on u2404: one unscheduled upload each within 60–120 s; each search returns only its host.
7. Metrics: `bitscan_agents{status="online"}` 1 (this session's VM). In u2204's session also the counted total 2 (`bitscan_agents` summed over every status except `awaiting_approval` and `decommissioned`, #65 (b)). No alert entry yet (REQ-147 (7)); in u2204's phase A the one exception is u2404's `agents_offline` entry (row REQ-147 (4a) below) if it has already come.

**Phase B, in three sessions (one VM running in each, except u2404 session 2, which overlaps the u2204 session).**

*u2404 session 1 (after u2404's phase A; u2204 not started yet).*

| Time | u2404 |
| --- | --- |
| 25–35 | Idle cost (REQ-149, #95): 600 s (§5), nothing touched, start at 25 |
| 35–45 | Runner helper (REQ-147 (2)): enable the capread socket, entry; disable, second entry; `bitscan-capread.service` never started |
| 45 | Pin test (REQ-148 (1)), 45–60: wrong pin, restart; 10 min with no request; restore; heartbeats resume |
| ≈ 60 | `Stop-VM` with the disk kept: no restore, no revoke, no purge. Its last heartbeat is just before this. |

*u2204 session (u2404 is off until its session 2; start u2204 straight after u2404's `Stop-VM`, so that u2204 is approved before u2404 has been 30 min without a heartbeat).*

| Time | u2204 |
| --- | --- |
| 25–40 | CA test (REQ-148 (2)): `ca_file` → a second test CA, restart; 10 min with no request from this host; restore, heartbeats resume within 6 min |
| ≈ 30 (u2404's last heartbeat + 30 min) | Agents offline (REQ-147 (4a)): `offline` 30 min after u2404's last heartbeat; one `agents_offline` entry (1 of 2 counted agents, #65 (b)) |
| 40–55 | Clock skew (REQ-147 (1)): `timedatectl set-ntp false`, clock +6 min; one `clock_skew` entry within 330 s; none more in 15 min; restore NTP |
| 55–65 | Route groups and API-token refusals (REQ-148 (3), (4)) with this host's `bsa_` (read as root) |
| 65 | First `chmod o-x /usr/bin/dpkg-query` (the agent user can no longer run it; root still can), then `PATCH /settings` `inventory_interval_s` 3,600 (one `settings_changed` entry); the agent keeps heartbeating |
| 65 – T + 2 h | (stale window running; nothing on this VM may stop its heartbeats) |
| ≈ T + 2 h (T = u2204's last successful upload, the `tree` upload at about 20 min) | Stale inventory (REQ-147 (4)): one `inventory_stale` entry for u2204 once `last_inventory_at` is over 7,200 s old (expected near minute 140, within one sweep); an `inventory_stale` entry for u2404 after it returns is recorded, not failed (as the "Extra entries" line below); then restore `dpkg-query`'s mode |
| + 10 | Machine-id (REQ-147 (3)): save `/etc/machine-id`, write a new one, restart the agent: 401 `machine_id_mismatch`, `token_revoked_at` set, one entry, the agent idles |
| + 15 | Restore the original machine-id; re-enrol as the agent runbook's re-enrol section says, with a new single-use `bse_`; held `reenrol` request listing the existing agent; approve: same `agent_id`, `online`, one `reenrolment_approved` entry |
| + 25 | Revoke and purge as u2404 does in session 2 (the two rows below) |
| then | Phase C for u2204 (below): its sweep, restore to `clean` |

*u2404 session 2 (the same disk; starts once u2204's stale window is open, after its minute-65 row, and u2404's `agents_offline` entry has been seen; runs alongside u2204, after the ≥ 2000 MB preflight).*

| Time | u2404 |
| --- | --- |
| 0 | `Start-VM`, IP lookup; wait for its first heartbeat (`online`), so that REQ-146 (11)'s 10 minutes count from a heartbeat in this session |
| 0, before the revoke | Metrics (REQ-147 (6)): while u2204 still heartbeats, a viewer `bsk_` on `GET /api/v1/metrics` sees `bitscan_agents{status="online"}` 2 |
| 0–15 | Revoke (REQ-146 (9)): 401 on the next call, one journal line, no further call for 10 min, `NRestarts` 0 |
| 15–30 | Purge (REQ-146 (10)); `stale` 10 min after the last heartbeat (REQ-146 (11)) |
| then | Phase C for u2404 and the manager side (below) |

**For every alert entry** (REQ-147 (5)): `detail.alert = true`, its `alert_kind`, the sink received the same `audit_id` within 5 s of the entry's `at`, and `bitscan_alerts_total{kind}` rose by exactly one.

**Phase C, per VM, at the end of its last session:** the canary sweep of that VM's journal (no `bsa_`/`bse_`; for u2404 covering both sessions), then restore it to `clean`. **Then once, on the manager side, after both VMs' last sessions:** the canary sweep of the manager journal and the sink log, the manager-host write sweep (REQ-140 (5)), metrics after the purges, then remove the manager host container.

**Checks not kept exactly as written** (one-VM order; `work/requirements.md` still has the two-VM wording):
- REQ-147 (6) `online` 2 "while both VMs heartbeat" now runs as written in the overlap (u2404 session 2, before the revoke); phase A step 7 adds `online` 1 per phase A and the counted total 2 in u2204's session.
- REQ-147 (7) "while both hosts are healthy" is never true; it is checked in each phase A, except u2404's expected `agents_offline` entry if that falls inside u2204's phase A.
- REQ-147 (4a) says u2404 is "revoked and purged" when it goes offline; it is now only stopped (`Stop-VM`). The plan row is kept as written.

**Extra entries in u2404 session 2** (an `inventory_stale` or a second `agents_offline` entry for u2404 after it comes back) are recorded, not a failure (lead, 2026-10-26).

**Plants (mutation rows CHK-M6-340 to -345)** run afterwards as targeted mini-runs on one VM: only the phase A steps and the one row each plant targets, with a planted RC `.deb` or a planted copy of the installed wheel in a fresh manager host.

## 5. Idle cost method (#95, recommended answer)

On u2404, from minute 25 to 35 (600 s instead of the earlier 1800 s, a shorter sample by the user's choice, decisions 2026-10-26): no dpkg change, no API call that touches the host, pulls return empty (the next inventory job is 6 h away). Sample `/proc/<pid>/stat` (utime + stime) of `bitscan-agent` at the start and end, and `VmRSS` from `/proc/<pid>/status` every 10 s; also `systemctl show -p MemoryCurrent bitscan-agent`. CPU % of one CPU = Δticks ÷ (CLK_TCK × Δt) × 100; CPU % of the VM = that ÷ 2. Record the largest `VmRSS`. Compare with TS §3.3 L216 (< 0.1 % CPU, < 30 MB RSS). Recorded, with no gate; a miss is a finding for the lead and the user.

## 6. Options for the user if Wave 0 fails (none is taken without the user)

1. A Windows-side forward from the Default Switch address (`172.31.0.1:8443`) to WSL (`netsh interface portproxy`), admin.
2. A third Hyper-V VM on the Default Switch as the manager host (Ubuntu 24.04, installed by the same runbook); VM-to-VM traffic stays on the switch. Needs about 2 GB more RAM and the user's go-ahead.
3. A per-session SSH reverse tunnel from Git Bash (`ssh -R 8443:localhost:8443`), with the agents using `https://localhost:8443` (the certificate then needs `DNS:localhost`). The user ruled "wait for me" for this one overnight.
4. A Windows firewall profile change for the mirrored WSL interface (the 2026-10-26 timeouts on both 8443 and 8444 suggest the packets never reach WSL), admin.

## 7. Risks

- **Listener permission:** the auto-mode safety check refused to start a listener twice on 2026-10-26. If it refuses again, W0 is NOT RUN, and so is everything in W4.
- **systemd features in a container:** `LoadCredential=` and `DynamicUser=` need mount and user namespaces; if the container cannot provide them, use the fallback host (§1) after asking `main`. This is an environment limit, not a product defect, and must be recorded.
- **TLS interception on the WSL host:** `pip` and `apt` inside the manager host need the corporate root that WSL trusts (decisions 2026-10-20); add it to the container's trust store only.
- **Memory:** WSL is capped at 6 GB and each VM has 2 GB static; the manager host container adds PostgreSQL and Python inside WSL's 6 GB.
- **IP changes:** a Windows reboot changes the VM addresses and possibly the Default Switch address (`172.31.0.1`); re-run the IP lookup and check the Default Switch address after any reboot. If it changes, the portproxy listen address, the firewall rule's addresses, the certificate SAN and each VM's `/etc/hosts` line must follow it.
- **Clock skew step:** restore NTP before the stale window; a wrong clock left on u2204 would make later timing rows unreliable.
