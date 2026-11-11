# Install, re-enrol and remove the Bitscan agent

The `bitscan-agent` package installs two services, `bitscan-agent` and `bitscan-runner`, and the optional `bitscan-capread` helper (installed but disabled). The agent opens every connection to the manager; the host needs no inbound port.

**Release 0.2.0** (package `0.2.0-1`) is the current release. It supports enrolment, heartbeat, job pull and the mandatory inventory (`os_info` and the full `dpkg` package list), which the manager shows on its host pages and in package search, and it runs compliance jobs. The runner runs each check in its sandbox and returns redacted output, which the agent keeps in an on-disk spool until the manager has answered. Sections 9 to 11 cover the runner, the optional helper and the spool.

**Release 0.1.0** (package `0.1.0-1`) runs no compliance check: its runner and helper are installed but idle, and it reports every check of a compliance job as `runner_unavailable`. Upgrade it as in section 6. The pre-release builds (`0.1.0~preN-1`, `0.2.0~preN-1`) are not supported; upgrade them the same way.

## 1. Before you start

- **Supported hosts:** Ubuntu 22.04 LTS and Ubuntu 24.04 LTS on amd64, with the default unified cgroup v2 hierarchy. No other release or architecture is supported.
- **cgroup v2:** the host must boot with the unified cgroup v2 hierarchy, the Ubuntu default. `stat -fc %T /sys/fs/cgroup` must print `cgroup2fs`. Otherwise the runner refuses to start, and every check of a compliance job is reported as `runner_unavailable` (section 9). The usual cause is `systemd.unified_cgroup_hierarchy=0` on the kernel command line (see `cat /proc/cmdline`). Remove it from `GRUB_CMDLINE_LINUX` in `/etc/default/grub`, run `sudo update-grub` and reboot.
- **Time:** the host must be NTP-synced. `timedatectl` must show `System clock synchronized: yes`. The manager alerts on a clock skew over 5 minutes.
- **Network:** outbound HTTPS from the host to the manager URL, for example `https://mgr.example:8443`. Plain HTTP is refused.
- **Cloned hosts:** hosts cloned from one image share `/etc/machine-id`, so the second host appears as a re-enrolment of the first. Regenerate the machine id on every clone before you install the agent. Remove both copies: if `/var/lib/dbus/machine-id` is still a file, `systemd-machine-id-setup` copies the old id from it instead of making a new one. Then restore the usual link:

  ```sh
  cat /etc/machine-id    # note the old id
  sudo rm -f /etc/machine-id /var/lib/dbus/machine-id
  sudo systemd-machine-id-setup
  if [ -d /var/lib/dbus ]; then sudo ln -sf /etc/machine-id /var/lib/dbus/machine-id; fi
  cat /etc/machine-id    # must now differ from the old id
  ```

  Install the agent after cloning, never in the template image. A cloned agent token used with a different machine id gets 401 and the manager revokes it.
- **Enrolment token:** an admin creates a `bse_` enrolment token in the manager. Use one single-use token per host where you can. For a scripted install across many hosts, set `max_uses` to the number of hosts, a short expiry and `allowed_cidrs`. Leave `auto_approve` off unless you need it; a token with `auto_approve` or more than 100 uses raises an alert.
- **Private manager CA:** if the manager's certificate is not signed by a CA in the system store, copy that CA certificate (that CA only, not a bundle) to the host under `/etc`, readable by every user. Do not keep it under `/home`, `/root`, `/run/user` or `/tmp`: the install accepts such a path, but the agent service cannot see those folders, so it fails to start and keeps restarting.

  ```sh
  sudo install -d -m 0755 /etc/bitscan
  sudo install -m 0644 manager-ca.pem /etc/bitscan/ca.pem
  ```

- **Key pin (recommended):** the pin is the SHA-256 of the manager certificate's public key (DER `SubjectPublicKeyInfo` of the leaf certificate), as 64 hexadecimal characters. Compute it **on the manager host**, from the certificate it serves, not over the network:

  ```sh
  sudo openssl x509 -in /etc/bitscan/secrets/tls.crt -noout -pubkey |
      openssl pkey -pubin -outform DER | sha256sum | cut -d' ' -f1
  ```

  `openssl x509` reads the first certificate in the file, which must be the manager's own (leaf) certificate. The pin is checked in addition to normal certificate verification, never instead of it. Without a pin, anyone holding a publicly trusted certificate for the manager's host name could impersonate the manager to the agent. Keep the same key when you renew the certificate, and the pin stays valid. Pinning is optional.

## 2. Check the package

Download `bitscan-agent_<version>_amd64.deb` (for 0.2.0, `bitscan-agent_0.2.0-1_amd64.deb`). The release page, which is served from a different origin than the download, shows the release's `SHA256SUMS` text in its notes. Copy that text from the release page into a file named `SHA256SUMS` next to the package. Never use a checksum file fetched from the same host as the package, including the `SHA256SUMS` file attached to the release.

`SHA256SUMS` lists every file of the release, so check only the files you downloaded:

```sh
sha256sum -c --ignore-missing SHA256SUMS
```

It must print `bitscan-agent_<version>_amd64.deb: OK`. Stop if it does not, if any line says `FAILED`, or if it reports that no file was verified. Each release also ships CycloneDX SBOMs, one per binary, listed in the same `SHA256SUMS`.

## 3. Install

Give the install inputs in **one** of three ways. Never pass them as command-line environment variables: they end up in shell history and process lists, and the package ignores them.

| Input | debconf question | `install.env` key | Required |
| --- | --- | --- | --- |
| Manager URL (`https://` only) | `bitscan/manager_url` | `MANAGER_URL` | yes |
| Enrolment token (`bse_…`) | `bitscan/enrol_token` | `ENROL_TOKEN` | yes |
| CA file (absolute path the `bitscan` user can read) | `bitscan/ca_file` | `CA_FILE` | no |
| Key pin (64 hexadecimal characters) | `bitscan/manager_spki_sha256` | `MANAGER_SPKI_SHA256` | no |

### 3a. Preseed (recommended)

Create the preseed file root-only and edit it with `sudoedit`, so the token never appears on a command line:

```sh
sudo install -m 0600 /dev/null /root/bitscan.preseed
sudoedit /root/bitscan.preseed
```

Content (the token question is a `password` question, so debconf keeps it only in its root-only `passwords.dat`):

```text
bitscan-agent bitscan/manager_url string https://mgr.example:8443
bitscan-agent bitscan/enrol_token password bse_REPLACE_WITH_THE_ENROLMENT_TOKEN
# Optional, for a private CA and a key pin:
# bitscan-agent bitscan/ca_file string /etc/bitscan/ca.pem
# bitscan-agent bitscan/manager_spki_sha256 string <64 hexadecimal characters>
```

Then load it, install the package and delete the preseed file:

```sh
sudo debconf-set-selections /root/bitscan.preseed
sudo apt install ./bitscan-agent_<version>_amd64.deb
sudo rm -f /root/bitscan.preseed
```

> **Warning: always preseed `bitscan/enrol_token` as `password`, as shown above, never as `string`.** A `string` answer goes to debconf's `/var/cache/debconf/config.dat`, which every local user can read. The install clears the token there, but a copy stays in the backup file `/var/cache/debconf/config.dat-old` (also readable by every user) until debconf next saves its database. If you used `string`, clear that copy after the install, either by removing the backup file as root (debconf writes a new one at its next save):
>
> ```sh
> sudo rm -f /var/cache/debconf/config.dat-old
> ```
>
> or by making debconf save once more, for example by loading the manager URL line again:
>
> ```sh
> echo 'bitscan-agent bitscan/manager_url string https://mgr.example:8443' | sudo debconf-set-selections
> ```
>
> Use your own manager URL in that line. Treat the token as exposed to the host's local users until then.

### 3b. Interactive

`sudo apt install ./bitscan-agent_<version>_amd64.deb` asks for the manager URL and the enrolment token. The CA file and the key pin are asked only at low debconf priority, so a normal interactive install does not ask them. If you need a private CA or a pin, preseed those two questions first (3a) or use `install.env` (3c).

### 3c. `/etc/bitscan/install.env`

A root-only file that replaces debconf completely while it exists. Create it with the right owner and mode first, then edit it:

```sh
sudo install -d -m 0755 /etc/bitscan
sudo install -m 0600 /dev/null /etc/bitscan/install.env
sudoedit /etc/bitscan/install.env
```

```text
MANAGER_URL=https://mgr.example:8443
ENROL_TOKEN=bse_REPLACE_WITH_THE_ENROLMENT_TOKEN
# CA_FILE=/etc/bitscan/ca.pem
# MANAGER_SPKI_SHA256=<64 hexadecimal characters>
```

Rules: one `KEY=value` per line, taken literally (no quotes, no `export`, no variables); blank lines and lines starting with `#` are skipped; only the four keys above, each at most once. The file must be a regular file owned by `root:root` with mode 0600, and `/etc/bitscan` must be owned by root and not writable by group or others. Otherwise the install stops, the file is left in place and the package stays unconfigured. After a successful install the file is deleted.

Then run `sudo apt install ./bitscan-agent_<version>_amd64.deb`.

### What the install does

It creates the system users `bitscan` and `bitscan-runner` (no shell, no home). It writes `/etc/bitscan/agent.yaml` (`root:bitscan`, 0640, without the token) and `/var/lib/bitscan-agent/enroll.token` (`bitscan:bitscan`, 0600). It clears the token from debconf. Then it enables and starts `bitscan-runner.socket` and `bitscan-agent.service`.

## 4. Check the result

```sh
systemctl is-enabled bitscan-agent.service bitscan-runner.socket
systemctl is-active bitscan-agent.service bitscan-runner.socket
sudo journalctl -u bitscan-agent -n 20
```

Both units must be `enabled` and `active`. The capread units stay disabled. `bitscan-runner.service` itself stays `inactive` until the first compliance job connects to its socket (section 9).

The host then appears in the manager. Unless the enrolment token has `auto_approve` and the machine id is new, an admin must approve the enrolment request; until then the agent keeps retrying with back-off. After the agent's first enrolment call, even while the request still waits for approval, `/var/lib/bitscan-agent/` holds `agent_id` and `token` and `enroll.token` is gone, so these files do not show that the host is approved. The host is enrolled once an admin approves it in the manager (or at once with `auto_approve` and a new machine id). The first inventory follows the first inventory job.

## 5. If the install stops

A missing or invalid input stops the install with one line starting `bitscan-agent:` and leaves the package unconfigured, with no service enabled or started. Fix the cause, then run `sudo dpkg --configure bitscan-agent`.

| Message (after `bitscan-agent:`) | Fix |
| --- | --- |
| `the manager URL is missing; …` / `the enrolment token is missing; …` | Preseed the question named in the line, or write `install.env` |
| `the manager URL must be an https:// URL with a host` | Use `https://host[:port]`, no spaces or quotes |
| `the enrolment token must be a bse_ enrolment token` | Copy the full `bse_` token from the manager |
| `the CA file must be an absolute path the bitscan user can read` | Absolute path under `/etc` to a regular file with mode 0644 in readable folders (section 1) |
| `the manager key pin must be empty or 64 hexadecimal characters` | Recompute the pin (section 1) |
| `/etc/bitscan/install.env must be a regular file owned by root:root with mode 0600` | `sudo chown root:root` and `sudo chmod 0600` the file |
| `/etc/bitscan/install.env: every line must be KEY=value` / `a key is given twice` / `unknown key` | Correct the file (section 3c) |
| `/etc/bitscan/install.env may hold only ENROL_TOKEN once agent.yaml exists` | On an installed host the file may hold only a new token (section 7) |
| `/etc/bitscan must be a directory owned by root and not writable by group or others` | `sudo chown root /etc/bitscan` and `sudo chmod go-w /etc/bitscan`, after checking who changed it |

For the interactive route, `dpkg --configure` asks again for a required answer that was left empty.

## 6. Upgrade

**Order:** upgrade the manager first (migrate, then restart, as the manager operations runbook `manager-operations.md` describes), then the agents.

**Compatibility:** a manager supports agents of its own version and the one before, and an agent supports a manager of its own version and the one before. So agent 0.2.0-1 works with managers 0.2.0 and 0.1.0, and manager 0.2.0 works with agents 0.2.0-1 and 0.1.0-1. Under manager 0.1.0, which has no scans, agent 0.2.0-1 gets no compliance job. The pre-release builds (`0.1.0~preN-1`, `0.2.0~preN-1`) are not supported by any manager; upgrade every such host to 0.2.0-1.

Check the new package as in section 2, then:

```sh
sudo apt install ./bitscan-agent_<new version>_amd64.deb
```

An upgrade asks nothing. It keeps `agent.yaml`, the token and the agent id, and restarts the services. A `0.1.0-1` host and a pre-release host upgrade to `0.2.0-1` in place the same way: `0.1.0-1`, `0.2.0~pre1-1` and `0.2.0~pre2-1` all sort below `0.2.0-1`.

Check the result:

```sh
dpkg-query -W -f='${Version}\n' bitscan-agent
sudo journalctl -u bitscan-agent -n 20
```

The first command prints the new package version. On an enrolled host the log shows `bitscan-agent started` with that version, and the host does not need to be re-enrolled.

## 7. Re-enrol a host

Re-enrol when the agent log says the host must be re-enrolled (its token was revoked or has expired, or the host was decommissioned), or when it logs `enrolment did not complete; the agent stays idle until it is restarted` with the reason `enrolment refused; the host needs a new enrolment token`. In both cases the agent stays idle until it is restarted. Get a new enrolment token from an admin, then either:

- run `sudo dpkg-reconfigure bitscan-agent`, which asks only for the new enrolment token; or
- write `/etc/bitscan/install.env` holding only `ENROL_TOKEN=…` (section 3c for owner and mode), then run `sudo dpkg-reconfigure bitscan-agent`. Any other key in the file is refused on an installed host.

The package writes the new `enroll.token`, clears the token from debconf and restarts the agent, which enrols again; `agent.yaml` is not changed. A re-enrolment onto the same machine id is always held for admin approval, even with `auto_approve`; on approval the host keeps its history and the old token is revoked.

To change the CA file or the key pin of an installed host, edit `/etc/bitscan/agent.yaml` as root (`sudoedit /etc/bitscan/agent.yaml`; keep the owner `root:bitscan` and mode 0640), then run `sudo systemctl restart bitscan-agent`. `dpkg-reconfigure` does not ask these questions.

## 8. Remove and purge

```sh
sudo apt remove bitscan-agent
```

stops and disables the units and keeps the configuration and state.

```sh
sudo apt purge bitscan-agent
```

also removes `/var/lib/bitscan-agent`, `/etc/bitscan/agent.yaml` and any leftover `/etc/bitscan/install.env`, and the package's debconf answers. It removes `/etc/bitscan` only if the folder is then empty, so a manager's `manager.env` and `secrets/` on the same host are kept. The `bitscan` and `bitscan-runner` users and a CA file you copied are kept; if that is `/etc/bitscan/ca.pem`, `/etc/bitscan` stays too.

Removing the package does not deregister the host. It goes `offline` after 30 minutes and is decommissioned after `decommission_after_days` (default 7; 0 means never), which also revokes its token. To cut the host off at once, an admin revokes the agent in the manager.

## 9. Compliance jobs and the runner

`bitscan-agent` hands each compliance job whole to `bitscan-runner` over `/run/bitscan/runner.sock`. The runner runs each check as the `bitscan-runner` user. That user can read every file, but it cannot write outside its private `/tmp`, open IP connections or gain privileges. The runner redacts the output on the host before it returns it. It never logs a check command or its output.

After the first compliance job:

```sh
systemctl is-active bitscan-runner.socket bitscan-runner.service
sudo journalctl -u bitscan-runner -n 20
```

Both must be `active`, and the log shows `bitscan-runner started` with the package version.

**`runner_unavailable`.** If the runner cannot take or finish a job, every check of that job without a result is reported as ERROR `runner_unavailable`. The job still finishes and is not sent again. The agent logs `the runner is unavailable; plugins without a result are reported runner_unavailable` with the `job_id` and a `reason`: `connect`, `timeout`, `broken`, `protocol` or `refused_<reason>`. Its next heartbeat carries `last_error` `runner_unavailable: <reason>`, which the manager writes to its own log as `agent last_error` with the agent id. To find the cause:

```sh
sudo journalctl -u bitscan-agent -n 50 | grep runner_unavailable
sudo journalctl -u bitscan-runner -n 20
```

A runner that refuses to start logs one line, `start-up refused`, with a `reason`, and systemd tries again every 10 seconds:

- `runner: refusing to start: /sys/fs/cgroup is not cgroup2` or `… not on the unified cgroup v2 hierarchy`: fix the boot as in section 1.
- `runner: refusing to start: effective uid is 0` or `… holds capabilities beyond CAP_DAC_READ_SEARCH`: the unit was changed locally. `systemctl cat bitscan-runner.service` shows any drop-in under `/etc/systemd/system/`. Remove it, then run `sudo systemctl daemon-reload`. The units must stay as shipped.

**Mount checks.** Checks see the runner's private `/tmp` and `/dev`, so `findmnt /tmp` describes the sandbox, not the host. Checks of mount options must read the host's view with `findmnt --task 1` or `/proc/1/mountinfo`. For example, `findmnt --task 1 -n -o OPTIONS --mountpoint /tmp` prints the host's options for `/tmp`, or nothing if `/tmp` is not a separate mount. A host shell shows the same result without `--task 1`.

## 10. The capread helper (optional)

Live firewall and audit rules need capabilities the runner never has. Checks that want them call `bitscan-capread nft_ruleset` (`nft -j list ruleset`) or `bitscan-capread audit_rules` (`auditctl -l`), and the helper answers. The helper is installed disabled. While it is off, the call exits 1 with `bitscan-capread: not enabled`, and checks read the rule files on disk instead.

Only an administrator on the host enables the helper, by hand or with configuration management. The manager has no route, setting or job that can enable it, and the agent and runner never change a unit.

Enable it:

```sh
sudo systemctl enable --now bitscan-capread.socket
systemctl is-active bitscan-capread.socket
ls -l /run/bitscan/capread.sock
sudo -u bitscan-runner /usr/sbin/bitscan-capread nft_ruleset
```

The socket is `active`, and the socket file is `srw-rw----`, owned by `root bitscan-runner`. The last command prints the ruleset as JSON. If `nft` or `auditctl` is not installed, the answer is `bitscan-capread: not_installed`. The helper accepts only the `bitscan-runner` user.

The next heartbeat (within about 5 minutes) reports `runner_helpers` as `["capread"]`. The manager shows that in `GET /agents` and writes a `runner_helper_changed` alert.

Disable it:

```sh
sudo systemctl disable --now bitscan-capread.socket
ls /run/bitscan/capread.sock
```

Stopping the socket also stops the helper and removes the socket file, so `ls` reports `No such file or directory`. The next heartbeat reports `[]`, with another alert.

## 11. The result spool

The agent keeps results in `/var/lib/bitscan-agent/spool/`, one folder per compliance job, until the manager has answered them. The spool holds only redacted output. A restart or upgrade keeps it, and results spooled before a restart are sent after it.

- **Size:** `spool_max_mb` in `/etc/bitscan/agent.yaml`, 1 to 50 (default 50). Any other value refuses start-up with `agent.yaml: spool_max_mb: must be 1 to 50`. After a change, run `sudo systemctl restart bitscan-agent`.
- **Full:** the oldest results are replaced first by ERROR `spool_overflow` entries. The agent logs `spool full: …`.
- **Age:** results are kept for 7 days from when their job was received, since the manager refuses them after that. At start the agent drops older ones, or damaged ones, and logs `spooled results dropped at start` with `reason` `expired` or `unreadable`. `last_error` is then `spool: results dropped at start (<reason>)`.
- **`spool_bytes`:** every heartbeat reports the spool's size. The manager in this version does not store or show it, so check it on the host with `sudo du -sb /var/lib/bitscan-agent/spool`.

**If the spool cannot be opened**, the agent keeps sending heartbeats and running inventory, but it refuses every compliance job:

- at start it logs `the result spool could not be opened; compliance jobs are refused`, with a `reason`;
- for each compliance job it pulls, it logs `job refused; not run` with `reason=no compliance handler`;
- `last_error` is `spool: not opened; compliance jobs refused`, then `job refused: no compliance handler`;
- a refused job never starts, so the manager fails it 24 hours after it was handed out.

Check:

```sh
sudo journalctl -u bitscan-agent | grep 'result spool'
sudo ls -ld /var/lib/bitscan-agent /var/lib/bitscan-agent/spool
df -h /var/lib/bitscan-agent
```

`spool` must be a directory (not a file or a symbolic link) owned by `bitscan:bitscan` with mode 0700, and the filesystem must be writable and have free space. If `spool` is missing, the agent creates it. Fix the cause, then run `sudo systemctl restart bitscan-agent`.
