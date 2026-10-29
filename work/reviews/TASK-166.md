# TASK-166 REVIEW: CLI `bitscan-manager bits rebuild`

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-28. REQ-175. High risk (importer and CLI; TS §8.2 two approvals: this is the first).

Scope reviewed, per `work/reports/TASK-166-impl.md`:
- `manager/bitscan_manager/cli/bits.py`: new, 145 non-blank lines.
- `manager/bitscan_manager/cli/__init__.py`: +5, the dispatch and the epilog line.

Two files.

TEST: PASS (`work/reports/TASK-166-test.md`, tester-m7).
- 12/12, covering REQ-175 (1)–(6) plus the failed and not-running exit-1 paths. 7/7 plants red.
- Plant c7 had to be re-run with `PYTHONPATH`, because the shared venv's console script imports the installed tree. The lead's shared-venv check confirms that plants c1–c6 ran the plant copy.

Spec read: TS §8.7 L1347, §4.2 L540, §4.6 L613; `.claude/rules/manager/config-and-cli.md` "Server CLI"; #107 (a)–(f); TASK-157 r2 (`NOT_RUNNING`); the TASK-046 rule (no DSN content in any output).

## Checks
1. **Secrets (TS §8.7; security invariants).**
   - The DSN is read only from `/etc/bitscan/secrets/app.dsn`, through the serve profile's loader (readable, UTF-8, 64 KiB at most, TLS `sslmode` required). It is never read from argv or the environment (plant c1).
   - Messages name the file, never its content.
   - A database error prints only its exception type (plant c3), and the canary password appears in no output.
2. **Folder (#107 (a)).**
   - The folder is `BITSCAN_BITS_DIR` from the environment, else the last line of `manager.env`, else the default.
   - A missing folder or `uploaded/` exits 2, which stops a rebuild of a wrong, empty folder from deleting every policy (plant c2).
   - An unreadable `manager.env` exits 2 without showing its content.
3. **Run (#107 (d)–(f)).** It calls `rebuild.start_task` with `requested_by` NULL, then `rebuild.run` in the foreground with actor `cli:root`. The run waits on the catalog lock (REQ-175 (4)) and writes the same alerts as the API rebuild. There is no upload finish, integrity check or prompt. The one-connection pool is closed in a `finally`.
4. **Output and exit codes (#107 (b), (c)).**
   - One line per file, then the not-imported, leftover and deleted lines, then a summary.
   - It exits 0 when the rebuild committed (rejected files included, plant c5), 1 when it failed or did not run (`NOT_RUNNING`, plant c4), and 2 for usage and configuration errors.
   - File names printed on stdout can't carry terminal control codes, because `folders.storable` already refuses names with control characters.
5. **Layering.** The CLI only resolves its configuration and calls `rebuild`; usage errors exit before any database module loads.

## Findings
None blocking or should-fix.

1. nit, `cli/__init__.py:16`: the new epilog line `bits rebuild re-import …` isn't padded like its neighbours, which align their descriptions at column 33. Pad it to match.
2. nit, `bits.py:116`: a database error after `start_task` has written the row leaves that task `running` until the next `serve` start-up fails it (TS §4.2 L540). Printing the task id on that stderr line would help an operator match it.
