# Operate the Bitscan manager: upgrade, certificates, backups, removal, retention, releases

This runbook covers a manager installed with `manager-install.md`: the venv `/opt/bitscan-manager`, the units in `/etc/systemd/system/`, `/etc/bitscan/manager.env` and `/etc/bitscan/secrets/`. Run every command as an administrator with `sudo`. As at install time, never put a password, token or DSN on a command line or in an environment variable. Create secret files empty with mode 0600 first, then write them with `sudoedit`.

## 1. Upgrade

**Order:** manager first (migrate, then restart), then the agents. Never upgrade agents before the manager. Hosts whose agent is one version behind keep working while you roll the agents out (see **Compatibility** below).

1. Check the new release files as in `manager-install.md` section 2: the wheel, the requirements file and the four unit files, against `SHA256SUMS` copied from the release page.
2. Stop the manager, so it never runs with half-installed code, then install the new dependencies and the new wheel (for example 0.1.1). The manager is unavailable from this stop until the start in step 4. Agents back off and retry meanwhile, and users can't sign in.

   ```sh
   sudo systemctl stop bitscan-manager
   sudo /opt/bitscan-manager/bin/pip install --require-hashes --only-binary :all: -r bitscan-manager-0.1.1-requirements.txt
   sudo /opt/bitscan-manager/bin/pip install --no-deps --no-index --force-reinstall ./bitscan_manager-0.1.1-py3-none-any.whl
   ```

3. Install the release's unit files. If one changed, the install replaces it unchanged; never edit them or add drop-ins.

   ```sh
   sudo install -o root -g root -m 0644 bitscan-manager.service bitscan-manager-migrate.service \
       bitscan-manager-maintain.service bitscan-manager-maintain.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   ```

4. Migrate the database, then start the manager:

   ```sh
   sudo systemctl start bitscan-manager-migrate
   sudo journalctl -u bitscan-manager-migrate -n 20 --no-pager
   sudo systemctl start bitscan-manager
   ok=no
   for i in 1 2 3 4 5 6 7 8 9 10; do
       if curl -sS --cacert manager-ca.pem https://mgr.example:8443/readyz; then ok=yes; break; fi
       sleep 1
   done
   [ "$ok" = yes ] || echo "readyz: no answer after $i tries; see sudo journalctl -u bitscan-manager" >&2
   ```

   The migration must return without an error, and its log ends with the new head revision id. The manager starts listening a moment after `systemctl start` returns, so the loop tries `curl` up to 10 times, a second apart. `curl` must print `{"status":"ok"}`; a 503 with `migrations` means the migration did not run. Agents keep their tokens: while the manager is down they retry with back-off, and they need no re-enrolment.
5. Upgrade the agents with `agent-install.md` section 6.

**Compatibility:** a manager supports agents of its own version and the one before, and an agent supports a manager of its own version and the one before. For release 0.2.0 (manager `0.2.0`, agent package `0.2.0-1`, git tag `v0.2.0`): manager 0.2.0 supports agents `0.2.0-1` and `0.1.0-1`, and agent `0.2.0-1` supports managers 0.2.0 and 0.1.0. So between step 4 and the end of step 5, hosts still on the previous agent version keep enrolling, sending heartbeats and uploading inventory as before.
- The 0.1.0-1 agent runs no compliance checks. Under a newer manager, every check of its compliance jobs is stored as ERROR `runner_unavailable`, so its hosts show the score `n/a` until their agent is upgraded.
- Manager 0.1.0 has no scans, so it sends a `0.2.0-1` agent no compliance job.
- An agent more than one version behind the new manager is not supported by it. Before step 2, list the agent versions in the fleet (on the database host), and upgrade any such host to at least the version before the new one first:

  ```sh
  sudo -u postgres psql -X -d bitscan -c "SELECT agent_version, count(*) FROM agent WHERE status <> 'decommissioned' GROUP BY agent_version ORDER BY count(*) DESC"
  ```

- Pre-release agent builds (`X.Y.Z~preN-1`, for example `0.2.0~pre2-1`) are not supported by any manager; upgrade them to a release (`0.2.0-1`, `agent-install.md` section 6).

## 2. Replace the TLS certificate

The unit hands the certificate and key to the service as copies that systemd makes when the service starts. A restart makes fresh copies:

```sh
sudo cp new-manager.crt /etc/bitscan/secrets/tls.crt
sudo cp new-manager.key /etc/bitscan/secrets/tls.key
sudo systemctl restart bitscan-manager
```

Copying onto the existing files keeps their owner (`root:root`) and mode 0600. Delete your working copy of the key afterwards. A restart takes a few seconds; agents retry with back-off. If the service doesn't come back (`systemctl is-active bitscan-manager`), `sudo journalctl -u bitscan-manager` names the problem, for example a certificate and key that don't match.

Agents pinned with `bitscan/manager_spki_sha256` accept the new certificate only if it keeps the same key. Renew with the same key where you can. With a new key, every pinned agent stops reaching the manager until its pin is changed to the new key (`agent-install.md` section 7), so plan that change with the certificate replacement.

## 3. Replace the OpenBao token

The manager reads its OpenBao token when it starts, and `bitscan-openbao-renew.timer` keeps the token alive (`manager-install.md` section 5). Replace the token if it may have been exposed, or if it expired because renewal stopped. Until a valid token is in place, sign-in for users with TOTP answers 503.

1. Note the old token's accessor, which names the token for revocation but grants no access. This works only while the old token is still valid. If curl reports `error: 403` and the block prints `no accessor: the old token is no longer valid`, the token has already expired or been revoked, and there is nothing to revoke:

   ```sh
   bao_url="$(sudo sed -n 's/^BITSCAN_VAULT_ADDR=//p' /etc/bitscan/manager.env)"
   sudo sed -n '1s/^/X-Vault-Token: /p' /etc/bitscan/secrets/vault.token |
       curl -sS --fail -H @- --data '{}' "${bao_url%/}/v1/auth/token/renew-self" |
       python3.12 -I -c 'import json, sys; d = sys.stdin.read(); print(json.loads(d)["auth"]["accessor"] if d else "no accessor: the old token is no longer valid")'
   ```

   If the old token may have been exposed, revoke it now (step 4) rather than after the new token is in place.
2. As an OpenBao admin, create the new token from the same role and write it over the old one, as in `manager-install.md` section 5 (or paste it with `sudoedit /etc/bitscan/secrets/vault.token`):

   ```sh
   bao token create -role=bitscan-manager -policy=bitscan-manager -no-default-policy \
       -display-name=bitscan-manager -field=token | sudo tee /etc/bitscan/secrets/vault.token >/dev/null
   ```

3. Run the token check of `manager-install.md` section 5, then restart the manager and renew once, so both use the new token:

   ```sh
   sudo systemctl restart bitscan-manager
   sudo systemctl start bitscan-openbao-renew.service
   ```

4. Revoke the old token as an OpenBao admin: `bao token revoke -accessor <accessor>`, with the accessor from step 1.

## 4. Backups

The database holds scan output and token hashes, so every backup is encrypted at rest. The examples encrypt to a backup public key with `gpg --encrypt`, so no passphrase is typed on the host; your backup system's own encryption works the same way.

**Nightly dump** (schedule it with your backup system):

```sh
sudo install -d -o root -g root -m 0700 /var/backups/bitscan
sudo -u postgres pg_dump -Fc bitscan |
    sudo gpg --encrypt --recipient backup@example.org --output "/var/backups/bitscan/bitscan-$(date -u +%F).dump.gpg"
```

The dump is the logical nightly copy, and the monthly restore test below uses it. It restores the database as it was at dump time. WAL can't be replayed onto a dump. Recovery to a point between dumps needs a physical base backup plus the WAL archived since it was taken.

**WAL archiving:** in `/etc/postgresql/16/main/conf.d/bitscan-archive.conf` set

```text
wal_level = replica
archive_mode = on
archive_command = 'test ! -f /var/lib/postgresql/wal-archive/%f && cp %p /var/lib/postgresql/wal-archive/%f'
```

Create `/var/lib/postgresql/wal-archive` on encrypted storage, owned by `postgres` with mode 0700, then restart PostgreSQL (`sudo systemctl restart postgresql`). Copy the archive off the host, encrypted.

**Weekly base backup** (schedule it with your backup system, like the dump). It copies the whole PostgreSQL cluster as `postgres` over the local socket. `-X none` leaves WAL out, so `pg_basebackup` finishes only once the archive holds the WAL the backup needs:

```sh
ts="$(date -u +%Y%m%dT%H%M%SZ)"
sudo -u postgres pg_basebackup -D - -Ft -X none -l "base-$ts" |
    sudo gpg --encrypt --recipient backup@example.org --output "/var/backups/bitscan/base-$ts.tar.gpg"
```

**Archive pruning:** keep at least two base backups. After you delete an older one, drop the WAL that only it needed. Each base backup leaves a `*.backup` file in the archive holding its label. Find the one for the oldest base backup you keep, check with `-n` (prints what would go), then prune:

```sh
sudo grep -rl --include='*.backup' 'LABEL: base-YYYYMMDDTHHMMSSZ' /var/lib/postgresql/wal-archive
sudo -u postgres /usr/lib/postgresql/16/bin/pg_archivecleanup -n /var/lib/postgresql/wal-archive 000000010000000000000042.00000028.backup
sudo -u postgres /usr/lib/postgresql/16/bin/pg_archivecleanup /var/lib/postgresql/wal-archive 000000010000000000000042.00000028.backup
```

Use the file name that `grep` printed, without its folder. Prune the off-host copy of the archive the same way.

**Point-in-time recovery** (outline) replaces the whole cluster with the newest base backup taken before the target time, then replays archived WAL up to that time. Anything written after the target is lost from the database. Audit entries the sink received after the target stay in the sink as history, by design.

1. Stop the manager and PostgreSQL, and move the data folder aside. Restore the base backup into an empty folder (decrypting needs the backup private key, as in the restore test below):

   ```sh
   sudo systemctl stop bitscan-manager bitscan-manager-maintain.timer postgresql
   sudo mv /var/lib/postgresql/16/main /var/lib/postgresql/16/main.before-pitr
   sudo install -d -o postgres -g postgres -m 0700 /var/lib/postgresql/16/main
   sudo gpg --decrypt /var/backups/bitscan/base-YYYYMMDDTHHMMSSZ.tar.gpg | sudo -u postgres tar -C /var/lib/postgresql/16/main -xf -
   ```

2. If the host's archive is gone, copy the off-host archive back to `/var/lib/postgresql/wal-archive`. Write `/etc/postgresql/16/main/conf.d/bitscan-recovery.conf` with the target time in UTC:

   ```text
   restore_command = 'cp /var/lib/postgresql/wal-archive/%f %p'
   recovery_target_time = '2026-10-25 14:30:00+00'
   recovery_target_action = 'promote'
   ```

3. Start recovery:

   ```sh
   sudo -u postgres touch /var/lib/postgresql/16/main/recovery.signal
   sudo systemctl start postgresql
   ```

   `/var/log/postgresql/postgresql-16-main.log` must report that recovery stopped at the target and that the database accepts connections. PostgreSQL removes `recovery.signal` when it promotes.
4. Move the audit id sequence past the audit shipper's cursor. **Don't start the manager until this step is done.** Recovery rolled `audit_log` and its sequence back, but the cursor in `/var/lib/bitscan/audit-queue/state.json` sits outside the database and stays ahead. New entries with ids at or below the cursor would never reach the sink. This reads the cursor and sets the sequence to the higher of the cursor and the highest restored id, so it never moves backwards:

   ```sh
   if sudo test -f /var/lib/bitscan/audit-queue/state.json; then
       cursor="$(sudo python3.12 -I -c 'import json; print(int(json.load(open("/var/lib/bitscan/audit-queue/state.json"))["cursor"]))')"
       printf '%s\n' "SELECT setval('audit_log_audit_id_seq', GREATEST(:'cursor'::bigint, (SELECT max(audit_id) FROM audit_log), 1));" |
           sudo -u postgres psql -X -d bitscan -v ON_ERROR_STOP=1 -v cursor="$cursor"
   else
       echo "no state.json: the shipper starts again from the beginning; nothing to do"
   fi
   ```

   `psql` prints the value it set, and the next audit entry gets the id after it. If `state.json` doesn't exist, the shipper starts again from the beginning, so the block skips the change.
5. Delete `bitscan-recovery.conf`, start `bitscan-manager` and `bitscan-manager-maintain.timer`, and check `/readyz` as in section 1. Take a new base backup at once: recovery starts a new WAL timeline. Delete `main.before-pitr` (it holds the same secrets) once you no longer need it.

**Configuration and secrets** are not in the database dump. Back them up separately, also encrypted:

```sh
sudo tar -C /etc/bitscan -cf - manager.env secrets |
    sudo gpg --encrypt --recipient backup@example.org --output "/var/backups/bitscan/etc-$(date -u +%F).tar.gpg"
```

**Monthly restore test** into a scratch database on the same server:

1. Allow the migrate role into the scratch database: add this line to `/etc/postgresql/16/main/pg_hba.conf` directly **above** the `hostssl bitscan …` line, then `sudo systemctl reload postgresql`:

   ```text
   hostssl    bitscan_restore  bitscan_migrate  127.0.0.1/32   scram-sha-256
   ```

2. Restore the latest dump. `gpg --decrypt` needs the backup private key: import it for the test only and remove it afterwards, or decrypt on the host that holds it and copy the file over SSH. Restore from a file, not from a pipe:

   ```sh
   sudo install -d -o postgres -g postgres -m 0700 /var/lib/postgresql/restore-test
   sudo gpg --decrypt --output /var/lib/postgresql/restore-test/bitscan.dump /var/backups/bitscan/bitscan-YYYY-MM-DD.dump.gpg
   sudo chown postgres:postgres /var/lib/postgresql/restore-test/bitscan.dump
   sudo -u postgres createdb -O bitscan_owner bitscan_restore
   sudo -u postgres pg_restore --exit-on-error -d bitscan_restore /var/lib/postgresql/restore-test/bitscan.dump
   ```

3. Check that the restored schema is at head. Write a migrate DSN for the scratch database into a root-only file (the `migrate.dsn` line with `dbname=bitscan_restore`), and run `db migrate` with it:

   ```sh
   sudo install -o root -g root -m 0600 /dev/null /root/bitscan-restore.dsn
   sudoedit /root/bitscan-restore.dsn
   sudo env BITSCAN_MIGRATE_DSN_FILE=/root/bitscan-restore.dsn bitscan-manager db migrate
   ```

   It must print the same head revision id as the live database's last migration (`sudo journalctl -u bitscan-manager-migrate`), and a second run must change nothing.
4. Clean up: `sudo -u postgres dropdb bitscan_restore`, `sudo rm -rf /var/lib/postgresql/restore-test /root/bitscan-restore.dsn`, remove the `bitscan_restore` line from `pg_hba.conf` and `sudo systemctl reload postgresql`.

If only the policy catalog is damaged, it is rebuilt from the policy folder (`sudo bitscan-manager bits rebuild`), not restored from a backup.

## 5. Remove the manager

**First, before anything is disabled or removed,** stop the manager and check that every audit entry has reached the sink. Stopping can still write audit rows, for example the failed-check flush `serve` writes on `SIGTERM`. The check needs two things:
- no `segment-*.jsonl` file is left in the queue (a segment is deleted once the sink has every entry in it);
- the shipper's `cursor` in `state.json` equals the newest `audit_id` in `audit_log`, so no committed row is still waiting to be read into the queue.

```sh
sudo systemctl stop bitscan-manager bitscan-manager-maintain.timer
segments="$(sudo find /var/lib/bitscan/audit-queue -name 'segment-*.jsonl' | wc -l)"
newest="$(sudo -u postgres psql -X -d bitscan -Atc 'SELECT coalesce(max(audit_id),0) FROM audit_log')"
cursor="$(sudo python3.12 -I -c 'import json, os; p = "/var/lib/bitscan/audit-queue/state.json"; print(int(json.load(open(p))["cursor"]) if os.path.exists(p) else 0)')"
echo "segment files: $segments, newest audit_id: $newest, shipper cursor: $cursor"
if [ "$segments" = 0 ] && [ -n "$newest" ] && [ "$newest" = "$cursor" ]; then echo OK; else echo "not drained"; fi
```

If it prints `not drained`, start the manager (`sudo systemctl start bitscan-manager`), wait a minute, and run the block again. Repeat until it prints `OK`. If it never does, the sink isn't taking entries: see `sudo journalctl -u bitscan-manager`. The queue's own `state.json` and `acked.json` stay, and are expected.

Then disable and remove the service:

```sh
sudo systemctl disable --now bitscan-manager.service bitscan-manager-maintain.timer bitscan-openbao-renew.timer
sudo rm -f /etc/systemd/system/bitscan-manager.service /etc/systemd/system/bitscan-manager-migrate.service \
    /etc/systemd/system/bitscan-manager-maintain.service /etc/systemd/system/bitscan-manager-maintain.timer \
    /etc/systemd/system/bitscan-openbao-renew.service /etc/systemd/system/bitscan-openbao-renew.timer \
    /usr/local/sbin/bitscan-openbao-renew
sudo systemctl daemon-reload
sudo rm -f /usr/bin/bitscan-manager
sudo rm -rf /opt/bitscan-manager
```

The database, `/etc/bitscan/manager.env`, `/etc/bitscan/secrets/` and `/var/lib/bitscan/` stay until you decide to destroy them; keep the backups as your retention rules require. Destroy the data only after the drain check above printed `OK`. Then revoke the manager's OpenBao token, and if you decide to destroy the data:

```sh
sudo -u postgres dropdb bitscan
sudo -u postgres psql -X -c 'DROP ROLE bitscan_app' -c 'DROP ROLE bitscan_retention' -c 'DROP ROLE bitscan_migrate' -c 'DROP ROLE bitscan_owner'
sudo rm -rf /etc/bitscan/secrets /etc/bitscan/manager.env /var/lib/bitscan
sudo deluser --system bitscan-manager
```

Remove the Bitscan lines from `pg_hba.conf` as well. On a host that also runs the agent, keep `/etc/bitscan` itself: it holds the agent's `agent.yaml`.

## 6. Retention

The manager deletes old data itself, in its retention job. Nothing needs to be scheduled for it, and there is no setting or command to run it by hand or to turn it off.

| Data | Deleted when |
| --- | --- |
| A scan, with its jobs, results and re-evaluations, all together | the scan was created more than 400 days ago |
| An inventory job | it finished more than 30 days ago |
| An inventory snapshot | it was collected more than 180 days ago |
| An enrolment request | it was decided more than 90 days ago; pending requests stay |
| A user token (session or API token) | it expired more than 90 days ago, revoked or not |
| An audit log entry | it is more than 3 calendar years old, oldest first, and already queued for the audit sink |
| A package version | no host lists it any more |

Hosts, their OS details and current package lists, enrolment tokens, policies, schedules and settings are never deleted. Whole `scan_result` partitions past retention are dropped separately, by `bitscan-manager-maintain.timer` (`db maintain`); `systemctl list-timers bitscan-manager-maintain.timer` shows its last and next run.

**When:** the first run starts 10 minutes after the manager starts, then one runs at the interval of the `retention` row of `system_schedule` (daily, as the first migration seeds it), read when the manager starts. Every restart begins this again. Runs never overlap. On `systemctl stop` a running run stops at its next batch.

**As which role:** every retention statement runs as the database role `bitscan_retention`, with the DSN in `/etc/bitscan/secrets/retention.dsn` (`manager-install.md` section 5). That role can read every table, delete only from the tables above, and add audit checkpoint entries. The manager doesn't start without that file.

**Batches:** each batch is one transaction: 2 scans, 1,000 inventory jobs or 10,000 rows. A batch that fails is rolled back alone; batches committed before it stay deleted, and the next run continues. Each statement may take at most 5 minutes. On a large database, the scan and inventory-job deletes use the indexes that migration `m0006` adds (on the scan and retry columns of `scan_job`, and on the job column of `scan_result_reeval`).

**Audit log:** each batch of at most 10,000 entries first appends one `audit.checkpoint` entry (actor `system`) with the id and row hash of the last entry it deletes and the number deleted, so the hash chain still verifies from there. The checkpoint goes to the audit sink like every entry. Entries not yet queued for the sink stay, so a sink outage also holds back the audit deletes. The last checkpoints (on the database host):

```sh
sudo -u postgres psql -X -d bitscan -c "SELECT audit_id, at, detail FROM audit_log WHERE action = 'audit.checkpoint' ORDER BY audit_id DESC LIMIT 5"
```

**Logs:** each run writes one JSON line per step to the manager's journal. The lines hold step names, counts and error types, never a deleted row's content. Show recent runs:

```sh
sudo journalctl -u bitscan-manager --since yesterday -o cat --no-pager | grep -E '"message": "retention |"job": "retention"'
```

A completed step looks like this; the steps are `scans`, `inventory_jobs`, `snapshots`, `requests`, `tokens`, `audit` and `packages`, in that order, and `deleted` counts scans for `scans` and rows for the others:

```text
{"time": "2026-11-09T02:10:01.204+00:00", "level": "INFO", "logger": "bitscan_manager.services.retention.task", "message": "retention step done", "request_id": null, "agent_id": null, "job_id": null, "step": "scans", "deleted": 120, "chunks": 2, "skipped": null}
```

What `skipped` and the other lines mean:
- `null`: the step ran.
- `clock_doubt`, on every step, after a `retention refused: clock_doubt` line: the manager's clock and the database's differ by more than 5 minutes, so the run deleted nothing. Fix the time sync of both hosts (`timedatectl`); the next run deletes as usual.
- `future_rows`: the step's table holds a row dated more than a day after now, written while a clock was wrong. That step is skipped while such a row exists; the other steps run. Check the clocks of the manager and database hosts.
- `failed`, after a `retention step failed` line with `exc_type`: the step stopped; the later steps still ran. `QueryCanceled` means a statement hit the 5-minute limit. If a step fails on every run, keep its log lines for the support case.
- `scheduler run failed` with `"job": "retention"`: the run stopped before its steps, for example because the database was unreachable for the clock check. Nothing was deleted; the next interval tries again.

## 7. Release checklist

A release changes the version in a release pull request, tests that exact build, and only then gets its tag. Nothing is published before the tag: the `release` workflow refuses a changelog version holding `~`, and it only drafts a release, which a person publishes. The steps for 0.2.0:

1. Check that nothing planned for the release is still open, including the deferred review of the importer's BIT102 command rules and the CIS control numbers in `bits/samples/`.
2. In a release pull request, set the versions:
   - `deploy/debian/changelog`: a new top entry `bitscan-agent (0.2.0-1)`, dated after the entry below it, describing the release;
   - `manager/pyproject.toml` (`version`) and `manager/bitscan_manager/__init__.py` (`__version__`): `0.2.0`;
   - the runbooks and `README.md`: replace the pre-release notes with the release, and update **Compatibility** in section 1.
3. On that pull request's branch, run the end-to-end workflow by hand and wait for it. It must be green: every row of the nightly chain and of the compatibility rows (this manager with the 0.1.0 agent, this agent with the 0.1.0 manager) is PASS. Read the uploaded report, not only the result:

   ```sh
   gh workflow run e2e.yml --ref <release branch>
   gh run list --workflow e2e.yml --branch <release branch> --limit 1
   ```

4. Run the `release` workflow by hand with version `0.2.0` on the same branch. It checks that the given version, `pyproject.toml` and the changelog agree, builds the agent package twice and checks both builds are identical, builds the manager files and writes the SHA-256 sums, without creating a release.
5. Merge the pull request once it is approved and every check is green.
6. The release owner tags the merge commit and pushes the tag. The `release` workflow then builds the files and creates a draft release:

   ```sh
   git tag -a v0.2.0 -m "Bitscan 0.2.0" <merge commit>
   git push origin v0.2.0
   ```

7. Check the draft (the files, and the `SHA256SUMS` text in its notes), then publish it.

## 8. Known limits

**Results CSV memory.** The manager builds a scan's results CSV (`GET /scans/{id}/results.csv`) in full in memory before sending it, and refuses an export of more than 100,000 rows. For operators and admins each row also carries the check's stdout (up to 64 KB) and stderr (up to 16 KB), so at the cap with maximal output one export can need about 8 GB of manager memory, and more while the file is written. A viewer's export has no output columns and stays far smaller.
- Size the manager host's memory for the largest exports your operators and admins will run.
- For big scans, have users narrow the export with the `status` and `agent_id` filters (one result status, or one host at a time) rather than export the whole scan.
