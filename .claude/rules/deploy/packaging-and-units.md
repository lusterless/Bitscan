---
paths:
  - "deploy/**"
  - "**/*.service"
  - "**/*.socket"
  - "**/*.timer"
---

# Packaging, systemd units and manager deployment

Spec: TS §3.1 (agent package), §3.7 (agent units and the D-Bus policy), §8.6 (configuration) and §8.7 (manager deployment). Copy the units from the spec verbatim (`deploy/systemd/`; D-Bus policy in `deploy/dbus/`; debconf templates and maintainer scripts in `deploy/debian/`), with one recorded exception: `bitscan-capread.socket` adds `RemoveOnStop=yes` (user decision 2026-10-26, TASK-138; `deploy/tests/check_units_verbatim.py` allows exactly that line).

. Any change must still pass `systemd-analyze verify` as written (TS §8.3).

## systemd unit syntax

- `#` is a comment only at the start of a line. Put every comment on its own line; never put a comment at the end of a directive line.
- Optional paths take a `-` prefix, for example `ExecPaths=/usr /bin /sbin /lib -/lib64`, because arm64 has no `/lib64`.
- `ProtectControlGroups=` stays unset on the runner: it would make the cgroup tree read-only and stop the runner killing plugin cgroups (TS §3.7). `PrivateNetwork=` also stays unset: `ss` and `ip` must see the host network (reachable abstract Unix sockets are accepted).
- `NoExecPaths=`, `ExecPaths=` and `PrivateIPC=` need systemd 248+, which every supported release has.

## Security-critical directives (values exactly as TS §3.7 / §8.7; check they survive every edit)

- `bitscan-runner.service`: `User=`/`Group=bitscan-runner`; `AmbientCapabilities=` and `CapabilityBoundingSet=CAP_DAC_READ_SEARCH` only; `NoNewPrivileges=yes`; `Delegate=yes`; `ProtectSystem=strict` with `PrivateTmp=yes` and `ReadOnlyPaths=/dev/shm`; `NoExecPaths=/ /tmp /var/tmp` with `ExecPaths=/usr /bin /sbin /lib -/lib64`; `ProtectHome=read-only` (not `yes`); `SystemCallArchitectures=native`, `SystemCallFilter=@system-service` then `SystemCallFilter=~@debug @mount @module @raw-io @reboot @swap @obsolete @cpu-emulation` (`~@debug` blocks `ptrace` and `process_vm_readv`), `SystemCallErrorNumber=EPERM`; `RestrictAddressFamilies=AF_UNIX AF_NETLINK`; `IPAddressDeny=any`; `InaccessiblePaths=` for the Docker, containerd, snapd and journald sockets, each `-`-prefixed; `MemoryMax=256M`, `TasksMax=64`, `CPUQuota=25%`.
- `bitscan-runner.socket`: `ListenStream=/run/bitscan/runner.sock`, `SocketUser=root`, `SocketGroup=bitscan`, `SocketMode=0660`, `DirectoryMode=0755`.
- `bitscan-agent.service`: `User=`/`Group=bitscan`, `NoNewPrivileges=yes`, empty `CapabilityBoundingSet=`, `ProtectSystem=strict` with `ReadWritePaths=/var/lib/bitscan-agent` only.
- `bitscan-capread.socket`: `ListenStream=/run/bitscan/capread.sock`, `SocketUser=root`, `SocketGroup=bitscan-runner`, `SocketMode=0660`, then `RemoveOnStop=yes` (the TASK-138 deviation from TS §3.7: systemd deletes the socket file on stop, so the heartbeat reports `[]` after the helper is disabled). Keep it, and add nothing else. `bitscan-capread.service`: `DynamicUser=yes`; ambient and bounding capabilities exactly `CAP_NET_ADMIN CAP_AUDIT_CONTROL`; `RestrictAddressFamilies=AF_UNIX AF_NETLINK`; `IPAddressDeny=any`. It has no `[Install]` section and no `UMask=` or `SystemCallErrorNumber=`; copy it verbatim and add nothing (TS §3.7).
- D-Bus policy `/etc/dbus-1/system.d/bitscan-runner.conf`, verbatim: for user `bitscan-runner`, `<deny send_type="method_call"/>`, then allow only `org.freedesktop.DBus`, Properties `Get`/`GetAll`, `Introspectable`, and the systemd1 Manager methods `GetUnit`, `LoadUnit`, `GetUnitFileState`, `ListUnits`, `ListUnitFiles`, `ListUnitFilesByPatterns`, `ListUnitsByPatterns`, `ListUnitsFiltered` and `GetUnitByPID`.
- `bitscan-manager.service`: `User=`/`Group=bitscan-manager`, `NoNewPrivileges=yes`, empty `CapabilityBoundingSet=`, `ProtectSystem=strict` with `ReadWritePaths=/var/lib/bitscan/bits/uploaded /var/lib/bitscan/audit-queue` only, `ExecReload=/bin/kill -HUP $MAINPID`. The remaining hardening, the migrate and maintain units and the timer (`OnCalendar=daily`, `Persistent=true`) are verbatim TS §8.7.

## Agent `.deb`

- One package per architecture, `bitscan-agent_<version>_<arch>.deb` for amd64 and arm64. It contains `/usr/sbin/bitscan-agent`, `/usr/sbin/bitscan-runner` and `/usr/sbin/bitscan-capread`, the units (`bitscan-agent.service`, `bitscan-runner.socket`, `bitscan-runner.service`, `bitscan-capread.socket`, `bitscan-capread.service`), and `/etc/dbus-1/system.d/bitscan-runner.conf`.
- `dh_installsystemd`:
  - `--no-enable` for `bitscan-runner.service`, which its socket starts;
  - `--no-enable --no-start` for both capread units.
- Install inputs come from debconf (preseedable: `bitscan/manager_url`, `bitscan/enrol_token`, optional `bitscan/ca_file` and `bitscan/manager_spki_sha256`) or a root-only `/etc/bitscan/install.env` (0600), which `postinst` deletes. Never from command-line environment variables.
- `bitscan/enrol_token` is a `password`-type debconf question; `postinst` clears it after use (`db_set bitscan/enrol_token ""`).
- `postinst` on first install:
  1. Creates system users `bitscan` and `bitscan-runner`, with no shell and no home.
  2. Writes `agent.yaml` (`root:bitscan`, 0640) from the inputs.
  3. Writes `enroll.token` (`bitscan:bitscan`, 0600), never into `agent.yaml`.
  4. Enables and starts `bitscan-runner.socket` and `bitscan-agent.service`.

  It fails clearly, leaving the package unconfigured, if the manager URL or enrolment token is missing. On upgrade it needs no inputs, keeps the existing config, token and agent id, and restarts the services. All maintainer scripts must be idempotent and pass `lintian`.
- `apt remove` stops and disables the units. `postrm purge` removes `/etc/bitscan` and `/var/lib/bitscan-agent`. The host then goes `offline` and is decommissioned under TS §3.3 (`decommission_after_days`, default 7; 0 = never). None of the agent endpoints in TS §6.1 deregisters a host (TS §3.1, §3.3, §6.1).
- File ownership (TS §3.7): `/run/bitscan/` `root:root` 0755; `runner.sock` `root:bitscan` 0660; `capread.sock` `root:bitscan-runner` 0660; `/var/lib/bitscan-agent/` `bitscan:bitscan` 0700, with `token` and `enroll.token` 0600 and `agent_id` 0644.
- Each release publishes its SHA-256 on the release page, a different origin from the download host. Builds are reproducible, and each release ships an SBOM. The install runbook follows TS §3.1 (`sha256sum -c`, preseed, `apt install ./…deb`, delete the preseed file) and states the prerequisite that hosts must be NTP-synced (TS §3.3). Hosts cloned from one image share `/etc/machine-id` and enrol as a re-enrolment of the first; the fix is to regenerate `/etc/machine-id` on the clone (TS §3.2 step 9). The runbook recommends pinning with `bitscan/manager_spki_sha256`; for a private manager, set `bitscan/ca_file` to that CA only or pin the key; pinning stays optional (TS §3.2 Transport).

## Manager

- `bitscan-manager.service` runs as `bitscan-manager`, one instance, HTTPS only on `BITSCAN_LISTEN`; `SIGHUP` reloads the TLS certificate. Configuration comes from `/etc/bitscan/manager.env` (`root:root`, 0600). Secrets come from `/etc/bitscan/secrets/` (`root:root`, 0700) via `LoadCredential=`, so each unit reads only what it loads; the manager loads `app_dsn`, `retention_dsn`, `tls_cert`, `tls_key` and `vault_token`, never `migrate_dsn`. `BITSCAN_*_FILE` variables point to `%d/<name>`.
- `bitscan-manager-migrate.service` and `bitscan-manager-maintain.service` (with its daily timer) run as `DynamicUser`, so the manager user can never read the migrate credential. They are the only units that load `migrate_dsn`. The migrate unit is ordered `Before=bitscan-manager.service`. The upgrade runbook starts it first (`systemctl start bitscan-manager-migrate`) (TS §8.7).
- Upgrade order: run migrate, restart the manager, then roll out agents. The manager supports agents of its own version and the one before.
- The server CLI runs as root (`sudo bitscan-manager …`) and reads its DSN from `/etc/bitscan/secrets/app.dsn`.
- Folders:
  - `/var/lib/bitscan/bits/`: `root:bitscan-manager`, 0750;
  - `bits/uploaded/`: `bitscan-manager`, 0750;
  - `/var/lib/bitscan/audit-queue/`: `bitscan-manager`, 0700.
- Database bootstrap: run the TS §5.2 Bootstrap block once as a superuser. It creates the roles and database, makes `bitscan_owner` the owner of the `public` schema, and installs `pg_trgm`, `pgcrypto` and `debversion` (package `postgresql-16-debversion`). PostgreSQL accepts connections only from the manager host, over TLS. Backups follow TS §5.3 (nightly `pg_dump` + WAL archiving, encrypted, restore tested monthly).
- Python dependencies are installed with `pip --require-hashes`.
- **Decided** (`work/open-questions.md` #6, owner-approved): the manager ships as a Python wheel (the built web UI inside) installed into the venv `/opt/bitscan-manager` with `pip --require-hashes`, and `/usr/bin/bitscan-manager` links to its entry point; the install runbook creates the user and folders. `serve` returns the UI's `index.html` at `/` and its build files at `/assets/<file>` from its own origin, without a token, like the health routes.

Tests (TS §8.3): Sandbox (`systemd-analyze verify` as written, plus the plugin-cannot list in `.claude/rules/testing.md`) on every PR touching units; package tests in `deploy/tests/` (TS §3.1: lintian; install, reinstall, upgrade and purge idempotency); reproducible build and SBOM check per release (TS §3.1, §8.1).
