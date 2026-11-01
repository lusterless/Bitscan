// TP-M10-18 (tester-m10c): the runner serve loop (TASK-225) over a real Unix
// socket with a fake executor, REQ-234, REQ-235 (4), REQ-236 (2), REQ-261;
// #130 (b)–(g); decisions "TASK-224 (job) and TASK-225 (serve) design
// points" (2). Linux (W): on Windows AF_UNIX a refusal sent without reading
// the request can arrive as a reset (TASK-218 note), so the busy row is
// meaningful on Linux only. Deadlines are the #130 (f) values, waited out in
// wall time only in the two rows that test them (30 s, 60 s).
package runner

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"math"
	"net"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
)

// jobLog is a goroutine-safe log sink (also used by the delegated job rows).
type jobLog struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *jobLog) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}

func (l *jobLog) String() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.String()
}

// unixListener adapts *net.UnixListener to Listener.
type unixListener struct{ l *net.UnixListener }

func (u unixListener) Accept() (*net.UnixConn, error) { return u.l.AcceptUnix() }
func (u unixListener) Close() error                   { return u.l.Close() }

// fakeExec is the exec counter of TP-M10-01 (CHK-M10-H02): it counts Run,
// keeps each request, emits a scripted number of results, and can be held
// at a barrier or return a fatal error.
type fakeExec struct {
	calls    atomic.Int32
	mu       sync.Mutex
	reqs     []proto.Request
	results  int           // results to emit per job (−1 = one per plugin)
	big      bool          // emit maximal stdout/stderr items
	hold     chan struct{} // if set, Run waits on it (or ctx) before returning
	started  chan struct{} // closed when the first Run starts
	fatal    error
	canceled chan time.Time // receives when ctx is done during hold
	once     sync.Once
}

func (f *fakeExec) Run(ctx context.Context, req proto.Request, emit func(proto.Result) error) error {
	f.calls.Add(1)
	f.mu.Lock()
	f.reqs = append(f.reqs, req)
	f.mu.Unlock()
	if f.started != nil {
		f.once.Do(func() { close(f.started) })
	}
	n := f.results
	if n < 0 {
		n = len(req.Job.Plugins)
	}
	for i := range n {
		code := int64(i)
		now := wire.NewTime(time.Now())
		it := wire.ResultItem{PluginUUID: req.Job.Plugins[i%len(req.Job.Plugins)].PluginUUID, ExitCode: &code,
			Stdout: "out M10SRVCANARY-stdout", Stderr: "", StartedAt: now, FinishedAt: now}
		if f.big {
			it.Stdout, it.Stderr = strings.Repeat("o", 65536), strings.Repeat("e", 16384)
		}
		r, err := proto.NewResult(it)
		if err != nil {
			panic(err)
		}
		if emit(r) != nil {
			break
		}
		if ctx.Err() != nil {
			break
		}
	}
	if f.hold != nil {
		select {
		case <-f.hold:
		case <-ctx.Done():
			if f.canceled != nil {
				f.canceled <- time.Now()
			}
		}
	}
	return f.fatal
}

type srvHarness struct {
	path  string
	srv   *Server
	exec  *fakeExec
	logs  *jobLog
	stop  context.CancelFunc
	errCh chan error
}

const srvExecCanary = "M10SRVCANARY-execute"

func startServer(t *testing.T, ex *fakeExec) *srvHarness {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "runner.sock")
	l, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	logs := &jobLog{}
	s := &Server{Listener: unixListener{l}, Checks: NewChecks(agentFile(t, ownID+"\n")), Exec: ex,
		Clock: func() time.Time { return now0 }, Log: slog.New(slog.NewJSONHandler(logs, &slog.HandlerOptions{Level: slog.LevelDebug}))}
	ctx, cancel := context.WithCancel(context.Background())
	h := &srvHarness{path: path, srv: s, exec: ex, logs: logs, stop: cancel, errCh: make(chan error, 1)}
	go func() { h.errCh <- s.Serve(ctx) }()
	t.Cleanup(func() {
		cancel()
		select {
		case <-h.errCh:
		case <-time.After(10 * time.Second):
			t.Error("Serve did not return after its context was cancelled")
		}
		if l := logs.String(); strings.Contains(l, "M10SRVCANARY") {
			t.Errorf("a canary is in the runner log (CHK-M10-171): %s", l)
		}
	})
	return h
}

func (h *srvHarness) dial(t *testing.T) *net.UnixConn {
	t.Helper()
	c, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: h.path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = c.Close() })
	return c
}

func srvReq(id wire.UUID, mod func(*proto.Request)) proto.Request {
	return req(id, func(r *proto.Request) {
		for i := range r.Job.Plugins {
			r.Job.Plugins[i].Execute = srvExecCanary + " " + r.Job.Plugins[i].Execute
		}
		r.Job.RedactionPatterns = []string{"M10SRVCANARY-pattern"}
		if mod != nil {
			mod(r)
		}
	})
}

func rawFrame(body []byte) []byte {
	n := len(body)
	if n < 0 || n > math.MaxUint32 {
		panic("rawFrame: body over the 4-byte length")
	}
	b := make([]byte, 4, 4+n)
	binary.BigEndian.PutUint32(b, uint32(n))
	return append(b, body...)
}

// readAll reads replies until EOF (or the bound), returning their kinds.
func readAll(t *testing.T, c *net.UnixConn, bound time.Duration) ([]proto.Reply, error) {
	t.Helper()
	_ = c.SetReadDeadline(time.Now().Add(bound))
	var out []proto.Reply
	for {
		r, err := proto.ReadReply(c)
		if err != nil {
			// The runner closes without reading what the client sent (busy,
			// refusals): Linux then answers the client's next read with
			// ECONNRESET instead of EOF, after the queued replies.
			if errors.Is(err, io.EOF) || errors.Is(err, syscall.ECONNRESET) {
				return out, nil
			}
			return out, err
		}
		out = append(out, r)
	}
}

func kinds(rs []proto.Reply) string {
	var s []string
	for _, r := range rs {
		k := string(r.Kind)
		if r.Kind == proto.KindRefused {
			k += " " + string(r.Reason)
		}
		s = append(s, k)
	}
	return strings.Join(s, ",")
}

func jsonOf(t *testing.T, v any) string {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// CHK-M10-163: accepted, the results in emit order, done, close; the
// executor got the request unchanged.
func TestServeGoodJob(t *testing.T) {
	h := startServer(t, &fakeExec{results: -1})
	c := h.dial(t)
	r := srvReq(jobN(163), nil)
	if err := proto.WriteRequest(c, r); err != nil {
		t.Fatal(err)
	}
	reps, err := readAll(t, c, 10*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if got := kinds(reps); got != "accepted,result,result,result,done" {
		t.Fatalf("replies %s", got)
	}
	for i, rep := range reps[1:4] {
		if rep.Result.Item().PluginUUID != r.Job.Plugins[i].PluginUUID {
			t.Fatalf("result %d for %s", i, rep.Result.Item().PluginUUID)
		}
	}
	if h.exec.calls.Load() != 1 || jsonOf(t, h.exec.reqs[0]) != jsonOf(t, r) {
		t.Fatalf("executor calls %d, request %s", h.exec.calls.Load(), jsonOf(t, h.exec.reqs))
	}
	if l := h.logs.String(); !strings.Contains(l, `"job_id":"`+string(jobN(163))+`"`) || !strings.Contains(l, "runner: job done") {
		t.Fatalf("log %s", l)
	}
}

// CHK-M10-164 (REQ-235 (4)): a second connection while a job runs gets
// refused busy at once, its request unread; the running job is unaffected.
func TestServeBusy(t *testing.T) {
	ex := &fakeExec{results: 1, hold: make(chan struct{}), started: make(chan struct{})}
	h := startServer(t, ex)
	c1 := h.dial(t)
	if err := proto.WriteRequest(c1, srvReq(jobN(1641), nil)); err != nil {
		t.Fatal(err)
	}
	<-ex.started
	c2 := h.dial(t)
	if err := proto.WriteRequest(c2, srvReq(jobN(1642), nil)); err != nil {
		t.Logf("RECORDED: the busy client's write failed (%v): the runner never reads it", err)
	}
	start := time.Now()
	reps, err := readAll(t, c2, 5*time.Second)
	if err != nil || kinds(reps) != "refused busy" {
		t.Fatalf("second connection: %s, %v", kinds(reps), err)
	}
	if d := time.Since(start); d > time.Second {
		t.Fatalf("busy refusal after %v, want at once", d)
	}
	close(ex.hold)
	reps1, err := readAll(t, c1, 10*time.Second)
	if err != nil || kinds(reps1) != "accepted,result,done" {
		t.Fatalf("first connection: %s, %v", kinds(reps1), err)
	}
	if n := ex.calls.Load(); n != 1 {
		t.Fatalf("executor ran %d times, want 1 (the busy request must not run)", n)
	}
	// the slot is free again: a third job runs
	c3 := h.dial(t)
	if err := proto.WriteRequest(c3, srvReq(jobN(1643), nil)); err != nil {
		t.Fatal(err)
	}
	if reps3, err := readAll(t, c3, 10*time.Second); err != nil || kinds(reps3) != "accepted,result,done" {
		t.Fatalf("third connection: %s, %v", kinds(reps3), err)
	}
}

// CHK-M10-165 (REQ-261, Q1): malformed requests → one refused frame, then
// close; the exec counter stays 0.
func TestServeMalformed(t *testing.T) {
	good := srvReq(jobN(165), nil)
	enc := func(mod func(m map[string]any)) []byte {
		var m map[string]any
		if err := json.Unmarshal([]byte(jsonOf(t, good)), &m); err != nil {
			t.Fatal(err)
		}
		mod(m)
		return []byte(jsonOf(t, m))
	}
	job := func(m map[string]any) map[string]any { return m["job"].(map[string]any) }
	cases := []struct {
		name string
		raw  []byte
		want string
	}{
		{"bare JSON string", rawFrame([]byte(`"/bin/sh -c id"`)), "malformed"},
		{"plugins without a job", rawFrame([]byte(`{"plugins":[{"plugin_uuid":"abcdef00-0000-4000-8000-000000000001","execute":"id","timeout_s":5}]}`)), "malformed"},
		{"unknown key command beside job (CHK-M10-323)", rawFrame(enc(func(m map[string]any) { m["command"] = "id" })), "malformed"},
		{"unknown key in the job", rawFrame(enc(func(m map[string]any) { job(m)["command"] = "id" })), "malformed"},
		{"inventory job (CHK-M10-324)", rawFrame(enc(func(m map[string]any) {
			j := job(m)
			j["kind"] = "inventory"
			delete(j, "plugins")
			delete(j, "redaction_patterns")
		})), "not_compliance"},
		{"v 2", rawFrame(enc(func(m map[string]any) { m["v"] = 2 })), "malformed"},
		{"max_parallel_plugins 9 (Q1)", rawFrame(enc(func(m map[string]any) { m["max_parallel_plugins"] = 9 })), "malformed"},
		{"0 plugins (Q1)", rawFrame(enc(func(m map[string]any) { job(m)["plugins"] = []any{} })), "malformed"},
		{"zero-length frame", []byte{0, 0, 0, 0}, "malformed"},
		{"oversize header", []byte{0x02, 0x00, 0x00, 0x01}, "malformed"},
		{"garbage bytes", rawFrame([]byte("\x00\xffGARBAGE{")), "malformed"},
		{"two JSON values", rawFrame(append(enc(func(map[string]any) {}), []byte(` {}`)...)), "malformed"},
	}
	h := startServer(t, &fakeExec{results: -1})
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			c := h.dial(t)
			if _, err := c.Write(tc.raw); err != nil {
				t.Fatal(err)
			}
			reps, err := readAll(t, c, 5*time.Second)
			if err != nil || kinds(reps) != "refused "+tc.want {
				t.Fatalf("replies %q (%v), want refused %s", kinds(reps), err, tc.want)
			}
		})
	}
	if n := h.exec.calls.Load(); n != 0 {
		t.Fatalf("executor ran %d times for malformed requests", n)
	}
	if l := h.logs.String(); strings.Count(l, "runner: request refused") != len(cases) || strings.Contains(l, "GARBAGE") || strings.Contains(l, "/bin/sh") {
		t.Fatalf("log %s", l)
	}
}

// CHK-M10-166 (REQ-261, CHK-M10-322): a second request frame on the same
// connection is never decoded or run; its first byte ends the job (recorded).
// After a refusal, a second frame gets nothing.
func TestServeSecondFrame(t *testing.T) {
	ex := &fakeExec{results: 0, hold: make(chan struct{}), started: make(chan struct{}), canceled: make(chan time.Time, 1)}
	h := startServer(t, ex)
	c := h.dial(t)
	if err := proto.WriteRequest(c, srvReq(jobN(1661), nil)); err != nil {
		t.Fatal(err)
	}
	<-ex.started
	if err := proto.WriteRequest(c, srvReq(jobN(1662), nil)); err != nil {
		t.Fatal(err)
	}
	select {
	case <-ex.canceled:
		t.Log("RECORDED: the second frame's first byte cancelled the running job")
	case <-time.After(5 * time.Second):
		t.Log("RECORDED: the second frame did not cancel the running job")
		close(ex.hold)
	}
	reps, _ := readAll(t, c, 5*time.Second)
	if n := ex.calls.Load(); n != 1 || strings.Count(kinds(reps), "accepted") != 1 {
		t.Fatalf("executor ran %d times, replies %s; want 1 run and one accepted", n, kinds(reps))
	}
	for _, r := range ex.reqs {
		if r.Job.JobID == jobN(1662) {
			t.Fatal("the second frame's job reached the executor")
		}
	}
	// after a refusal
	c2 := h.dial(t)
	bad := srvReq(jobN(1663), func(r *proto.Request) { r.Job.AgentID = foreignID })
	if err := proto.WriteRequest(c2, bad); err != nil {
		t.Fatal(err)
	}
	_ = proto.WriteRequest(c2, srvReq(jobN(1664), nil)) // may fail: the runner closes
	reps2, _ := readAll(t, c2, 5*time.Second)
	if kinds(reps2) != "refused foreign_agent" || ex.calls.Load() != 1 {
		t.Fatalf("after a refusal: %s, %d runs", kinds(reps2), ex.calls.Load())
	}
}

// CHK-M10-167 (REQ-236 (2), REQ-261): foreign, expired, too far, replayed →
// refused with its word, exec counter 0, one log line with job_id + word.
func TestServeJobChecks(t *testing.T) {
	h := startServer(t, &fakeExec{results: -1})
	cases := []struct {
		name string
		r    proto.Request
		want proto.Reason
	}{
		{"foreign", srvReq(jobN(1671), func(r *proto.Request) { r.Job.AgentID = foreignID }), proto.ReasonForeignAgent},
		{"expired", srvReq(jobN(1672), at(0)), proto.ReasonPickupPassed},
		{"too far", srvReq(jobN(1673), at(25*time.Hour+time.Second)), proto.ReasonPickupTooFar},
		{"replayed (CHK-M10-327)", srvReq(jobN(1671), nil), proto.ReasonReplayed},
	}
	for _, tc := range cases {
		c := h.dial(t)
		if err := proto.WriteRequest(c, tc.r); err != nil {
			t.Fatal(err)
		}
		reps, err := readAll(t, c, 5*time.Second)
		if err != nil || kinds(reps) != "refused "+string(tc.want) {
			t.Errorf("%s: %s %v, want refused %s", tc.name, kinds(reps), err, tc.want)
		}
	}
	if n := h.exec.calls.Load(); n != 0 {
		t.Fatalf("executor ran %d times for refused jobs", n)
	}
	l := h.logs.String()
	for _, tc := range cases {
		line := `"msg":"runner: job refused","job_id":"` + string(tc.r.Job.JobID) + `","reason":"` + string(tc.want) + `"`
		if !strings.Contains(l, line) {
			t.Errorf("no log line %s in %s", line, l)
		}
	}
	if strings.Count(l, "runner: job refused") != len(cases) {
		t.Errorf("log %s", l)
	}
}

// CHK-M10-168 (#130 (f)): a connection that sends nothing, or half a header,
// is closed after 30 s (the constant requestWait, waited out in wall time:
// the spec value), and the next connection is then served. While it waits it
// holds the one job slot, so another connection meanwhile is refused busy
// (recorded: #130 (g) one connection at a time).
func TestServeRequestDeadline(t *testing.T) {
	if requestWait != 30*time.Second {
		t.Fatalf("requestWait %v, want 30 s (#130 (f))", requestWait)
	}
	for _, mode := range []string{"silent", "half header"} {
		t.Run(mode, func(t *testing.T) {
			t.Parallel()
			h := startServer(t, &fakeExec{results: -1})
			c := h.dial(t)
			if mode == "half header" {
				if _, err := c.Write([]byte{0, 0}); err != nil {
					t.Fatal(err)
				}
			}
			start := time.Now()
			time.Sleep(200 * time.Millisecond)
			other := h.dial(t)
			if err := proto.WriteRequest(other, srvReq(jobN(1680), nil)); err != nil {
				t.Logf("RECORDED: the busy client's write failed (%v)", err)
			}
			if reps, err := readAll(t, other, 5*time.Second); err != nil || kinds(reps) != "refused busy" {
				t.Errorf("a connection during the wait: %s %v", kinds(reps), err)
			}
			reps, err := readAll(t, c, 45*time.Second)
			d := time.Since(start)
			t.Logf("RECORDED: closed after %v with replies %q (%v)", d, kinds(reps), err)
			if d < 29*time.Second || d > 35*time.Second {
				t.Errorf("closed after %v, want about 30 s", d)
			}
			if k := kinds(reps); k != "" && k != "refused malformed" {
				t.Errorf("after the deadline: %q, want nothing or one refused malformed", k)
			}
			next := h.dial(t)
			if err := proto.WriteRequest(next, srvReq(jobN(1681), nil)); err != nil {
				t.Fatal(err)
			}
			if reps, err := readAll(t, next, 10*time.Second); err != nil || kinds(reps) != "accepted,result,result,result,done" {
				t.Fatalf("next connection: %s %v", kinds(reps), err)
			}
			if h.exec.calls.Load() != 1 {
				t.Fatalf("executor calls %d, want 1", h.exec.calls.Load())
			}
		})
	}
}

// CHK-M10-169 (TASK-225 acceptance; CHK-M10-391 serve half): closing the
// client mid-job cancels the executor's context within 1 s; a half-close
// (EOF) cancels too, and no done follows.
func TestServeCloseCancels(t *testing.T) {
	for _, mode := range []string{"close", "half-close"} {
		t.Run(mode, func(t *testing.T) {
			ex := &fakeExec{results: 1, hold: make(chan struct{}), started: make(chan struct{}), canceled: make(chan time.Time, 1)}
			h := startServer(t, ex)
			c := h.dial(t)
			if err := proto.WriteRequest(c, srvReq(jobN(169), nil)); err != nil {
				t.Fatal(err)
			}
			<-ex.started
			// Read accepted and the one result first: after that the runner
			// writes nothing until the job ends, so only the connection
			// watcher (not a failed write) can cancel the job.
			_ = c.SetReadDeadline(time.Now().Add(5 * time.Second))
			for range 2 {
				if _, err := proto.ReadReply(c); err != nil {
					t.Fatal(err)
				}
			}
			at := time.Now()
			if mode == "close" {
				_ = c.Close()
			} else {
				_ = c.CloseWrite()
			}
			select {
			case got := <-ex.canceled:
				if d := got.Sub(at); d > time.Second {
					t.Fatalf("cancelled after %v, want within 1 s", d)
				}
			case <-time.After(5 * time.Second):
				close(ex.hold)
				t.Fatal("closing the client did not cancel the executor")
			}
			if mode == "half-close" {
				reps, _ := readAll(t, c, 5*time.Second)
				if strings.Contains(kinds(reps), "done") {
					t.Fatalf("done after a cancelled job: %s", kinds(reps))
				}
			}
		})
	}
}

// CHK-M10-170 (#130 (f)): a client that stops reading while the executor
// emits large results → the job is cancelled after the 60 s write deadline
// (replyWait, wall time) and the next connection is served.
func TestServeWriteDeadline(t *testing.T) {
	if replyWait != 60*time.Second {
		t.Fatalf("replyWait %v, want 60 s (#130 (f))", replyWait)
	}
	ex := &fakeExec{results: 100, big: true, started: make(chan struct{})}
	h := startServer(t, ex)
	c := h.dial(t)
	if err := proto.WriteRequest(c, srvReq(jobN(1701), func(r *proto.Request) { r.Job.Plugins = plugins(100) })); err != nil {
		t.Fatal(err)
	}
	<-ex.started
	start := time.Now()
	// never read c; wait until the job ends (the slot is free again)
	var reps []proto.Reply
	for {
		time.Sleep(time.Second)
		if !h.srv.busy.Load() {
			break
		}
		if time.Since(start) > 90*time.Second {
			t.Fatal("the job is still running 90 s after the client stopped reading")
		}
	}
	d := time.Since(start)
	t.Logf("RECORDED: the job ended %v after the client stopped reading", d)
	if d < 55*time.Second {
		t.Fatalf("the job ended after %v, before the 60 s write deadline", d)
	}
	reps, _ = readAll(t, c, 5*time.Second)
	if strings.Contains(kinds(reps), "done") || len(reps) >= 101 {
		t.Fatalf("%d replies with done after a write timeout: %s", len(reps), kinds(reps)[:min(80, len(kinds(reps)))])
	}
	ex.big = false // the first job has ended (busy is false)
	c2 := h.dial(t)
	if err := proto.WriteRequest(c2, srvReq(jobN(1702), nil)); err != nil {
		t.Fatal(err)
	}
	if _, err := readAll(t, c2, 30*time.Second); err != nil {
		t.Fatalf("next connection: %v", err)
	}
	if ex.calls.Load() != 2 {
		t.Fatalf("executor calls %d, want 2", ex.calls.Load())
	}
}

// Decisions "TASK-224 … TASK-225 design points" (2): a fatal executor
// error → no done, Serve returns that error and stops accepting.
func TestServeFatalExecutorError(t *testing.T) {
	planted := errors.New("planted: sweep failed")
	h := startServer(t, &fakeExec{results: 1, fatal: planted})
	c := h.dial(t)
	if err := proto.WriteRequest(c, srvReq(jobN(1801), nil)); err != nil {
		t.Fatal(err)
	}
	reps, _ := readAll(t, c, 10*time.Second)
	if kinds(reps) != "accepted,result" {
		t.Fatalf("replies %s, want accepted,result and no done", kinds(reps))
	}
	select {
	case err := <-h.errCh:
		if !errors.Is(err, planted) {
			t.Fatalf("Serve returned %v, want the executor's error", err)
		}
		h.errCh <- err // for the cleanup
	case <-time.After(10 * time.Second):
		t.Fatal("Serve kept running after a fatal executor error")
	}
	if _, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: h.path, Net: "unix"}); err == nil {
		t.Fatal("the listener still accepts after a fatal error")
	}
	if !strings.Contains(h.logs.String(), "runner: job ended, cleanup failed") {
		t.Fatalf("log %s", h.logs.String())
	}
}

// Shutdown: cancelling Serve's context mid-job cancels the job, Serve
// returns nil after it ended, and no done is sent.
func TestServeShutdownMidJob(t *testing.T) {
	ex := &fakeExec{results: 1, hold: make(chan struct{}), started: make(chan struct{}), canceled: make(chan time.Time, 1)}
	h := startServer(t, ex)
	c := h.dial(t)
	if err := proto.WriteRequest(c, srvReq(jobN(1901), nil)); err != nil {
		t.Fatal(err)
	}
	<-ex.started
	h.stop()
	select {
	case <-ex.canceled:
	case <-time.After(5 * time.Second):
		close(ex.hold)
		t.Fatal("shutdown did not cancel the job")
	}
	select {
	case err := <-h.errCh:
		if err != nil {
			t.Fatalf("Serve returned %v after a shutdown, want nil", err)
		}
		h.errCh <- nil
	case <-time.After(10 * time.Second):
		t.Fatal("Serve did not return")
	}
	reps, _ := readAll(t, c, 5*time.Second)
	if kinds(reps) != "accepted,result" {
		t.Fatalf("replies %s", kinds(reps))
	}
}
