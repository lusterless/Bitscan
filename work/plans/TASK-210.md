# Plan TASK-210: redaction and capture (D3)

Covers TASK-210 (`ag/internal/redact`) and TASK-214 (`ag/internal/runner/capture.go`, `result.go`), and the pattern part of TASK-213. REQ-241 to REQ-244. Open items #57, #113, #114, #116 (a), #121, #133, #134.

## 1. Spec quotes

- TS §3.5 L251: "The runner reads up to 1 MB of each stream, applies the job's redaction patterns (RE2; each match replaced with `[REDACTED]`; a `BEGIN … PRIVATE KEY` line with no matching end line is redacted to the end of the buffer), and only then truncates to 64 KB stdout and 16 KB stderr, so a secret cut by the cap is never partly returned. Unredacted output never leaves the host or reaches the spool. Redaction is best-effort: it removes only what the patterns match (§8.1)."
- TS §8.6 L1329: "Default redaction patterns (RE2, one per line, exactly as written; each match becomes `[REDACTED]`; no capture-group replacement)", then the five lines L1332–L1336.
- TS §4.5 L599: the manager rejects stdout over 64 KB or stderr over 16 KB as ERROR `oversize` (#116 (a): UTF-8 bytes, strictly over).
- TS §4.5 L593 and #113: "stdout truncated at 64 KB" is an ERROR; `truncated` means stdout only.

## 2. Package `ag/internal/redact` (TASK-210)

Pure Go (`regexp`, `regexp/syntax`, `bytes`, `unicode/utf8`); tests run on Windows and Linux.

```go
package redact

const (
    ReadLimit   = 1 << 20 // 1,048,576 bytes per stream (#134 (a))
    StdoutCap   = 65536
    StderrCap   = 16384
    GrowthLimit = 4 << 20 // #134 (f)
    MaxPatterns = 50
    Marker      = "[REDACTED]"
)

var (
    ErrTooMany    = errors.New("redact: more than 50 patterns")
    ErrEmptyMatch = errors.New("redact: a pattern can match the empty string")
)
type PatternError struct{ Index int; Err error } // never holds the pattern text

type Set struct{ res []*regexp.Regexp }
func Compile(patterns []string) (*Set, error)

type Stream int
const (Stdout Stream = iota; Stderr)

type Captured struct {
    Data     []byte // at most ReadLimit bytes
    Overflow bool   // more than ReadLimit bytes were produced
}

// Apply returns the text that may leave the runner and, for Stdout, whether
// it was truncated. It never returns more than the stream's cap in bytes and
// always returns valid UTF-8.
func (s *Set) Apply(c Captured, st Stream) (text string, truncated bool)
```

### Compile (`patterns.go`)

1. `len(patterns) > 50` → `ErrTooMany`.
2. For each pattern `i`: `syntax.Parse(p, syntax.Perl)` then `regexp.Compile(p)`; any error → `PatternError{i, err}` (the error text is Go's, which may quote the pattern, so callers log only `Index`).
3. Can-match-empty: walk the parsed `*syntax.Regexp` (after `Simplify`): `OpEmptyMatch`, `OpBeginLine`, `OpEndLine`, `OpBeginText`, `OpEndText`, `OpWordBoundary`, `OpNoWordBoundary` → nullable; `OpLiteral`, `OpCharClass`, `OpAnyChar*` → not; `OpCapture` → its child; `OpStar`, `OpQuest` → nullable; `OpPlus` → child; `OpRepeat` → `Min == 0` or child; `OpConcat` → all children nullable; `OpAlternate` → any child nullable. Nullable → `PatternError{i, ErrEmptyMatch}`. The five defaults are not nullable (each starts with a literal).
4. An empty list gives an empty `Set` (the cut-off rule still runs).

### Apply (`redact.go`), in this order

1. `b := bytes.ToValidUTF8(c.Data, []byte("�"))` (#134 (c)): each run of invalid bytes becomes one U+FFFD; U+0000 is kept.
2. For each regexp in list order: `b = re.ReplaceAllLiteral(b, []byte(Marker))`; if `len(b) > GrowthLimit` → return `Marker`, and `truncated = (st == Stdout)` (#134 (f)).
3. `b = cutOff(b)` (`cutoff.go`, §3).
4. `cap := StdoutCap or StderrCap`; if `len(b) > cap`: `cut := cap; for cut > 0 && !utf8.RuneStart(b[cut]) { cut-- }; b = b[:cut]`, and mark cut.
5. `truncated = st == Stdout && (c.Overflow || cut)`; stderr returns `false` always (#113).

Notes:
- `ReplaceAllLiteral` never expands `$1` (REQ-242 (5)).
- Go's `regexp` is RE2 syntax with linear-time matching; `(?s)`, `(?i)`, `\b`, `\z` used by the defaults are supported. A construct `google-re2` accepts but Go refuses (rare) fails step 2 of Compile and the job is refused (#134, owner note).
- Memory: `Data` ≤ 1 MiB; sanitising can at most triple invalid bytes; the growth guard bounds every intermediate to 4 MiB. The executor holds a lock so only one plugin is redacted at a time (#134 (h)).

## 3. Cut-off private-key rule (`cutoff.go`, #133)

```go
var (
    begin = regexp.MustCompile(`-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----`)
    end   = regexp.MustCompile(`-----END [A-Z0-9 ]*PRIVATE KEY-----`)
)
func cutOff(b []byte) []byte
```

Let `e` be the end offset of the last `end` match (0 if none). The first `begin` match starting at or after `e` has no END after it; replace from its start to `len(b)` with one `Marker`. A `begin` before `e` has an END after it and is left to the patterns. One pass, linear. The rule always runs, whatever the job's list holds (#133); with default pattern 2 present it usually finds nothing, because pattern 2 already replaced the block (its `\z` branch handles the same case).

## 4. Capture and result (TASK-214, `ag/internal/runner`)

```go
// Capture reads r until EOF: the first ReadLimit bytes are kept, the rest is
// read and discarded so the writer never blocks (#134 (b)).
func Capture(r io.Reader) (redact.Captured, error)

// ExitCode maps a wait status per #114 / #136 (e): exited → status;
// signalled → 128 + signal.
func ExitCode(ws syscall.WaitStatus) int64   // portable build: takes (exited bool, status, signal int)

type Outcome struct {
    Plugin    wire.UUID
    Started   time.Time
    Finished  time.Time
    Stdout    redact.Captured
    Stderr    redact.Captured
    Exit      int64
    TimedOut  bool
}
// Build applies the set to both streams and returns a validated Result.
// If NewResult fails (a bug), it returns UnavailableResult for the plugin:
// raw or over-cap text is never sent (REQ-241, CHK-M10-357).
func Build(set *redact.Set, o Outcome) proto.Result
```

- Both pipes are read concurrently (one goroutine each), started before `Wait`, as `os/exec` requires.
- `started_at`/`finished_at` from the runner's clock just before `Start` and just after `Wait`, formatted by `wire.NewTime` (UTC, `Z`).
- After `Build` returns, the `Captured` buffers are dropped; nothing raw is logged or kept (#134 (i)).

## 5. Fixtures and tests (tester)

- TP-M10-03: the five patterns are extracted at test time from the `text` block after "Default redaction patterns" in TS §8.6 (the same approach as the M1 schema-diff test), compared byte for byte with the manager's seeded default (`manager/bitscan_manager/db/migrations/` seed), then used for the REQ-243 fixtures. Must be redacted: a shadow line (`root:$6$…:19000:0:99999:7:::`), a full PEM key, a cut-off PEM key, a full OpenSSH key, `password=hunter2`, `api_key: abc`, `bsa_` / `bse_` / `bsu_` / `bsk_` tokens of 43 characters, `AKIAIOSFODNN7EXAMPLE`, an `ASIA…` id. Must stay unchanged: `install ok installed`, `PasswordAuthentication no`, `passwd: files`, and the expected outputs of the `bits/samples/` plugins.
- The shared corpus `manager/tests/contract/fixtures/redaction/corpus.json` (input → expected match spans per default pattern) is checked by the Go suite and by `manager/tests/test_redaction_crosscheck.py` with `google-re2` (REQ-243 (3)).
- Fuzz (`FuzzApply`): random text with secrets inserted at random offsets, including across 65,536 and across 1,048,576; property: no secret's random body in the output; output ≤ cap; output valid UTF-8.
- Mutation rows CHK-M10-344 to -357.
