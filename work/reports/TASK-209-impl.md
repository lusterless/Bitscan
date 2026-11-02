# TASK-209 IMPL: agent–runner protocol (`internal/runner/proto`)

Implementer: impl-agent-m10 (runner side), 2026-10-30. REQ-234. Spec: TS §3.7 L281–L283, §3.5 L249, L252, §6.5 L1165–L1184. Open items applied: #29, #60, #116 (a), #130 (as approved, decisions 2026-10-30). Plan: `work/plans/TASK-209.md` §2.

## Files

- `agent/internal/runner/proto/proto.go` (new, 174 lines): types, reason words, `Result` and its constructors, error values.
- `agent/internal/runner/proto/frame.go` (new, 183 lines): frames, request and reply codecs.

No other file changed. No new module. The package imports only `internal/agent/wire` and the standard library.

Size: 275 code lines without comments and blank lines (estimate 170). The extra is the 13 reason constants with their validity switch, the three strict reply structs, and the I/O-error classification in `readFrame` that TASK-218 needs to tell `broken` from `protocol` (below). Nothing outside the plan's scope was added.

## Interface (frozen once W1 passes)

```go
const Version = 1; MaxRequest = 32 << 20; MaxReply = 1 << 20; MaxStdout = 65536; MaxStderr = 16384

type Request struct { V int `json:"v"`; Job wire.Job `json:"job"`; MaxParallelPlugins int `json:"max_parallel_plugins"` }
type Reason string   // ReasonBusy … ReasonInternal: the 13 #130 (d) words
type Kind string     // KindAccepted, KindRefused, KindResult, KindDone
type Reply struct { Kind Kind; Reason Reason; Result Result }
type Result struct{ /* unexported wire.ResultItem */ }

func NewResult(item wire.ResultItem) (Result, error)
func (r Result) Item() wire.ResultItem             // deep copy (pointer fields copied)
func UnavailableResult(plugin wire.UUID, now time.Time) Result   // #131 (b)
func OverflowMarker(from Result) Result                           // #140
func WriteRequest(w io.Writer, req Request) error
func ReadRequest(r io.Reader) (Request, error)
func WriteReply(w io.Writer, rep Reply) error
func ReadReply(r io.Reader) (Reply, error)
func RefusalFor(err error) Reason                  // ReadRequest error -> refusal word

var ErrFrame, ErrMalformed, ErrNotCompliance error
```

Additions to the plan's listing, for the serve loop and the client (no new behaviour):
- `ErrNotCompliance` and `RefusalFor`. The plan says an inventory job "is `ErrMalformed`, mapped to `not_compliance` by the serve loop". To make that mapping possible, ReadRequest wraps both `ErrMalformed` and `ErrNotCompliance` (`errors.Is` finds either). `RefusalFor` returns `not_compliance` for that error and `malformed` for every other (r1). TASK-225 writes `refused <RefusalFor(err)>`.
- Error classes of `readFrame`, which TASK-218 needs for the #131 (c) words:
  - a clean end before any header byte wraps `io.EOF`, without `ErrFrame`, so it maps to `broken`;
  - a header or body cut short is `ErrFrame` wrapping `io.ErrUnexpectedEOF`;
  - a zero or oversize length is `ErrFrame`;
  - other read errors (deadlines: `os.ErrDeadlineExceeded`) are wrapped with `%w` as they are, so they map to `timeout`.

## How each acceptance point is met

| REQ-234 | Where |
| --- | --- |
| (1) Round trips | `WriteRequest` uses `wire.Encode`; `wire.Time` keeps its decoded text and UUIDs encode lowercase, so a decoded fixture job re-encodes byte for byte (checked in a scratch copy: decode → encode gives the identical frame). Replies: `{"type":"accepted"}`, `{"type":"done"}`, `{"type":"refused","reason":…}`, `{"type":"result","result":<item>}`. |
| (2) Refused at decode | `ReadRequest`: frame, then `wire.DecodeStrict` into `Request`. That refuses unknown or missing keys at any depth (`"command"` beside `job`, or inside a plugin), wrong types, null, trailing data (two JSON values), and the #60 bounds. Then `v != 1` gives `ErrMalformed`; an inventory job gives `ErrNotCompliance`; `max_parallel_plugins` outside 1–8 gives `ErrMalformed` (r1). A missing `max_parallel_plugins` is a missing key. `readFrame` reads the 4-byte header, and refuses a length of 0 or over the cap (32 MiB request, 1 MiB reply) **before reading any body byte**. A truncated frame is `ErrFrame`. |
| (3) Result caps | `checkItem`, shared by `NewResult`, `ReadReply` (through `NewResult`) and `WriteReply`: `wire.Validate` (the `error` enum is null, `spool_overflow` or `runner_unavailable`), stdout ≤ 65,536 and stderr ≤ 16,384 bytes, both valid UTF-8, and when `error` is set, `exit_code` null and empty streams. |
| (4) No command API | The only exported functions take a `Request` (a whole `wire.Job`), a `Reply`, a `wire.ResultItem`, a `wire.UUID` plus time, or an error. No exported function or type takes a command string. |
| (5) Windows and Linux | Pure Go, no build tags. |

Other points:
- #130 (i): `WriteReply` re-checks a result before sending. A zero `Result{}` fails (`wire.Validate` refuses its empty UUID), so a result that never went through a constructor can't be sent.
- A valid result always fits a reply frame: in the worst case every character is JSON-escaped to 6 bytes, so (65,536 + 16,384) × 6 ≈ 480 KiB < 1 MiB.
- Error texts are fixed words. Decoder errors, which can quote an input character, are dropped, never wrapped (checklist item 12).
- `writeFrame` refuses an empty or oversize body and writes header and body in one `Write`. `WriteRequest` writes nothing for a request the runner would refuse at decode.

## Gates (run from `agent/`, Windows + Git Bash)

- `gofmt -l .`: prints nothing.
- `go vet ./internal/runner/...` and `GOOS=linux go vet ./internal/runner/...`: clean.
- `golangci-lint run ./internal/runner/...` (Windows and `GOOS=linux`): 0 issues. One G115 was fixed by a bound check, not a `nolint`.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: OK. `go mod verify`: all modules verified.
- A smoke test was run in a throwaway copy under `/tmp` (not in the tree): round trip, the refusals above, the 4-byte-only read of an oversize header, reply shapes, the caps and copy semantics. It's evidence only; the real suite is TP-M10-02.

## For the tester (tester-m10, TP-M10-02)

- Mutation rows targeting this task (pure, they run locally, in WSL and in CI; none needs a VM):
  - **CHK-M10-323:** unknown key `"command"` beside `job` accepted. Plant: replace `wire.DecodeStrict` in `ReadRequest` with `json.Unmarshal`. Red in G75 and G78.
  - **CHK-M10-324:** inventory job accepted. Plant: drop the `Kind` case in `checkRequest`. Red in G72 and G78, together with TASK-213's own kind check.
- For the oversize-frame row, a reader that panics or fails on any read past 4 bytes proves the body is never read.
- `ReadRequest` returns a zero `Request` on every error, so the seen-set recording of #132 (c) happens only for requests that decode. As #132 (e) orders the checks, a resend of a request refused at decode is refused again the same way.
- The 0 and 5,001 plugin counts and `timeout_s` 0 and 601 are #60 wire bounds, so over the socket they are refused `malformed` at decode. TASK-213's `Checks` gives `bad_plugins` for the same values when it gets a `Request` built in a test. Both refuse, and nothing runs.

## Revision 1 (2026-10-30, the lead's Q1 ruling, raised by tester-m10)

The decisions row "tester-m10's M10 plan questions" Q1 says a socket request outside the #60 bounds, **including `max_parallel_plugins` 0 or 9**, is refused `malformed` at decode. `bad_parallel` and `bad_plugins` are TASK-213's unit-level words only. r0 mapped `max_parallel_plugins` to `bad_parallel` through `ErrBadParallel`.

Changes:
- `proto.go`: `ErrBadParallel` is removed. `RefusalFor` returns `not_compliance` for `ErrNotCompliance` and `malformed` for everything else.
- `frame.go`: `checkRequest` returns plain `ErrMalformed` for `max_parallel_plugins` outside 1–8.

`WriteRequest` still refuses such a request and writes nothing. Size is now 271 code lines. The gates (gofmt, vet on Windows and Linux, golangci-lint on Windows and Linux, the static Linux build) are green again, and the scratch smoke run shows `par0`, `par9` and a missing key all mapping to `malformed`.
