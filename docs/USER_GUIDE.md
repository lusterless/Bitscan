# Bitscan user guide

How to use Bitscan, and how to write `.bit` policy files. For installation steps, see the runbooks this guide links to; for the full rules, see the specifications in `docs/spec/`.

> **Version:** written for the M10 build (agent `0.2.0~pre1-1`), November 2026. Features marked **(M11)** are specified but not built yet: the results views, results CSV and re-evaluation.

### Web UI or API: what is where today

| Task | Web UI screen | API / CLI |
| --- | --- | --- |
| Sign in, change password, set up TOTP | Sign-in, **Password**, **TOTP** | `POST /auth/login`, `/auth/password`, `/auth/totp/enrol` |
| Hosts and host detail | **Hosts** | `GET /agents`, `/agents/{id}` |
| Package search (+ CSV) | **Package search** | `GET /packages/search`, `/packages/search.csv` |
| Profiles: view, enable/disable, delete | **Profiles** | `GET/PATCH/DELETE /policies/{id}` |
| Upload a policy | **Upload policy** | `POST /policies/import` |
| Import history | **Import history** | `GET /imports` |
| Rebuild the catalog | **Rebuild catalog** | `POST /policies/rebuild`, `sudo bitscan-manager bits rebuild` |
| Enrolment tokens and requests | **Enrolment tokens**, **Enrolment requests** | `/enrollment-tokens`, `/enrollment-requests` |
| Set host tags, revoke a host | (not in the UI yet) | `PUT /agents/{id}/tags`, `POST /agents/{id}/revoke` |
| Start / cancel a scan, schedules | (not in the UI yet) | `POST /scans`, `/scans/{id}/cancel`, `/scan-schedules` |
| Users, settings, audit log | (not in the UI yet) | `/users`, `/settings`, `GET /audit-log` |
| API tokens | (not in the UI yet) | `POST /api-tokens` from a session, or `sudo bitscan-manager users create-api-token` |
| Results views, CSV, re-evaluation | **(M11)** | **(M11)** |

The API-only tasks are covered in [section 13](#13-automation-with-api-tokens).

---

## Contents

1. [What Bitscan does](#1-what-bitscan-does)
2. [How it fits together](#2-how-it-fits-together)
3. [Roles and sign-in](#3-roles-and-sign-in)
4. [Setting up](#4-setting-up)
5. [Enrolling hosts](#5-enrolling-hosts)
6. [Hosts and inventory](#6-hosts-and-inventory)
7. [Writing a `.bit` policy file](#7-writing-a-bit-policy-file)
8. [Loading and managing policies](#8-loading-and-managing-policies)
9. [Running scans](#9-running-scans)
10. [How results are judged](#10-how-results-are-judged)
11. [The capread helper (live firewall and audit rules)](#11-the-capread-helper-live-firewall-and-audit-rules)
12. [Settings](#12-settings)
13. [Automation with API tokens](#13-automation-with-api-tokens)
14. [Security model in brief](#14-security-model-in-brief)
15. [Troubleshooting](#15-troubleshooting)
16. [Glossary](#16-glossary)

---

## 1. What Bitscan does

Bitscan inventories Ubuntu servers and checks them against compliance policies such as the CIS benchmarks.

- **Inventory (always on):** every host reports its operating system and its full list of installed packages. You can search packages across the whole fleet by name, version, architecture and host. No user, role or API call can switch inventory off.
- **Compliance scans:** you load policies written as `.bit` files. Each policy is a list of read-only checks. You scan one host, every host with a tag, or the whole fleet, either now or on a schedule.

**Supported hosts:** Ubuntu 22.04 and Ubuntu 24.04 on amd64, running unified cgroup v2 (the default on both).

**Not in this version:** network or agentless scanning, Windows or macOS hosts, CVE matching, automatic remediation (checks only read), single sign-on (OIDC), and a policy editor in the UI.

---

## 2. How it fits together

```
        ┌──────────────────────── Manager ────────────────────────┐
 Admin ─►  Web UI / API  →  catalog (.bit policies)  →  job builder │
        │        ▲                                         │        │
        │        └── evaluate results (PASS/FAIL/ERROR) ◄──┤        │
        └───────────────────────────▲───────────────────────┼────────┘
                                    │ HTTPS, started by the host only
                     results / inventory │      │ job pull (every job_pull_seconds)
        ┌───────────────────────── Host ─────────┴─────────────────────┐
        │  bitscan-agent (no privileges)  ──whole job──►  bitscan-runner │
        │                                                 (read any file,│
        │                                                  sandboxed)    │
        │                              plugin ──► bitscan-capread (opt.) │
        └───────────────────────────────────────────────────────────────┘
```

- **Manager:** a web service with a PostgreSQL database. It stores policies, hosts, inventory and results, and it judges results. It **never** connects to a host.
- **Agent (`bitscan-agent`):** installed on each host from one `.deb`.
  - Sends a heartbeat every 5 minutes.
  - Pulls jobs every `job_pull_seconds`.
  - Uploads inventory and results.
  - Has no privileges.
- **Runner (`bitscan-runner`):** runs each check (a "plugin") in a tight sandbox, as a user that can read any file but change nothing. It also hides secrets in the output before it leaves the host.
- **capread helper (`bitscan-capread`):** an optional, off-by-default helper that lets checks read the live firewall and audit rules. See [section 11](#11-the-capread-helper-live-firewall-and-audit-rules).

Every connection starts from the host. There is no command channel into a host and no "run this command" API: a host only ever runs the plugins of the enabled policies you have loaded.

---

## 3. Roles and sign-in

| Role | Can do |
| --- | --- |
| **viewer** | See hosts, inventory, package search, policies, scans and results (without raw command output) |
| **operator** | Everything a viewer can, plus: start and cancel scans, manage scan schedules, set host tags, see raw command output (stdout and stderr) |
| **admin** | Everything, including: upload and delete policies, rebuild the catalog, manage users, enrolment tokens and requests, revoke hosts, change settings, read the audit log |

**Sign-in:**
- Use your username and password.
- **Admins must set up a TOTP authenticator app** (for example Google Authenticator), offered at first sign-in, before they can do sensitive actions.
- Sensitive actions need a TOTP-verified session and are refused for API tokens: approving or rejecting enrolments, revoking hosts, rebuilding the catalog, deleting policies, re-evaluating, and managing users, enrolment tokens and settings.

You can change your own password and replace your own TOTP from the **Password** and **TOTP** screens. A lost authenticator is reset on the server with `sudo bitscan-manager users reset-totp <username>`.

---

## 4. Setting up

Follow the runbooks; they hold the exact commands.

| Step | Runbook |
| --- | --- |
| Install the manager (PostgreSQL 16, TLS certificate, secrets vault, audit-log sink, systemd units) | `deploy/runbooks/manager-install.md` |
| Create the first admin | `sudo bitscan-manager users create-admin <name>` (manager-install §10) |
| Back up, restore, upgrade the manager | `deploy/runbooks/manager-operations.md` |
| Install the agent on a host | `deploy/runbooks/agent-install.md` |

Order of a fresh setup:
1. Install the manager.
2. Create the first admin, sign in and set up TOTP.
3. Load policies.
4. Create an enrolment token.
5. Install agents and approve them.
6. Scan.

---

## 5. Enrolling hosts

### 5.1 Create an enrolment token (admin, TOTP session)

Go to **Enrolment tokens** and create one. The options:

| Option | Range | Default | Meaning |
| --- | --- | --- | --- |
| `max_uses` | 1–10,000 | 1 | How many hosts can enrol with this one token (share it in an install script for many hosts) |
| `expires_in_hours` | 1–720 | 24 | When the token stops working |
| `allowed_cidrs` | up to 64 networks | none | Only hosts from these source networks may use it, e.g. `["10.20.0.0/16"]` |
| `auto_approve` | true / false | false | Approve hosts at once, without the manual approval step |

The token (`bse_…`) is shown **once**. Only its hash is stored.

### 5.2 Install the agent on the host

1. Check the package hash: `sha256sum -c --ignore-missing SHA256SUMS`.
2. Write the install answers into a root-only preseed file and install the package (agent-install §3a). The answers are:
   - the manager URL (`https://…`);
   - the enrolment token;
   - optionally, your private CA file;
   - optionally, the manager's key pin (`manager_spki_sha256`). Recommended.
3. Delete the preseed file.

The token never ends up in `/etc/bitscan/agent.yaml`, in logs or in debconf.

### 5.3 Approve the host (admin, TOTP session)

The host appears under **Enrolment requests** as `awaiting_approval`. Choose **Approve** or **Reject**. Once approved, the host:
- gets its own agent token (`bsa_…`);
- goes `online` at its next heartbeat;
- sends its first inventory shortly after.

**Clones:** hosts cloned from one image share `/etc/machine-id`, and a clone enrols as a re-enrolment of the first host. Regenerate `/etc/machine-id` on each clone.

### 5.4 Revoke, re-enrol and remove

- **Revoke** (admin, TOTP session; API only for now: `POST /agents/{id}/revoke`): the host's token stops working at once, and the agent goes idle. To bring the host back, re-enrol it with a new enrolment token (agent-install §7).
- **Remove:** `apt purge bitscan-agent` on the host. The host goes `offline` and is decommissioned after `decommission_after_days` (setting, default 7; 0 = never).

---

## 6. Hosts and inventory

- **Hosts:** a list with status (`awaiting_approval`, `online`, `offline`, `revoked`, `decommissioned`), OS, last heartbeat and package count. Open a host to see its OS details, its packages, its tags and whether the capread helper is enabled on it (`runner_helpers`).
- **Tags** (operator): free labels such as `prod-web` or `db`, used to target scans. Shown on the host page; set them through the API for now: `PUT /agents/{id}/tags` with `{"tags": ["prod-web"]}`.
- **Inventory:** collected every `inventory_interval_s` (default from settings, 1–24 h). The host also sends a fresh list about a minute after packages change, at most once every 10 minutes.
- **Package search:** search the whole fleet by name, version, architecture or host. Export the result as CSV; cells that could run as spreadsheet formulas are escaped.

---

## 7. Writing a `.bit` policy file

A `.bit` file is one UTF-8 XML document holding **one policy**. A policy is shown in the app as a *compliance profile*. It belongs to **one family** (the standard it implements, e.g. `CIS Ubuntu 24.04`) and holds **plugins**: one plugin is one check, i.e. one line item of the standard.

### 7.1 Minimal example

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Policy formatVersion="1.0">
  <PolicyName>CIS Ubuntu 24.04 Level 1 - Server</PolicyName>
  <PolicyDescription>CIS Benchmark Level 1 controls for Ubuntu 24.04 servers.</PolicyDescription>
  <PolicyStatus>enabled</PolicyStatus>
  <Family>
    <FamilyName>CIS Ubuntu 24.04</FamilyName>
  </Family>
  <PluginsGroups>
    <Plugin>
      <PluginName>1.3.1.1 - Ensure AppArmor is installed</PluginName>
      <PluginDescription>Checks that the AppArmor package is installed.</PluginDescription>
      <PluginId>3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48</PluginId>
      <Execute timeout="30"><![CDATA[
        dpkg-query -W -f='${Status}' apparmor 2>/dev/null
      ]]></Execute>
      <Operator>equals</Operator>
      <ExpectedResult>install ok installed</ExpectedResult>
    </Plugin>
  </PluginsGroups>
</Policy>
```

In the app this check is shown as **CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed** (`<FamilyName> - <PluginName>`).

### 7.2 Elements and options

Elements must appear **in this order**, with these exact (case-sensitive) names. All are required unless marked optional.

| Element / attribute | Occurs | Rules | What it is for |
| --- | --- | --- | --- |
| `<Policy>` | 1 | Root element | One compliance profile |
| `@formatVersion` | optional | Only `1.0` (default `1.0`) | Format version |
| `<PolicyName>` | 1 | 1–128 characters, trimmed, **unique across all policies** | Profile name and permanent key. The file name is never used as the name |
| `<PolicyDescription>` | 1 | 0–4,000 characters, plain text | Shown in the app |
| `<PolicyStatus>` | 1 | `enabled` or `disabled` (any case) | Whether the profile can be selected and scanned |
| `<Family>` / `<FamilyName>` | 1 | 1–128 characters | The standard, prefixed to every plugin name |
| `<PluginsGroups>` | 1 | Holds 1–5,000 `<Plugin>` | Order in the file = display order |
| `<PluginName>` | 1 per plugin | 1–255 characters; should **start with the control number**, e.g. `5.2.4 - Ensure …` | Line item name; the leading number is used for sorting |
| `<PluginDescription>` | 1 per plugin | 0–4,000 characters | What the check verifies |
| `<PluginId>` | 1 per plugin | Lowercase RFC 4122 UUID, unique in the file, owned by one policy | Permanent id: keeps a check's result history across versions. **Never reuse or change it** |
| `<Execute>` | 1 per plugin | 1–16,384 characters after trimming; wrap in `<![CDATA[ … ]]>` | The `sh` script the host runs |
| `<Execute timeout="…">` | optional | 1–600 seconds, default 60 | Per-check time limit |
| `<Operator>` | 1 per plugin | One of the 14 operators below (any case) | How the output is compared |
| `<ExpectedResult>` | 1 per plugin | 0–4,000 characters, trimmed (see operator rules) | The value to compare with |

Generate a fresh UUID for each new plugin, e.g. with `uuidgen | tr A-Z a-z`.

### 7.3 Operators

The check's **stdout** is compared with `ExpectedResult`. Before comparing, both are trimmed and Windows line endings (CRLF) become LF. Comparison is case-sensitive.

| Operator | Compares as | PASS when stdout… | Example `ExpectedResult` |
| --- | --- | --- | --- |
| `equals` | text | is identical to it | `install ok installed` |
| `not_equals` | text | differs from it | `disabled` |
| `contains` | text | includes it | `PermitRootLogin no` |
| `not_contains` | text | does not include it | `nullok` |
| `regex` | RE2 pattern | matches (multiline; anchor with `^` / `$`) | `^MaxAuthTries\s+[1-4]$` |
| `not_regex` | RE2 pattern | does not match | `^\s*PermitEmptyPasswords\s+yes` |
| `eq` | number | = it | `0` |
| `ne` | number | ≠ it | `0` |
| `gt` | number | > it | `13` |
| `ge` | number | ≥ it | `14` |
| `lt` | number | < it | `91` |
| `le` | number | ≤ it | `90` |
| `empty` | presence | is empty | *(leave empty)* |
| `not_empty` | presence | is not empty | *(leave empty)* |

Rules tied to the operator:
- `ExpectedResult` is empty **only** with `empty` / `not_empty`, and must be empty with them.
- Numeric operators need a number: an integer or decimal, optionally signed. The whole stdout must also be one number, or the result is ERROR.
- `regex` / `not_regex` patterns must be valid **RE2**, which has no back-references and no look-around.

### 7.4 Writing good checks

**Do**
- Print **only the observed value**, not a sentence: `install ok installed`, `5`, `no`.
- Keep it read-only: read files, query packages, list settings.
- Mount-option checks must read the **host's** view with `findmnt --task 1 …` or `/proc/1/mountinfo`. The sandbox has its own private `/tmp` and `/dev`.
- Read config files instead of running commands that need root; checks don't run as root.
- Rewrite published CIS scripts that use `xargs` or `find -exec` with `find … -print | while read -r f; do …; done`.
- Send noise to `/dev/null` (`2>/dev/null`), or write scratch files only under `/tmp`.
- Make sure the value you compare is never something the redaction patterns would hide. For example, don't compare a password hash; it comes back as `[REDACTED]`.

**Don't**
- Don't run anything that writes, deletes, installs or changes services. The importer rejects it (BIT102, below), and the sandbox blocks it anyway.
- Don't execute, `source` or `cd` into files or folders that ordinary users can write.
- Don't expect network access: checks can't open network connections.
- Don't rely on the command's exit code to decide PASS or FAIL. Only stdout is compared (for example, `grep` exiting 1 on no match is fine).

**More examples**

```xml
<!-- Number of world-writable files in /etc (should be 0) -->
<Plugin>
  <PluginName>6.1.9 - Ensure no world writable files exist in /etc</PluginName>
  <PluginDescription>Counts world-writable regular files under /etc.</PluginDescription>
  <PluginId>0b8f0d7e-4c43-4c9a-9a4e-0f5c7d1e2a91</PluginId>
  <Execute timeout="120"><![CDATA[
    find /etc -xdev -type f -perm -0002 -print 2>/dev/null | wc -l
  ]]></Execute>
  <Operator>eq</Operator>
  <ExpectedResult>0</ExpectedResult>
</Plugin>

<!-- sshd MaxAuthTries must be 4 or less -->
<Plugin>
  <PluginName>5.1.7 - Ensure sshd MaxAuthTries is configured</PluginName>
  <PluginDescription>Reads MaxAuthTries from the sshd configuration.</PluginDescription>
  <PluginId>6a1d2f3c-9e8b-4b7a-8c6d-5e4f3a2b1c0d</PluginId>
  <Execute timeout="30"><![CDATA[
    grep -hiE '^\s*MaxAuthTries\s+' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null | tail -n 1
  ]]></Execute>
  <Operator>regex</Operator>
  <ExpectedResult>^\s*[Mm]ax[Aa]uth[Tt]ries\s+[1-4]\s*$</ExpectedResult>
</Plugin>

<!-- Mount option read from the host's view, not the sandbox's -->
<Plugin>
  <PluginName>1.1.2.2.3 - Ensure nosuid option set on /dev/shm partition</PluginName>
  <PluginDescription>Reads the mount options of /dev/shm from PID 1's mount table.</PluginDescription>
  <PluginId>2c4e6a8b-1d3f-4a5b-9c7d-8e9f0a1b2c3d</PluginId>
  <Execute timeout="30"><![CDATA[
    findmnt --task 1 -n -f -o OPTIONS --mountpoint /dev/shm
  ]]></Execute>
  <Operator>contains</Operator>
  <ExpectedResult>nosuid</ExpectedResult>
</Plugin>
```

> The UUIDs above are examples. Generate your own for real policies. The sample policies in `bits/samples/` are good starting points; their CIS control numbers are not yet confirmed against the benchmark.

### 7.5 Validation codes

A file is imported **whole or not at all**. Every problem is reported with its line number in the import history (**Imports** screen).

| Code | Meaning | Severity |
| --- | --- | --- |
| BIT001 | Not well-formed UTF-8 XML, over 5 MB, or contains a DTD or external entities | Reject |
| BIT002 | Wrong element names, a missing or repeated element, or wrong order | Reject |
| BIT003 | `PolicyStatus` is not `enabled` / `disabled` | Reject |
| BIT004 | `PluginId` is not a valid UUID | Reject |
| BIT005 | `PluginId` repeated within the file | Reject |
| BIT007 | `PolicyName` already belongs to another file in the server folder | Reject |
| BIT008 | `Execute` empty or longer than 16,384 characters | Reject |
| BIT010 | Unknown `Operator` | Reject |
| BIT011 | `ExpectedResult` missing | Reject |
| BIT012 | Numeric operator with a non-numeric `ExpectedResult` | Reject |
| BIT013 | Invalid RE2 pattern | Reject |
| BIT014 | `ExpectedResult` empty with an operator other than `empty`/`not_empty`, or not empty with them | Reject |
| BIT015 | `PluginId` already owned by another (not deleted) policy | Reject |
| BIT016 | `formatVersion` is not `1.0` | Reject |
| BIT017 | Any other limit broken (lengths, `timeout` outside 1–600, over 5,000 plugins) | Reject |
| BIT102 | `Execute` contains a write-like or state-changing command (below) | Reject |
| BIT101 | `PluginName` has no leading control number | Warning |
| BIT103 | Leading control number longer than 32 characters | Warning |

**BIT102 rejects** (the command is split into words like a shell would, not searched as text):
- the commands `rm`, `mv`, `cp`, `tee`, `dd`, `chmod`, `chown`, `chgrp`, `truncate`, `ln`, `install`, `mkfs`, `mount`, `umount`;
- `sed -i` / `--in-place`;
- `apt`/`apt-get` `install|remove|purge|upgrade|full-upgrade|dist-upgrade|autoremove`;
- `dpkg -i|-r|-P|--install|--remove|--purge|--configure`;
- `systemctl start|stop|restart|reload|enable|disable|mask|unmask|kill|isolate|set-property`;
- output redirection (`>`, `>>`, `>|`) anywhere except `/dev/null`, `/dev/stdout`, `/dev/stderr` or `/tmp/…`;
- `.` / `source`, `eval`, `exec`, `xargs`, `find -exec|-execdir|-ok|-okdir`;
- `sh`/`bash`/`dash` given a script file, or `-c` with `$(…)`, backticks or `<(…)`.

These are fine: `apt-cache policy`, `apt list --installed`, `find … -perm`, `systemctl is-enabled`, `systemctl is-active`, `2>/dev/null`.

---

## 8. Loading and managing policies

**Two ways to load (admin):**
1. **Upload:** **Policies → Upload**, or `POST /api/v1/policies/import`. An admin's API token may upload.
2. **Server folder:** a server administrator copies the file into `/var/lib/bitscan/bits/`. It loads automatically within moments.

A successful import is **live immediately**; there is no approval step. Every import, including a rejected one, is audit-logged and raises an alert that lists every changed command.

| Action | How | Who |
| --- | --- | --- |
| Update a policy | Upload (or replace in the folder) a file with the same `PolicyName`. The version goes up only if the file changed | admin |
| Disable / enable a profile | **Policies → (profile) → status**, or `PATCH /policies/{id}` with `{"policy_status": "disabled"}`. A later file update won't re-enable a profile you disabled | admin |
| Delete a policy | **Delete**, or `DELETE /policies/{id}`. Soft delete: queued jobs are cancelled, schedules disabled, its plugins retired | admin, TOTP session |
| Delete a server-folder policy | Remove its file from `/var/lib/bitscan/bits/` (the API answers 409 `policy_managed_on_server`) | server administrator |
| Rebuild the catalog | **Rebuild**, or `POST /policies/rebuild` (or `sudo bitscan-manager bits rebuild`). Re-imports every file; fixes a damaged catalog | admin, TOTP session |
| See import history and errors | **Imports** screen | admin |

**Renaming:**
- **Server-folder policy:** change `<PolicyName>` in the same file, and the policy is renamed in place, keeping its id, plugins and history.
- **Uploaded policy:** delete it, then upload it under the new name.

**Queued jobs keep the commands they were built with.** A policy update applies to scans started after it.

---

## 9. Running scans

### 9.1 Manual scan (operator)

Scans are started through the API for now (the scan screens come with M11). Call `POST /api/v1/scans`:

```json
{ "policy_id": 12, "target": { "tags": ["prod-web"] } }
```

The target is exactly one of:

| Target | Meaning |
| --- | --- |
| `{"agents": ["<agent-id>", …]}` | These hosts |
| `{"tags": ["prod-web", …]}` | Hosts with **any** of these tags |
| `{"all": true}` | The whole fleet (an alert is raised when an API token does this) |

The target is resolved when the scan is queued. Decommissioned hosts, and hosts still awaiting approval, are left out. Cancel a scan with `POST /scans/{id}/cancel`.

### 9.2 Scheduled scans (operator)

Through the API for now: `POST /api/v1/scan-schedules`:

```json
{ "name": "Nightly prod CIS", "policy_id": 12, "target": { "tags": ["prod"] },
  "cron": "30 2 * * *", "timezone": "Asia/Singapore", "enabled": true }
```

- `cron` is a standard 5-field cron expression, evaluated in `timezone` (default `UTC`).
- Runs missed while the manager was down are not caught up.

### 9.3 What happens on the host

1. The agent pulls the job at its next pull (every `job_pull_seconds`). It checks the job is for this host, not expired and not a repeat.
2. The runner checks the same again, then runs each plugin:
   - as `/bin/sh -c "<Execute>"`, in its own cgroup;
   - with a minimal environment, at low CPU and I/O priority, within its `timeout`;
   - at most `max_parallel_plugins` at once.
3. The output is **redacted on the host**, then cut to 64 KB of stdout and 16 KB of stderr. Results are uploaded as each plugin finishes, from a local spool that survives a manager outage.

---

## 10. How results are judged

The **manager** judges each result, using the `Operator` and `ExpectedResult` recorded when the scan was queued. Hosts never see the expected answers.

| Result | When |
| --- | --- |
| **PASS** | The comparison is true |
| **FAIL** | The comparison is false |
| **ERROR** | Any of: the check timed out; it exited 126 or 127 (can't run, or not found); it was killed by a signal (exit ≥ 128); stdout was cut at 64 KB; a numeric operator got a non-number; the runner was unavailable or its result was lost (`runner_unavailable`, `spool_overflow`) |

- **Raw output:** only operators and admins see stdout and stderr; viewers get the verdict only. Output is always redacted.
- **Default redaction patterns:** crypt password hashes, PEM and OpenSSH private keys (including cut-off ones), Bitscan tokens (`bs[aeku]_…`), AWS access key ids (`AKIA…` / `ASIA…`), and `password=…` / `secret: …` / `api_key=…` / `token=…` style values.
- **(M11)** The results screens, results CSV export and re-evaluation (`POST /scans/{id}/reevaluate`, admin with TOTP) arrive in M11.

---

## 11. The capread helper (live firewall and audit rules)

Some CIS checks need the **live** firewall or audit rules, and reading those needs privileges the sandbox doesn't give. The optional `bitscan-capread` helper reads them on a check's behalf. It answers exactly two requests:

| Use in `Execute` | Runs | Returns |
| --- | --- | --- |
| `bitscan-capread nft_ruleset` | `/usr/sbin/nft -j list ruleset` | Live nftables firewall rules, as JSON |
| `bitscan-capread audit_rules` | `/usr/sbin/auditctl -l` | Live Linux audit rules, one per line |

- **It's off by default.** Only an administrator *on the host* can switch it on: `sudo systemctl enable --now bitscan-capread.socket` (agent-install §10). The manager can't.
- The host's heartbeat reports whether it's on (`runner_helpers: ["capread"]`), and every change raises an alert.
- **When it's off**, the call prints `bitscan-capread: not enabled` and exits 1. Without `auditd`, `audit_rules` answers `bitscan-capread: not_installed`.
- **For checks meant for every host,** read the rule files on disk instead (`/etc/nftables.conf`, `/etc/audit/rules.d/*.rules`). That shows the configured rules rather than the live ones.

Example (live firewall default-drop policy):

```xml
<Execute timeout="30"><![CDATA[
  bitscan-capread nft_ruleset | grep -c '"policy": "drop"'
]]></Execute>
<Operator>gt</Operator>
<ExpectedResult>0</ExpectedResult>
```

---

## 12. Settings

Through the API for now: `GET /api/v1/settings`, and `PATCH /api/v1/settings` (admin, TOTP-verified session):

| Setting | Range | Meaning |
| --- | --- | --- |
| `job_pull_seconds` | 60–3,600 | How often agents ask for jobs |
| `inventory_interval_s` | 3,600–86,400 | How often agents send a full inventory |
| `max_parallel_plugins` | 1–8 | Plugins run at the same time on one host |
| `agent_token_ttl_days` | 60–730 | Lifetime of a host's agent token (renewed automatically) |
| `decommission_after_days` | 0–365 | Days offline before a host is decommissioned (0 = never) |
| `enrolment_alert_per_hour` | 1–10,000 | Enrolment requests per hour that trigger an alert |
| `redaction_patterns` | up to 50 RE2 patterns | Patterns hidden as `[REDACTED]` on the host before output leaves it |

---

## 13. Automation with API tokens

1. Get a token. It is shown once, and only its hash is stored.
   - **API token (`bsk_…`)**, for scripts. On the manager host, run `sudo bitscan-manager users create-api-token <username> --name ci --days 90` (lifetime 1–365 days, default 90). Or, from a signed-in session, `POST /api/v1/api-tokens` with `{"name": "ci", "expires_in_days": 90}`. API tokens can't create other API tokens, and can't do the TOTP-only actions in [section 3](#3-roles-and-sign-in).
   - **Session token (`bsu_…`)**, for the TOTP-only actions (users, settings, revoke, …). Run `POST /api/v1/auth/login` with `{"username": …, "password": …, "totp_code": "123456"}`; the response holds `token`.
2. Call the API at `https://<manager>/api/v1/…` with `Authorization: Bearer <token>`.

Examples:

```sh
TOKEN=bsk_...        # keep this out of shell history and logs
M=https://bitscan.example.com

# List enabled profiles
curl -sS -H "Authorization: Bearer $TOKEN" "$M/api/v1/policies?status=enabled"

# Upload a policy (admin token)
curl -sS -H "Authorization: Bearer $TOKEN" -F "file=@cis-ubuntu-24.04.bit" "$M/api/v1/policies/import"

# Scan every host tagged prod-web with profile 12 (operator token)
curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"policy_id":12,"target":{"tags":["prod-web"]}}' "$M/api/v1/scans"

# Tag a host (operator)
curl -sS -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"tags":["prod-web"]}' "$M/api/v1/agents/<agent-id>/tags"

# Nightly schedule at 02:30 Singapore time (operator)
curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"name":"Nightly prod","policy_id":12,"target":{"tags":["prod"]},"cron":"30 2 * * *","timezone":"Asia/Singapore"}' \
     "$M/api/v1/scan-schedules"

# Create a user (admin, TOTP session token $SESSION)
curl -sS -H "Authorization: Bearer $SESSION" -H "Content-Type: application/json" \
     -d '{"username":"bob","password":"<a long password>","role":"operator"}' "$M/api/v1/users"

# Fleet-wide package search, as CSV
curl -sS -H "Authorization: Bearer $TOKEN" "$M/api/v1/packages/search.csv?q=openssl" -o openssl.csv
```

- Errors use RFC 9457 problem details: `{type, title, status, detail}`.
- `GET /healthz` and `GET /readyz` (outside `/api/v1`) report service health.
- The full API is described by the manager's OpenAPI document (`manager/openapi.json`).

---

## 14. Security model in brief

- **Hosts pull, the manager never pushes.** There's no listening port on a host and no remote shell.
- **Jobs contain only plugins from enabled policies.** There is no "run this command" endpoint.
- **Jobs and `.bit` files are not signed** (an owner decision). Protection comes instead from:
  - TLS, with optional key pinning on agents;
  - each host's own token;
  - least-privilege database roles;
  - admin TOTP;
  - a hash-chained audit log shipped off the manager;
  - an alert on every import.
- **Treat admin accounts and the policy folder as highly sensitive.** Whoever controls them can make every host read and return any file.
- **The runner sandbox** (TS §3.7) blocks the following for every plugin, as checked by the sandbox test suite on Ubuntu 22.04 and 24.04:
  - writes outside its private `/tmp`; `/dev/shm` is read-only;
  - executing files from `/tmp`, `/var/tmp` or home folders;
  - network sockets;
  - the Docker, containerd, snapd and journald sockets;
  - tracing the runner;
  - state-changing D-Bus calls;
  - gaining privileges or loading kernel modules;
  - outliving its job.
- **Tokens** are 256-bit random values, and only their hashes are stored. Plugin output and tokens never go into logs.

---

## 15. Troubleshooting

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| Host stuck in `awaiting_approval` | No admin has approved it, or `auto_approve` is off | Approve under **Enrolment requests** |
| Install stops asking for the URL or token | Preseed missing or unreadable | agent-install §5 |
| Host `offline` | No heartbeat for a while: agent stopped, network or clock problem | `systemctl status bitscan-agent`; `journalctl -u bitscan-agent`; check NTP |
| Agent log says re-enrol with a new token | The host was revoked | agent-install §7 |
| Every result `ERROR` with `runner_unavailable` | Runner can't start: host not on unified cgroup v2, or runner masked | `stat -fc %T /sys/fs/cgroup` must print `cgroup2fs` (agent-install §1, §9) |
| One check `ERROR`, exit 126/127 | Command not found, or not executable from the sandbox | Use system binaries only; no scripts from `/tmp` or home folders |
| Check `ERROR` "not a number" | Numeric operator, but stdout has extra text | Print only the number |
| Check FAILs on a value you expected | It's comparing redacted text (`[REDACTED]`) | Compare something that isn't a secret |
| `bitscan-capread: not enabled` | Helper off on that host | Enable it on the host, or read rule files on disk |
| Upload rejected | Validation code in the response and on **Imports** | See [7.5](#75-validation-codes) |
| Upload refused 409 `policy_managed_on_server` | The policy lives in the server folder | Change the file in `/var/lib/bitscan/bits/` |

---

## 16. Glossary

| Term | Meaning |
| --- | --- |
| **Agent** | The `bitscan-agent` and `bitscan-runner` services installed from one `.deb` on a host |
| **Policy / compliance profile** | One `<Policy>` in a `.bit` file; selectable in the app |
| **Family** | The standard a policy implements (e.g. `CIS Ubuntu 24.04`) |
| **Plugin** | One check (one line item of the standard) with the command to run |
| **Job** | One inventory collection, or one compliance scan unit, for one host |
| **Scan** | A request to run one profile on a target; split into one job per host |
| **Enrolment token (`bse_`)** | Lets hosts enrol; may be shared by many installs |
| **Agent token (`bsa_`)** | Each host's own credential |
| **Session token (`bsu_`) / API token (`bsk_`)** | A user's web session / a personal automation token |
| **TOTP** | Time-based one-time password from an authenticator app |
| **capread** | Optional host helper for live firewall and audit rules |

---

*Source documents: `docs/spec/Technical_Specification.md` (TS), `docs/spec/bit_Schema_Reference.md` (SR), `deploy/runbooks/`. Where this guide and the specifications differ, the specifications win.*
