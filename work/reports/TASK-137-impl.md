# TASK-137 IMPL: README for the first release

Implementer: impl-manager, 2026-10-26. REQ-145; TS §8.7 (L1343–L1348), §3.1 (L165, L177), §8.2 (L1267); #6, #90, #91.

## What changed

Only `README.md` changed (+44 / −9). It contains no task id, REQ id, process note or secret.

- **Intro.** The "Supported hosts" line is split. Agent hosts are Ubuntu 22.04 and 24.04 (amd64, cgroup v2), and the manager host is Ubuntu 24.04 on amd64, as in `manager-install.md` §1.
- **Status.** The "M5" line is replaced by the 0.1.0 status: manager `0.1.0`, agent package `0.1.0-1`, tag `v0.1.0`, and what the release covers.
  - Compliance is not in 0.1.0. The runner and capread are idle, and compliance checks answer `runner_unavailable`. This wording is taken from `agent-install.md`.
  - The `0.1.0~preN-1` pre-release builds are not supported.
  - The line "The agent package and compliance scans do not run yet." is removed. In its place, one line says what the agent package installs and does.
- **New section "Installing a release":**
  - A table linking the three runbooks.
  - The release file list, taken from the `sums` job in `release.yml`. SBOMs are named generically ("CycloneDX SBOMs"), so the list stays true when the manager SBOMs from TASK-136 are added.
  - Download verification: copy `SHA256SUMS` from the release page (a different origin), never use the attached copy, then run `sha256sum -c --ignore-missing SHA256SUMS`, with the stop conditions. This follows the release notes text and the two runbooks.
  - Versions (semantic versioning plus the Debian revision).
  - Compatibility: manager N supports agents N and N−1, and agent N supports managers N and N−1. This is TS §8.2 L1267 and §8.7 L1348, the same wording as `agent-install.md` §6.
  - Upgrade order: manager first, linking `manager-operations.md` §1 and `agent-install.md` §6.
- **Setup (development).** "A production install method is not provided yet." becomes a pointer to *Installing a release*.
- **Configuration.** One sentence on where installed units read their settings: `manager.env`, plus the `*_FILE` variables pointing at credential copies (link to the install runbook §5). The other-host database CA (#97) is not restated anywhere; the README only links to the runbook.
- **Database.** A pointer to `manager-install.md` §3 for production, which covers TLS-only roles. The development Bootstrap block is unchanged.
- **Starting the app:**
  - The "not provided yet" clause is replaced by a link to the install runbook.
  - The audit-queue bullet now says the folder must exist before the first start under the unit (install runbook §4). Without that, it would contradict the runbook's "it fails to start if they are missing".
  - The certificate bullet is reworded to avoid contradicting `manager-operations.md` §2, which says *restart*, and #96, which is still pending its fact check. SIGHUP (what `systemctl reload` sends) still reloads the files the process was started with, as TS §8.7 L1343 says. Replacing the certificate on an installed manager now links to operations §2. The README makes no claim about whether `reload` refreshes the `LoadCredential=` copies.
- **Web UI.** "The release wheel already contains the built UI" is added before the build steps.

## Checks done

- Every relative link target exists: `deploy/runbooks/{manager-install,manager-operations,agent-install}.md`. The `#installing-a-release` anchor matches the new heading.
- Section numbers cited, checked against the runbooks:
  - install §3 PostgreSQL, §4 user and folders, §5 configuration and secrets;
  - operations §1 upgrade, §2 TLS certificate;
  - agent §6 upgrade.
- File names checked against `release.yml` (`sums` job `expect` list).
- `grep` for `TASK|REQ-|M[0-9]` found nothing new. The only remaining "not yet" is the literal CLI message `unknown or not yet implemented command`.
- No CI job lints the README.

## For the tester (TP-M6-09)

- Walk the *Installing a release* section, and the changed lines in *Configuration*, *Database*, *Starting the app* and *Web UI*, against the TASK-133 host.
- The verification step has the same commands as `manager-install.md` §2 and `agent-install.md` §2.
- If #96 resolves to "reload works", only `manager-operations.md` §2 changes. The README's certificate bullet is correct either way.
- Files changed outside the task list: none.
