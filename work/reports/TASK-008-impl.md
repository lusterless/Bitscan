# TASK-008 IMPL report: manager systemd units, verbatim from TS §8.7

Implementer: impl-deploy. REQ-016, REQ-008. Implements TS §8.7 (unit files only).

## What changed

Four new files, each the exact contents of its TS §8.7 `ini` block with the two fence lines removed. Nothing reworded, added or reordered. The files were produced by extracting the spec lines with `sed`, not by retyping.

| File | TS lines (fences included) | Lines |
|---|---|---|
| `deploy/systemd/bitscan-manager.service` | L1352–L1401 | 48 |
| `deploy/systemd/bitscan-manager-migrate.service` | L1405–L1435 | 29 |
| `deploy/systemd/bitscan-manager-maintain.service` | L1439–L1467 | 27 |
| `deploy/systemd/bitscan-manager-maintain.timer` | L1469–L1480 | 10 |

I re-checked the line ranges against `docs/spec/Technical_Specification.md` myself: each start line is exactly ```` ```ini ```` and each end line is exactly ```` ``` ```` (L1480 is the last line of the spec). The spec is UTF-8 with LF line endings, no CR bytes, and these blocks are pure ASCII. `.gitattributes` sets `* text=auto eol=lf`.

`ExecStart=/usr/bin/bitscan-manager serve` (and `db migrate`, `db maintain`) is copied as written. How the manager is installed to `/usr/bin` is Open spec question #6 (packaging-and-units.md); this task does not decide it. REQ-008 (TASK-002) only provides the console script so CI can verify the units against a real executable.

## How to check (run from the repository root, Git Bash or Linux)

```bash
S=docs/spec/Technical_Specification.md; rc=0; while read s e f; do
  [ "$(sed -n "${s}p" $S)" = '```ini' ] && [ "$(sed -n "${e}p" $S)" = '```' ] || { echo "FENCE MISMATCH $f"; rc=1; }
  if sed -n "${s},${e}p" $S | sed '1d;$d' | cmp -s - "deploy/systemd/$f"; then echo "IDENTICAL $f"; else echo "DIFF $f"; rc=1; fi
done <<'EOF'
1352 1401 bitscan-manager.service
1405 1435 bitscan-manager-migrate.service
1439 1467 bitscan-manager-maintain.service
1469 1480 bitscan-manager-maintain.timer
EOF
grep -nE '^[^#].*#' deploy/systemd/bitscan-manager* && rc=1 || echo "no end-of-line comments"
grep -l $'\r' deploy/systemd/bitscan-manager* && rc=1 || echo "no CR bytes"
echo "rc=$rc"
```

Local result (Windows 11, Git Bash): all four `IDENTICAL`, `no end-of-line comments`, `no CR bytes`, `rc=0`. The same command with all nine rows (the five from TASK-007 plus these four) also gave `rc=0`.

## systemd-analyze verify

NOT RUN locally: this machine has no systemd, and WSL and Docker are not installed (`systemd-analyze` is not on the PATH). It runs in CI in TASK-010 (`units.yml`), with `/usr/bin/bitscan-manager` installed from TASK-002, where it must exit 0 with no output. Without the binary, only "not executable" errors are acceptable.

## Notes for the tester

- The comparison command above is the acceptance check; it is not committed as a test file.
- Only the migrate and maintain units load `migrate_dsn`, both with `DynamicUser=yes`; the manager unit loads `app_dsn`, `retention_dsn`, `tls_cert`, `tls_key` and `vault_token`. The migrate unit has `Before=bitscan-manager.service`; the timer has `OnCalendar=daily` and `Persistent=true`.
