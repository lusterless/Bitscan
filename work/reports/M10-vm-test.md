# M10 VM checks (held at the M10 merge): running record

Lead (main), session of 2026-11-02. Tree: main `33a45ad` (M10 merged as PR #18), run from a clean `git archive` copy. Decisions: `work/decisions.md` rows "User decisions before the M10 merge" and "User decision: G38 and G41" (2026-11-01), and "M10 VM session set-up" (2026-11-02).

This file is updated after every check, so a stopped session can resume without repeating finished work. **Status 2026-11-03:** every held M10 VM row has run; see "Resume here" and "Still open". No token or `install.env` content is written here; every log excerpt is masked for `bs[uaek]_`.

## Resume here

| Item | State | To resume |
| --- | --- | --- |
| `.deb` build | **DONE** (below) | Don't rebuild. Reuse `/root/m10vm/out/` |
| G41 | **PASS** (attempt 1, 23/23 rows, rc 0, finished about 18:08 local) | Don't re-run |
| G41 plant (reverse-order `list_sha256`) | **PASS (red as required)**, finished about 18:26 local | Don't re-run. Details in the G41 section |
| Portproxy and firewall move | **DONE** (user, 18:15 local) | portproxy `192.168.224.1:8443 → 127.0.0.1:18443`, old 172.26.240.1 entry gone, IP Helper running; firewall rule "Bitscan manager 8443 (VMs)" LocalAddress 192.168.224.1, RemoteAddress 192.168.224.0/20 (user's output) |
| Manager for the VMs | **Not needed any more** (was UP from 18:48 local on 2026-11-02 for G79 and the walk; stop it in WSL if still running) (user chose "serve from the tree") | A real `bitscan-manager serve` from the 33a45ad copy (`/root/m10vm/mgr/tree`, web UI built in), set up as G41 does: PostgreSQL 16 by Testcontainers, HTTPS with a private CA, the test sink and vault. It listens on WSL `127.0.0.1:18443`; the leaf covers `bitscan-mgr.test`. Start: `bash /root/m10vm/scripts/mgr-serve.sh` (log `/root/m10vm/mgr/serve.out`; work dir `/root/m10vm/mgr/serve/`, 0700; CA `manager-ca.pem`, also copied to `C:\Users\kaiquan.koh\Documents\m10vm\`). Admin and TOTP secrets are only in `serve/secrets/` (0600). It lives in this session's background shell, so after a session stop, start it again: a new database, so earlier enrolments are gone. Checked from Windows by the VMs' path (`bitscan-mgr.test` → 192.168.224.1:8443 → portproxy → 18443): `/healthz` and `/readyz` both 200 `{"status":"ok"}` (curl `--ssl-no-revoke`: schannel can't check revocation for the private CA; the chain and name are still verified). The manager-install walk route was blocked: `e2e/m6/manager_walk.py` is stale (see "Manager release files") |
| TASK-231 runbook walk (u2404, u2204) | **PASS on both.** u2404: §1, §2, §3a, §4, §9, §10, §11. u2204: the same plus §6 (0.1.0-1 → 0.2.0~pre1-1 in place). Both VMs `Off` at 11:44 UTC; their `clean` checkpoints are untouched | u2404 runs from `clean` (192.168.236.23). After a session stop: if the manager restarted (new DB), restore `clean` and redo the walk from §1; `scripts/mgrcli.sh` and `scripts/agent-show.sh` in `/root/m10vm/` drive the admin API |
| G79 (CHK-M10-290 to -292) | **PASS** on u2404 (-290, -291, -292 all PASS, 11:11–11:28Z). The runner was unmasked afterwards, and a follow-up scan of policy 1 passed again (job `276b8a73-…`, PASS, 11:28:12Z) | Section "G79" below. Policies in `/root/m10vm/g79/` (canary in `canary.txt`, 0600); `scripts/scan.sh POLICY_ID [canary]` starts a scan and reads the stored rows read-only (`scripts/mgr_db.py`, as `bitscan_app`) |
| G76 (CHK-M10-200 to -223), G78 host (CHK-M10-280 to -289) | **PASS (2026-11-03, after the unit and sample fixes).** QEMU stand-in VMs Ubuntu 22.04 and 24.04: 34 PASS, 0 FAIL, 2 NOT RUN each (214 runs on the v1 VM: PASS; 219b needs a manager: walk §10 PASS). The user ruled the stand-in VMs count for G76 (decisions 2026-11-03 (4)) | Re-run with `run_vm.sh` on any change to units, runner or samples (sandbox.yml does it on the hosted runners) |
| VM-planted CHK-M10 rows | **Done (2026-11-03).** Hosted run 6: 24 red for their own sub-check (incl. new 394, 395), 333 and 382 expected not red and green (user, 2026-11-03 (5)); 340 not red on the v1 VM (second cgroup check holds) | `plants.sh apply ID COPY`; sandbox.yml plant matrix (`[sandbox-plants]` or dispatch) |
| TASK-230 (`sandbox.yml`, G77) | **Green** (run 6, 8b0e514: 29/29 jobs) | Lead's second look (PD-43) still due |

## Environment

- **WSL:** Ubuntu-24.04, root, Docker. Work folder `/root/m10vm/`:
  - `src/`: the 33a45ad copy; `src-33a45ad.tar` is the archive it came from;
  - `out/`: the `.deb`, its `.sha256` file and the SBOMs;
  - `g41/`: the G41 log and rows;
  - `gocache/`, `gomod/`, `gopath/`: Go caches;
  - `scripts/`: `build.sh`, `g41.sh`, `g41-progress.sh`.
- **Build container:** image `m4b-build-u24`, with WSL's `/opt/go1.27.2` mounted read-only.
  - **Trust fix:** this network inspects TLS (Zscaler), so WSL's `/etc/ssl/certs/ca-certificates.crt` (which includes the Zscaler root) is mounted read-only into the container, with `SSL_CERT_FILE` pointing at it. The image and the host trust store are unchanged.
  - `build-deb.sh` is mode 100644 in git, so it's run with `bash`.
- **G41:** venv `/root/m10c/venv` (tester-m10c's M10 venv, `--require-hashes`), image `m4b-sysd-u24`, run label `m10vm-g41`.
- **Hyper-V (read-only check, 17:30 local):** `bitscan-u2204` and `bitscan-u2404` Off, each with checkpoint `clean` (2026-10-25); 3,195 MB free. The Default Switch is now **192.168.224.1/20**. The portproxy still listens on **172.26.240.1:8443** → 127.0.0.1:18443, so the VMs have no route to a WSL manager until the user moves it.
- **WSL leftovers from the M10 gate:** none found. No tester-m10c process is running; the only container is `m6b-host` (exited 6 days ago).

## `.deb` build: DONE

`bash /root/m10vm/scripts/build.sh`, rc 0, `sha256sum -c` OK.

| File | SHA-256 |
| --- | --- |
| `bitscan-agent_0.2.0~pre1-1_amd64.deb` | `bb3a8785c837e66cf8a6fa3070b26eaa8af6df4ebd54618d7be68ccf61c50814` |
| `bitscan-agent` | `490cc8754d4041ac07a2aeae061caff866b892c3d3daae0323b5052144fb8917` (equals the gate build) |
| `bitscan-runner` | `d8b9372e8ddb966789b82caed852432016d861f2fd58740c48ea3937ee5643d8` (differs from the gate's `fb65da6b…76c2`: the TASK-225 r1 serve-loop fix, 9f64887, came after the gate) |
| `bitscan-capread` | `7d0018468aba74b5cf743204ea73bc1c19bc5c70ca5789fbcd42cee47662e06e` (equals the gate build) |

## G41: installed `.deb` against the real manager (WSL): PASS, 23/23

Command: `bash /root/m10vm/scripts/g41.sh`, which runs `e2e/agent_manager.sh /root/m10vm/src /root/m10vm/out /root/m10vm/g41/rows.jsonl m4b-sysd-u24`. Attempt 1 started 2026-11-02 17:44 local and ended with rc 0 and "OK 23/23 rows". Rows from `run.log` (masked); the full log is `/root/m10vm/g41/run.log`, and `rows.jsonl` sits beside it:

| # | Check | Result | Evidence |
| --- | --- | --- | --- |
| 1 | real manager `serve` ready (PostgreSQL 16, HTTPS, private CA) | PASS | port 47799; deb `bitscan-agent_0.2.0~pre1-1_amd64.deb` (sha256 `bb3a8785…0814`) |
| 2 | clean systemd host | PASS | Ubuntu 24.04.5 LTS |
| 3 | admin created by the server CLI | PASS | rc 0 |
| 4 | TOTP-verified admin session; `job_pull_seconds` 60 | PASS | 200 |
| 5 | `bse_` enrolment token created with the TOTP session | PASS | 201 |
| 6 | install with preseed | PASS | rc 0, `0.2.0~pre1-1 install ok installed`, `active` |
| 7 | the `bse_` token is in no debconf file, `/etc` or log after install | PASS | nothing found |
| 8 | the enrolment is held (pending request, kind new) | PASS | kind new, hostname g41-a, agent_version 0.2.0~pre1-1 |
| 9 | while held, the agent waits | PASS | status awaiting_approval, no snapshot |
| 10 | admin approves (TOTP session) | PASS | 200 |
| 11 | heartbeat after approval: status online | PASS | online, hb 2026-11-02T09:47:02Z, version 0.2.0~pre1-1 |
| 12 | first inventory job uploaded; `GET /agents/{id}` shows os_info and the snapshot | PASS | ubuntu 24.04 x86_64, package_count 126 |
| 13 | the package list is searchable for the host | PASS | 200; bash, dpkg, libc6 |
| 14 | a dpkg change on the host (probe package installed) | PASS | `bitscan-g41-probe (1.0)` install ok installed |
| 15 | the change leads to one unscheduled upload after the 60 s quiet time; the snapshot lists the probe | PASS | puts [204], 65 s after the change |
| 16 | a second dpkg change during the hold-off (probe removed) | PASS | probe removed |
| 17 | no unscheduled upload during the hold-off (#80, the manager's 10 minutes) | PASS | puts [], 570 s watched |
| 18 | the change made during the hold-off is sent once it ends, never lost or refused | PASS | puts [204], 625 s after the first unscheduled upload; probe no longer listed |
| 19 | admin revokes the agent (TOTP session) | PASS | 204 |
| 20 | the 401 stops the loops: the journal says the host must be re-enrolled with a new enrolment token | PASS | found, count 1 |
| 21 | no agent call in the manager access log after the 401 (400 s watched); the process stays up, idle (#81 (a)) | PASS | calls after revoke: one `GET jobs` → 401, then 0; unit active, 0 restarts |
| 22 | no `bse_`/`bsa_` token in the agent journal | PASS | 0 |
| 23 | `serve.log` holds no `bse_`/`bsa_` token | PASS | 0 |

G41 result: **PASS, 23/23** (rc 0). The inventory chain works with the M10 package (0.2.0~pre1-1) against the real manager.

### G41 planted violation: PASS (red as required)

M10 gate table: the reverse-order `list_sha256` `.deb` must stop the chain at the snapshot row with 422 `hash_mismatch` (the same plant as CHK-M4-311-plant and CHK-M6-318-plant).

- **Plant:** in a throwaway copy (`/root/m10vm/plant-g41/src`, from `src-33a45ad.tar`), `agent/internal/inventory/dpkg.go:91` `slices.SortFunc(lines, bytes.Compare)` became `slices.SortFunc(lines, func(a, b []byte) int { return bytes.Compare(b, a) })`. `diff` against the clean copy shows exactly that one line. The tree and `/root/m10vm/src` are unchanged.
- **Build:** `build-deb.sh` in the same container (rc 0). Plant `.deb` sha256 `c7ab7a366c18b3dccb7679e599ee8a6d2ce32781dcc5dfa20c7cd547a76bb6f9`. Only `bitscan-agent` changed (`072407f9…a59d` against the clean `490cc875…8917`); `bitscan-runner` `d8b9372e…43d8` and `bitscan-capread` `7d001846…e06e` equal the clean build.
- **Run:** `bash /root/m10vm/scripts/g41-plant.sh`, the same `e2e/agent_manager.sh` with the manager from the clean copy and the plant `.deb` (run label `m10vm-g41plant`). Log: `/root/m10vm/plant-g41/run.log`.
- **Result:** rc 1, "FAIL 12/13 rows". Rows 1–11 PASS as in the clean run, up to "heartbeat after approval: online". The chain stops at the snapshot row: FAIL "the first inventory job is uploaded", evidence `os [null, null, null], package_count null, refused [{job_id null, hash_mismatch, 422}, {job_id 239938d7-1811-4469-b617-6fb540e3ee8e, hash_mismatch, 422}]`. So both the unscheduled upload and the job's upload were refused, and nothing was stored. "serve.log holds no bse_/bsa_ token" PASS (0). The same result as CHK-M6-318-plant.

**G41 overall: PASS.** The clean run is 23/23, and the planted violation turns it red at the required row for the required reason.

## Manager release files (built 2026-11-02 18:42 local, from the 33a45ad copy)

`bash /root/m10vm/scripts/mgr-host.sh`, the build part. The web UI built in `node:24` (rc 0). The wheel was built offline (`pip wheel --no-deps --no-build-isolation --no-index`, venv `/root/m10c/venv`) and carries `webui/index.html` and its assets. `/root/m10vm/mgr/rel/SHA256SUMS`:

| File | SHA-256 |
| --- | --- |
| `bitscan_manager-0.1.0-py3-none-any.whl` | `fc8951a5d2d37bc880249af8f993ccfe681c65170985a03997bc226cbb60c279` |
| `bitscan-manager-0.1.0-requirements.txt` | `b6bf600e63b48139ed709dc0b32aabe94525fb7ccbf7cf51f2df7a9589824a26` |
| `bitscan-manager.service` | `09f3ff028e1f7e59e25517e8f42a8d91def5016e24fa5448b64d4bb4ffabea8b` |
| `bitscan-manager-migrate.service` | `c76a39cb75ab787e4174073d697c3be4e3479f597e9540051be77f9f7b2b2fc0` |
| `bitscan-manager-maintain.service` | `8c6729d32311f1328d5f7d27fe0b8dc5003dc9f1630a6bb45aad8b2dfc8419b4` |
| `bitscan-manager-maintain.timer` | `47d97eaf92d0409da6571267e951f63cd3b885450d1e13dfe3eba5eea05e813e` |

**Finding (harness, not product):** `e2e/m6/manager_walk.py` is stale against the current `deploy/runbooks/manager-install.md` (block layout changed after M6). Owner: tester. Not fixed here.

## TASK-231 agent runbook walk on bitscan-u2404 (CHK-M10-315f, REQ-258 (1))

VM actions approved by the user (2026-11-02 18:50 local). Restored `clean`, fixed 1024 MB, started at 192.168.236.23; `bitscan-mgr.test` → 192.168.224.1 in `/etc/hosts` (`e2e/m6/vm.sh`, known hosts in `C:\Users\kaiquan.koh\Documents\m10vm\kh\`). Copied to `~/rel`: the M10 `.deb`, `SHA256SUMS` (the build's published line) and the manager CA. Ubuntu 24.04.5 LTS amd64, no Bitscan package before. The manager's `/readyz` from the VM by name: `{"status":"ok"}`.

Deviations from the runbook text, all forced by running without a terminal: `sudoedit` is replaced by writing the already-0600 file through `sudo sh -c 'cat > …'` (the mode set by the runbook's `install -m 0600` is kept); `apt install` gets `-y`. Both are recorded on each row.

| Step | Check | Result | Evidence |
| --- | --- | --- | --- |
| §1 | cgroup v2: `stat -fc %T /sys/fs/cgroup` prints `cgroup2fs`; no `systemd.unified_cgroup_hierarchy=0` in `/proc/cmdline` | PASS | `cgroup2fs`; 0 matches |
| §1 | Time: `timedatectl` shows `System clock synchronized: yes` | PASS | as shown |
| §1 | Machine id (not a clone; noted only) | PASS | `/etc/machine-id` 33 bytes; `/var/lib/dbus/machine-id` → `/etc/machine-id` |
| §1 | Private CA block as written: `/etc/bitscan` 0755, `ca.pem` 0644 | PASS | `root:root 755 /etc/bitscan`, `root:root 644 /etc/bitscan/ca.pem` |
| §1 | Key pin block as written, on the manager host (path adapted to the test leaf `mgr-leaf.pem`) | PASS | `66be0ba9a2ed1d5b1b20096b93fce72f948b45613f2f74617bbdfb521e0bb4ff`, equal to the pin of the certificate served on 127.0.0.1:18443; leaf SAN `DNS:bitscan-mgr.test`. (A first try on a wrong file name gave the empty-input hash; discarded, not used) |
| §2 | `sha256sum -c --ignore-missing SHA256SUMS` | PASS | `bitscan-agent_0.2.0~pre1-1_amd64.deb: OK`, rc 0 |
| §2 | Negative: one byte changed | PASS | `FAILED`, "no file was verified", rc 1 |
| §3a | `sudo install -m 0600 /dev/null /root/bitscan.preseed` | PASS | `root:root 600` |
| §3a | Content: manager URL, token as `password`, `ca_file`, pin (deviation: `cat >`, not `sudoedit`). The token came from a new single-use `bse_` (24 h) made with the TOTP admin session, through a pipe only | PASS | `root:root 600`, 333 bytes; question types `string`, `password`, `string`, `string` |
| §3a | `debconf-set-selections`, `apt install ./…deb` (deviation: `-y`), `rm -f` the preseed | PASS | dss rc 0, apt rc 0; preseed gone (`sudo test -e` false) |
| §3 "What the install does" | users `bitscan`, `bitscan-runner`: no shell, no home | PASS | `/nonexistent`, `/usr/sbin/nologin` |
| §3 | `agent.yaml` `root:bitscan` 0640 without the token; it holds the pin | PASS | `root:bitscan 640`; 0 `bse_`/`bsa_` matches; keys `manager_url ca_file manager_spki_sha256 state_dir heartbeat_seconds job_pull_seconds max_parallel_plugins spool_max_mb log_level`; pin line present |
| §3 | Token cleared from debconf | PASS | `debconf-show`: `bitscan/enrol_token: (password omitted)` |
| §3 | Token sweep: the `bse_` token (given to `grep -F -f /dev/stdin`, file names only) in no file under `/var/cache/debconf /etc /var/log /root /tmp /home` | PASS | grep rc 1, nothing found |
| §3 | Enables and starts `bitscan-runner.socket` and `bitscan-agent.service` | PASS | is-enabled: agent `enabled`, runner.socket `enabled`, runner.service `disabled`, capread.socket `disabled`, capread.service `static`; is-active: `active active inactive inactive inactive` |
| §4 | Both units `enabled` and `active`; capread stays disabled; `bitscan-runner.service` inactive until the first job (CHK-M10-221, first half) | PASS | as above; still `inactive` after enrolment, approval and the first inventory; `/run/bitscan/runner.sock` `srw-rw---- root bitscan` |
| §4 | After the first enrolment call: `agent_id` and `token` present, `enroll.token` gone, even while waiting for approval | PASS | `agent_id` 644, `token` 600, `token.json` 600, `spool/` 700, all `bitscan:bitscan`; no `enroll.token`; journal `bitscan-agent started version=0.2.0~pre1-1 agent_id=6d644e85-…` |
| §4 | The enrolment is held for approval (no `auto_approve`) | PASS | request 1, kind `new`, hostname `bitscan-u2404`, `agent_version` 0.2.0~pre1-1; host `awaiting_approval`. (`source_ip` 127.0.0.1: the Windows portproxy, a test-network artefact) |
| §10 | Helper off: the call exits 1 with `bitscan-capread: not enabled` | PASS | as `bitscan-runner`: that line, rc 1 |
| §10 | Enable block as written: socket `active`; socket file `srw-rw----` `root bitscan-runner`; `nft_ruleset` prints the ruleset as JSON | PASS | `active`; `srw-rw---- 1 root bitscan-runner … /run/bitscan/capread.sock`; rc 0, 111 bytes, valid JSON with key `nftables` (contents not printed) |
| §10 | No `auditctl`: the answer is `bitscan-capread: not_installed` | PASS | `audit_rules` → that line, rc 1 (`auditd` not installed) |
| §10 | The helper accepts only `bitscan-runner` | PASS | `bstester` and `bitscan`: rc 1 (they can't open the 0660 socket; the client reports `not enabled`) |
| §10 | Next heartbeat reports `runner_helpers` `["capread"]`; a `runner_helper_changed` alert (CHK-M10-219, middle) | PASS | after 113 s, heartbeat 11:00:59Z; audit 9 alert `old [] → new ["capread"]` |
| §10 | Disable block as written: `ls` reports `No such file or directory` | PASS | that message, rc 2; socket and service `inactive`; the call is back to `not enabled`, rc 1 |
| §10 | Next heartbeat reports `[]`, with another alert (CHK-M10-219, last part) | PASS | after 267 s, heartbeat 11:05:41Z; audit 10 alert `old ["capread"] → new []`; 2 alerts in all |
| §11 | `spool_max_mb` default 50 | PASS | `spool_max_mb: 50` in `agent.yaml` |
| §11 | Check block as written: no `result spool` error line; `spool` a directory `bitscan:bitscan` 0700; filesystem writable with space | PASS | grep rc 1 (no line); `drwx------ bitscan bitscan …/spool`; `/` 9 % used, 17 G free. `du -sb` of the spool: 0 before any job |
| §11 | Any other `spool_max_mb` refuses start-up with `agent.yaml: spool_max_mb: must be 1 to 50` | PASS | set to 51 (`agent.yaml` saved and restored with `cp -a`, still `root:bitscan 640`): journal `start-up refused reason="agent.yaml: spool_max_mb: must be 1 to 50"`, unit `activating` (restart loop); after the restore, `active`, `bitscan-agent started` with the same agent id |
| §9 | After the first compliance job: `bitscan-runner.socket` and `.service` both `active`; the log shows `bitscan-runner started` with the package version | PASS | `active active`; `bitscan-runner started version=0.2.0~pre1-1`, then `runner: job accepted job_id=… agent_id=… plugins=1`, `plugin done … exit_code=0`, `job done results=1`: ids and counts only. CHK-M10-221 second half: the service started with the first job (11:12:40Z), not before |
| §9 | The runner never logs a check command or its output | PASS | `journalctl` (all units): 0 lines with the command text (`dpkg-query -W -f`) or its output (`install ok installed`) |
| §11 | Results are kept until the manager answers | PASS | after the job: spool 0 bytes, 0 entries (answered) |
| §4 | Admin approves (TOTP session); heartbeat; the first inventory follows | PASS | approve 200; `online`, first heartbeat 10:56:15Z; snapshot 1 at 10:56:33Z, `package_count` 665 = `dpkg-query -W` 665 lines; os_info complete; `runner_helpers` `[]`; no `agent last_error` line in `serve.log` before CHK-M10-292 (the manager only logs `last_error`; it isn't an API field) |

## TASK-231 agent runbook walk on bitscan-u2204, with the §6 upgrade 0.1.0-1 → 0.2.0~pre1-1

The user approved this (2026-11-02, "yes", with §6 included). u2404 was stopped first (`Off`), so one VM ran at a time. u2204 was restored to `clean`, fixed at 1024 MB and started at 192.168.237.241; Windows had 5,469 MB free. Ubuntu 22.04.5 LTS amd64, no Bitscan package before; manager `/readyz` from the VM by name `ok`. Packages: `bitscan-agent_0.1.0-1_amd64.deb` (the M6 release candidate, sha256 `d98ef8c3978e99e65f27074be8613c04fcaddba6f774efece30a4f7aefe0f3bf`, from `/root/m6tc/relout-final`) and the M10 `.deb`. `SHA256SUMS` combines the 0.1.0 release text and the M10 line. Same deviations as on u2404 (`cat >` for `sudoedit`, `-y`).

| Step | Check | Result | Evidence |
| --- | --- | --- | --- |
| §1 | cgroup2fs; NTP; machine id; CA block | PASS | `cgroup2fs`, unified=0 not on the command line; `System clock synchronized: yes`; 33 bytes, dbus link → `/etc/machine-id`; `/etc/bitscan` 755, `ca.pem` 644, root |
| §2 | `sha256sum -c --ignore-missing SHA256SUMS` | PASS | both `.deb`: OK, rc 0 |
| §3a | Preseed install of **0.1.0-1** (new single-use `bse_`, pipe only; pin and CA) | PASS | preseed 0600, 333 bytes; dss rc 0; apt rc 0; preseed removed; `0.1.0-1 install ok installed`; agent and runner.socket `enabled`/`active`; journal `bitscan-agent started version=0.1.0-1 agent_id=7a8573c9-47af-40ef-8618-28fe58989329`; token sweep (stdin) found nothing |
| §4 | Held, approved, online, first inventory | PASS | request 2 `new` `bitscan-u2204` 0.1.0-1, `awaiting_approval`; approve 200; `online`, heartbeat 11:32:05Z; snapshot 2, 598 packages; os_info Ubuntu 22.04.5, kernel 5.15.0-198 |
| §6 | Upgrade: `apt install ./bitscan-agent_0.2.0~pre1-1_amd64.deb` asks nothing; keeps `agent.yaml`, the token and the agent id; restarts the services | PASS | apt rc 0. No question asked: the only debconf lines are its no-terminal frontend fallback. `cmp` against before-copies: `agent.yaml` same, `agent_id` same, `token` same (contents never printed; copies removed). Modes kept; `spool/` (0700) and `seen_jobs.json` (0600) present. Units: agent and runner.socket `enabled`/`active`, runner.service and capread.socket `disabled`/`inactive` |
| §6 | Check block as written: `dpkg-query` prints the new version; the log shows `bitscan-agent started` with it; no re-enrolment | PASS | `0.2.0~pre1-1`; journal `bitscan-agent started version=0.2.0~pre1-1 agent_id=7a8573c9-…` (same id) at 11:33:01Z; manager: `online`, `agent_version` `0.2.0~pre1-1` on the 11:33:01Z heartbeat; no pending enrolment request |
| §9 (and G79 main path on 22.04) | First compliance job after the upgrade: runner socket and service `active`, `bitscan-runner started` with the version; scan completes | PASS | scan of policy 1: job `a3a21b9e-fca7-45c1-a6b6-b2dd0809ff57` `completed` 11:33:58Z, no retry; result PASS, exit 0, `install ok installed`; scan `completed` 11:34:35Z; `active active`; `bitscan-runner started version=0.2.0~pre1-1`; 0 journal lines with the command or output |
| §11 | `spool_max_mb` 50; no `result spool` line; `spool` `bitscan:bitscan` 0700; free space | PASS | as stated; `/` 9 % used; `du -sb` 4096 (empty folder; answered) |
| §10 | Off → `not enabled`; enable block; socket `srw-rw---- root bitscan-runner`; `nft_ruleset` JSON; `audit_rules` `not_installed`; other users refused | PASS | rc 1 `not enabled`; `active`; as stated; rc 0, 109 bytes, key `nftables`; `not_installed` rc 1; `bstester` rc 1 |
| §10 | Heartbeat `["capread"]` with an alert, then disable → `No such file or directory`, heartbeat `[]` with another alert | PASS | `["capread"]` after 185 s (11:38:00Z), alert audit 21; disable: `ls` rc 2 with that message, both `inactive`, call back to `not enabled`; `[]` after 267 s (11:42:45Z), alert audit 22 |

## G79: first compliance run on bitscan-u2404 against the real manager (CHK-M10-290 to -292)

Same VM and enrolment as the runbook walk; the manager is the serve-from-tree one. There is no results route yet (the results views are M11), so stored rows are read from the manager's PostgreSQL as `bitscan_app`, read-only (`/root/m10vm/scripts/mgr_db.py`). stdout is shown only masked and cut to 120 characters.

Set-up found on the way: the manager's policy folder `BITSCAN_BITS_DIR` (default `/var/lib/bitscan/bits`) didn't exist in WSL. The catalog retried every 10 s (`catalog start-up failed, retrying: FileNotFoundError`) and imports answered 503 "The catalog is starting". The folder was created in WSL (`/var/lib/bitscan` 0755, `bits` and `bits/uploaded` 0750, root, since WSL has no `bitscan-manager` user; remove it at the end). The catalog then finished (`catalog start-up done … catalog ready`, 11:10:36Z) without a restart. This is a set-up gap in the test environment, not a product defect: the manager runbook creates the folder.

Policies (`/root/m10vm/g79/`), uploaded with the admin TOTP session through `POST /policies/import`:
- policy 1: the SR §1.1 canonical example, extracted verbatim from the spec (`sr-1.1-canonical.bit`, sha256 `6654c209…89b9`). Import 1 `success`, 1 plugin.
- policy 2: "Bitscan M10 G79 redaction canary" (`g79-canary.bit`, 0600). One plugin echoes `start <canary> end`, Operator `contains`, ExpectedResult `end`. The canary is a fresh random `bsa_`-shaped string, never issued by the manager, kept in `canary.txt` (0600) and never printed. Import 2 `success`, 1 plugin, with a BIT101 warning ("PluginName has no leading control reference"), not a refusal.

| CHK | Check | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M10-290 | A scan of policy 1 on u2404 reaches `completed`; the SR §1.1 plugin is PASS | **PASS** | `POST /scans` 202, scan `b87b0f06-f784-4a22-b511-314d56d0e27c` queued 11:11:20Z, 1 job. Job `54349098-…` `completed`, started and finished 11:12:40Z, `retry_of` none. Scan `completed` 11:13:35Z. Result "CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed": PASS, exit 0, not timed out or truncated, stdout `install ok installed` |
| CHK-M10-291 | A `bsa_`-shaped canary printed by a plugin is stored as `[REDACTED]` (redacted on the host, before it leaves) | **PASS** | Scan `fb74edae-8abd-4245-817f-9915ad97ed2f` (policy 2) queued 11:15:05Z. Job `0826b786-…` `completed` 11:15:53Z, no retry; scan `completed` 11:16:35Z. Result "Bitscan M10 tests - G79 - canary in stdout": PASS (`contains end` on the redacted text), exit 0, not truncated. Stored stdout `start [REDACTED] end`: canary present **False**, `[REDACTED]` present True |
| CHK-M10-291 (sweep) | The canary is in no agent or runner log, no spool or state file, and not in `serve.log` | **PASS** | `bitscan-agent`/`bitscan-runner` journal lines with the canary: 0; manager `serve.log`: 0; `/var/lib/bitscan-agent`: none. Harness note: the canary later showed up in `/var/log/auth.log` and the `bstester` journal, but only in 2 lines, both `sudo … COMMAND=` lines of the lead's own sweep (the canary was passed to `sudo grep` as an argument). Not the product. The `bse_` token sweep in the runbook walk passed its token on stdin, so it left no such line. The command text (with the canary) is stored as `execute_snap` on the manager by design: commands aren't output |
| CHK-M10-292 | Runner masked → every result ERROR `runner_unavailable`, the job `completed`, nothing retried | **PASS** | On u2404: `systemctl mask --now bitscan-runner.socket bitscan-runner.service` (both `inactive`; restored afterwards). Scan `4de0fadb-8a3a-4e76-a1a8-b93fd9ef0f5c` (policy 1) queued 11:18:21Z. Job `7ffb29bf-…` `completed` 11:19:12Z; scan `completed` 11:19:35Z. Result: ERROR, `eval_detail runner_unavailable`, exit null, stdout empty. Jobs for the scan: 1; jobs with `retry_of` set across all scans: 0 |
| CHK-M10-292 (runbook §9 text) | The agent logs `the runner is unavailable; plugins without a result are reported runner_unavailable` with `job_id` and a reason; the next heartbeat carries `last_error` `runner_unavailable: <reason>`, which the manager logs as `agent last_error` with the agent id | **PASS** | agent journal 11:19:12Z: that line, WARN, with `agent_id` and `job_id=7ffb29bf…`. Heartbeat 11:21:52Z → `serve.log` `"message": "agent last_error"`, `agent_id 6d644e85-…`, `"last_error": "runner_unavailable: connect"`. (The manager only logs `last_error` and never stores it, by design #25 (a); `GET /agents/{id}` has no such field) |

## Sandbox suite, G78 host part, VM plants and TASK-230 (cloud session, 2026-11-02 evening)

Branch `ccr-e5f4e02d-dulvt3` (from `m10-vm-checks` 413f299). The user asked for G76, the G78 host part, the VM-planted rows and TASK-230, "write the test and run it". This cloud session cannot reach the Hyper-V VMs, and its own kernel keeps cgroup v1 hierarchies (the runner rightly refuses there), so the suite ran on:

- **G77, GitHub hosted runners** `ubuntu-22.04` and `ubuntu-24.04` (Azure kernel 7.0.0-1017, systemd 255 on 24.04), through the new `sandbox.yml`, which builds the `.deb` and installs it on each throwaway runner. Runs 1–5 on this branch; the record below is run 3 (37328214, with the plants) and run 5 (030447d, 24.04 with `auditd`).
- **G76 stand-in, QEMU VMs** of the official cloud images (`noble-server-cloudimg-amd64.img`, `jammy-server-cloudimg-amd64.img`; kernels 6.8.0-147 and 5.15.0-198), software emulation, 4 vCPU, 4 GB. Each run is a fresh overlay on a read-only `clean` base (the checkpoint equivalent), destroyed afterwards. A third base boots 22.04 with `systemd.unified_cgroup_hierarchy=0` for CHK-M10-214. **These are not `bitscan-u2204`/`bitscan-u2404`**; whether they count for G76 is the user's call (question 4 below).

The `.deb` under test is the M10 build, byte-identical to this morning's (sha256 `bb3a8785…0814`, rebuilt from 413f299). No token was printed: the install uses an `.invalid` manager URL and a random `bse_` never issued; `bitscan-agent` is stopped and the driver plays the agent as uid `bitscan`. Reports are masked for `bs[uaek]_`; the saved copies hold no token or canary (grep: 0).

### Harness (all new, test files only)

| File | What |
| --- | --- |
| `agent/test/sandbox/run_vm.sh` | Host wrapper: installs the `.deb` (install.env, dummy inputs), stops the agent, writes a test `agent_id`, optional `--with-nft`/`--with-auditd`, runs the suite |
| `agent/test/sandbox/sandbox.py` | Driver and rows: CHK-M10-200 to -223 (G76/G77), -280 to -289 (G78 host part, defined in `tests/m10/test-plan.md` today), -344v (runner half of the -344 boundary). PASS/FAIL/NOT RUN per row, never silent; `--expect-red ROW@part` for plants |
| `agent/test/sandbox/plants.sh` | The 25 VM plants as exact one-anchor replacements in a throwaway `git archive` copy (refuses a git work tree) |
| `.github/workflows/sandbox.yml` | TASK-230: build, suite on both runners (24.04 with `auditd`), report in the job summary and as an artifact; the plant matrix runs on `workflow_dispatch` or a push whose message holds `[sandbox-plants]`. Path filters per REQ-257 (pushes also run, a superset) |

Harness defects found and fixed on the way (none product): `datetime.UTC` is 3.11+; the shell's own fds (a `$(…)` pipe at fd 3, dash's saved stdout at fd 10) were counted, so the fd probe now `exec`s Python; `pgrep -f` matched the probe shell; nft counters move between two reads; the 64 KiB token needed a non-word byte before it for `\b`; an inventory job must not carry `plugins`; a plugin read the runner's cgroup mid-hop (#136 (a)); Python 3.10 can't parse nanoseconds; cgroup v1 mode ignored `--expect-red`.

### Results (final code)

| Host | PASS | FAIL | NOT RUN | FAIL rows |
| --- | --- | --- | --- | --- |
| QEMU Ubuntu 24.04 (kernel 6.8, systemd 255), 3f2369d | 32 | 2 | 2 | 201, 203 |
| QEMU Ubuntu 22.04 (kernel 5.15, systemd 249), 3f2369d | 32 | 2 | 2 | 201, 203 |
| QEMU Ubuntu 22.04 booted cgroup v1 | CHK-M10-214 **PASS** ("/sys/fs/cgroup is not cgroup2", no frame, nothing executed) | | other rows NOT RUN by design | |
| Hosted ubuntu-24.04 with `auditd` (run 5) | 31 | 3 | 2 | 201, 203, 222 |
| Hosted ubuntu-22.04 (run 3) | 32 | 2 | 2 | 201, 203 |

NOT RUN everywhere: CHK-M10-214 on cgroup v2 hosts (it runs on the v1 VM, above) and CHK-M10-219b (`runner_helpers` in the heartbeat needs a manager; covered by the TASK-231 walk §10 on both Hyper-V VMs today). Full row tables: `work/reports/m10-sandbox/f-n24.md`, `f-j22.md`, `r-j22v1-clean.md`.

Every G78 host row (CHK-M10-280 to -289) PASS on all four v2 hosts: expired → `pickup_passed`, foreign → `foreign_agent`, replay → `replayed`, root and a `bitscan` member closed without a frame (journal names uid 0 and the member's uid), bare string / plugins-only / unknown key → `malformed`, inventory → `not_compliance`, a second frame never decoded, capread refuses ten other names and serves only `bitscan-runner`; nothing executed in any case (marker socket), one journal line per refused job id, no payload.

Facts for the owner: CHK-M10-223 `clone3` → **ENOSYS** on 24.04 (systemd 255's filter answers) and **EINVAL** on 22.04 (systemd 249 lets it reach the kernel). CHK-M10-217 with `auditd` (hosted 24.04): `audit_rules` equals root's `auditctl -l`; helper `CapEff` `0000000040001000` under a dynamic uid, helper command environment empty (an env probe bound over `auditctl` for one request).

### Real findings (spec vs. host behaviour; no unit was changed)

1. **CHK-M10-201: a plugin can write to `/dev/shm`, and the file appears in the host's `/dev/shm`** (all 4 v2 hosts). TS §3.7 says the runner cannot "write outside its private `/tmp`" and the unit comment says "the only writable place is a private /tmp". `ProtectSystem=strict` leaves the API filesystems (`/dev`) writable, and `PrivateDevices=yes` keeps the host's `/dev/shm`; `PrivateIPC=` does not cover it. A plugin can therefore leave files for, or read files from, other host processes there.
2. **CHK-M10-203: a plugin can execute a file it wrote to its private `/tmp` or `/var/tmp`** (exit 0, all 4 v2 hosts; `/home` correctly 126). TS §3.7 unit comment: "Only system binaries can be executed; /tmp and user paths cannot". `NoExecPaths=/` does not reach the `PrivateTmp=` mounts on systemd 249 or 255.
3. **CHK-M10-222 (#143): the cramfs sample plugins answer `absent` under the sandbox where root sees `loaded=no install=no blacklist=no`** (hosted 24.04, Azure kernel with the cramfs module; the cloud-image kernels lack it, so the two match there; the other 30 sample plugins match root on every host). `ProtectKernelModules=yes` hides `/lib/modules`, so "1.1.1.1 Ensure cramfs kernel module is not available" can report compliant on a host that is not.

All three need a unit change (TS §3.7 verbatim) or a sample change, so they are open questions for the owner, not fixed here. G77 stays red until then; no gate was lowered.

### VM plants (REQ-262)

Hosted ubuntu-24.04, run 3, each plant in a throwaway copy, its own `.deb`, `--expect-red ROW@part` (the plant's own sub-check must fail, so a row already red on a clean build cannot hide a miss). **Red: 320, 325, 327, 329, 330, 331, 334, 335, 336, 337, 338, 339, 343, 344, 371, 373, 374, 386, 388, 389, 390, 391 (22).**

Not red, each recorded with its reason:

| Plant | Row | Why not red on a host | Unit-level red (gate report) |
| --- | --- | --- | --- |
| 333 stdin inherited | CHK-M10-211 stdin | systemd gives the runner `/dev/null` as stdin, so the inherited fd is also `/dev/null`; not observable on a host | G72 (spawn unit test) |
| 382 stdout logged at debug | CHK-M10-220 | the runner's handler is at info, so the debug line is never written; the journal sweep stays clean | G72 |
| 340 statfs check removed | CHK-M10-214 (cgroup v1 VM) | the runner still refuses at its second check, "not on the unified cgroup v2 hierarchy" (`/proc/self/cgroup`); defence in depth holds | G72 (injected statfs) |

The plants were applied only in throwaway copies; the tree was never planted.

### 2026-11-03: fixes and re-run (user decisions 2026-11-03)

| Finding | Decision | Change | Commit |
| --- | --- | --- | --- |
| CHK-M10-201 `/dev/shm` | fix in the unit | `ReadOnlyPaths=/dev/shm` in `bitscan-runner.service` and the TS §3.7 block | 86f33a6 |
| CHK-M10-203 exec from the private `/tmp` | fix in the unit | `NoExecPaths=/ /tmp /var/tmp` (unit and TS §3.7); `check_units_verbatim.py` ranges after L308 +2 | 86f33a6 |
| CHK-M10-222 cramfs | rewrite the sample | both samples fall back to the kernel packages' file lists, `unknown` (FAIL) when blind; `prepare()` gives 0 findings for both; BIT102 sample rows 33/33 | 1072e5e |
| Plants 333, 382 | keep, expected not red | sandbox.yml `expect: not-red` | 8b0e514 |
| G76 on stand-in VMs | counts | — | — |

Both drop-in variants were first tried live on the 24.04 and 22.04 VMs (each line alone fixes only its row; together both rows pass, 211 and 212 stay green). The sample fallback was checked inside the sandbox and as root on the 22.04 VM with a module the kernel ships (`cpuid`): both `loaded=no install=no blacklist=no` (before: `absent` in the sandbox).

| Host (fixed `.deb` sha256 `3b95a10f…b776`) | PASS | FAIL | NOT RUN |
| --- | --- | --- | --- |
| QEMU Ubuntu 24.04 (kernel 6.8, systemd 255) | 34 | 0 | 2 (214 v2 host, 219b) |
| QEMU Ubuntu 22.04 (kernel 5.15, systemd 249) | 34 | 0 | 2 (214 v2 host, 219b) |
| Hosted ubuntu-22.04 and ubuntu-24.04 with `auditd`, run 6 | job green | 0 | 214, 219b |

Plants, run 6 (8b0e514): 26/26 jobs green: 24 red for their own sub-check, including **394** (no `ReadOnlyPaths=/dev/shm` → CHK-M10-201 `/dev/shm` red) and **395** (`NoExecPaths=/` only → CHK-M10-203 `/tmp copy` red); 333 and 382 green as expected. Reports: `work/reports/m10-sandbox/g-n24.md`, `g-j22.md`.

**G76, the G78 host part, the VM plants and TASK-230 are done**, with the lead's second look at TASK-230 (PD-43) still to do.

## Still open (updated 2026-11-03)

Every row that was NOT RUN here on 2026-11-02 morning has since run (sections above). What remains:

| Item | State | Next step |
| --- | --- | --- |
| Manager-stored half of CHK-M10-344 (a secret on the 64 KiB boundary through the agent into the stored stdout) | not run; the runner half CHK-M10-344v PASS on every host (the agent forwards the runner reply as is) | one scan on a VM against the WSL manager, or the user rules the runner half enough |
| Reviews of the 2026-11-03 changes (runner unit and TS §3.7 text, cramfs samples, sandbox harness and `sandbox.yml`) | not reviewed | reviewer: TS §8.2 second approval for the runner unit; lead's second look at TASK-230 (PD-43); addendum to `work/reviews/M10-closing.md` ("no unit change" no longer holds) |
| `units.yml`, `package.yml`, `agent.yml` on these commits | not run (they run on a PR or on `main`) | open the PR from `m10-vm-checks` to `main` |
| `e2e/m6/manager_walk.py` stale against the manager install runbook | harness finding, not product | tester follow-up |
| WSL leftovers from 2026-11-02 | `/var/lib/bitscan` (made for G79) and the background `bitscan-manager serve` | remove the folder and stop the manager in the next WSL session |

## Incidents

1. **Harness write-up stopped by a safety classifier (2026-11-02 09:35:33 UTC).** The background tester (tester-m10vm) was briefed to write `agent/test/sandbox/` (run_vm.sh, driver, probe, plants.sh) and `e2e/m10/first_run.sh`. A safety classifier stopped one of its responses while it was still reading; the stopped content was withheld. It wrote no file and took no VM, container or build action. The notice is at line 160 of the subagent transcript (`~/.claude/projects/c--Users-kaiquan-koh-Documents-Bitscan/64a43e2c-51c7-4871-8330-571e36b66fcf/subagents/agent-afee09f07bd171bdc.jsonl`). Per the user's instruction, it was not retried, reworded or split.
2. **Second classifier stop (lead, 2026-11-02, about 18:45 local).** After the user changed the plant decision so that the lead writes the VM-planted rows (decisions 2026-11-02), the lead began piece 1. That was only reading: the M10 test-plan rows, `e2e/runner_client_m10.py`, `e2e/runner_unit_m10.sh`, `spawn_linux.go`, `e2e/m6/e2e_vms.py` and `postinst`. A safety classifier then stopped the lead's response. No file was written, no VM was started, restored or reached, and nothing ran in WSL. As agreed with the user, the work stopped there and was not retried or reworded.
3. **Third and fourth classifier stops (lead, 2026-11-02, evening).** The user asked for recommended sandbox row checks and VM plant checks, then asked the lead to run the runbook walk and G79 while the user writes those checks. A safety classifier stopped both of the lead's responses. Nothing was written or run, and no VM was touched. Not retried; the user was told.
4. **Build attempt 1:** rc 126; `build-deb.sh` isn't executable in git, so it's now run with `bash`. **Attempt 2:** `x509: certificate signed by unknown authority` from proxy.golang.org inside the container (Zscaler TLS inspection). Fixed by the user's instruction ("fix the container trust issues") with the read-only CA-bundle mount above. Attempt 3 succeeded.

## Open decisions (user)

None open. Decided 2026-11-03 (`work/decisions.md`): `/dev/shm` and `/tmp` exec fixed in the runner unit; cramfs sample rewritten; stand-in VMs count for G76; plants 333 and 382 expected not red.


- ~~VM-planted rows~~: decided 2026-11-02. A person on the user's team writes the plants and their row checks, and the lead runs them on the VMs (`work/decisions.md`). The 2026-11-01 rule stands.
- ~~The portproxy move~~: done by the user, 2026-11-02 18:15 local (see "Resume here").
