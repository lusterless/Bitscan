# M11 end to end: the nightly chain and the N / N−1 rows

Test harness (tester-owned) for TS §8.3 "End-to-end (nightly, 3 VMs): enrol → approve enrolment → heartbeat → inventory → import → scan → results" (REQ-285), run by `.github/workflows/e2e.yml` (TASK-254, REQ-286). Plan rows: `tests/m11/test-plan.md` CHK-M11-290 to -309 and the plants CHK-M11-370 to -374. Results: `work/reports/M11-e2e-test.md`.

## The three machines (#152 (a))

| Machine | What | Made by |
| --- | --- | --- |
| Runner | a hosted `ubuntu-24.04` runner (CI), or WSL2 for development | the workflow |
| Manager host | systemd container `m11n-mgr` (image `m6b-mgrhost`, `e2e/m6/manager-host.Dockerfile`), installed by `deploy/runbooks/manager-install.md` through `e2e/m6/manager_walk.py`, with M6's OpenBao and HTTPS-sink test doubles (`e2e/m6/doubles.py`, #152 (c)) and the runbook's §1.1 lab CA made fresh each run | `nightly.py` (the walk) |
| Two guests | QEMU/KVM, official Ubuntu 22.04 (`jammy`) and 24.04 (`noble`) cloud images, one fresh overlay each, destroyed afterwards (the stand-in VM form accepted for G76, decisions 2026-11-03 (4)) | `guests.sh` |

The guests reach the manager as `bitscan-mgr.test` → `10.0.2.2:18443`. That is QEMU user networking to the runner, where the manager container publishes `127.0.0.1:18443`. Agents install from `/etc/bitscan/install.env` (agent-install.md §3c) with `CA_FILE`; the 24.04 guest also uses the SPKI pin (#152 (d)). The policy is the SR §1.1 canonical example, extracted byte for byte from `docs/spec/bit_Schema_Reference.md` (#152 (e)). The `bits/samples/` files join only after #111 is answered.

No Hyper-V VM is used by the harness. The user's standing approval for `bitscan-u2204`/`bitscan-u2404` (decisions 2026-11-08 (4)) covers only the nightly workflow's fallback when a runner has no KVM, not development runs.

## Files

- `nightly.py`: the chain, one row per step and host, plus the report check (`--check-report`).
- `guests.sh`: `fetch`, `up`, `ssh`, `put`, `down` for the QEMU guests.
- `compat.py` (TP-M11-19): the N / N−1 rows (manager N with the previous release's agent, the upgrade walk, agent N with the previous release's manager; N−1 = the previous release: v0.3.0 since release 0.4.0).

## Run (root, Linux, Docker, QEMU, /dev/kvm)

```sh
apt-get install -y --no-install-recommends qemu-system-x86 qemu-utils cloud-image-utils
docker build -t m6b-mgrhost -f e2e/m6/manager-host.Dockerfile <context with extra-ca/>
bash e2e/m11/guests.sh fetch /var/tmp/m11-img
python3 -I e2e/m11/nightly.py --tree . --rel REL --deb bitscan-agent_<version>_amd64.deb \
    --images /var/tmp/m11-img --work /var/tmp/m11-run --log /var/tmp/m11-run.log > /var/tmp/m11-run.log 2>&1
python3 -I e2e/m11/nightly.py --check-report /var/tmp/m11-run/report.json
```

- `REL` holds the manager release files that `manager-install.md` §2 lists: the wheel with the web UI, `bitscan-manager-<v>-requirements.txt`, the four units, and `SHA256SUMS`.
- The `.deb` needs its `.sha256` file beside it, as the build writes it.
- `--guest-mem` is in MB (default 1024).
- `--keep` keeps the guests and the container.
- `--expect-red CHK-M11-302` is for the plants: the run then passes only when that row is FAIL.

In WSL, run everything inside one `wsl.exe --exec` call: WSL ends the distro, and with it Docker's containers, about a minute after the last `wsl.exe` client exits. Behind a TLS-inspecting proxy, mount the host's CA bundle read-only into any build container. The walk's `/etc/pip.conf` already allows slow PyPI reads.

## Rows and the report

`WORK/report.json` holds `expected` (every `[check, host]` a complete run has) and `rows` (`chk`, `host`, `step`, `status` PASS / FAIL / NOT RUN, `evidence`, `reason`). `WORK/report.md` has the same as a table. A step whose input is missing is NOT RUN with the reason, never skipped silently: for example, after a failed pre-check (no `/dev/kvm`) every later row is NOT RUN. `--check-report` exits 1 when any row is FAIL or an expected row is missing; the workflow fails on that.

## Secrets

The admin session, its TOTP seed, the viewer's `bsk_` and the `bse_` tokens stay in memory or in 0600 files under `WORK/secrets`, which is deleted at the end. A `bse_` reaches the guest's root-only `install.env` through ssh's standard input, never a command line. Every saved or printed text is masked for `bs[uaek]_` and for each secret value. Row CHK-M11-303 sweeps the report, the logs and all three journals for those values and for the token pattern.
