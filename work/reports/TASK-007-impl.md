# TASK-007 IMPL report: agent systemd units, verbatim from TS §3.7

Implementer: impl-deploy. REQ-016. Implements TS §3.7 (unit files only) and TS §3.1 (unit list). Needs two approvals (TS §8.2).

## What changed

Five new files, each the exact contents of its TS §3.7 `ini` block with the two fence lines removed. Nothing reworded, added or reordered. The files were produced by extracting the spec lines with `sed`, not by retyping.

| File | TS lines (fences included) | Lines |
|---|---|---|
| `deploy/systemd/bitscan-runner.socket` | L289–L302 | 12 |
| `deploy/systemd/bitscan-runner.service` | L308–L363 | 54 |
| `deploy/systemd/bitscan-agent.service` | L369–L408 | 38 |
| `deploy/systemd/bitscan-capread.socket` | L437–L449 | 11 |
| `deploy/systemd/bitscan-capread.service` | L451–L482 | 30 |

I re-checked the line ranges against `docs/spec/Technical_Specification.md` myself: each start line is exactly ```` ```ini ```` and each end line is exactly ```` ``` ````. The spec is UTF-8 with LF line endings, no CR bytes, and these blocks are pure ASCII. `.gitattributes` sets `* text=auto eol=lf`, so git keeps the files byte-identical.

The D-Bus policy (`deploy/dbus/`) is deferred to M6 with the `.deb` (REQ-016).

## How to check (run from the repository root, Git Bash or Linux)

```bash
S=docs/spec/Technical_Specification.md; rc=0; while read s e f; do
  [ "$(sed -n "${s}p" $S)" = '```ini' ] && [ "$(sed -n "${e}p" $S)" = '```' ] || { echo "FENCE MISMATCH $f"; rc=1; }
  if sed -n "${s},${e}p" $S | sed '1d;$d' | cmp -s - "deploy/systemd/$f"; then echo "IDENTICAL $f"; else echo "DIFF $f"; rc=1; fi
done <<'EOF'
289 302 bitscan-runner.socket
308 363 bitscan-runner.service
369 408 bitscan-agent.service
437 449 bitscan-capread.socket
451 482 bitscan-capread.service
EOF
grep -nE '^[^#].*#' deploy/systemd/bitscan-{agent,runner,capread}.* && rc=1 || echo "no end-of-line comments"
grep -n '^\[Install\]' deploy/systemd/bitscan-capread.service && rc=1 || echo "capread.service has no [Install]"
grep -l $'\r' deploy/systemd/* && rc=1 || echo "no CR bytes"
echo "rc=$rc"
```

Local result (Windows 11, Git Bash): all five `IDENTICAL`, `no end-of-line comments`, `capread.service has no [Install]`, `no CR bytes`, `rc=0`.

Negative check: in a temporary copy, `TasksMax=64` changed to `TasksMax=64 # planted` made `cmp` exit 1 (`differ: char 1615, line 48`) and the end-of-line comment grep reported line 48. The copy was deleted; the tree has no planted change.

## systemd-analyze verify

NOT RUN locally: this machine has no systemd, and WSL and Docker are not installed (`systemd-analyze` is not on the PATH). It runs in CI in TASK-010 (`units.yml`), with stub binaries at `/usr/sbin/bitscan-{agent,runner,capread}`, where it must exit 0 with no output. Without the binaries, only "not executable" errors are acceptable (CLAUDE.md Commands, "Units").

## Notes for the tester

- The comparison command above is the acceptance check; it is not committed as a test file (tests are yours).
- Security-critical directives (packaging-and-units.md) are present because the files are the spec text: for example the runner keeps `ProtectHome=read-only`, `NoExecPaths=/` with `ExecPaths=/usr /bin /sbin /lib -/lib64`, `SystemCallFilter=~@debug ...`, `IPAddressDeny=any`; `ProtectControlGroups=` and `PrivateNetwork=` are unset on the runner; `bitscan-capread.service` has no `[Install]`, `UMask=` or `SystemCallErrorNumber=`.
