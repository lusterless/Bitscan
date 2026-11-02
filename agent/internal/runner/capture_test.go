// TP-M10-07 (tester-m10): capture and result building, REQ-241, REQ-242
// through the capture path; #113, #114, #134 (b). Internal test (package
// runner) for the portable exitCode. Pure part: Windows and Linux.
package runner

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/redact"
	"bitscan.local/agent/internal/runner/proto"
)

const capPlugin = wire.UUID("abcdef00-0000-4000-8000-000000000001")

// pipeWrite writes n bytes of b's pattern into an os.Pipe from a goroutine
// and returns the read end and a channel that reports when the writer is
// done (it can only finish if the reader keeps draining).
func pipeWrite(t *testing.T, chunk []byte, n int) (*os.File, chan struct{}) {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		defer func() { _ = w.Close() }()
		left := n
		for left > 0 {
			c := chunk
			if len(c) > left {
				c = c[:left]
			}
			k, err := w.Write(c)
			if err != nil {
				return
			}
			left -= k
		}
	}()
	t.Cleanup(func() { _ = r.Close() })
	return r, done
}

// CHK-M10-044: 1 MiB kept, the rest drained, Overflow exact at the boundary.
func TestCaptureLimitAndDrain(t *testing.T) {
	for _, tc := range []struct {
		n        int
		keep     int
		overflow bool
	}{{0, 0, false}, {1, 1, false}, {redact.ReadLimit, redact.ReadLimit, false}, {redact.ReadLimit + 1, redact.ReadLimit, true}, {3 << 20, redact.ReadLimit, true}} {
		r, done := pipeWrite(t, bytes.Repeat([]byte("0123456789abcdef"), 4096), tc.n)
		got := make(chan redact.Captured, 1)
		go func() {
			c, err := Capture(r)
			if err != nil {
				t.Error(err)
			}
			got <- c
		}()
		select {
		case <-done:
		case <-time.After(30 * time.Second):
			t.Fatalf("n=%d: the writer blocked (the rest was not drained)", tc.n)
		}
		c := <-got
		if len(c.Data) != tc.keep || c.Overflow != tc.overflow {
			t.Fatalf("n=%d: kept %d overflow %v, want %d %v", tc.n, len(c.Data), c.Overflow, tc.keep, tc.overflow)
		}
		want := bytes.Repeat([]byte("0123456789abcdef"), (tc.keep/16)+1)[:tc.keep]
		if !bytes.Equal(c.Data, want) {
			t.Fatalf("n=%d: kept bytes are not the first %d", tc.n, tc.keep)
		}
	}
}

// CHK-M10-044 (read error): the bytes so far come back with the error.
type errAfter struct{ n int }

func (e *errAfter) Read(p []byte) (int, error) {
	if e.n <= 0 {
		return 0, io.ErrUnexpectedEOF
	}
	k := min(len(p), e.n)
	for i := range k {
		p[i] = 'z'
	}
	e.n -= k
	return k, nil
}

func TestCaptureReadError(t *testing.T) {
	c, err := Capture(&errAfter{n: 10})
	if err == nil || len(c.Data) != 10 {
		t.Fatalf("err %v, kept %d", err, len(c.Data))
	}
	c, err = Capture(&errAfter{n: redact.ReadLimit + 5})
	if err == nil || len(c.Data) != redact.ReadLimit || !c.Overflow {
		t.Fatalf("past the limit: err %v kept %d overflow %v", err, len(c.Data), c.Overflow)
	}
}

// CHK-M10-046: REQ-241 (1) exit codes, portable form; never negative.
func TestExitCodeMapping(t *testing.T) {
	for _, tc := range []struct {
		sig          bool
		status, sign int
		want         int64
	}{
		{false, 0, 0, 0}, {false, 1, 0, 1}, {false, 126, 0, 126}, {false, 127, 0, 127}, {false, 255, 0, 255},
		{true, 0, 9, 137}, {true, 0, 15, 143}, {true, 0, 11, 139}, {true, 0, 1, 129}, {true, 0, 6, 134},
	} {
		if got := exitCode(tc.sig, tc.status, tc.sign); got != tc.want || got < 0 {
			t.Errorf("exitCode(%v, %d, %d) = %d, want %d", tc.sig, tc.status, tc.sign, got, tc.want)
		}
	}
}

func defaultsSet(t *testing.T) *redact.Set {
	t.Helper()
	s, err := redact.Compile(specDefaults(t))
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// CHK-M10-047: REQ-241 (2), (4) Build: UTC Z times, start ≤ end, timed_out,
// truncated, redaction of both streams, NewResult passes.
func TestBuildItem(t *testing.T) {
	set := defaultsSet(t)
	start := time.Date(2026, 10, 30, 9, 0, 0, 123456789, time.FixedZone("CET", 3600))
	tok := "bsa_" + strings.Repeat("Q", 43)
	o := Outcome{
		Plugin: capPlugin, Started: start, Finished: start.Add(1500 * time.Millisecond),
		Stdout:   redact.Captured{Data: []byte("out " + tok + "\n"), Overflow: true},
		Stderr:   redact.Captured{Data: []byte("password=hunter2\n")},
		Exit:     137,
		TimedOut: true,
	}
	r := Build(set, o)
	it := r.Item()
	if it.Error != nil || it.ExitCode == nil || *it.ExitCode != 137 || !it.TimedOut || !it.Truncated ||
		it.Stdout != "out [REDACTED]\n" || it.Stderr != "[REDACTED]\n" || it.PluginUUID != capPlugin {
		t.Fatalf("item %+v", it)
	}
	b, _ := json.Marshal(it)
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	sa, fa := m["started_at"].(string), m["finished_at"].(string)
	if !strings.HasSuffix(sa, "Z") || !strings.HasSuffix(fa, "Z") || !it.StartedAt.Time().Equal(start) ||
		it.FinishedAt.Time().Before(it.StartedAt.Time()) {
		t.Fatalf("times %s %s", sa, fa)
	}
	if _, err := proto.NewResult(it); err != nil {
		t.Fatalf("NewResult: %v", err)
	}
	// A clock step back never gives finished_at < started_at.
	o.Finished = start.Add(-time.Hour)
	if it := Build(set, o).Item(); it.FinishedAt.Time().Before(it.StartedAt.Time()) {
		t.Fatal("finished_at before started_at")
	}
	// Not over 1 MiB, not cut: truncated false; stderr never truncated.
	o.Stdout = redact.Captured{Data: []byte("x")}
	o.Stderr = redact.Captured{Data: bytes.Repeat([]byte("e"), 20000), Overflow: true}
	if it := Build(set, o).Item(); it.Truncated || len(it.Stderr) != redact.StderrCap {
		t.Fatalf("truncated %v stderr %d", it.Truncated, len(it.Stderr))
	}
}

// CHK-M10-048, CHK-M10-357: when the item can't pass NewResult, the plugin is
// runner_unavailable and no raw text goes out; and no log holds output.
func TestBuildFallbackNeverRaw(t *testing.T) {
	var logs bytes.Buffer
	old := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{Level: slog.LevelDebug})))
	defer slog.SetDefault(old)
	set := defaultsSet(t)
	canary := "M10CANARY-RAW-OUTPUT"
	r := Build(set, Outcome{
		Plugin: "not-a-uuid", Started: time.Unix(0, 0), Finished: time.Unix(1, 0),
		Stdout: redact.Captured{Data: []byte(canary)}, Stderr: redact.Captured{Data: []byte(canary)}, Exit: 0,
	})
	it := r.Item()
	if it.Error == nil || *it.Error != wire.ErrRunnerUnavailable || it.Stdout != "" || it.Stderr != "" || it.ExitCode != nil {
		t.Fatalf("fallback item %+v", it)
	}
	b, _ := json.Marshal(it)
	if strings.Contains(string(b), canary) || strings.Contains(logs.String(), canary) {
		t.Fatal("raw output left the build")
	}
}

// CHK-M10-049: REQ-242 (6) through the capture path.
func TestCaptureThenBuildOverflow(t *testing.T) {
	r, _ := pipeWrite(t, []byte(strings.Repeat("a", 4096)), redact.ReadLimit+1)
	c, err := Capture(r)
	if err != nil {
		t.Fatal(err)
	}
	set, err := redact.Compile([]string{"a+"})
	if err != nil {
		t.Fatal(err)
	}
	it := Build(set, Outcome{Plugin: capPlugin, Started: time.Unix(0, 0).UTC(), Finished: time.Unix(1, 0).UTC(), Stdout: c}).Item()
	if it.Stdout != "[REDACTED]" || !it.Truncated {
		t.Fatalf("stdout %q truncated %v", it.Stdout, it.Truncated)
	}
}

// CHK-M10-050: the runner_unavailable item shape (REQ-241 (5)).
func TestUnavailableShape(t *testing.T) {
	it := proto.UnavailableResult(capPlugin, time.Unix(5, 0)).Item()
	if it.ExitCode != nil || it.Stdout != "" || it.Stderr != "" || it.TimedOut || it.Truncated ||
		it.Error == nil || *it.Error != wire.ErrRunnerUnavailable {
		t.Fatalf("%+v", it)
	}
}

// Both streams captured concurrently never deadlock even when one stream is
// silent and the other writes 3 MiB (portable form with two pipes).
func TestCaptureTwoStreamsConcurrently(t *testing.T) {
	r1, d1 := pipeWrite(t, []byte("1"), 3<<20)
	r2, d2 := pipeWrite(t, []byte("2"), 0)
	var wg sync.WaitGroup
	var c1, c2 redact.Captured
	wg.Add(2)
	go func() { defer wg.Done(); c1, _ = Capture(r1) }()
	go func() { defer wg.Done(); c2, _ = Capture(r2) }()
	ch := make(chan struct{})
	go func() { wg.Wait(); <-d1; <-d2; close(ch) }()
	select {
	case <-ch:
	case <-time.After(30 * time.Second):
		t.Fatal("concurrent capture blocked")
	}
	if !c1.Overflow || len(c1.Data) != redact.ReadLimit || len(c2.Data) != 0 {
		t.Fatalf("c1 %d %v c2 %d", len(c1.Data), c1.Overflow, len(c2.Data))
	}
}
