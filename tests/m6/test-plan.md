# M6 test plan (first-release gate)

Owner: tester (`tester-m6`). Written 2026-10-26 from `work/tasks.md` "M6 first-release gate" (acceptance tests of TASK-129 to TASK-137, TP-M6-00 to TP-M6-14, the gate table G1 to G53 and the mutation table CHK-M6-320 to -345), `work/requirements.md` REQ-137 to REQ-149, `work/plans/M6-e2e.md`, `work/m6-vms.md` and `work/decisions.md` rows of 2026-10-26 (overnight rule; VM → manager PASS through the portproxy; **environment ruling**: nothing in WSL binds 8443), before any M6 product file was read. Results go to [report.md](report.md).

`bm/` means `manager/bitscan_manager/`.

## Conventions

- Type: **CODE** = static gate, unit test or script on the tree. **APP** = the real thing running: the built wheel installed and served, the `.deb` installed in a systemd container or VM, a real TLS listener, a real PostgreSQL 16.
- Where: **L** = Windows 11 + Git Bash, worktree `C:\Users\kaiquan.koh\Documents\Bitscan-m6` (ruff, mypy, gofmt, golangci-lint with `GOOS=linux`; never pytest). **W** = WSL2 Ubuntu 24.04 (mirrored networking, systemd, Docker), tester copy `/root/m6t/tree-<label>` (tree copied without `.venv`, `node_modules`, `__pycache__`), venv `/root/m6t/venv` from `pip install --require-hashes -r manager/requirements-dev.txt` plus `pip install --no-deps --no-build-isolation -e manager`, `CI=true`, `BSTEST_RUN_LABEL=m6-<label>`, pytest-xdist with one PostgreSQL 16 container per worker, every run under `timeout`. **W-c** = a throwaway container in W (`m4b-build-u24` for builds and lintian, `m4b-sysd-u22`/`-u24` for maintainer scripts, a fresh systemd `ubuntu:24.04` manager host for TP-M6-03/04/09). **VM** = `bitscan-u2204` / `bitscan-u2404` on Hyper-V, reached by Windows `ssh`/`scp` (Git Bash), never from WSL. **CI** = GitHub Actions (NOT RUN overnight: no push).
- **Network path (environment ruling 2026-10-26):** nothing in W binds TCP 8443 (the Windows portproxy `172.31.0.1:8443 → 127.0.0.1:18443` holds it). The manager, or a test listener, listens on `127.0.0.1:18443` in W, or in a container published `-p 127.0.0.1:18443:8443`. Each VM maps `bitscan-mgr.test` → `172.31.0.1` in `/etc/hosts` and uses `https://bitscan-mgr.test:8443`. The test CA is made per run under `/root/m6t/ca` (never committed); the leaf SAN holds `DNS:bitscan-mgr.test` and `IP:172.31.0.1`. The Default Switch address is re-checked first; if it is not `172.31.0.1`, W0 stops (the portproxy, the firewall rule and the certificate depend on it).
- **Not allowed** (decisions 2026-10-26 (4)): SSH tunnels, port forwards, firewall, portproxy, `.wslconfig` or any admin change. A failed step stops that line of work: record step, address, error and options; message `main`.
- **Planted violations** are made in a throwaway copy (`/root/m6t/mut-<id>` on W, `$TEMP/m6-mut-<id>` on L), image or VM state, never in the tree; the unmodified copy is green first; "red" = non-zero exit **and** the named check fails for the planted reason. Every VM is restored to `clean` afterwards.
- **Results are reported as totals** (`passed/total`, plus failed, errors, skipped). A failing test is re-run alone by node id after the fix, as its own row.
- Rigor (decisions 2026-10-25): TASK-129, 130, 131 (W1), 133, 134, 135 (W2), 136, 137 (W3) are low risk: one run per wave batch, plants only for security rows (the gate keeps its full mutation table). TASK-132 is high risk: every plant, including alias, function-value and dot-import variants, plus G8 and G36.

## Expected values (spec and approved answers)

| Item | Expected | Source |
| --- | --- | --- |
| Manager version | `0.1.0`; wheel `bitscan_manager-0.1.0-py3-none-any.whl`, pure Python | REQ-137; #90 |
| Agent package | `bitscan-agent (0.1.0-1) unstable; urgency=medium` on top of the changelog; `.deb` `bitscan-agent_0.1.0-1_amd64.deb`; `dpkg --compare-versions 0.1.0~pre1-1 lt 0.1.0-1` | REQ-142; #90 |
| Tag | `v0.1.0`; strict `v<major>.<minor>.<patch>`; tag = pyproject = changelog upstream; changelog with `~` refused | REQ-141; #90 |
| Wheel contents | `bitscan_manager/webui/index.html`, every file of the build's `webui/assets/`, every file under `bitscan_manager/db/migrations/`, no `tests/` path | REQ-137 (1) |
| Wheel install | Python 3.12 venv; `manager/requirements.txt` with `--require-hashes --only-binary :all:`; wheel with `--no-deps`; `bitscan-manager --help` lists `serve`, `users …`, `db migrate`, `db maintain` | REQ-137 (2) |
| Served UI | `GET /` body byte-identical to the build's `index.html`; every asset 200; no-UI wheel logs `web ui not built; serving the API only` | REQ-137 (3), (5) |
| Host layout | TS §8.7 L1344–L1345 paths, owners and modes; `manager.env` `root:root` 0600, no secret; `/etc/bitscan/secrets/` `root:root` 0700 with `app.dsn`, `retention.dsn`, `migrate.dsn`, `tls.crt`, `tls.key`, `vault.token`; venv `/opt/bitscan-manager`; `/usr/bin/bitscan-manager` link | REQ-138; plan TASK-133 §2 |
| Units | the four manager unit files byte-identical to TS §8.7; `systemd-analyze verify` prints nothing with the real binary installed | REQ-140 (1), (2) |
| Service | `bitscan-manager` user; CapEff/CapPrm/CapBnd/CapAmb 0; NoNewPrivs 1; writes only `/var/lib/bitscan/bits/uploaded` and `/var/lib/bitscan/audit-queue`; credentials folder exactly `app_dsn`, `retention_dsn`, `tls_cert`, `tls_key`, `vault_token`; `migrate.dsn` unreadable to `bitscan-manager` | REQ-140 (4)–(6) |
| Database | PostgreSQL 16 + `postgresql-16-debversion`; the three roles accepted only with TLS from the manager host; DSNs `host=127.0.0.1 … sslmode=require` (same host); Bootstrap block byte-identical to TS §5.2 L1018–L1033 (fences included) | REQ-138 (3), (4); decisions 2026-10-26 (database CA (a)) |
| Release files | plan TASK-135 §3 list (with TASK-136's two `bitscan-manager-<v>.{python,web}.cdx.json`); `SHA256SUMS` lists every released file once and nothing else; two `.deb` builds byte-identical | REQ-141 (2); plan TASK-135 |
| Workflow | actionlint clean; every `uses:` pinned by 40-hex commit; top-level `contents: read`; only `publish` has `contents: write`; `gh release create … --draft` | REQ-141 (1) |
| Cursors | `/agents` cursor holds only `[agent_id]`, `/agents/{id}/packages` only `[package_id]`; ≤ 512 characters; tampered, foreign-agent, vanished-anchor cursor → 400 `invalid_request`, never 500; order and shapes unchanged; `openapi.json` byte-identical | REQ-143; #89 |
| Lint | forbidigo forbids `fcgi.Serve`, `net.FileConn`, `net.FilePacketConn` in non-test agent code, with a "no listening socket" message; no rule removed or narrowed | REQ-144 |
| Agent on a VM | `bitscan-agent.service` and `bitscan-runner.socket` active; `bitscan-runner.service` and both capread units neither enabled nor active; `agent.yaml` `root:bitscan` 0640, `token` `bitscan:bitscan` 0600, `agent_id` 0644, no `enroll.token`; heartbeat 270–330 s; first inventory within `job_pull_seconds` + 30 s of approval | REQ-146; REQ-148 (6); TS §3.3 |
| Alerts | `detail.alert = true`, sink receives the same `audit_id` within 5 s, `bitscan_alerts_total{kind}` +1 | REQ-147 (5) |
| Idle target | < 0.1 % CPU, < 30 MB RSS; recorded, no gate | TS §3.3 L216; #95 |

## TP-M6-01: Wave 0 network check (REQ-146 (0)) — `e2e/m6/netcheck.sh`, `e2e/m6/tls_listener.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M6-001 | APP | The Default Switch address is `172.31.0.1`; the portproxy listen line `172.31.0.1:8443 → 127.0.0.1:18443` is present (read only) | L |
| CHK-M6-002 | APP | Both VMs: restore `clean`, start, IP from the static MAC (`Get-NetNeighbor`; record both) | L |
| CHK-M6-003 | APP | Tester → VM: SSH from Git Bash; `cloud-init status --wait` `done`; `stat -fc %T /sys/fs/cgroup` `cgroup2fs`; `timedatectl` synchronised; `/etc/os-release` 22.04.x / 24.04.x; no Bitscan package | VM |
| CHK-M6-004 | APP | `scp` a 10 MB random file to each VM; SHA-256 equal on both ends | VM |
| CHK-M6-005 | APP | `bitscan-mgr.test 172.31.0.1` written into each VM's `/etc/hosts`; test CA copied to `/etc/bitscan-netcheck/ca.pem` | VM |
| CHK-M6-006 | APP | Test CA and leaf (SAN `DNS:bitscan-mgr.test`, `IP:172.31.0.1`) made; nothing in W listens on 8443 before the start | W |
| CHK-M6-007 | APP | **Listener A** (TLS, test leaf, fixed body with a run nonce) in W on `127.0.0.1:18443`; from each VM `curl --cacert … https://bitscan-mgr.test:8443/` returns the body (handshake, name check, one GET); also by `https://172.31.0.1:8443/` (IP SAN) | VM + W |
| CHK-M6-008 | APP | **Listener B**: the same listener in a container published `-p 127.0.0.1:18443:8443`; same checks from each VM | VM + W-c |
| CHK-M6-009 | APP | Control: from each VM, TCP to `bitscan-mgr.test:8444` (nothing listening): record "refused" or "timeout" (diagnostic only) | VM |
| CHK-M6-010 | APP | Negative: the VM's curl against listener A with the system CA store only fails verification (proves the CA file is what makes it pass) | VM |
| CHK-M6-011 | APP | From each VM `apt-get update` reaches the Ubuntu archive | VM |
| CHK-M6-012 | APP | Listeners stopped, nothing left on 18443, `/etc/bitscan-netcheck` removed, VMs shut down | L + W |

PASS = 003, 004, 007 or 008, and 011 pass on both VMs. 008 is what the planned environment needs; if only 007 passes, the fallback manager host (`work/plans/M6-e2e.md` §1) needs `main` first.

## TP-M6-02: wheel (TASK-129, REQ-137, G47) — `deploy/tests/test_manager_wheel.sh`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M6-020 | APP | `npm ci --ignore-scripts && npm run build` in `web/`, then `pip wheel --no-deps --no-build-isolation` of `manager/` in the dev-lock venv: exit 0, exactly one file `bitscan_manager-0.1.0-py3-none-any.whl` | W-c (24.04) |
| CHK-M6-021 | CODE | `unzip -l`: `bitscan_manager/webui/index.html` and every file of the build's `webui/assets/` (set equal, same bytes); every file under `bm/db/migrations/` in the tree (set equal); no path under `tests/` or `manager/tests/`; no `__pycache__` | W-c |
| CHK-M6-022 | CODE | Wheel metadata: `Name: bitscan-manager`, `Version: 0.1.0`, tag `py3-none-any`, `Requires-Python` ≥ 3.12, entry point `bitscan-manager` | W-c |
| CHK-M6-023 | APP | Fresh 24.04 venv: `pip install --require-hashes --only-binary :all: -r manager/requirements.txt` exit 0; wheel `--no-deps` exit 0; `pip check` clean; `bitscan-manager --help` lists `serve`, `users`, `db migrate`, `db maintain` | W-c |
| CHK-M6-024 | APP | From that install, against a freshly bootstrapped PostgreSQL 16 (TS §5.2 Bootstrap from the spec): `db migrate` reaches head (= the last migration file's revision); a second run changes nothing | W-c |
| CHK-M6-025 | APP | `serve` (real TLS, test cert): `GET /` body byte-identical to the build's `index.html`, `text/html`; every asset 200 with bytes equal to the build | W-c |
| CHK-M6-026 | CODE | G42 on the `index.html` inside the wheel (no inline script, no `<style>`, no `style=`, no scheme or `//` URL, no `on<event>=`, no `srcdoc=`) | W-c |
| CHK-M6-027 | APP | A wheel built without a UI build installs; `serve` logs `web ui not built; serving the API only`; `/` answers 404 problem+json | W-c |

## TP-M6-03: manager install walk and REQ-140 (TASK-133, REQ-138, REQ-140, G48) — `e2e/m6/manager-host.Dockerfile`, `deploy/tests/check_manager_host.sh`, `deploy/tests/check_runbook_bootstrap.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M6-040 | CODE | `check_runbook_bootstrap.py`: the runbook's only ```` ```sql ```` block (fences included) is byte-identical to TS §5.2 L1018–L1033 | L |
| CHK-M6-041 | CODE | No secret on a command line in the runbook: no `PGPASSWORD=` outside a warning, no `--password`, no `password=` on a command, no echoed secret, no token; no task id, REQ, CHK or `#nn` | L |
| CHK-M6-042 | APP | Fresh systemd `ubuntu:24.04` container (privileged, `-p 127.0.0.1:18443:8443`); it can run `LoadCredential=` and `DynamicUser=` (a probe unit); else stop and ask `main` | W-c |
| CHK-M6-043 | APP | Walk §2 release check: `sha256sum -c --ignore-missing SHA256SUMS` OK; a one-byte change fails | W-c |
| CHK-M6-044 | APP | Walk §3 PostgreSQL: packages install; `SHOW ssl` `on`; Bootstrap from the runbook runs once; `\password` at a prompt for the three roles; `pg_hba.conf` lines; `pg_hba_file_rules` no error | W-c |
| CHK-M6-045 | APP | Each of the three roles: `sslmode=disable` over TCP refused; Unix socket refused; `sslmode=require` to `127.0.0.1` accepted | W-c |
| CHK-M6-046 | APP | Walk §4 user and folders: `bitscan-manager` system user, shell `/usr/sbin/nologin`, home `/nonexistent` (absent); folders, owners, modes = TS §8.7 L1344–L1345 | W-c |
| CHK-M6-047 | APP | Walk §5: `/etc/bitscan` 0755, `secrets/` `root:root` 0700, `manager.env` `root:root` 0600 with no secret, the six secret files 0600 created before content | W-c |
| CHK-M6-048 | APP | Walk §6: venv `/opt/bitscan-manager` from the hashed lock and the wheel; `/usr/bin/bitscan-manager` link; `--help`; no group/other-writable file in the venv | W-c |
| CHK-M6-049 | APP | Walk §7–§8: units installed unchanged; `systemd-analyze verify` prints nothing (exit 0); `start bitscan-manager-migrate` exit 0, second start changes nothing; `bitscan-manager-maintain.service` exit 0; the timer enabled with `OnCalendar=daily` | W-c |
| CHK-M6-050 | APP | Walk §9: `bitscan-manager.service` active as `bitscan-manager`; `/readyz` 200 `{"status":"ok"}` (OpenBao and sink: test doubles, recorded as such) | W-c |
| CHK-M6-051 | APP | Walk §10: `sudo bitscan-manager users create-admin` (password at the prompt); sign-in; TOTP enrolment gives a TOTP-verified session | W-c |
| CHK-M6-052 | APP | Walk §11 install check, as written, gives the expected results | W-c |
| CHK-M6-053 | APP | REQ-140 (1): the four installed unit files `cmp` equal to TS §8.7 (`check_units_verbatim.py`) | W-c |
| CHK-M6-054 | APP | REQ-140 (4): CapEff, CapPrm, CapBnd, CapAmb 0, NoNewPrivs 1 for the service's main PID | W-c |
| CHK-M6-055 | APP | REQ-140 (5): write sweep (file tree snapshot before and after a session of API and agent calls) finds changes only under `/var/lib/bitscan/bits/uploaded`, `/var/lib/bitscan/audit-queue` and systemd runtime folders | W-c |
| CHK-M6-056 | APP | REQ-140 (6): `sudo -u bitscan-manager cat /etc/bitscan/secrets/migrate.dsn` denied; the service's credentials folder holds exactly `app_dsn`, `retention_dsn`, `tls_cert`, `tls_key`, `vault_token` | W-c |
| CHK-M6-057 | APP | The server CLI runs as root with `/etc/bitscan/secrets/app.dsn` | W-c |
| CHK-M6-058 | APP | Canary: the manager journal holds no `bsu_`, `bsk_`, `bsa_`, `bse_` token, no DSN password, no key text | W-c |

## TP-M6-04: operations walk (TASK-134, REQ-139) — evidence only

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M6-080 | APP | Upgrade section with the same wheel: migrate unit exit 0, head unchanged; service restarts (new PID); `/readyz` 200; an enrolled agent (G41-style systemd container) keeps heartbeating without re-enrolment | W-c |
| CHK-M6-081 | APP | **#96 fact check:** new `tls.crt`/`tls.key` written, `systemctl reload bitscan-manager`: record whether a new TLS connection presents the new certificate, with the PID and the credential copy hashes before and after | W-c |
| CHK-M6-082 | APP | Certificate step as written in the runbook: a new connection presents the new certificate | W-c |
| CHK-M6-083 | APP | OpenBao token replacement as written (with the fake): service restarts and `/readyz` 200 | W-c |
| CHK-M6-084 | APP | Backup as written (`pg_dump -Fc`, encrypted), restore test as written into a scratch database; `db migrate` reports the same head; second run changes nothing | W-c |
| CHK-M6-085 | APP | Removal section as written leaves data unless destroyed; `/etc/bitscan` kept when the agent is installed | W-c |
| CHK-M6-086 | CODE | No secret on a command line, no task id or process note | L |

## TP-M6-05: agent 0.1.0-1 package (TASK-130, REQ-142, G37–G40)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M6-100 | CODE | `check_debian_meta.py` (VERSION_RE accepts `0.1.0-1`, #90): all checks pass on the tree | L |
| CHK-M6-101 | APP | `build-deb.sh` gives `bitscan-agent_0.1.0-1_amd64.deb`; `go version -m` shows `-X main.version=0.1.0-1` | W-c |
| CHK-M6-102 | APP | G37 lintian `--fail-on error,warning`: clean; every override used (no `unused-override`, no `initial-upload-closes-no-bugs` emitted) | W-c |
| CHK-M6-103 | APP | G38 install, reinstall, upgrade, purge twice each on 22.04 and 24.04 | W-c |
| CHK-M6-104 | APP | G38 upgrade `0.1.0~pre1-1` → `0.1.0-1`: `agent_id`, `token`, `agent.yaml` byte-identical | W-c |
| CHK-M6-105 | APP | G39 two builds byte-identical; G40 SBOM complete | W-c |
| CHK-M6-106 | CODE | `dpkg --compare-versions 0.1.0~pre1-1 lt 0.1.0-1` | W |
| CHK-M6-107 | CODE | Runbook text: 0.1.0 status, `runner_unavailable`, `SHA256SUMS` from the release page, upgrade order, compatibility; no secret, task id or process note (walked on a VM in TP-M6-10) | L |
| CHK-M6-108 | APP | The installed agent's start line reports `0.1.0-1` (G41 run) | W-c |

## TP-M6-06: release workflow (TASK-135, TASK-136, REQ-141, G49) — `deploy/tests/check_release_workflow.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M6-110 | CODE | actionlint clean on `release.yml` | W |
| CHK-M6-111 | CODE | Every `uses:` pinned by a 40-hex commit; top-level `contents: read`; only `publish` has `contents: write`; `--draft`; `publish` only on a tag push; no `${{` inside `run:` | L |
| CHK-M6-112 | APP | The build jobs' commands run locally on the M6 head in Ubuntu 24.04: the final folder equals plan TASK-135 §3 (with the two manager SBOMs); `sha256sum -c SHA256SUMS` passes and lists every file once; the two `.deb` builds identical | W-c |
| CHK-M6-113 | APP | The `versions` step: `v0.1.0` + `0.1.0-1` + pyproject 0.1.0 OK; `v0.1.1` refused; changelog `0.1.1-1` refused; `~` refused; `v0.1.0-rc1` refused | W |
| CHK-M6-114 | APP | The wheel check refuses a wheel without `webui/index.html` and one without assets | W |
| CHK-M6-115 | APP | `SHA256SUMS` check refuses a file changed after the sums are written, a file missing from the sums, an extra listed file | W |
| CHK-M6-116 | APP | TASK-136: the Python SBOM lists every `requirements.txt` package with version and every hash; the web SBOM lists react, react-dom, scheduler, openapi-fetch, openapi-typescript-helpers, qrcode-generator as `required` with their versions; both in `SHA256SUMS` | W-c |
| CHK-M6-117 | APP | TASK-136 completeness check: red on a dropped Python package, a dropped hash, a dropped web runtime package | W |
| CHK-M6-118 | CODE | REQ-141 (5): GitHub run and publication NOT RUN (no push authorised) | — |

## TP-M6-07: cursors (TASK-131, REQ-143, G53) — `manager/tests/test_agent_cursors_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M6-120 | APP | `/agents` with a 255-character non-ASCII hostname on each page boundary: N + 1 items with `limit=N` (several N incl. 1) appear once each, in (hostname, agent_id) order | W |
| CHK-M6-121 | APP | `/agents/{id}/packages` with a 255-character non-ASCII package name on each boundary, plus `1.0`/`1.0-0` and multi-arch: every item once, in the M3 order (name, Debian version, version text, architecture) | W |
| CHK-M6-122 | APP | Every returned cursor ≤ 512 characters; the decoded payload is `[agent_id]` / `[package_id]` only (no hostname, no package text) | W |
| CHK-M6-123 | APP | 400 `invalid_request` (problem+json, never 500) for: a tampered cursor, a cursor of another route, a package cursor of another agent, a vanished package anchor (row deleted as `bitscan_retention`/owner), an `/agents` cursor naming a missing agent, non-UUID and non-int payloads, booleans, negative and over-range ids | W |
| CHK-M6-124 | APP | The M3 and M5 suites for both routes pass (changed only where they inspect cursor content) | W |
| CHK-M6-125 | CODE | G6: `manager/openapi.json` byte-identical | L |
| CHK-M6-126 | CODE | G1 (ruff S608) clean on the changed repositories; `mypy --strict manager` clean after the four old-tuple test calls move to ids | L |

## TP-M6-08: agent lint (TASK-132, REQ-144, G8, G36) — evidence only (full rigor)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M6-140 | CODE | G7 gofmt and G8 `golangci-lint run ./...` (Linux) clean on the tree; nolint grep prints nothing | W |
| CHK-M6-141 | CODE | Each of `fcgi.Serve`, `net.FileConn`, `net.FilePacketConn` planted in a non-test file under `agent/internal/agent/`: red with its configured message (CHK-M6-337..339) | W |
| CHK-M6-142 | CODE | Variants: aliased import, function value, dot import, method value through a variable, in a file under each other agent package (`cmd/bitscan-agent`, `internal/spool`, `internal/inventory`): red | W |
| CHK-M6-143 | CODE | Controls: the same calls in a `_test.go` are lifted; `InsecureSkipVerify` in a `_test.go` stays red | W |
| CHK-M6-144 | CODE | No existing rule removed or narrowed (diff of `.golangci.yml` against `main`; every old forbidigo rule still red on its M0/M4 plant) | W |
| CHK-M6-145 | APP | G36 agent security subset and G35 contract pass (`go test -race` on the security packages) | W |

## TP-M6-09: README walk (TASK-137, REQ-145) — evidence only

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M6-150 | CODE | Every link and anchor in the changed sections resolves; cited runbook section numbers match their headings | L |
| CHK-M6-151 | APP | Each changed step behaves as written on the TP-M6-03 host | W-c |
| CHK-M6-152 | CODE | No statement contradicts a runbook or the spec (versions, file list, compatibility, upgrade order, certificate); the removed lines are gone | L |
| CHK-M6-153 | CODE | No secret, task id or process note | L |

## TASK-138: `RemoveOnStop=yes` in the capread socket unit (user decision 2026-10-26, a deviation from the verbatim TS §3.7 unit; high risk, full rigor) — `deploy/tests/check_units_verbatim.py`

Added 2026-10-26 by tester-m6d from the acceptance in the decisions rows (TASK-138, user decision; lead rulings (1)–(5)) and the rows tester-m6c already ran; results in [report.md](report.md) (CHK-M6-160..167) and the VM row CHK-M6-261-r.

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M6-160 | CODE | `check_units_verbatim.py all` (and `agent`, `manager`) on the tree: a `DEVIATIONS` table with exactly one entry, `bitscan-capread.socket` = its TS §3.7 block plus `RemoveOnStop=yes` right after `SocketMode=0660`; every other unit and the D-Bus policy byte-identical to TS | L + W |
| CHK-M6-161 | CODE | Plants in throwaway copies, each red at the planted line: a second extra line, a line in `[Install]`, the line moved, the line removed (back to verbatim TS), `RemoveOnStop=no`, another line changed, the line in another unit, a duplicate, a trailing space, CRLF; spec-side guards: the anchor gone from a TS copy, and TS already holding the line, both stop | L |
| CHK-M6-162 | APP | `systemd-analyze verify` of every unit (24.04, systemd 255) and the 5 agent units installed with the binaries (22.04, systemd 249) prints nothing about our units; a verify plant `RemoveOnStop=maybe` is flagged on both | W-c |
| CHK-M6-163 | APP | The new RC: two `build-deb.sh` builds at different paths are byte-identical (the `.deb`, its `.sha256`, 3 SBOMs); `test_build_deb.sh repro`; `dpkg-deb -R` + `diff -r` against the old RC shows only the added line and its `md5sums` line; the new SHA-256 recorded (lead ruling (2)) | W-c |
| CHK-M6-164 | APP | G37: `test_build_deb.sh … lintian` and raw `lintian --pedantic`: no E/W/P tag, no unused or mismatched override | W-c |
| CHK-M6-165 | APP | G38: `test_maintainer_scripts.sh all upgradefrom` on 22.04 and 24.04 with the new RC (pre1 → 0.1.0-1 included); the capread units are still neither enabled nor active after install | W-c |
| CHK-M6-166 | APP | Runtime on 22.04 and 24.04: `enable --now` creates `/run/bitscan/capread.sock` (root:bitscan-runner 0660); `disable --now` and `stop` remove it; control: the old RC keeps the file (the CHK-M6-261 defect) | W-c |
| CHK-M6-167 | CODE | `git diff` of `deploy/systemd` and `deploy/debian/rules`: one line added in the capread socket (LF), comment-only edits in `rules`; no other unit changed; every other consumer of the unit text found and covered | L |
| CHK-M6-261-r | APP | On a VM with the new RC: enable gives `runner_helpers` `["capread"]` and one `runner_helper_changed` entry; `disable --now` gives `[]`, a second entry, and the socket file is gone; both entries reach the sink, counter +2 (TS §3.7 L484) | VM + W |

## TP-M6-10 to TP-M6-13: end-to-end on the VMs (W4; needs W0 PASS and TASK-129, 130, 133 TEST PASS) — `e2e/m6/e2e_vms.py`, `e2e/m6/vm.sh`, `e2e/m6/idle_cost.sh`

| Check | Type | What (REQ) | Where |
| --- | --- | --- | --- |
| CHK-M6-200 | APP | REQ-146 (0): W0 quick re-check after the IP lookup | VM |
| CHK-M6-201 | APP | (1) release, `cgroup2fs`, synchronised clock, no Bitscan package | VM |
| CHK-M6-202 | APP | (2) `sha256sum -c` RC `.deb` OK; one-byte change fails | VM |
| CHK-M6-203 | APP | (3) preseeded install (u2204 `ca_file`; u2404 + pin) exit 0, preseed deleted, unit states | VM |
| CHK-M6-204 | APP | (4) held request fields; `awaiting_approval`; no `os_info` | VM + W |
| CHK-M6-205 | APP | (5) approve 200 (TOTP session), `online` ≤ 330 s, three heartbeats 270–330 s apart | VM + W |
| CHK-M6-206 | APP | (6) first inventory timing; `os_info` and packages equal the VM | VM + W |
| CHK-M6-207 | APP | (7) package search rows, `os`, `group_by=host`, `version_op` vs `dpkg --compare-versions`, CSV = JSON | VM + W |
| CHK-M6-208 | APP | (8) `apt-get install` → one unscheduled upload in 60–120 s; search returns only that VM | VM + W |
| CHK-M6-209 | APP | (9) revoke 204 → 401 on the next call (manager access log), one re-enrol journal line counted from the revoke on, no call for 10 min (counted by request path `/api/v1/agent/<id>/…`, not by the access log's `agent_id` field, which a refused call never carries; the first refused call is the control that the count sees refused calls), `ActiveState` active and `NRestarts` 0, each read by property name (`systemctl show -p ActiveState -p NRestarts`; with `--value` systemd prints the values in its own order) | VM + W |
| CHK-M6-210 | APP | (10) purge removes the agent's files, units, binaries; no process | VM |
| CHK-M6-211 | APP | (11) `stale` 10 min after the last heartbeat | W |
| CHK-M6-212 | APP | (12) VMs restored to `clean` | L |
| CHK-M6-213 | APP | REQ-142 (4): the changed agent runbook sections behave as written on the VMs | VM |
| CHK-M6-260 | APP | REQ-147 (1) clock skew | VM + W |
| CHK-M6-261 | APP | REQ-147 (2) runner helper | VM + W |
| CHK-M6-262 | APP | REQ-147 (3) machine-id mismatch and re-enrolment: a new machine-id gives one `machine_id_mismatch` entry and `token_revoked_at` set; after the runbook §7 re-enrolment the held request has `kind` = `reenrol` and `agent_id` = the existing agent's id (TS §3.2: a held re-enrolment returns the existing `agent_id`); `matches` lists only *other* agents sharing the hostname or machine-id (TS §3.2 L192, cloned images), so the agent itself is never in it; approve gives the same `agent_id`, `online`, one `reenrolment_approved` entry | VM + W |
| CHK-M6-263 | APP | REQ-147 (4) stale inventory, (4a) agents offline | VM + W |
| CHK-M6-264 | APP | REQ-147 (5) every alert: `detail.alert`, sink ≤ 5 s, `bitscan_alerts_total` +1 | W |
| CHK-M6-265 | APP | REQ-147 (6) metrics by status; (7) no alert in phase A | W |
| CHK-M6-280 | APP | REQ-148 (1) wrong pin on u2404 | VM + W |
| CHK-M6-281 | APP | REQ-148 (2) wrong CA on u2204 | VM + W |
| CHK-M6-282 | APP | REQ-148 (3) tokens on the wrong route group → 401 | W |
| CHK-M6-283 | APP | REQ-148 (4) admin `bsk_` on approve and revoke → 403 `totp_session_required` | W |
| CHK-M6-284 | APP | REQ-148 (5) no listening socket, no capabilities, writes only `/var/lib/bitscan-agent` | VM |
| CHK-M6-285 | APP | REQ-148 (6) file modes (whole lines); debconf empty; token in no file under `/var/cache/debconf` or `/etc`, searched with `grep -rlFf <token file>` so the token is on no command line (sudo logs every command line to the journal); a missing token file is a FAIL, and a control count (the token file itself) must be ≥ 1 | VM |
| CHK-M6-286 | APP | REQ-148 (7) canary sweep: each VM's whole journal (`journalctl -o json`, every field) has no token-shaped string (`bs[uaek]_` + ≥ 20) and no exact value of any `bsa_` the host held, read from root-only copies, never on a command line; the count inside the agent units is reported apart; a fake control line logged with `logger -f` must be found; the manager journal (every field) and the sink have none. Evidence masked to prefix and length (`e2e/m6/tokscan_vm.py`) | VM + W |
| CHK-M6-300 | APP | REQ-149 idle cost on u2404 (recorded, no gate) | VM |

## TP-M6-14: the gate (G-rows CHK-M6-310 onwards)

| Check | Gate |
| --- | --- |
| CHK-M6-310 | G1–G4 ruff, format, `mypy --strict`, hashed locks |
| CHK-M6-311 | G5 services coverage ≥ 85 % (Linux) |
| CHK-M6-312 | G6 OpenAPI byte-identical |
| CHK-M6-313 | G7–G11 Go gates |
| CHK-M6-314 | G17 units verbatim + `systemd-analyze verify` (manager units with the real binary) |
| CHK-M6-315 | G18 full manager suite, 0 skipped |
| CHK-M6-316 | G35, G36 |
| CHK-M6-317 | G37–G40 on 0.1.0-1 |
| CHK-M6-318 | G41 `e2e/agent_manager.sh` on the 0.1.0-1 `.deb` |
| CHK-M6-319 | The RC `.deb` tested on the VMs has the SHA-256 of the release build |

G47 = TP-M6-02, G48 = TP-M6-03, G49 = TP-M6-06, G50–G52 = TP-M6-10..12, G53 = TP-M6-07.

## Mutation table (CHK-M6-320 to -345)

As `work/tasks.md` "M6 mutation table". W1–W3 plants run for security rows only (TASK-131 333–336, TASK-132 337–339, TASK-133 323–326, TASK-135 327–331, TASK-136 332); the wheel rows 320–322 and the real-host rows 340–345 run at the gate.
