// Tests for the run state and the heartbeat loop (TS §3.3 L202–L206, L211,
// L224–L226; §3.2 steps 7–8; §6.5 L1163; #30, #78, #81; lead rulings
// 2026-10-24; REQ-097, REQ-095, REQ-103; tests/m4/test-plan.md TP-M4-16,
// CHK-M4-185 to -193; mutation rows CHK-M4-335, -338, -355). Fake clock,
// fake manager (Doer), fake rotator, recorded slog output. Expected values come
// from the spec and the answered questions, not from the implementation.
package loops_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/loops"
	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/state"
	"bitscan.local/agent/internal/agent/token"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
)

const (
	agentID = wire.UUID("6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b")
	jobA    = wire.UUID("c1a4e5f6-0718-4293-a4b5-c6d7e8f9a0b1")
	version = "0.1.0~pre1"
)

var (
	t0        = time.Date(2026, 10, 24, 8, 0, 0, 0, time.UTC)
	canaryTok = wire.AgentToken("bsa_CANARY" + strings.Repeat("k", 37))
)

// ---- fake clock: After fires only when the test fires it ----

type waiter struct {
	d  time.Duration
	at time.Time
	ch chan time.Time
}

type fakeClock struct {
	mu      sync.Mutex
	now     time.Time
	waiters []*waiter
}

func (c *fakeClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}

func (c *fakeClock) After(d time.Duration) <-chan time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	w := &waiter{d: d, at: c.now.Add(d), ch: make(chan time.Time, 1)}
	c.waiters = append(c.waiters, w)
	return w.ch
}

// next waits (real time, bounded) until a loop sleeps, and returns the wait.
func (c *fakeClock) next(t *testing.T) time.Duration {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		c.mu.Lock()
		if len(c.waiters) > 0 {
			d := c.waiters[0].d
			c.mu.Unlock()
			return d
		}
		c.mu.Unlock()
		time.Sleep(200 * time.Microsecond)
	}
	t.Fatal("no loop is waiting on the clock")
	return 0
}

// fire moves the clock to the first waiter's time and wakes it.
func (c *fakeClock) fire(t *testing.T) time.Duration {
	t.Helper()
	d := c.next(t)
	c.mu.Lock()
	w := c.waiters[0]
	c.waiters = c.waiters[1:]
	c.now = w.at
	c.mu.Unlock()
	w.ch <- w.at
	return d
}

// advance moves the clock without waking anyone (to prove nothing happens).
func (c *fakeClock) advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.now = c.now.Add(d)
}

type half struct{}

func (half) Float64() float64 { return 0.5 }

// splitmix is a deterministic uniform source.
type splitmix struct {
	mu sync.Mutex
	x  uint64
}

func (s *splitmix) Float64() float64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.x += 0x9e3779b97f4a7c15
	z := s.x
	z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9
	z = (z ^ (z >> 27)) * 0x94d049bb133111eb
	z ^= z >> 31
	return float64(z>>11) / (1 << 53)
}

// ---- fake manager ----

type reply struct {
	status int
	typ    string
	body   []byte
	err    error
}

type fakeManager struct {
	mu    sync.Mutex
	reqs  []transport.Request
	reply func(n int, r transport.Request) reply
}

func (f *fakeManager) Do(_ context.Context, r transport.Request) (transport.Response, error) {
	f.mu.Lock()
	f.reqs = append(f.reqs, r)
	n := len(f.reqs)
	rp := f.reply
	f.mu.Unlock()
	a := rp(n, r)
	resp := transport.Response{Status: a.status, Body: a.body}
	if a.status != 0 && (a.status < 200 || a.status > 299) {
		resp.Problem = wire.Problem{Type: a.typ, Status: a.status}
	}
	resp.Class = transport.Classify(a.status, a.typ, a.err)
	return resp, a.err
}

func (f *fakeManager) count() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.reqs)
}

func (f *fakeManager) req(i int) transport.Request {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.reqs[i]
}

func hbBody(pull, par int) []byte {
	return []byte(fmt.Sprintf(`{"job_pull_seconds":%d,"max_parallel_plugins":%d,"server_time":"2026-10-24T08:00:00Z"}`, pull, par))
}

func okHeartbeat(int, transport.Request) reply { return reply{status: 200, body: hbBody(300, 2)} }

// ---- fake rotator ----

type fakeRotator struct {
	mu   sync.Mutex
	nows []time.Time
	err  error
}

func (r *fakeRotator) MaybeRotate(_ context.Context, now time.Time) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.nows = append(r.nows, now)
	return r.err
}

func (r *fakeRotator) count() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.nows)
}

// ---- recorded logs ----

type logBuf struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *logBuf) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}

func (l *logBuf) String() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.String()
}

type harness struct {
	clock *fakeClock
	f     *fakeManager
	rot   *fakeRotator
	logs  *logBuf
	run   *loops.Run
	sock  string
	done  chan struct{}
	stop  context.CancelFunc
}

func newHarness(t *testing.T, reply func(int, transport.Request) reply) *harness {
	t.Helper()
	return newHarnessRand(t, reply, half{})
}

func newHarnessRand(t *testing.T, reply func(int, transport.Request) reply, rnd schedule.Source) *harness {
	t.Helper()
	h := &harness{
		clock: &fakeClock{now: t0},
		f:     &fakeManager{reply: reply},
		rot:   &fakeRotator{},
		logs:  &logBuf{},
		sock:  filepath.Join(t.TempDir(), "capread.sock"),
	}
	ctx, cancel := context.WithCancel(context.Background())
	h.stop = cancel
	t.Cleanup(cancel)
	h.run = loops.NewRun(ctx, loops.Deps{
		Client: h.f, Tokens: token.NewHolder(state.Token{Value: canaryTok, IssuedAt: t0, ExpiresAt: t0.AddDate(1, 0, 0), TimesKnown: true}),
		Rotator: h.rot, AgentID: agentID, Version: version, Clock: h.clock, Rand: rnd,
		Log:            slog.New(slog.NewJSONHandler(h.logs, &slog.HandlerOptions{Level: slog.LevelDebug})),
		JobPullSeconds: 300, MaxParallelPlugins: 2, CapreadSock: h.sock,
	})
	return h
}

func (h *harness) start() {
	h.done = make(chan struct{})
	go func() {
		defer close(h.done)
		h.run.Heartbeat()
	}()
}

// waitCalls waits (real time, bounded) for n manager calls.
func (h *harness) waitCalls(t *testing.T, n int) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for h.f.count() < n {
		if time.Now().After(deadline) {
			t.Fatalf("%d calls, want %d", h.f.count(), n)
		}
		time.Sleep(200 * time.Microsecond)
	}
}

func (h *harness) exited(t *testing.T, within time.Duration) {
	t.Helper()
	select {
	case <-h.done:
	case <-time.After(within):
		t.Fatalf("the heartbeat loop did not return within %v", within)
	}
}

// decoded is a heartbeat body as the manager would read it.
func decoded(t *testing.T, r transport.Request) (wire.HeartbeatRequest, map[string]any) {
	t.Helper()
	if r.Op != transport.OpHeartbeat {
		t.Fatalf("call %v, want heartbeat", r.Op)
	}
	var hb wire.HeartbeatRequest
	if err := wire.DecodeStrict(r.Body, &hb); err != nil {
		t.Fatalf("heartbeat body fails the contract: %v (%s)", err, r.Body)
	}
	var m map[string]any
	if err := json.Unmarshal(r.Body, &m); err != nil {
		t.Fatal(err)
	}
	return hb, m
}

// CHK-M4-185: first heartbeat at start, then 20 more at 270..330 s; #78 values.
func TestHeartbeatTimerAndBody(t *testing.T) {
	h := newHarnessRand(t, okHeartbeat, &splitmix{x: 42})
	h.start()
	h.waitCalls(t, 1) // at start, before any wait
	if d := h.clock.next(t); d < 270*time.Second || d > 330*time.Second {
		t.Fatalf("first interval %v", d)
	}
	seen := map[time.Duration]bool{}
	for i := 1; i <= 20; i++ {
		d := h.clock.fire(t)
		if d < 270*time.Second || d > 330*time.Second {
			t.Fatalf("interval %d = %v, want 270..330 s", i, d)
		}
		seen[d] = true
		h.waitCalls(t, i+1)
		hb, m := decoded(t, h.f.req(i))
		now := h.clock.Now()
		if hb.AgentVersion != version || hb.SpoolBytes != 0 || hb.UptimeS != int64(now.Sub(t0).Seconds()) || !hb.Clock.Time().Equal(now) {
			t.Fatalf("heartbeat %d: %+v (now %v)", i, hb, now)
		}
		for _, k := range []string{"last_pull_at", "current_job_id", "last_error"} {
			if v, ok := m[k]; !ok || v != nil {
				t.Fatalf("heartbeat %d: %s = %v (present %v), want null", i, k, v, ok)
			}
		}
		if fmt.Sprint(m["runner_helpers"]) != "[]" {
			t.Fatalf("runner_helpers %v", m["runner_helpers"])
		}
		if r := h.f.req(i); r.Token != string(canaryTok) || r.AgentID != agentID {
			t.Fatal("heartbeat without the current token or the agent id")
		}
	}
	if len(seen) < 10 {
		t.Fatalf("only %d distinct intervals: no jitter", len(seen))
	}
	h.clock.next(t)
	if h.rot.count() != 21 {
		t.Fatalf("MaybeRotate called %d times, want 21 (after each successful heartbeat)", h.rot.count())
	}
	for i, now := range h.rot.nows {
		if want := h.f.req(i); want.Op != transport.OpHeartbeat || now.Before(t0) {
			t.Fatalf("rotation %d at %v", i, now)
		}
	}
	for i := 0; i < h.f.count(); i++ {
		if h.f.req(i).Op != transport.OpHeartbeat {
			t.Fatalf("call %d is %v", i, h.f.req(i).Op)
		}
	}
	h.stop()
	h.exited(t, time.Second)
}

// CHK-M4-185: last_pull_at and current_job_id come from the run state.
func TestHeartbeatRunStateValues(t *testing.T) {
	h := newHarness(t, okHeartbeat)
	pulled := t0.Add(-90 * time.Second)
	h.run.SetLastPull(pulled)
	id := strings.ToUpper(string(jobA))
	jid := wire.UUID(id)
	h.run.SetCurrentJob(&jid)
	h.start()
	h.waitCalls(t, 1)
	_, m := decoded(t, h.f.req(0))
	if m["last_pull_at"] != "2026-10-24T07:58:30Z" || m["current_job_id"] != string(jobA) {
		t.Fatalf("last_pull_at %v current_job_id %v", m["last_pull_at"], m["current_job_id"])
	}
	h.run.SetCurrentJob(nil)
	h.clock.fire(t)
	h.waitCalls(t, 2)
	if _, m = decoded(t, h.f.req(1)); m["current_job_id"] != nil {
		t.Fatalf("current_job_id after the job: %v", m["current_job_id"])
	}
}

// CHK-M4-186: runner_helpers is ["capread"] iff a file exists at the socket
// path (a socket or any file, lead ruling 2026-10-24), else [].
func TestHeartbeatRunnerHelpers(t *testing.T) {
	h := newHarness(t, okHeartbeat)
	ln, err := net.Listen("unix", h.sock)
	if err != nil {
		t.Fatal(err)
	}
	h.start()
	h.waitCalls(t, 1)
	if _, m := decoded(t, h.f.req(0)); fmt.Sprint(m["runner_helpers"]) != "[capread]" {
		t.Fatalf("with a socket: %v", m["runner_helpers"])
	}
	_ = ln.Close()
	_ = os.Remove(h.sock)
	h.clock.fire(t)
	h.waitCalls(t, 2)
	if _, m := decoded(t, h.f.req(1)); fmt.Sprint(m["runner_helpers"]) != "[]" {
		t.Fatalf("after removal: %v", m["runner_helpers"])
	}
	if err := os.WriteFile(h.sock, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	h.clock.fire(t)
	h.waitCalls(t, 3)
	if _, m := decoded(t, h.f.req(2)); fmt.Sprint(m["runner_helpers"]) != "[capread]" {
		t.Fatalf("with a regular file: %v", m["runner_helpers"])
	}
	if loops.CapreadSock != "/run/bitscan/capread.sock" {
		t.Fatalf("production path %q", loops.CapreadSock)
	}
}

// CHK-M4-187: the answer's job_pull_seconds and max_parallel_plugins apply,
// clamped; a change wakes the pull loop, the same value does not.
func TestHeartbeatAppliesIntervals(t *testing.T) {
	answers := []int{60, 60, 3600, 300}
	h := newHarness(t, func(n int, _ transport.Request) reply {
		return reply{status: 200, body: hbBody(answers[min(n, len(answers))-1], min(n, 8))}
	})
	if h.run.MaxParallelPlugins() != 2 {
		t.Fatalf("initial max_parallel %d (agent.yaml value)", h.run.MaxParallelPlugins())
	}
	select {
	case <-h.run.PullChanged():
		t.Fatal("PullChanged fired for the initial value")
	default:
	}
	if d := h.run.PullInterval(); d != 300*time.Second {
		t.Fatalf("initial pull interval %v (u=0.5)", d)
	}
	h.start()
	h.waitCalls(t, 1)
	h.clock.next(t)
	if d := h.run.PullInterval(); d != 60*time.Second || h.run.MaxParallelPlugins() != 1 {
		t.Fatalf("after job_pull_seconds 60: interval %v, max_parallel %d", d, h.run.MaxParallelPlugins())
	}
	select {
	case <-h.run.PullChanged():
	default:
		t.Fatal("PullChanged not signalled for 300 → 60")
	}
	h.clock.fire(t)
	h.waitCalls(t, 2)
	h.clock.next(t)
	select {
	case <-h.run.PullChanged():
		t.Fatal("PullChanged signalled for an unchanged value")
	default:
	}
	h.clock.fire(t)
	h.waitCalls(t, 3)
	h.clock.next(t)
	if d := h.run.PullInterval(); d != 3600*time.Second || h.run.MaxParallelPlugins() != 3 {
		t.Fatalf("after 3600: %v, %d", d, h.run.MaxParallelPlugins())
	}
	// out-of-contract values reach the Run only through SetIntervals: clamped
	for _, c := range [][4]int{{3601, 9, 3600, 8}, {0, 0, 60, 1}, {59, -3, 60, 1}, {1 << 40, 1 << 20, 3600, 8}} {
		h.run.SetIntervals(c[0], c[1])
		if d := h.run.PullInterval(); d != time.Duration(c[2])*time.Second || h.run.MaxParallelPlugins() != c[3] {
			t.Fatalf("SetIntervals(%d, %d): %v, %d", c[0], c[1], d, h.run.MaxParallelPlugins())
		}
	}
}

// CHK-M4-188 (CHK-M4-355): heartbeat answers never cause any other call.
func TestHeartbeatAnswerTriggersNothing(t *testing.T) {
	bodies := [][]byte{
		hbBody(60, 1), hbBody(3600, 8), hbBody(300, 2),
		[]byte(`{"job_pull_seconds":60,"max_parallel_plugins":1,"server_time":"2026-10-24T08:00:00Z","jobs":[{"job_id":"` + string(jobA) + `"}]}`),
		[]byte(`{"job_pull_seconds":60,"max_parallel_plugins":1,"server_time":"2026-10-24T08:00:00Z","command":"id"}`),
		[]byte(`{"job_pull_seconds":60,"max_parallel_plugins":1,"server_time":"2026-10-24T08:00:00Z","upload_inventory":true}`),
		[]byte(`not json`), nil,
	}
	h := newHarness(t, func(n int, _ transport.Request) reply {
		return reply{status: 200, body: bodies[(n-1)%len(bodies)]}
	})
	h.start()
	h.waitCalls(t, 1)
	for i := 2; i <= 50; i++ {
		h.clock.fire(t)
		h.waitCalls(t, i)
	}
	h.clock.next(t)
	for i := 0; i < h.f.count(); i++ {
		if op := h.f.req(i).Op; op != transport.OpHeartbeat {
			t.Fatalf("call %d is %v: a heartbeat answer caused another call", i, op)
		}
	}
	if h.f.count() != 50 {
		t.Fatalf("%d calls for 50 heartbeats", h.f.count())
	}
	// refused answers changed nothing: the last good one (3600 or 300…) stands
	if d := h.run.PullInterval(); d != 300*time.Second && d != 60*time.Second && d != 3600*time.Second {
		t.Fatalf("pull interval %v after refused answers", d)
	}
	// a refused answer is reported once as last_error (fixed text)
	h2 := newHarness(t, func(n int, _ transport.Request) reply {
		if n == 1 {
			return reply{status: 200, body: bodies[3]}
		}
		return okHeartbeat(n, transport.Request{})
	})
	h2.start()
	h2.waitCalls(t, 1)
	h2.clock.fire(t)
	h2.waitCalls(t, 2)
	if hb, _ := decoded(t, h2.f.req(1)); hb.LastError == nil || strings.Contains(*hb.LastError, "jobs") || strings.Contains(*hb.LastError, "c1a4") {
		t.Fatalf("last_error after a refused answer: %v", hb.LastError)
	}
	if h2.run.PullInterval() != 300*time.Second {
		t.Fatalf("a refused answer changed the pull interval: %v", h2.run.PullInterval())
	}
	if h2.rot.count() != 1 {
		t.Fatalf("MaybeRotate after a refused answer: %d calls (want only after the good one)", h2.rot.count())
	}
}

// CHK-M4-189 (CHK-M4-335): a 401 on the heartbeat stops the loops; the Run
// stays up and idle; the line is logged once.
func TestHeartbeat401Stops(t *testing.T) {
	for _, typ := range []string{"token_revoked", "token_expired", "enrollment_rejected", "unauthorized", "machine_id_mismatch", ""} {
		t.Run("type "+typ, func(t *testing.T) {
			h := newHarness(t, func(n int, _ transport.Request) reply {
				if n == 2 {
					return reply{status: 401, typ: typ}
				}
				return okHeartbeat(n, transport.Request{})
			})
			h.start()
			h.waitCalls(t, 1)
			h.clock.fire(t)
			h.exited(t, time.Second)
			if !h.run.Stopped() || h.run.Context().Err() == nil {
				t.Fatal("the Run is not stopped")
			}
			h.clock.advance(48 * time.Hour)
			resp, err := h.run.Call(context.Background(), transport.Request{Op: transport.OpJobs})
			if !errors.Is(err, loops.ErrStopped) || resp.Class != transport.Stop {
				t.Fatalf("Call after stop: %v %v", resp.Class, err)
			}
			time.Sleep(50 * time.Millisecond)
			if h.f.count() != 2 {
				t.Fatalf("%d calls after the 401, want none", h.f.count()-2)
			}
			logs := h.logs.String()
			if strings.Count(logs, "re-enrolled") != 1 {
				t.Fatalf("re-enrol line logged %d times:\n%s", strings.Count(logs, "re-enrolled"), logs)
			}
			if (typ == "token_revoked" || typ == "token_expired") && !strings.Contains(logs, "new enrolment token") {
				t.Fatalf("TS §3.2 step 8: %s must log that a new enrolment token is needed:\n%s", typ, logs)
			}
			// REQ-096 (3): 401 enrollment_rejected on a later heartbeat (a rejected
			// held enrolment, TS §3.2 step 5) gives the same line.
			if typ == "enrollment_rejected" && !strings.Contains(logs, "new enrolment token") {
				t.Fatalf("REQ-096 (3): %s on a heartbeat must log that the host must be re-enrolled with a new enrolment token:\n%s", typ, logs)
			}
		})
	}
}

// CHK-M4-189 (CHK-M4-335): a 401 on another loop's call (the pull) stops the
// heartbeat loop within 1 s; a second 401 logs nothing more.
func TestOther401StopsHeartbeat(t *testing.T) {
	h := newHarness(t, func(_ int, r transport.Request) reply {
		if r.Op == transport.OpJobs {
			return reply{status: 401, typ: "token_revoked"}
		}
		return okHeartbeat(0, r)
	})
	h.start()
	h.waitCalls(t, 1)
	h.clock.next(t) // heartbeat loop asleep
	t1 := time.Now()
	resp, _ := h.run.Call(context.Background(), transport.Request{Op: transport.OpJobs})
	if resp.Class != transport.Stop {
		t.Fatalf("pull 401 class %v", resp.Class)
	}
	h.exited(t, time.Second)
	if time.Since(t1) > time.Second {
		t.Fatal("heartbeat loop took more than 1 s to stop")
	}
	h.run.Stop("token_revoked")
	if c := strings.Count(h.logs.String(), "re-enrolled"); c != 1 {
		t.Fatalf("re-enrol line %d times", c)
	}
	h.clock.advance(72 * time.Hour)
	time.Sleep(50 * time.Millisecond)
	if h.f.count() != 2 {
		t.Fatalf("%d calls after stop", h.f.count())
	}
}

// CHK-M4-189: a rotation 401 (token.ErrStop) stops the loops too.
func TestRotationStopStopsLoops(t *testing.T) {
	h := newHarness(t, okHeartbeat)
	h.rot.err = token.ErrStop
	h.start()
	h.exited(t, time.Second)
	if !h.run.Stopped() || h.f.count() != 1 {
		t.Fatalf("stopped %v, %d calls", h.run.Stopped(), h.f.count())
	}
	if c := strings.Count(h.logs.String(), "re-enrolled"); c != 1 {
		t.Fatalf("re-enrol line logged %d times:\n%s", c, h.logs.String())
	}
	// TS §3.2 step 8: a rotate 401 token_revoked (reuse detection revokes both
	// tokens on rotate) or token_expired must log that a new enrolment token is
	// needed. token.ErrStop carries no type, so every rotation stop needs it.
	if !strings.Contains(h.logs.String(), "new enrolment token") {
		t.Fatalf("TS §3.2 step 8: a rotation 401 must log that the host must be re-enrolled with a new enrolment token:\n%s", h.logs.String())
	}
	// another rotation error does not stop anything
	h2 := newHarness(t, okHeartbeat)
	h2.rot.err = errors.New("token: rotate 503 about:blank")
	h2.start()
	h2.waitCalls(t, 1)
	h2.clock.fire(t)
	h2.waitCalls(t, 2)
	if h2.run.Stopped() {
		t.Fatal("a rotation error that is not a 401 stopped the loops")
	}
}

// CHK-M4-190: 403 pending_approval waits with the back-off (10, 20 … s), not
// the 300 s timer; an approval is picked up without restart.
func TestHeartbeatPendingApproval(t *testing.T) {
	h := newHarness(t, func(n int, _ transport.Request) reply {
		if n <= 4 {
			return reply{status: 403, typ: "pending_approval"}
		}
		return okHeartbeat(n, transport.Request{})
	})
	h.start()
	want := []time.Duration{10 * time.Second, 20 * time.Second, 40 * time.Second, 80 * time.Second}
	for i, w := range want {
		h.waitCalls(t, i+1)
		if d := h.clock.fire(t); d != w {
			t.Fatalf("wait %d after pending_approval = %v, want %v", i+1, d, w)
		}
	}
	h.waitCalls(t, 5)
	if d := h.clock.next(t); d != 300*time.Second {
		t.Fatalf("after approval the wait is %v, want the 300 s timer (u=0.5)", d)
	}
	if h.run.Stopped() || h.rot.count() != 1 {
		t.Fatalf("stopped %v, rotations %d", h.run.Stopped(), h.rot.count())
	}
}

// CHK-M4-191 (CHK-M4-338): 503, 429 and network errors back off 10 → 300 s
// (cap), never a tight loop, and reset after a success.
func TestHeartbeatBackoff(t *testing.T) {
	fails := 9
	h := newHarness(t, func(n int, _ transport.Request) reply {
		switch {
		case n <= fails:
			switch n % 3 {
			case 0:
				return reply{status: 503, typ: "about:blank"}
			case 1:
				return reply{status: 429, typ: "rate_limited"}
			}
			return reply{err: errors.New("dial tcp: connection refused")}
		case n == fails+2:
			return reply{status: 500, typ: "about:blank"}
		}
		return okHeartbeat(n, transport.Request{})
	})
	h.start()
	want := []time.Duration{10, 20, 40, 80, 160, 300, 300, 300, 300}
	for i, w := range want {
		h.waitCalls(t, i+1)
		if d := h.clock.fire(t); d != w*time.Second {
			t.Fatalf("failure %d: wait %v, want %v s", i+1, d, w)
		}
	}
	h.waitCalls(t, fails+1) // success
	if d := h.clock.fire(t); d != 300*time.Second {
		t.Fatalf("after success: %v, want the 300 s timer", d)
	}
	h.waitCalls(t, fails+2) // 500 after a success: back at 10 s
	if d := h.clock.next(t); d != 10*time.Second {
		t.Fatalf("first failure after a success: %v, want 10 s (reset)", d)
	}
}

// CHK-M4-192: a drop becomes last_error "<route> <status> <type>" in the next
// heartbeat and is null in the one after; kept when that heartbeat fails.
func TestHeartbeatLastError(t *testing.T) {
	fail := false
	var mu sync.Mutex
	h := newHarness(t, func(_ int, r transport.Request) reply {
		mu.Lock()
		defer mu.Unlock()
		switch r.Op {
		case transport.OpInventory:
			return reply{status: 422, typ: "about:blank"}
		case transport.OpResults:
			return reply{status: 409, typ: "job_not_acceptable"}
		}
		if fail {
			return reply{status: 503, typ: "about:blank"}
		}
		return okHeartbeat(0, r)
	})
	h.start()
	h.waitCalls(t, 1)
	h.clock.next(t)
	if _, err := h.run.Call(context.Background(), transport.Request{Op: transport.OpInventory, Body: []byte{1}, Gzip: true}); err != nil {
		t.Fatal(err)
	}
	h.clock.fire(t)
	h.waitCalls(t, 3)
	if hb, _ := decoded(t, h.f.req(2)); hb.LastError == nil || *hb.LastError != "inventory 422 about:blank" {
		t.Fatalf("last_error %v, want \"inventory 422 about:blank\"", hb.LastError)
	}
	h.clock.fire(t)
	h.waitCalls(t, 4)
	if hb, _ := decoded(t, h.f.req(3)); hb.LastError != nil {
		t.Fatalf("last_error sent twice: %v", *hb.LastError)
	}
	// a drop, then a failing heartbeat: the error is kept for the next one
	if _, err := h.run.Call(context.Background(), transport.Request{Op: transport.OpResults, JobID: jobA, Body: []byte(`{}`)}); err != nil {
		t.Fatal(err)
	}
	mu.Lock()
	fail = true
	mu.Unlock()
	h.clock.fire(t)
	h.waitCalls(t, 6)
	if hb, _ := decoded(t, h.f.req(5)); hb.LastError == nil || *hb.LastError != "results 409 job_not_acceptable" {
		t.Fatalf("last_error in the failing heartbeat: %v", hb.LastError)
	}
	mu.Lock()
	fail = false
	mu.Unlock()
	h.clock.fire(t)
	h.waitCalls(t, 7)
	if hb, _ := decoded(t, h.f.req(6)); hb.LastError == nil || *hb.LastError != "results 409 job_not_acceptable" {
		t.Fatalf("last_error lost after an unanswered heartbeat: %v", hb.LastError)
	}
	// bounds and sanitising
	h.run.SetLastError(strings.Repeat("é", 2000))
	h.clock.fire(t)
	h.waitCalls(t, 8)
	if hb, _ := decoded(t, h.f.req(7)); hb.LastError == nil || len([]rune(*hb.LastError)) != 1024 {
		t.Fatalf("long last_error not cut to 1,024 characters")
	}
}

// CHK-M4-192: a manager-sent problem type cannot break last_error or a log line.
func TestLastErrorSanitised(t *testing.T) {
	h := newHarness(t, func(_ int, r transport.Request) reply {
		if r.Op == transport.OpInventory {
			return reply{status: 413, typ: "too_large\nINJECTED\x00" + strings.Repeat("x", 3000)}
		}
		return okHeartbeat(0, r)
	})
	h.start()
	h.waitCalls(t, 1)
	h.clock.next(t)
	_, _ = h.run.Call(context.Background(), transport.Request{Op: transport.OpInventory, Body: []byte{1}, Gzip: true})
	h.clock.fire(t)
	h.waitCalls(t, 3)
	hb, _ := decoded(t, h.f.req(2))
	if hb.LastError == nil || strings.ContainsAny(*hb.LastError, "\n\x00") || len([]rune(*hb.LastError)) > 1024 || !strings.HasPrefix(*hb.LastError, "inventory 413 too_large") {
		t.Fatalf("last_error %q", *hb.LastError)
	}
	for _, line := range strings.Split(strings.TrimSpace(h.logs.String()), "\n") {
		if !json.Valid([]byte(line)) {
			t.Fatalf("a log line is not one JSON line: %q", line)
		}
	}
}

// CHK-M4-193: cancelling the parent ends the loop within 1 s, no goroutine left.
func TestHeartbeatCancel(t *testing.T) {
	before := runtime.NumGoroutine()
	h := newHarness(t, okHeartbeat)
	h.start()
	h.waitCalls(t, 1)
	h.clock.next(t)
	t1 := time.Now()
	h.stop()
	h.exited(t, time.Second)
	if time.Since(t1) > time.Second {
		t.Fatal("too slow")
	}
	deadline := time.Now().Add(2 * time.Second)
	for runtime.NumGoroutine() > before && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if n := runtime.NumGoroutine(); n > before {
		t.Fatalf("goroutines %d, before %d", n, before)
	}
	if h.run.Stopped() {
		t.Fatal("a SIGTERM-style cancel is not a 401 stop")
	}
}

// No token, body or manager text in any log line (debug level).
func TestHeartbeatLogsNoSecrets(t *testing.T) {
	h := newHarness(t, func(n int, r transport.Request) reply {
		switch {
		case r.Op == transport.OpResults:
			return reply{status: 400, typ: "invalid_request", body: []byte(`{"detail":"BODY-CANARY"}`)}
		case n%3 == 0:
			return reply{err: errors.New("dial: CANARY-in-error")}
		}
		return reply{status: 200, body: []byte(`{"job_pull_seconds":60,"max_parallel_plugins":1,"server_time":"2026-10-24T08:00:00Z","x":"ANSWER-CANARY"}`)}
	})
	h.start()
	h.waitCalls(t, 1)
	for i := 2; i <= 8; i++ {
		h.clock.fire(t)
		h.waitCalls(t, i)
	}
	_, _ = h.run.Call(context.Background(), transport.Request{Op: transport.OpResults, JobID: jobA, Body: []byte(`{"stdout":"PLUGIN-CANARY"}`)})
	h.run.Stop("token_revoked")
	logs := h.logs.String()
	if strings.Contains(logs, "CANARY") || strings.Contains(logs, "bsa_") {
		t.Fatalf("logs hold a secret:\n%s", logs)
	}
	if !strings.Contains(logs, string(agentID)) {
		t.Fatalf("log lines carry no agent_id:\n%s", logs)
	}
}
