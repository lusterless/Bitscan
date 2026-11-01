# TASK-210 IMPL: redaction engine (`internal/redact`)

Implementer: impl-agent-m10 (runner side), 2026-10-30. REQ-242, REQ-243 (fixtures are the tester's), REQ-244 (package level). Spec: TS §3.5 L251, §8.6 L1324, L1329–L1339, §8.1 L1249. Open items applied: #57, #113, #116 (a), #121, #133, #134 (as approved, decisions 2026-10-30). Plan: `work/plans/TASK-210.md` §2–§3.

## Files

- `agent/internal/redact/redact.go` (new, 98 lines): constants, `Stream`, `Captured`, `Apply`, the guarded replace.
- `agent/internal/redact/cutoff.go` (new, 39 lines): the built-in cut-off private-key rule.
- `agent/internal/redact/patterns.go` (new, 89 lines): `Compile`, `PatternError`, the can-match-empty walk.

161 code lines without comments and blank lines (estimate 180). No other file changed. Pure Go: `bytes`, `errors`, `fmt`, `regexp`, `regexp/syntax`, `unicode/utf8`.

## Interface (frozen once W1 passes)

```go
const ReadLimit = 1 << 20; StdoutCap = 65536; StderrCap = 16384; GrowthLimit = 4 << 20; MaxPatterns = 50; Marker = "[REDACTED]"
var ErrTooMany, ErrEmptyMatch error
type PatternError struct{ Index int; Err error }   // Error() = "redact: pattern <i> refused"; Unwrap() = Err
type Set struct{ /* unexported */ }
func Compile(patterns []string) (*Set, error)
type Stream int                                     // Stdout, Stderr
type Captured struct{ Data []byte; Overflow bool }
func (s *Set) Apply(c Captured, st Stream) (text string, truncated bool)
```

`PatternError.Error()` never holds the pattern text, a small hardening over the plan. Go's compile error quotes the pattern, so it is reachable only through `Unwrap`, `errors.Is` or `errors.As`. A careless `log(err)` in the runner can't leak a pattern. `Index` is 0-based in list order.

## How each acceptance point is met

| Point | Where |
| --- | --- |
| REQ-242 (1) secret across 64 KiB | `Apply` runs every pattern on the whole sanitised buffer (at most 1 MiB), then cuts. A `bsa_` token at byte 65,530 is already `[REDACTED]` before the cut. |
| (2) key past the 1 MiB read limit, with and without pattern 2 | `cutOff` always runs after the patterns (#133). It finds the start of the last END marker, then the first BEGIN starting after it, and replaces from there to the end with one `Marker`. Searches resume one byte after the previous END start, so overlapping markers (`…KEY-----BEGIN …`) are caught. A BEGIN with an END after it is left to the patterns. |
| (3) caps and rune boundary | Cut at `limit`, stepping back while `!utf8.RuneStart(b[n])`. stdout: `truncated` = `Overflow` or cut. stderr: always `false` (#113). |
| (4) invalid UTF-8 first | `bytes.ToValidUTF8(data, "�")` before any pattern. Markers are ASCII and matches fall on rune boundaries, so the result stays valid and the byte length is the UTF-8 length. U+0000 is kept (#121). |
| (5) no `$1` expansion | The replace callback returns the literal `Marker` bytes. |
| (6) `truncated` when over 1 MiB | `overflow` is carried through, even when redaction shrinks the text. A `Data` longer than `ReadLimit` (a caller bug) is cut to `ReadLimit` and counted as overflow. |
| (7) growth guard | `replace` uses `ReplaceAllFunc` and tracks the projected output size. Once it would pass `GrowthLimit`, the remaining matches are replaced by nothing, so the buffer never exceeds `len(src) + 4 MiB`. `Apply` then returns `Marker`, and `truncated` = (stream is stdout). This is a little stricter than the plan's check after `ReplaceAllLiteral`: it trips when the running size passes 4 MiB, even if later, longer matches would have shrunk it again (fail closed, contrived case). It also avoids the up-to-40 MiB intermediate that a full `ReplaceAllLiteral` of `[a-z]` on 4 MiB would build under `MemoryMax=256M`. |
| (8) fuzz property | Output ≤ cap, valid UTF-8, no secret body. Checked with a 20 s fuzz in a scratch copy (159k execs, no failure); the real `FuzzApply` is the tester's. |
| REQ-244 (1), (2) at package level | `Compile` refuses 51 entries with `ErrTooMany`. A compile failure (`(`, `a{1001}`, `\C`) is a `PatternError`. A nullable entry (`x*`, `(?:)`, `a?`, `\b`, `^`, plus `$`, `a|`, `(a*)+`, `\B`, `x{0,3}`) is a `PatternError` wrapping `ErrEmptyMatch`. 50 valid patterns, the five defaults and `[]` / `nil` compile; an empty list still gets the cut-off rule. The whole list is refused, never part of it. |
| REQ-243 fixtures | With the five TS §8.6 patterns: a shadow hash, a full PEM key, a cut-off OpenSSH key, `password=…`, `api_key: …`, a `bsa_` token, AKIA and ASIA ids are redacted; `install ok installed`, `PasswordAuthentication no`, `passwd: files` are unchanged (scratch smoke run). |

Nullability walk, on `syntax.Parse(p, syntax.Perl).Simplify()`:
- **nullable:** empty match, the zero-width assertions (`^ $ \A \z \b \B`), `*`, `?`, a zero-length literal, `{0,n}`;
- **pass through:** capture and `+` take their child's answer; concat is nullable when every child is, alternation when any child is;
- **not nullable:** char class, any-char, no-match.

Assertions count as nullable, so a pattern made only of assertions is refused (#134 (e): it could only insert markers).

Memory and logging: nothing is logged. `Apply` holds the sanitised copy plus one replace output at a time. One-plugin-at-a-time (#134 (h)) is the executor's lock (TASK-224), not this package's.

## Gates (run from `agent/`, Windows + Git Bash)

- `gofmt -l .`: prints nothing.
- `go vet ./internal/redact/...` and the same with `GOOS=linux`: clean.
- `golangci-lint run ./internal/redact/...` (Windows and `GOOS=linux`, with impl-agent-m10b's TASK-211 config in the tree): 0 issues.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK. `go mod verify`: all modules verified.
- The smoke test and fuzz ran in throwaway copies under `/tmp`, never in the tree.

## For the tester (tester-m10, TP-M10-03)

Mutation rows targeting this task. All are pure and run locally, in WSL and in CI; none needs a VM. G79 for -344 is the gate's VM + WSL run.

| CHK | Plant |
| --- | --- |
| -344 | Move the cut before the pattern loop in `Apply` |
| -345 | Call `cutOff` only when a pattern contains `BEGIN` |
| -347 | Drop `overflow` from the return |
| -348 | Remove the `RuneStart` step-back |
| -349 | Return `cut` for stderr |
| -350 | `ReplaceAll` with `$1`-style expansion instead of the literal marker |
| -351 | `> MaxPatterns` changed to `> 51` |
| -352 | `continue` on a compile error |
| -353 | `nullable` always `false` |
| -354 | Remove the `over` return in `Apply` |

- REQ-242 (2) "without pattern 2": `Compile(nil)` or the list without pattern 2. The overlap case `-----END RSA PRIVATE KEY-----BEGIN RSA PRIVATE KEY-----\nsecret` is worth a row: without pattern 2, the BEGIN starts inside the END's dashes.
- REQ-242 (7): `[a-z]` then `[A-Z]` on `"aB"` × 524,288 trips the guard in the first pass. stdout gives `("[REDACTED]", true)`, stderr `("[REDACTED]", false)`.
- `Apply` on a nil `*Set` panics by design (fail closed). The runner always gets its `Set` from `Compile`.
