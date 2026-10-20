# TASK-004 TEST report: Go module, golangci-lint config, binary stubs

Tester: tester. REQ-010, REQ-011, REQ-012. Date 2026-10-20. Impl report: `work/reports/TASK-004-impl.md` (round 2 section). Toolchain: go1.27.2 windows/amd64, golangci-lint 2.14.0.

## Verdict: PASS (round 3)

- Round 1 was FAIL on CHK-M0-076: four stdlib listener APIs passed lint.
- Round 2 fixed that and was PASS.
- The reviewer then asked for changes (`work/reviews/TASK-004.md`, findings 1 to 3: generated-file exclusion, embedded and interface `http.Server`, the `InsecureSkipVerify` field). `main` added syscall Socket and Bind, x/sys, `net.FileListener` and nolintlint.
- Round 3 closes all of these (CHK-M0-076-r3, -r3-ctl, -r3-nolint), and the rounds 1 and 2 regression is unchanged (CHK-M0-070-r3).

REQ-010 (3) was reworded on 2026-10-20 (planner-m0) and is checked by the `CGO_ENABLED=1 go list` CgoFiles listing (CHK-M0-063; the CI step is CHK-M0-147 in TASK-010). The residual — a specific, explained `//nolint:forbidigo // reason` still suppresses the guard — belongs to the TASK-010 grep step (review finding 4).

## Commands and counts

The `$P;` PATH line was used. Builds wrote to temp dirs. Every plant went into a `mktemp -d` copy of `go.mod`, `.golangci.yml` and `cmd/`, was made gofmt-clean, and the copy was deleted afterwards. Each group started with an unmodified-copy control, which exited 0.
- Clean tree: gofmt (empty), `golangci-lint run ./...` (`0 issues.` under GOOS windows, linux/amd64 and linux/arm64), `golangci-lint config verify`, `go vet ./...`, `go mod verify` (`all modules verified`), `go test ./...`, and the CgoFiles listing (empty, amd64 and arm64): all exit 0.
- Builds: 2 architectures, 6 binaries, all CGO_ENABLED=0 and static (ELF proxy).
- Round 3: 20 new plants (15 red, 2 green controls, 3 nolint red, 1 explained nolint green as a residual), 0 mismatches. Regression of rounds 1 and 2: 32 plants, 0 mismatches.

## Acceptance criteria and rows in [tests/m0/report.md](../../tests/m0/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-010 (1): amd64 and arm64 `CGO_ENABLED=0` builds give 3 binaries each | CHK-M0-060 | PASS |
| REQ-010 (2): `go version -m` shows `CGO_ENABLED=0`, `GOOS=linux`, matching `GOARCH`; statically linked | CHK-M0-061, CHK-M0-062 | PASS (static: ELF proxy; `file` NOT RUN locally, CI) |
| REQ-010 (3), reworded: the CgoFiles listing prints nothing, and prints the package for a planted `import "C"` file | CHK-M0-063 | PASS |
| REQ-010 (4): exits non-zero within 1 s, no stdout, one `not implemented` stderr line | CHK-M0-064 | PASS (Windows proxy); Linux run NOT RUN locally (CI, CHK-M0-146) |
| REQ-011 (1): gofmt, golangci-lint and `go mod verify` pass | CHK-M0-065, CHK-M0-067, CHK-M0-077 | PASS |
| REQ-011 (2): an unformatted file is listed by gofmt | CHK-M0-066 | PASS |
| REQ-011 (3): an ignored error is red | CHK-M0-068 | PASS |
| REQ-011 (4): a `%v` wrap is red (also `%s`; `%w` is green) | CHK-M0-069 | PASS |
| REQ-011 (5): `go mod verify` prints `all modules verified` | CHK-M0-077 | PASS (no red case possible until M6) |
| REQ-012 (1): net.Listen, ListenTCP, ListenUDP, ListenUnix, ListenPacket (and Unixgram, IP, MulticastUDP) are red | CHK-M0-070, CHK-M0-073, CHK-M0-074, CHK-M0-070-r2 | PASS (also in other packages, and through alias, function-value and dot-import evasions) |
| REQ-012 (2): http.ListenAndServe and ListenAndServeTLS are red | CHK-M0-071 | PASS |
| REQ-012 (3): `InsecureSkipVerify: true` is red | CHK-M0-072 | PASS |
| REQ-012 (4): the same calls in `_test.go` pass | CHK-M0-075, CHK-M0-076-ctl | PASS |
| REQ-012 statement: other stdlib listeners (ListenConfig, http.Server methods, http.Serve and ServeTLS, httptest, syscall.Listen) | CHK-M0-076 | PASS (round 2) |
| G10 `go test ./...` | CHK-M0-078 | PASS (a planted failing test is red) |

## Notes

- golangci-lint is run on Windows here, so it type-checks for GOOS=windows. Linux-only files (build tags) are linted only in CI.
- `InsecureSkipVerify: true` and package-level `http.Serve` and `http.ServeTLS` stay red in `_test.go` files through gosec, per `main`'s ruling.
- Needs two approvals (TS §8.2): the reviewer plus the user.
