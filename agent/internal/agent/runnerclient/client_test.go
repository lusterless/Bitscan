// TP-M10-11 (tester-m10): the agent's runner client, REQ-245, REQ-234;
// #130 (f), (g), #131 (a), (c). A fake runner on a Unix socket speaks the
// #130 frames from a script; a fake clock drives every deadline (no
// sleeps). Expected words from #131 (c).
package runnerclient_test

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/runnerclient"
	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
)

// ---- fake clock ----

type waiter struct {
	at time.Time
	ch chan time.Time
}

type fakeClock struct {
	mu      sync.Mutex
	now     time.Time
	waiters []waiter
}

func (c *fakeClock) Now() time.Time { c.mu.Lock(); defer c.mu.Unlock(); return c.now }
func (c *fakeClock) After(d time.Duration) <-chan time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	ch := make(chan time.Time, 1)
	c.waiters = append(c.waiters, waiter{c.now.Add(d), ch})
	return ch
}

// advance moves the clock and fires every waiter that is due.
func (c *fakeClock) advance(d time.Duration) {
	c.mu.Lock()
	c.now = c.now.Add(d)
	var keep []waiter
	for _, w := range c.waiters {
		if !w.at.After(c.now) {
			w.ch <- c.now
		} else {
			keep = append(keep, w)
		}
	}
	c.waiters = keep
	c.mu.Unlock()
}

func (c *fakeClock) pending() int { c.mu.Lock(); defer c.mu.Unlock(); return len(c.waiters) }

// sleeping reports whether a timer of exactly d from now is armed (the
// client's busy back-off), so the clock moves only while it sleeps.
func (c *fakeClock) sleeping(d time.Duration) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	for _, w := range c.waiters {
		if w.at.Equal(c.now.Add(d)) {
			return true
		}
	}
	return false
}

// waitPending waits (real time, bounded) until n timers are armed.
func (c *fakeClock) waitPending(t *testing.T, n int) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for c.pending() < n {
		if time.Now().After(deadline) {
			t.Fatalf("%d timers armed, want %d", c.pending(), n)
		}
		time.Sleep(200 * time.Microsecond)
	}
}

// ---- fake runner ----

type step func(c net.Conn) // one scripted reply step

func reply(r proto.Reply) step {
	return func(c net.Conn) { _ = proto.WriteReply(c, r) }
}

func raw(b []byte) step { return func(c net.Conn) { _, _ = c.Write(b) } }

type fakeRunner struct {
	path  string
	ln    net.Listener
	mu    sync.Mutex
	reqs  []proto.Request
	conns int
	// script for the n-th connection (0-based); nil: the last script repeats.
	scripts [][]step
	hold    chan struct{} // closed to release a step that waits
}

func newRunner(t *testing.T, scripts ...[]step) *fakeRunner {
	t.Helper()
	dir, err := os.MkdirTemp("", "rc-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	r := &fakeRunner{path: filepath.Join(dir, "runner.sock"), scripts: scripts, hold: make(chan struct{})}
	ln, err := net.Listen("unix", r.path)
	if err != nil {
		t.Fatal(err)
	}
	r.ln = ln
	t.Cleanup(func() { _ = ln.Close(); r.release() })
	go r.serve()
	return r
}

func (r *fakeRunner) release() {
	r.mu.Lock()
	defer r.mu.Unlock()
	select {
	case <-r.hold:
	default:
		close(r.hold)
	}
}

func (r *fakeRunner) serve() {
	for {
		c, err := r.ln.Accept()
		if err != nil {
			return
		}
		r.mu.Lock()
		n := r.conns
		r.conns++
		script := r.scripts[min(n, len(r.scripts)-1)]
		r.mu.Unlock()
		go func() {
			defer func() { _ = c.Close() }()
			req, err := proto.ReadRequest(c)
			if err == nil {
				r.mu.Lock()
				r.reqs = append(r.reqs, req)
				r.mu.Unlock()
			}
			for _, s := range script {
				s(c)
			}
		}()
	}
}

func (r *fakeRunner) requests() []proto.Request {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]proto.Request(nil), r.reqs...)
}

func (r *fakeRunner) connections() int { r.mu.Lock(); defer r.mu.Unlock(); return r.conns }

// readEOF waits until the client closes the connection (or 10 s).
func readEOF(seen chan<- struct{}) step {
	return func(c net.Conn) {
		_ = c.SetReadDeadline(time.Now().Add(10 * time.Second))
		b := make([]byte, 1)
		_, err := c.Read(b)
		if err != nil {
			close(seen)
		}
	}
}

// ---- jobs and results ----

const agentID = "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"

func pid(i int) wire.UUID { return wire.UUID(fmt.Sprintf("abcdef00-0000-4000-8000-%012d", i)) }

func job(n int) wire.Job {
	ps := make([]wire.PluginSpec, n)
	for i := range ps {
		ps[i] = wire.PluginSpec{PluginUUID: pid(i + 1), Execute: "echo M10CANARY-EXEC", TimeoutS: 30 + i}
	}
	return wire.Job{JobID: "dddddddd-0000-4000-8000-000000000001", AgentID: agentID, Kind: wire.KindCompliance,
		PickupBy: wire.NewTime(time.Date(2026, 10, 30, 13, 0, 0, 0, time.UTC)), Plugins: ps, RedactionPatterns: []string{}}
}

func result(t *testing.T, id wire.UUID) proto.Result {
	t.Helper()
	code := int64(0)
	r, err := proto.NewResult(wire.ResultItem{PluginUUID: id, ExitCode: &code, Stdout: "out " + string(id[33:]),
		StartedAt: wire.NewTime(time.Unix(0, 0)), FinishedAt: wire.NewTime(time.Unix(1, 0))})
	if err != nil {
		t.Fatal(err)
	}
	return r
}

var (
	accepted = proto.Reply{Kind: proto.KindAccepted}
	done     = proto.Reply{Kind: proto.KindDone}
)

func res(t *testing.T, i int) step {
	return reply(proto.Reply{Kind: proto.KindResult, Result: result(t, pid(i))})
}

type runOut struct {
	err     error
	results []wire.UUID
}

func run(t *testing.T, r *fakeRunner, clk *fakeClock, j wire.Job, mpp int, ctx context.Context, onErr error) chan runOut {
	t.Helper()
	ch := make(chan runOut, 1)
	c := &runnerclient.Client{Socket: r.path, Clock: clk}
	go func() {
		var got []wire.UUID
		err := c.Run(ctx, j, mpp, func(res proto.Result) error {
			got = append(got, res.Item().PluginUUID)
			return onErr
		})
		ch <- runOut{err, got}
	}()
	return ch
}

func wait(t *testing.T, ch chan runOut) runOut {
	t.Helper()
	select {
	case o := <-ch:
		return o
	case <-time.After(20 * time.Second):
		t.Fatal("Run did not return")
	}
	return runOut{}
}

func word(err error) string {
	var f *runnerclient.Failure
	if errors.As(err, &f) {
		return f.Word
	}
	if err == nil {
		return "<nil>"
	}
	return "other: " + err.Error()
}

func newClock() *fakeClock { return &fakeClock{now: time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)} }

// CHK-M10-051: a normal run: one request carrying the job and the value
// passed; results delivered once each, in order; nil after done.
func TestNormalRun(t *testing.T) {
	r := newRunner(t, []step{reply(accepted), res(t, 2), res(t, 1), res(t, 3), reply(done)})
	j := job(3)
	o := wait(t, run(t, r, newClock(), j, 5, context.Background(), nil))
	if o.err != nil {
		t.Fatalf("err %v", o.err)
	}
	if fmt.Sprint(o.results) != fmt.Sprint([]wire.UUID{pid(2), pid(1), pid(3)}) {
		t.Fatalf("results %v (want the order received)", o.results)
	}
	reqs := r.requests()
	if len(reqs) != 1 || r.connections() != 1 {
		t.Fatalf("%d requests on %d connections", len(reqs), r.connections())
	}
	if reqs[0].V != 1 || reqs[0].MaxParallelPlugins != 5 || !reflect.DeepEqual(reqs[0].Job.Plugins, j.Plugins) || reqs[0].Job.JobID != j.JobID {
		t.Fatalf("request %+v", reqs[0])
	}
}

// CHK-M10-052: every #131 (a) failure kind yields its word.
func TestFailureWords(t *testing.T) {
	t.Run("no socket → connect", func(t *testing.T) {
		c := &runnerclient.Client{Socket: filepath.Join(t.TempDir(), "missing.sock"), Clock: newClock()}
		if w := word(c.Run(context.Background(), job(1), 1, func(proto.Result) error { return nil })); w != "connect" {
			t.Fatalf("%s", w)
		}
	})
	words := []string{"malformed", "not_compliance", "bad_plugins", "bad_parallel", "bad_patterns", "agent_id_unreadable",
		"foreign_agent", "pickup_passed", "pickup_too_far", "replayed", "seen_full", "internal"}
	for _, w := range words {
		t.Run("refused "+w, func(t *testing.T) {
			r := newRunner(t, []step{reply(proto.Reply{Kind: proto.KindRefused, Reason: proto.Reason(w)})})
			o := wait(t, run(t, r, newClock(), job(2), 1, context.Background(), nil))
			if got := word(o.err); got != "refused_"+w || r.connections() != 1 {
				t.Fatalf("word %s, %d connections", got, r.connections())
			}
		})
	}
	cases := []struct {
		name   string
		script func(*testing.T) []step
		want   string
		gotN   int
	}{
		{"EOF after 2 of 5", func(t *testing.T) []step { return []step{reply(accepted), res(t, 1), res(t, 2)} }, "broken", 2},
		{"EOF before the first reply", func(t *testing.T) []step { return nil }, "broken", 0},
		{"cut inside a frame", func(t *testing.T) []step { return []step{reply(accepted), raw([]byte{0, 0, 0, 50, '{'})} }, "broken", 0},
		{"oversize reply header", func(t *testing.T) []step {
			h := make([]byte, 4)
			binary.BigEndian.PutUint32(h, proto.MaxReply+1)
			return []step{reply(accepted), raw(h)}
		}, "protocol", 0},
		{"malformed reply", func(t *testing.T) []step {
			return []step{reply(accepted), raw(append([]byte{0, 0, 0, 7}, `{"x":1}`...))}
		}, "protocol", 0},
		{"unknown first reply", func(t *testing.T) []step {
			return []step{raw(append([]byte{0, 0, 0, 15}, `{"type":"done"}`...))}
		}, "protocol", 0},
		{"a result for a plugin not in the job", func(t *testing.T) []step {
			return []step{reply(accepted), res(t, 1), reply(proto.Reply{Kind: proto.KindResult, Result: result(t, pid(99))})}
		}, "protocol", 1},
		{"a repeated result", func(t *testing.T) []step { return []step{reply(accepted), res(t, 1), res(t, 1)} }, "protocol", 1},
		{"a second accepted", func(t *testing.T) []step { return []step{reply(accepted), reply(accepted)} }, "protocol", 0},
		{"refused after accepted", func(t *testing.T) []step {
			return []step{reply(accepted), reply(proto.Reply{Kind: proto.KindRefused, Reason: proto.ReasonInternal})}
		}, "protocol", 0},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := newRunner(t, c.script(t))
			o := wait(t, run(t, r, newClock(), job(5), 2, context.Background(), nil))
			if got := word(o.err); got != c.want || len(o.results) != c.gotN {
				t.Fatalf("word %s (want %s), %d results delivered (want %d)", got, c.want, len(o.results), c.gotN)
			}
			if r.connections() != 1 {
				t.Fatalf("%d connections (a failure is never resent)", r.connections())
			}
		})
	}
	// Recorded: done before every plugin's result.
	r := newRunner(t, []step{reply(accepted), res(t, 1), reply(done)})
	o := wait(t, run(t, r, newClock(), job(3), 2, context.Background(), nil))
	t.Logf("RECORDED: done after 1 of 3 results → %s", word(o.err))
}

// CHK-M10-052 timeout and CHK-M10-054: 30 s to the first reply; then
// max(timeout_s) + 30 s between replies.
func TestDeadlines(t *testing.T) {
	t.Run("no first reply in 30 s", func(t *testing.T) {
		r := newRunner(t, []step{r0wait()})
		clk := newClock()
		ch := run(t, r, clk, job(1), 1, context.Background(), nil)
		clk.waitPending(t, 2)         // the dial's timer, then the first-reply timer
		clk.advance(29 * time.Second) // 29 s: nothing yet
		select {
		case o := <-ch:
			t.Fatalf("returned at 29 s: %s", word(o.err))
		case <-time.After(100 * time.Millisecond):
		}
		clk.advance(time.Second)
		if o := wait(t, ch); word(o.err) != "timeout" {
			t.Fatalf("%s", word(o.err))
		}
	})
	t.Run("gap after accepted", func(t *testing.T) {
		j := job(3) // timeout_s 30, 31, 32 → gap 62 s
		r := newRunner(t, []step{reply(accepted), r0wait()})
		clk := newClock()
		ch := run(t, r, clk, j, 1, context.Background(), nil)
		deadline := time.Now().Add(10 * time.Second)
		for len(r.requests()) == 0 && time.Now().Before(deadline) {
			time.Sleep(time.Millisecond)
		}
		clk.waitPending(t, 3) // dial, first reply, then the gap timer
		clk.advance(61 * time.Second)
		select {
		case o := <-ch:
			t.Fatalf("returned at 61 s: %s", word(o.err))
		case <-time.After(100 * time.Millisecond):
		}
		clk.advance(time.Second)
		if o := wait(t, ch); word(o.err) != "timeout" {
			t.Fatalf("%s", word(o.err))
		}
	})
}

// r0wait blocks the script without replying (until the test ends).
func r0wait() step { return func(net.Conn) { time.Sleep(15 * time.Second) } }

// CHK-M10-053: busy is redialled every 2 s up to 30 s, then refused_busy;
// busy three times then a normal run.
func TestBusy(t *testing.T) {
	busy := []step{reply(proto.Reply{Kind: proto.KindRefused, Reason: proto.ReasonBusy})}
	t.Run("always busy", func(t *testing.T) {
		r := newRunner(t, busy)
		clk := newClock()
		ch := run(t, r, clk, job(1), 1, context.Background(), nil)
		var attempts []int
		for range 40 {
			select {
			case o := <-ch:
				if word(o.err) != "refused_busy" {
					t.Fatalf("%s", word(o.err))
				}
				t.Logf("RECORDED: %d connections over %v", r.connections(), attempts)
				if n := r.connections(); n < 15 || n > 16 {
					t.Fatalf("%d attempts in 30 s at 2 s steps", n)
				}
				return
			default:
			}
			deadline := time.Now().Add(5 * time.Second)
			for !clk.sleeping(2*time.Second) && time.Now().Before(deadline) {
				select {
				case o := <-ch:
					ch <- o
				default:
				}
				if len(ch) > 0 {
					break
				}
				time.Sleep(200 * time.Microsecond)
			}
			if len(ch) > 0 {
				continue
			}
			attempts = append(attempts, r.connections())
			clk.advance(2 * time.Second)
		}
		t.Fatal("still retrying after 80 s")
	})
	t.Run("busy 3 times then accepted", func(t *testing.T) {
		r := newRunner(t, busy, busy, busy, []step{reply(accepted), res(t, 1), reply(done)})
		clk := newClock()
		ch := run(t, r, clk, job(1), 1, context.Background(), nil)
		overall := time.Now().Add(30 * time.Second)
		for r.connections() < 4 {
			if time.Now().After(overall) {
				t.Fatalf("only %d connections: busy was not retried", r.connections())
			}
			deadline := time.Now().Add(5 * time.Second)
			for !clk.sleeping(2*time.Second) && time.Now().Before(deadline) {
				time.Sleep(200 * time.Microsecond)
			}
			clk.advance(2 * time.Second)
			deadline = time.Now().Add(5 * time.Second)
			for clk.sleeping(0) && time.Now().Before(deadline) {
				time.Sleep(200 * time.Microsecond)
			}
		}
		if o := wait(t, ch); o.err != nil || len(o.results) != 1 {
			t.Fatalf("%s %v", word(o.err), o.results)
		}
	})
}

// CHK-M10-055: the agent stopping: ctx.Err, not a Failure; the runner sees
// the connection close.
func TestCancel(t *testing.T) {
	seen := make(chan struct{})
	r := newRunner(t, []step{reply(accepted), res(t, 1), readEOF(seen)})
	ctx, cancel := context.WithCancel(context.Background())
	ch := run(t, r, newClock(), job(3), 1, ctx, nil)
	deadline := time.Now().Add(10 * time.Second)
	for len(r.requests()) == 0 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	time.Sleep(50 * time.Millisecond)
	cancel()
	o := wait(t, ch)
	var f *runnerclient.Failure
	if !errors.Is(o.err, context.Canceled) || errors.As(o.err, &f) {
		t.Fatalf("err %v", o.err)
	}
	select {
	case <-seen:
	case <-time.After(10 * time.Second):
		t.Fatal("the runner did not see the connection close")
	}
}

// CHK-M10-057: an onResult error stops the run.
func TestOnResultError(t *testing.T) {
	r := newRunner(t, []step{reply(accepted), res(t, 1), res(t, 2), reply(done)})
	o := wait(t, run(t, r, newClock(), job(2), 1, context.Background(), errors.New("spool full")))
	var f *runnerclient.Failure
	if o.err == nil || errors.As(o.err, &f) || len(o.results) != 1 {
		t.Fatalf("err %v results %v", o.err, o.results)
	}
}

// CHK-M10-056, -058: the client sends one frame per connection, holds no
// logger, uses only its clock, and never prints the execute or a reply body.
func TestClientStatic(t *testing.T) {
	f, err := parser.ParseFile(token.NewFileSet(), "client.go", nil, 0)
	if err != nil {
		t.Fatal(err)
	}
	for _, imp := range f.Imports {
		p := strings.Trim(imp.Path.Value, `"`)
		if p == "log" || p == "log/slog" || p == "os/exec" || strings.Contains(p, "internal/runner/") && p != "bitscan.local/agent/internal/runner/proto" {
			t.Errorf("client.go imports %s", p)
		}
	}
	ast.Inspect(f, func(n ast.Node) bool {
		if sel, ok := n.(*ast.SelectorExpr); ok {
			if x, ok := sel.X.(*ast.Ident); ok && x.Name == "time" && (sel.Sel.Name == "Now" || sel.Sel.Name == "Sleep" || sel.Sel.Name == "After" || sel.Sel.Name == "NewTimer") {
				t.Errorf("client.go calls time.%s (only the injected clock may be used)", sel.Sel.Name)
			}
			if x, ok := sel.X.(*ast.Ident); ok && x.Name == "fmt" && strings.HasPrefix(sel.Sel.Name, "Print") {
				t.Errorf("client.go prints")
			}
		}
		return true
	})
	if runnerclient.Socket != "/run/bitscan/runner.sock" {
		t.Fatalf("Socket %s", runnerclient.Socket)
	}
}

// CHK-M10-052 on every OS (lead's TASK-218 r1 row): a path whose socket file
// was removed (the runner's listener closed) → connect.
func TestConnectAfterListenerGone(t *testing.T) {
	dir, err := os.MkdirTemp("", "rc-gone-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	p := filepath.Join(dir, "runner.sock")
	ln, err := net.Listen("unix", p)
	if err != nil {
		t.Fatal(err)
	}
	_ = ln.Close()
	_ = os.Remove(p)
	c := &runnerclient.Client{Socket: p, Clock: newClock()}
	if w := word(c.Run(context.Background(), job(1), 1, func(proto.Result) error { return nil })); w != "connect" {
		t.Fatalf("%s", w)
	}
}
