# Security invariants (every session)

These apply to all code. Each line is a hard rule from the approved spec; breaking one is a defect even if tests pass.

## Never add

- An endpoint, flag or code path that queues or runs an ad-hoc command. Jobs are built only from active plugins of enabled policies (TS §3.3).
- A push, wake-up, remote-shell channel or listening port on the agent, or any connection the manager opens to an agent. The agent opens every connection (TS §2.2, §3.3).
- An endpoint, setting, role or agent option that disables inventory collection (TS §3.4, §6.2).
- Cryptographic signing of `.bit` files or jobs, or a policy approval workflow. These were removed by the owner on purpose (TS §3.7, §8.1).
- Agent client certificates. The only certificate is the manager's server certificate; agents authenticate with their `bsa_` token (TS §2.2).
- A manager route or job that changes host settings, such as enabling the `bitscan-capread` helper (TS §3.7).
- Automatic remediation. BIT102 is a safety net; the runner sandbox is the real control, and both must exist (TS §1.2; SR §4.2).

## Accepted risks (TS §8.1) — document, never "mitigate" with signing

- Jobs are not signed. Whoever controls the manager or its database, or holds a stolen admin session or admin API token, can make every host return any file. Mitigations are least-privilege DB roles, admin TOTP, the hash-chained and externally shipped audit log, and alerts on every import.
- A compromised `bitscan-agent` can make its host's runner read any file there; treat it as a compromise of every secret on that host (TS §3.7). The agent and runner job checks catch mistakes, not attacks.
- Without pinning, a holder of a publicly trusted certificate for the manager's hostname can impersonate the manager to that agent. Pinning stays optional.
- Redaction removes only what its patterns match; every operator and admin can see raw output from every host.

## Secrets and output

- Store only the SHA-256 hash of any token (`bsu_`, `bsk_`, `bsa_`, `bse_`). Tokens are 256 random bits, base64url, with their prefix (TS §6.2).
- Never write plugin stdout or stderr, or any token, to application logs or journald (TS §3.1, §5.3, §8.1, §8.4). Application logs are structured JSON with `request_id`, `agent_id` and `job_id`.
- Raw stdout and stderr are returned only to the operator and admin roles; viewers get verdicts only (TS §6.2).
- Output is redacted on the host before truncation; unredacted output never leaves the host or reaches the spool (TS §3.5). Backups are encrypted.
- Operator and ExpectedResult (`eval_spec`) stay on the manager and are never sent to agents (TS §3.5).
- Manager secrets come from systemd `LoadCredential=` files or the vault, never from the repository or plain environment values (TS §8.7).

## Data handling

- SQL goes through parameterised queries or the ORM only. Never build SQL from strings (TS §8.1).
- Parse XML only with `defusedxml`: no DTD and no external entities (TS §4.1).
- Use RE2 for every regular expression that touches untrusted input or patterns (TS §4.5).
- Render all stored text as plain text in the UI; never inject HTML (TS §6.3).
- Escape CSV cells that start with `=`, `+`, `-`, `@`, a tab, a carriage return, or whitespace followed by one of these, by prefixing `'`. This applies to every export (TS §6.3).

## Authorisation

- Agent routes accept only `bsa_` tokens (and `bse_` for enrolment); user routes accept only `bsu_` and `bsk_` tokens. Enforce this per router (TS §6).
- Sensitive actions need a TOTP-verified session and must refuse API tokens: approve or reject enrolments, revoke agents, rebuild, re-evaluate, and manage users, enrolment tokens and settings (TS §6.2). They are also refused after 15 minutes of audit-sink outage until the queue drains (TS §5.3).
- `DELETE /policies/{id}` also needs an admin TOTP-verified session (TS §4.3, §6.2 route table), so API tokens are refused. Policy upload is not a sensitive action: an admin's API token may upload.
- An API token can never create API tokens or enrol or replace TOTP (TS §6.2).
- Only admins upload policies and only server administrators write the policy folder; every import is validated, audit-logged and alerted. Re-evaluation adds rows through the admin route only (TS §4.5, §8.1).
