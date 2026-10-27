# TASK-133 revision 2: implementation report

Worktree `C:\Users\kaiquan.koh\Documents\Bitscan-m6`, branch `m6-release`. Nothing committed.

## Files changed (2)

- `deploy/runbooks/manager-install.md` (+235 lines net)
- `deploy/runbooks/manager-operations.md` (+17 lines net)

No other file changed. Section numbers `## 1.` to `## 11.` are unchanged; the new material is in subsections `### 1.1` to `### 1.3` and inside sections 5 and 10, so the README and runbook cross-references (all to `## N.` headings) still resolve.

## What changed

**manager-install.md**
- Intro: names the dependencies it now sets up.
- §1 Time: `sudo timedatectl set-ntp true` plus the existing check, and the `systemd-timesyncd` fallback.
- §1 bullets for certificate, OpenBao and sink now point to the new subsections.
- **§1.1 Manager TLS certificate:** (a) organisation CA: EC P-256 key and CSR with the SAN made on the manager host (`umask 077` in a subshell); what to ask for (SAN covering every name agents and browsers use, unencrypted PEM key, PEM chain with the leaf first, then intermediates, no root); checks for SAN and expiry, key/cert match (`cmp` of the public keys) and `openssl verify`. (b) Lab private CA with openssl on an admin workstation and an `issue <name>` function that is reused for the sink certificate; the CA is named `manager-ca.pem`, which matches §9's `--cacert manager-ca.pem` and the agent runbook's copy step. (c) What agents need: `bitscan/ca_file` (link to agent-install section 1) and the optional pin command, the same one as agent-install §1.
- **§1.2 OpenBao:** a link to the OpenBao docs for the server itself; trusting a private CA on the manager host (`/usr/local/share/ca-certificates/*.crt` + `update-ca-certificates`, because the manager uses the system store: `auth/vault.py:29-32`). The admin steps are: enable transit, create the `bitscan-totp` key, write the `bitscan-manager` policy (the existing two HCL lines **plus `auth/token/renew-self`**, see below) and create a token role (`orphan=true`, `token_no_default_policy=true`, `token_period=168h`). There is also an OpenBao backup note.
- **§1.3 Audit sink:** the two accepted forms, exactly what `sink_transport.py:190-219` parses (`https://…`, `syslog+tls://host[:port]` default 6514; no credentials, no query for syslog). The manager sends no auth header and no client certificate. The section has a concrete rsyslog receiver: `rsyslog-gnutls`, files under `/etc/rsyslog.d/tls/` (root:syslog, key 0640 created empty, then copied), a `60-bitscan-audit.conf` with gtls, imtcp TLS-only anon, its own ruleset writing `/var/log/bitscan-audit.log`, then `rsyslogd -N1`, restart and `ss`. It adds a firewall note and an `openssl s_client -verify_hostname` check from the manager host. It also states the TS §5.3 consequence: entries queue, an `audit_sink_unreachable` alert, and after 15 minutes sensitive actions answer 503 `audit_sink_unavailable` (`auth/dependencies.py:118-119`) until the queue drains.
- **§5:** a `manager.env` comment line for the `syslog+tls://` form and a sentence tying the three values to §1.2 and §1.3. Certificate/key copy is split from the token. **OpenBao token:** `bao token create -role=bitscan-manager -policy=bitscan-manager -no-default-policy -display-name=bitscan-manager -field=token | sudo tee /etc/bitscan/secrets/vault.token >/dev/null` (into the 0600 file made by the first block of §5), or paste it with `sudoedit` when `bao` runs elsewhere. **Token check:** the token goes to curl only via `sudo sed … vault.token | curl -H @-` (stdin header, never argv or env). It runs an encrypt/decrypt round trip (expects `Yml0c2Nhbg==`), a renew-self (expects `604800 True ['bitscan-manager']`) and five refused paths (each `403`). **Renewal:** `/usr/local/sbin/bitscan-openbao-renew` plus `bitscan-openbao-renew.service` (oneshot, `DynamicUser=yes`, `EnvironmentFile=/etc/bitscan/manager.env` for `BITSCAN_VAULT_ADDR`, `LoadCredential=vault_token:/etc/bitscan/secrets/vault.token`) plus `bitscan-openbao-renew.timer` (00:00 and 12:00, `RandomizedDelaySec=1h`, `Persistent=true`). After that come `systemd-analyze verify`, one start, `enable --now`, and failure monitoring. These are local units of the operator's own; the four released units are untouched.
- **§10:** after the first sign-in and TOTP enrolment, it checks that `auth.login` and `auth.totp_enrol` arrive at the sink (`grep -c` on the rsyslog file; actions from `auth/login.py:151`, `auth/totp_enrol.py:169`). Delivery errors are in the manager journal (`services/audit/shipper.py:168`).

**manager-operations.md**
- §3 Replace the OpenBao token, rewritten as four steps:
  1. Read the old token's accessor through renew-self (token on stdin only).
  2. Create a new token from the role into `vault.token`.
  3. Run the install check, restart the manager and run the renew service once.
  4. Revoke the old token with `bao token revoke -accessor`.

  If the old token was exposed, it is revoked first.
- §5 Remove: also disables the renew timer and removes its two units and the script.

## Token lifetime finding (with code references)

- The manager reads the token file once at start-up (`config/startup.py:167`, `loader.secret_file("BITSCAN_VAULT_TOKEN_FILE")`), builds the cipher once (`cli/serve.py:198`), and sends that fixed value as `X-Vault-Token` on every encrypt/decrypt call (`auth/vault.py:66`, `:84`). `grep -rni renew manager/bitscan_manager` finds 0 lines. **The manager never renews and never re-reads the token; a new token needs a restart.**
- The old text "periodic or non-expiring token … The manager doesn't renew the token" is not workable. A periodic token expires if it isn't renewed within its period. A non-periodic, non-root token is capped by the token max TTL (default 768 h). Only root-policy tokens have no expiry, and the manager must not hold one.
- Resolution: a **periodic orphan token from a token role, renewed by a local systemd timer** that reads the token file through `LoadCredential=`. Renewing with the token itself needs `auth/token/renew-self`, which the `default` policy normally grants. Since the token has no default policy, I **added `path "auth/token/renew-self" { capabilities = ["update"] }` to the manager's policy**. That goes beyond the brief's "encrypt and decrypt only". The only alternative is a second credential with `auth/token/renew-accessor`, which could renew any token, so it is broader. The lead should confirm this choice.
- **Outside my area:** `README.md:194` (owner impl-manager) still says "Use a periodic or non-expiring token … The manager does not renew tokens, so replacing the token is an operational step". It now contradicts the runbook and needs a matching change, for example "a periodic token renewed by the timer in `manager-install.md` section 5; its policy also allows `auth/token/renew-self`".

## Commands I am unsure of (please verify against a real OpenBao 2.x and Ubuntu 24.04)

OpenBao (§1.2, §5, ops §3):
1. `bao write auth/token/roles/bitscan-manager allowed_policies=bitscan-manager orphan=true token_no_default_policy=true token_period=168h`: the parameter names are accepted by OpenBao, and a non-root admin can create orphan tokens through the role.
2. `bao token create -role=bitscan-manager -policy=bitscan-manager -no-default-policy -display-name=bitscan-manager -field=token`: the token has policies exactly `["bitscan-manager"]`, is periodic at 168 h, and `-field=token` prints only the token.
3. Without the `default` policy, `auth/token/renew-self` is denied unless the policy grants it. I believe so; the check fails loudly if I'm wrong in either direction.
4. The expected renew-self output `604800 True ['bitscan-manager']` (`auth.lease_duration`, `auth.renewable`, `auth.policies`).
5. Each refused path answers `403`: POST `transit/encrypt/another-key`, POST `transit/keys/bitscan-totp/rotate`, POST `auth/token/create`, GET `sys/mounts`, GET `auth/token/lookup-self`.
6. `curl -H @-` reads the header from stdin (curl 8.5 on 24.04), both with and without a trailing newline in `vault.token`.
7. The runbook sentence "OpenBao gives only root tokens an unlimited lifetime".

Renewal units (§5):

8. Both units pass `systemd-analyze verify`. `EnvironmentFile=` on the root-only 0600 `manager.env` works with `DynamicUser=yes` (systemd reads it as PID 1). The script sees `$CREDENTIALS_DIRECTORY` and `BITSCAN_VAULT_ADDR`.

rsyslog receiver (§1.3):

9. `global(…)` with `DefaultNetstreamDriver*` and `maxMessageSize="1m"` works from a file in `/etc/rsyslog.d/`, and `maxMessageSize` takes effect when set there (the docs say "before inputs"). `MaxFrameSize` is accepted as an imtcp module parameter. A ruleset declared before the input is fine.
10. Ubuntu 24.04's rsyslogd AppArmor profile lets it read `/etc/rsyslog.d/tls/*` (I chose that folder because the profile allows reading under `/etc/rsyslog.d/`; I couldn't confirm this offline).
11. The manager's octet-counted RFC 5424 frames land in the file, and `grep '"action":"auth.login"'` matches (the BOM before the JSON shouldn't matter).

openssl and NTP:

12. `openssl s_client … -brief` prints `Verification: OK`.
13. `openssl req -x509 … -noenc` (OpenSSL 3.0) gives a `CA:TRUE` certificate from Ubuntu's default `v3_ca`, and the `issue` leaf (EC P-256, SAN, `serverAuth`, `digitalSignature`) is accepted by Go (agent), Python (manager → sink) and curl.
14. The exact `timedatectl set-ntp true` error text when no NTP service is installed (I wrote `NTP not supported`).

## Check results (run locally, Git Bash, Python from the main repo venv with `-I`)

- `check_runbook_text.py deploy/runbooks/manager-install.md deploy/runbooks/manager-operations.md`: `OK 2 files, 50 sh blocks, 0 findings`. With `README.md` added: `OK 3 files, 57 sh blocks, 0 findings`. (Run over `agent-install.md` too, the script reports 2 findings, at L76 and L120, on the `bse_REPLACE_WITH_THE_ENROLMENT_TOKEN` placeholders. That file wasn't touched and the findings were already there.)
- `check_md_links.py deploy/runbooks/*.md README.md`: `OK 17 relative links checked, 0 findings`.
- `check_runbook_bootstrap.py`: `OK Bootstrap block (16 lines, fences included) vs TS L1018-L1033`.
- My own extraction of every ```sh block in both runbooks, then `bash -n`: 50 blocks, 0 failures. `shellcheck` isn't installed locally. `systemd-analyze` isn't available on Windows, so the two new units are unverified here (item 8).

## Notes for the walk

- §1.2's admin commands run on an admin workstation with `bao` signed in. The token is created in §5, after the first block of §5 has made the empty 0600 `vault.token`, because that block empties every secret file.
- The token check and the renewal need `BITSCAN_VAULT_ADDR` and `BITSCAN_TOTP_KEY_REF` already in `manager.env` (they are written earlier in §5).
- §10's sink check runs on the sink host after the admin's TOTP enrolment.

## README (impl-manager-m6)

- `README.md` L194 (the **OpenBao** paragraph under "Starting the app"), 1 line changed. The last two sentences ("Use a periodic or non-expiring token whose policy allows only those two paths for the TOTP key. The manager does not renew tokens, so replacing the token is an operational step …") now read: the manager reads the token once at start-up and never renews it, so use the periodic token of `manager-install.md` section 1.2 (policy: only the two Transit paths for the TOTP key, plus renewing itself) and set up the renewal timer of section 5 there; to replace the token, follow `manager-operations.md` section 3. This also fixes "only those two paths", which contradicted the runbook policy's `auth/token/renew-self`.
- Rest of README grepped for OpenBao, vault, token, renew and audit sink: no other statement contradicts the runbooks (L24 runbook table, L79-L83 variables, L181 start-up and 503 behaviour, L188-L192 audit sink all agree). Unchanged.
- Checks (Git Bash, `-I`): `check_md_links.py README.md`: `OK 19 relative links checked, 0 findings`; `check_md_links.py deploy/runbooks/*.md README.md`: `OK 19 relative links checked, 0 findings`; `check_runbook_text.py README.md`: `OK 1 files, 7 sh blocks, 0 findings`. (`check_md_links.py` with no arguments checks nothing: `OK 0 relative links checked`.)

## Revision 2b (after TEST PASS, CHK-M6-133r2-07s and -18)

Two corrections, nothing else:

1. `manager-install.md` §1.1, lab CA block (L46-L48): `-addext "keyUsage=critical,keyCertSign,cRLSign"` added as a third continuation line of the `openssl req -x509 … -subj "/CN=Bitscan lab CA"` command. This is the exact form the tester verified OK under `openssl verify -x509_strict`, which fails without it with error 92 (no keyUsage on the CA, RFC 5280; Python 3.13 or later is strict by default).
2. `manager-operations.md` §3 step 1 (L63-L70): no traceback when the old token is invalid. The Python one-liner now reads stdin, and on empty input prints `no accessor: the old token is no longer valid` (exit 0) instead of letting `json.load` raise. With `--fail`, curl writes nothing to stdout on a 403 and reports `curl: (22) … error: 403` on stderr. The step's text now names both lines. A valid token still prints the accessor alone. Tried locally with empty input (prints the message, rc 0) and with `{"auth":{"accessor":"abc"}}` (prints `abc`).

Checks: `check_runbook_text.py` on both runbooks: `OK 2 files, 50 sh blocks, 0 findings`; `check_md_links.py deploy/runbooks/*.md README.md`: `OK 19 relative links checked, 0 findings`; my own `bash -n` over every sh block of both runbooks: 50 blocks, 0 failures.

To re-check: CHK-M6-133r2-07s (the lab CA block as written, then `openssl verify -x509_strict`) and CHK-M6-133r2-18 step 1 (on a valid token, then on a revoked one).

## Revision 2c (review nit 1, work/reviews/TASK-133-r2.md)

`manager-install.md` §5 "OpenBao token" (L323-L333) only. The workstation path (create there, paste with `sudoedit`) now comes first and is preferred, so the admin's own OpenBao token never reaches the manager host. The on-host path follows as a fallback: `bao login` with the admin token typed at its prompt, never `BAO_TOKEN`; then the unchanged `bao token create … | sudo tee …` line; then `bao token revoke -self` (to leave out if the admin still needs that token) and `rm -f ~/.vault-token`. Operations §3 step 2 is unchanged; it points to install §5 for this. Checks: `check_runbook_text.py` on both runbooks `OK 2 files, 50 sh blocks, 0 findings`; `check_md_links.py` `OK 19 relative links checked, 0 findings`; `bash -n` passes on the new block and on all 31 sh blocks of manager-install.md. Unsure: that `bao login` with no arguments prompts for a token with hidden input, and that it writes `~/.vault-token`, the name OpenBao's token helper keeps from Vault.

## Revision 2c-1 (re-check FAIL round 1, CHK-M6-133r2-30..33)

Cause: on success, `bao login` prints the admin token in its result table, so the token appeared on the manager host's screen and in its scrollback. Fix (`manager-install.md` §5, L325 and L328): `bao login` → `bao login -no-print` in the block and in the sentence before it, which now also says that without `-no-print` the token is shown on screen. The tester verified `-no-print`: same hidden prompt, `~/.vault-token` still written, and the token appears 0 times in the output. Sweep of both runbooks and the README for other commands that show a token: renew-self (install L346, ops L68) is piped into Python, which prints only lease, policies or accessor; the `lookup-self` probe (L351) and the renewal script (L370) use `-o /dev/null`; `bao token create -field=token` goes into `sudo tee` on the host, and on the workstation it prints on purpose, to be pasted; `bao token revoke` prints no token; README L331 `users create-api-token` shows the token once by design (impl-manager's file, untouched). No other change. Checks: `check_runbook_text.py` on both runbooks `OK 2 files, 50 sh blocks, 0 findings`; `check_md_links.py` `OK 19 relative links checked, 0 findings`; `bash -n` passes on all 31 sh blocks of manager-install.md.
