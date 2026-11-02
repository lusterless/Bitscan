// Tests for the job pull, the job checks and dispatch (TS §3.3 L203,
// L211–L216, L222–L226; §6.5 Job pull and Results; #74, #78 (b)/(c); lead
// rulings 2026-10-24; REQ-098, REQ-104; tests/m4/test-plan.md TP-M4-18,
// CHK-M4-215 to -224; mutation rows CHK-M4-330 to -334, -356). The heartbeat
// loop runs too (the first pull waits for it); the fake clock fires the
// earliest waiter; seen ids live in a real state directory.
package loops_test

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/loops"
	"bitscan.local/agent/internal/agent/state"
	"bitscan.local/agent/internal/agent/token"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
)

const otherAgent = wire.UUID("11111111-2222-4333-8444-555555555555")

// fireEarliest wakes the waiter due first (after want pending waiters exist),
// moving the clock forward to its time (never backwards).
func (c *fakeClock) fireEarliest(t *testing.T, want int) time.Time {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		c.mu.Lock()
		if len(c.waiters) >= want {
			break
		}
		c.mu.Unlock()
		if time.Now().After(deadline) {
			t.Fatalf("fewer than %d loops waiting on the clock", want)
		}
		time.Sleep(200 * time.Microsecond)
	}
	best := 0
	for i, w := range c.waiters {
		if w.at.Before(c.waiters[best].at) {
			best = i
		}
	}
	w := c.waiters[best]
	c.waiters = append(c.waiters[:best], c.waiters[best+1:]...)
	if w.at.After(c.now) {
		c.now = w.at
	}
	now := c.now
	c.mu.Unlock()
	w.ch <- now
	return now
}

func (c *fakeClock) pending() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return len(c.waiters)
}

func newLogger(w io.Writer) *slog.Logger {
	return slog.New(slog.NewJSONHandler(w, &slog.HandlerOptions{Level: slog.LevelDebug}))
}

// ---- recording manager for the pull tests ----

type call struct {
	at  time.Time
	req transport.Request
}

type pullManager struct {
	mu    sync.Mutex
	clock *fakeClock
	calls []call
	jobs  func(n int, now time.Time) reply // n-th pull
	other func(r transport.Request) reply  // results, inventory …
	pulls int
	// hbGate, when set, holds every heartbeat answer (after the call is
	// recorded) until it is closed, at most 10 s.
	hbGate chan struct{}
}

func (m *pullManager) Do(_ context.Context, r transport.Request) (transport.Response, error) {
	now := m.clock.Now()
	m.mu.Lock()
	m.calls = append(m.calls, call{now, r})
	var a reply
	switch r.Op {
	case transport.OpHeartbeat:
		a = reply{status: 200, body: hbBody(60, 2)}
	case transport.OpJobs:
		m.pulls++
		a = m.jobs(m.pulls, now)
	default:
		if m.other != nil {
			a = m.other(r)
		} else {
			a = reply{status: 200, body: []byte(`{"accepted":1,"duplicates":0}`)}
		}
	}
	gate := m.hbGate
	m.mu.Unlock()
	if r.Op == transport.OpHeartbeat && gate != nil {
		select {
		case <-gate:
		case <-time.After(10 * time.Second):
		}
	}
	resp := transport.Response{Status: a.status, Body: a.body}
	if a.status != 0 && (a.status < 200 || a.status > 299) {
		resp.Problem = wire.Problem{Type: a.typ, Status: a.status}
	}
	resp.Class = transport.Classify(a.status, a.typ, a.err)
	return resp, a.err
}

func (m *pullManager) ops(op transport.Op) []call {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []call
	for _, c := range m.calls {
		if c.req.Op == op {
			out = append(out, c)
		}
	}
	return out
}

func (m *pullManager) waitOps(t *testing.T, op transport.Op, n int) []call {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		if got := m.ops(op); len(got) >= n {
			return got
		}
		if time.Now().After(deadline) {
			t.Fatalf("%d %v calls, want %d", len(m.ops(op)), op, n)
		}
		time.Sleep(200 * time.Microsecond)
	}
}

// ---- fake inventory runner and compliance handler ----

type invRunner struct {
	mu    sync.Mutex
	jobs  []wire.UUID
	at    []time.Time
	clock *fakeClock
	check func(id wire.UUID) // runs inside RunJob
}

func (i *invRunner) RunJob(_ context.Context, id wire.UUID) {
	if i.check != nil {
		i.check(id)
	}
	i.mu.Lock()
	defer i.mu.Unlock()
	i.jobs = append(i.jobs, id)
	i.at = append(i.at, i.clock.Now())
}

func (i *invRunner) Unscheduled(context.Context) {}

func (i *invRunner) ids() []wire.UUID {
	i.mu.Lock()
	defer i.mu.Unlock()
	return append([]wire.UUID(nil), i.jobs...)
}

func (i *invRunner) waitN(t *testing.T, n int) []wire.UUID {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for len(i.ids()) < n {
		if time.Now().After(deadline) {
			t.Fatalf("%d inventory jobs run, want %d", len(i.ids()), n)
		}
		time.Sleep(200 * time.Microsecond)
	}
	return i.ids()
}

type pullHarness struct {
	clock *fakeClock
	m     *pullManager
	inv   *invRunner
	run   *loops.Run
	logs  *logBuf
	dir   string
	store *state.Store
	seen  *state.Seen
	stop  context.CancelFunc
	done  chan struct{}
}

func newPullHarness(t *testing.T, jobs func(n int, now time.Time) reply, comp loops.ComplianceHandler) *pullHarness {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "bitscan-agent")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	return startPull(t, dir, &fakeClock{now: t0}, jobs, comp)
}

func startPull(t *testing.T, dir string, clock *fakeClock, jobs func(n int, now time.Time) reply, comp loops.ComplianceHandler) *pullHarness {
	t.Helper()
	st, err := state.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = st.Close() })
	seen, err := st.LoadSeen(clock.Now)
	if err != nil {
		t.Fatal(err)
	}
	h := &pullHarness{clock: clock, m: &pullManager{clock: clock, jobs: jobs}, inv: &invRunner{clock: clock}, logs: &logBuf{}, dir: dir, store: st, seen: seen}
	ctx, cancel := context.WithCancel(context.Background())
	h.stop = cancel
	t.Cleanup(cancel)
	h.run = loops.NewRun(ctx, loops.Deps{
		Client: h.m, Tokens: token.NewHolder(state.Token{Value: canaryTok}), Rotator: &fakeRotator{},
		AgentID: agentID, Version: version, Clock: clock, Rand: half{},
		Log:            newLogger(h.logs),
		JobPullSeconds: 60, MaxParallelPlugins: 2, CapreadSock: filepath.Join(dir, "no-capread.sock"),
	})
	// PD-45: the M4 #74 Unavailable fallback is gone (REQ-245). A nil handler
	// now means "no compliance handler": each compliance job is refused,
	// inventory still runs. The #74 rows are rewritten in compliance_test.go.
	h.done = make(chan struct{})
	go h.run.Heartbeat()
	go func() {
		defer close(h.done)
		(&loops.Puller{Run: h.run, Seen: seen, Inventory: h.inv, Compliance: comp}).Loop()
	}()
	return h
}

func jobsBody(t testing.TB, jobs ...map[string]any) []byte {
	t.Helper()
	if jobs == nil {
		jobs = []map[string]any{}
	}
	b, err := json.Marshal(map[string]any{"jobs": jobs})
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func invJob(id wire.UUID, agent wire.UUID, pickup time.Time) map[string]any {
	return map[string]any{"job_id": string(id), "agent_id": string(agent), "kind": "inventory", "pickup_by": pickup.UTC().Format(time.RFC3339Nano)}
}

func compJob(id wire.UUID, pickup time.Time, nPlugins int, execute string) map[string]any {
	plugins := make([]map[string]any, nPlugins)
	for i := range plugins {
		plugins[i] = map[string]any{"plugin_uuid": fmt.Sprintf("00000000-0000-4000-8000-%012d", i+1), "execute": execute, "timeout_s": 30}
	}
	return map[string]any{"job_id": string(id), "agent_id": string(agentID), "kind": "compliance", "pickup_by": pickup.UTC().Format(time.RFC3339Nano), "plugins": plugins, "redaction_patterns": []string{}}
}

func uid(n int) wire.UUID { return wire.UUID(fmt.Sprintf("aaaaaaaa-0000-4000-8000-%012d", n)) }

// CHK-M4-215: 20 pulls job_pull_seconds ± 30 s apart (60 s here: 30..90 s);
// an empty list causes no other call and no collection.
func TestPullTimerAndEmptyList(t *testing.T) {
	h := newPullHarness(t, func(int, time.Time) reply { return reply{status: 200, body: jobsBody(t)} }, nil)
	h.m.waitOps(t, transport.OpJobs, 1)
	for len(h.m.ops(transport.OpJobs)) < 21 {
		h.clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	pulls := h.m.waitOps(t, transport.OpJobs, 21)
	hb := h.m.ops(transport.OpHeartbeat)
	if pulls[0].at.Before(hb[0].at) {
		t.Fatal("the first pull came before the first heartbeat")
	}
	for i := 1; i < len(pulls); i++ {
		gap := pulls[i].at.Sub(pulls[i-1].at)
		if gap < 30*time.Second || gap > 90*time.Second {
			t.Fatalf("pull %d came %v after the previous one, want 30..90 s", i+1, gap)
		}
	}
	for _, c := range h.m.calls {
		if c.req.Op != transport.OpJobs && c.req.Op != transport.OpHeartbeat {
			t.Fatalf("an empty list led to a %v call", c.req.Op)
		}
	}
	if len(h.inv.ids()) != 0 {
		t.Fatal("an empty list led to a collection")
	}
	// last_pull_at = the last pull answered 200 (#78 (b))
	h.clock.fireEarliest(t, 2)
	if got := h.m.ops(transport.OpHeartbeat); len(got) > 0 {
		last := got[len(got)-1]
		hbReq, m := decoded(t, last.req)
		if m["last_pull_at"] == nil || hbReq.LastPullAt.Time().After(last.at) {
			t.Fatalf("last_pull_at %v in the heartbeat at %v", m["last_pull_at"], last.at)
		}
	}
}

// CHK-M4-216 (CHK-M4-330 to -333): refused jobs are not run, are recorded as
// seen and logged with a fixed reason; the boundaries of pickup_by.
func TestJobChecks(t *testing.T) {
	h := newPullHarness(t, func(n int, now time.Time) reply {
		switch n {
		case 1:
			return reply{status: 200, body: jobsBody(t,
				invJob(uid(1), otherAgent, now.Add(time.Hour)),                                  // foreign
				invJob(uid(2), wire.UUID(strings.ToUpper(string(agentID))), now.Add(time.Hour)), // ours, upper case
				invJob(uid(3), agentID, now),                                                    // pickup_by = now
				invJob(uid(4), agentID, now.Add(-time.Second)),                                  // past
				invJob(uid(5), agentID, now.Add(25*time.Hour+time.Second)),                      // too far
				invJob(uid(6), agentID, now.Add(25*time.Hour)),                                  // exactly 25 h: ok
				invJob(uid(2), agentID, now.Add(time.Hour)),                                     // same pull, seen
				invJob(uid(7), agentID, now.Add(time.Second)),                                   // just ahead: ok
			)}
		case 2:
			return reply{status: 200, body: jobsBody(t, invJob(uid(6), agentID, now.Add(time.Hour)), invJob(uid(8), agentID, now.Add(time.Hour)))}
		}
		return reply{status: 200, body: jobsBody(t)}
	}, nil)
	got := h.inv.waitN(t, 3)
	time.Sleep(20 * time.Millisecond)
	if fmt.Sprint(h.inv.ids()) != fmt.Sprint([]wire.UUID{uid(2), uid(6), uid(7)}) {
		t.Fatalf("run %v, want [%s %s %s]", got, uid(2), uid(6), uid(7))
	}
	for _, id := range []int{1, 2, 3, 4, 5, 6, 7} {
		if !h.seen.Has(uid(id)) {
			t.Errorf("job %d not recorded as seen", id)
		}
	}
	logs := h.logs.String()
	for _, reason := range []string{"addressed to another agent", "pickup_by has passed", "pickup_by is more than 25 h away", "already seen"} {
		if !strings.Contains(logs, reason) {
			t.Errorf("no log line with reason %q", reason)
		}
	}
	// an earlier pull's id is refused; a new one runs
	h.clock.fireEarliest(t, 2)
	h.inv.waitN(t, 4)
	time.Sleep(20 * time.Millisecond)
	if ids := h.inv.ids(); len(ids) != 4 || ids[3] != uid(8) {
		t.Fatalf("second pull ran %v", ids)
	}
	// restart: a new store, Seen, Run and Puller on the same directory. Loop
	// returns only once both workers have; bounded, so a loop that never ends
	// fails here rather than through the package timeout.
	h.stop()
	select {
	case <-h.done:
	case <-time.After(5 * time.Second):
		t.Fatal("the pull loop did not return within 5 s of the stop")
	}
	h2 := startPull(t, h.dir, &fakeClock{now: h.clock.Now().Add(time.Hour)}, func(_ int, now time.Time) reply {
		return reply{status: 200, body: jobsBody(t, invJob(uid(7), agentID, now.Add(time.Hour)), invJob(uid(9), agentID, now.Add(time.Hour)))}
	}, nil)
	h2.inv.waitN(t, 1)
	time.Sleep(20 * time.Millisecond)
	if ids := h2.inv.ids(); len(ids) != 1 || ids[0] != uid(9) {
		t.Fatalf("after restart ran %v, want only %s (a replay must be refused)", ids, uid(9))
	}
	// no refused job led to any call of its own
	for _, c := range h.m.calls {
		if c.req.Op == transport.OpInventory || c.req.Op == transport.OpResults {
			t.Fatalf("a %v call from the pull loop itself", c.req.Op)
		}
	}
}

// CHK-M4-217 (CHK-M4-334): an id is refused 7 d − 1 s after it was first
// seen and accepted again 7 d + 1 s after.
func TestJobSeenSevenDays(t *testing.T) {
	var first time.Time
	h := newPullHarness(t, func(n int, now time.Time) reply {
		if n == 1 {
			first = now
		}
		return reply{status: 200, body: jobsBody(t, invJob(uid(1), agentID, now.Add(time.Hour)))}
	}, nil)
	h.inv.waitN(t, 1)
	h.clock.advance(first.Add(7*24*time.Hour - time.Second).Sub(h.clock.Now()))
	for len(h.m.ops(transport.OpJobs)) < 2 {
		h.clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	pulls := h.m.waitOps(t, transport.OpJobs, 2)
	if pulls[1].at.After(first.Add(7*24*time.Hour - time.Second + 2*time.Minute)) {
		t.Fatalf("second pull at %v, too late for the boundary check", pulls[1].at)
	}
	time.Sleep(20 * time.Millisecond)
	if n := len(h.inv.ids()); n != 1 {
		t.Fatalf("a job seen %v ago ran again", pulls[1].at.Sub(first))
	}
	h.clock.advance(first.Add(7*24*time.Hour + time.Second).Sub(h.clock.Now()))
	for len(h.m.ops(transport.OpJobs)) < 3 {
		h.clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	h.inv.waitN(t, 2)
}

// CHK-M4-218: the id is persisted as seen before the job is acted on; a
// failed record means the job is not run.
func TestJobSeenBeforeAct(t *testing.T) {
	h := newPullHarness(t, func(n int, now time.Time) reply {
		if n == 1 {
			return reply{status: 200, body: jobsBody(t, invJob(uid(1), agentID, now.Add(time.Hour)))}
		}
		return reply{status: 200, body: jobsBody(t)}
	}, nil)
	var inFile bool
	h.inv.mu.Lock()
	h.inv.check = func(id wire.UUID) {
		b, err := os.ReadFile(filepath.Clean(filepath.Join(h.dir, "seen_jobs.json")))
		inFile = err == nil && strings.Contains(string(b), string(id))
	}
	h.inv.mu.Unlock()
	h.inv.waitN(t, 1)
	if !inFile {
		t.Fatal("the job ran before its id was in seen_jobs.json")
	}
}

type failingSeen struct{}

func (failingSeen) Has(wire.UUID) bool { return false }
func (failingSeen) Add(wire.UUID) error {
	return fmt.Errorf("state: write seen_jobs.json: no space left on device")
}

func TestJobNotRunWhenSeenFails(t *testing.T) {
	clock := &fakeClock{now: t0}
	m := &pullManager{clock: clock, jobs: func(n int, now time.Time) reply {
		return reply{status: 200, body: jobsBody(t, invJob(uid(n), agentID, now.Add(time.Hour)), compJob(uid(100+n), now.Add(time.Hour), 1, "id"))}
	}}
	inv := &invRunner{clock: clock}
	logs := &logBuf{}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	r := loops.NewRun(ctx, loops.Deps{Client: m, Tokens: token.NewHolder(state.Token{Value: canaryTok}), Rotator: &fakeRotator{},
		AgentID: agentID, Version: version, Clock: clock, Rand: half{}, Log: newLogger(logs), JobPullSeconds: 60, MaxParallelPlugins: 2})
	go r.Heartbeat()
	done := make(chan struct{})
	go func() { defer close(done); (&loops.Puller{Run: r, Seen: failingSeen{}, Inventory: inv}).Loop() }()
	m.waitOps(t, transport.OpJobs, 1)
	clock.fireEarliest(t, 2)
	m.waitOps(t, transport.OpJobs, 2)
	time.Sleep(30 * time.Millisecond)
	if len(inv.ids()) != 0 || len(m.ops(transport.OpResults)) != 0 {
		t.Fatalf("jobs ran although their ids could not be recorded: %v, %d results", inv.ids(), len(m.ops(transport.OpResults)))
	}
	for len(m.ops(transport.OpHeartbeat)) < 2 {
		clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	for _, hb := range m.ops(transport.OpHeartbeat)[1:] {
		if hbReq, _ := decoded(t, hb.req); hbReq.LastError != nil && *hbReq.LastError == "seen job ids not saved" {
			cancel()
			select {
			case <-done:
			case <-time.After(5 * time.Second):
				t.Fatal("the pull loop did not return within 5 s of the cancel")
			}
			return
		}
	}
	t.Fatal("no last_error for the failed record")
}

// Plan TASK-101 ("the first pull waits for it", FirstHeartbeat) and the
// TASK-103 Loop: no pull is sent while the first heartbeat is unanswered; the
// first pull follows at once when it is.
func TestFirstPullWaitsForFirstHeartbeat(t *testing.T) {
	clock := &fakeClock{now: t0}
	gate := make(chan struct{})
	m := &pullManager{clock: clock, hbGate: gate, jobs: func(int, time.Time) reply { return reply{status: 200, body: jobsBody(t)} }}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	r := loops.NewRun(ctx, loops.Deps{Client: m, Tokens: token.NewHolder(state.Token{Value: canaryTok}), Rotator: &fakeRotator{},
		AgentID: agentID, Version: version, Clock: clock, Rand: half{}, Log: newLogger(&logBuf{}), JobPullSeconds: 60, MaxParallelPlugins: 2,
		CapreadSock: filepath.Join(t.TempDir(), "no-capread.sock")})
	go r.Heartbeat()
	done := make(chan struct{})
	go func() {
		defer close(done)
		(&loops.Puller{Run: r, Seen: failingSeen{}, Inventory: &invRunner{clock: clock}}).Loop()
	}()
	m.waitOps(t, transport.OpHeartbeat, 1)
	time.Sleep(200 * time.Millisecond)
	if n := len(m.ops(transport.OpJobs)); n != 0 {
		t.Fatalf("%d pulls while the first heartbeat was still unanswered, want 0", n)
	}
	close(gate)
	pulls := m.waitOps(t, transport.OpJobs, 1)
	if !pulls[0].at.Equal(t0) {
		t.Fatalf("first pull at %v, want at once after the first heartbeat (%v)", pulls[0].at, t0)
	}
	cancel()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("the pull loop did not return within 5 s of the cancel")
	}
}

// blockingHandler records compliance jobs and blocks each until released.
type blockingHandler struct {
	mu      sync.Mutex
	order   []wire.UUID
	active  int
	overlap bool
	release chan struct{}
}

func (b *blockingHandler) Handle(ctx context.Context, job wire.Job) {
	b.mu.Lock()
	b.order = append(b.order, job.JobID)
	b.active++
	if b.active > 1 {
		b.overlap = true
	}
	b.mu.Unlock()
	select {
	case <-b.release:
	case <-ctx.Done():
	}
	b.mu.Lock()
	b.active--
	b.mu.Unlock()
}

func (b *blockingHandler) seen() []wire.UUID {
	b.mu.Lock()
	defer b.mu.Unlock()
	return append([]wire.UUID(nil), b.order...)
}

// CHK-M4-219, -222: an inventory job runs at once, alongside a running
// compliance job; compliance jobs run one at a time in pull order.
func TestJobDispatchOrder(t *testing.T) {
	b := &blockingHandler{release: make(chan struct{})}
	h := newPullHarness(t, func(n int, now time.Time) reply {
		if n == 1 {
			return reply{status: 200, body: jobsBody(t,
				compJob(uid(1), now.Add(time.Hour), 1, "id"),
				compJob(uid(2), now.Add(time.Hour), 1, "id"),
				invJob(uid(3), agentID, now.Add(time.Hour)),
				compJob(uid(4), now.Add(time.Hour), 1, "id"),
			)}
		}
		return reply{status: 200, body: jobsBody(t)}
	}, b)
	h.inv.waitN(t, 1) // the inventory job ran while compliance job 1 is blocked
	if s := b.seen(); len(s) != 1 || s[0] != uid(1) {
		t.Fatalf("compliance jobs started %v while job 1 blocks", s)
	}
	// current_job_id is the compliance job being handled (#78 (c))
	for len(h.m.ops(transport.OpHeartbeat)) < 2 {
		h.clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	hb := h.m.ops(transport.OpHeartbeat)
	if _, m := decoded(t, hb[1].req); m["current_job_id"] != string(uid(1)) {
		t.Fatalf("current_job_id %v while job 1 runs", m["current_job_id"])
	}
	for range 3 {
		b.release <- struct{}{}
	}
	deadline := time.Now().Add(5 * time.Second)
	for len(b.seen()) < 3 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if fmt.Sprint(b.seen()) != fmt.Sprint([]wire.UUID{uid(1), uid(2), uid(4)}) || b.overlap {
		t.Fatalf("compliance order %v, overlap %v", b.seen(), b.overlap)
	}
}

// CHK-M4-222: 11 jobs in one answer are refused by the decoder: none runs.
func TestPullElevenJobsRefused(t *testing.T) {
	h := newPullHarness(t, func(_ int, now time.Time) reply {
		var jobs []map[string]any
		for i := range 11 {
			jobs = append(jobs, invJob(uid(i+1), agentID, now.Add(time.Hour)))
		}
		return reply{status: 200, body: jobsBody(t, jobs...)}
	}, nil)
	h.m.waitOps(t, transport.OpJobs, 1)
	h.clock.fireEarliest(t, 2)
	time.Sleep(30 * time.Millisecond)
	if n := len(h.inv.ids()); n != 0 {
		t.Fatalf("%d jobs of an 11-job answer ran", n)
	}
	if !strings.Contains(h.logs.String(), "job pull answer failed the contract check") {
		t.Fatal("no log line for the refused answer")
	}
}

// CHK-M4-220 and CHK-M4-221 (the #74 handler) are replaced by requirement
// (PD-45, REQ-245, REQ-246): see compliance_test.go, TestPD45ComplianceThroughRunner,
// TestPD45RunnerUnavailableFill and TestPD45Batches.

// CHK-M4-189 via the pull: a 401 on the pull stops both loops.
func TestPull401StopsAll(t *testing.T) {
	h := newPullHarness(t, func(int, time.Time) reply { return reply{status: 401, typ: "token_revoked"} }, nil)
	select {
	case <-h.done:
	case <-time.After(time.Second):
		t.Fatal("the pull loop did not stop on a 401")
	}
	if !h.run.Stopped() {
		t.Fatal("Run not stopped")
	}
	n := len(h.m.calls)
	h.clock.advance(48 * time.Hour)
	time.Sleep(50 * time.Millisecond)
	if len(h.m.calls) != n {
		t.Fatal("calls after the 401")
	}
}

// Pull back-off: 503, 429, network and 403 pending_approval use 10, 20, 40 s;
// a success resets to the normal interval.
func TestPullBackoff(t *testing.T) {
	h := newPullHarness(t, func(n int, _ time.Time) reply {
		switch n {
		case 1:
			return reply{status: 503, typ: "about:blank"}
		case 2:
			return reply{status: 429, typ: "rate_limited"}
		case 3:
			return reply{status: 403, typ: "pending_approval"}
		case 4:
			return reply{err: fmt.Errorf("connection refused")}
		}
		return reply{status: 200, body: jobsBody(t)}
	}, nil)
	for len(h.m.ops(transport.OpJobs)) < 7 {
		h.clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	p := h.m.ops(transport.OpJobs)
	want := []time.Duration{10, 20, 40, 80, 60, 60}
	for i, w := range want {
		if gap := p[i+1].at.Sub(p[i].at); gap != w*time.Second {
			t.Fatalf("gap after pull %d = %v, want %v s", i+1, gap, w)
		}
	}
}

// CHK-M4-187 via the pull: a new job_pull_seconds from a heartbeat restarts
// the pull wait from now.
func TestPullFollowsHeartbeatInterval(t *testing.T) {
	clock := &fakeClock{now: t0}
	pullSec := 3600
	var mu sync.Mutex
	m := &pullManager{clock: clock, jobs: func(int, time.Time) reply { return reply{status: 200, body: jobsBody(t)} }}
	d := &switchingDoer{m: m, hb: func() []byte { mu.Lock(); defer mu.Unlock(); return hbBody(pullSec, 2) }}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	r := loops.NewRun(ctx, loops.Deps{Client: d, Tokens: token.NewHolder(state.Token{Value: canaryTok}), Rotator: &fakeRotator{},
		AgentID: agentID, Version: version, Clock: clock, Rand: half{}, Log: newLogger(&logBuf{}), JobPullSeconds: 3600, MaxParallelPlugins: 2})
	go r.Heartbeat()
	dir := filepath.Join(t.TempDir(), "s")
	_ = os.Mkdir(dir, 0o700)
	st, _ := state.Open(dir)
	defer func() { _ = st.Close() }()
	seen, _ := st.LoadSeen(clock.Now)
	go (&loops.Puller{Run: r, Seen: seen, Inventory: &invRunner{clock: clock}}).Loop()
	first := m.waitOps(t, transport.OpJobs, 1)[0].at
	mu.Lock()
	pullSec = 60
	mu.Unlock()
	clock.fireEarliest(t, 2) // heartbeat at +300 answers 60
	// wait for the orphaned 3,600 s timer, the next heartbeat and the pull's
	// restarted timer before moving the clock, or the pull would register late
	clock.fireEarliest(t, 3)
	second := m.waitOps(t, transport.OpJobs, 2)[1].at
	if got := second.Sub(first); got != 360*time.Second {
		t.Fatalf("second pull %v after the first, want 300 s (heartbeat) + 60 s", got)
	}
}

// switchingDoer answers heartbeats with a changeable body, the rest via m.
type switchingDoer struct {
	m  *pullManager
	hb func() []byte
}

func (s *switchingDoer) Do(ctx context.Context, r transport.Request) (transport.Response, error) {
	if r.Op == transport.OpHeartbeat {
		s.m.mu.Lock()
		s.m.calls = append(s.m.calls, call{s.m.clock.Now(), r})
		s.m.mu.Unlock()
		return transport.Response{Status: 200, Body: s.hb(), Class: transport.Success}, nil
	}
	return s.m.Do(ctx, r)
}

// CHK-M4-220; CHK-M4-223 rewritten as CHK-M10-271 (user decision
// 2026-11-01 (2), old-to-new rule): static: jobs reach the handlers only from
// the pull code; nothing in the agent packages executes a process; the
// runner socket (runner.sock, AF_UNIX) is reached only from
// internal/agent/runnerclient (REQ-245); no agent package listens, and the
// only other socket is the manager connection in internal/agent/transport.
func TestNoOtherJobSourceStatic(t *testing.T) {
	root, err := os.OpenRoot(filepath.Join("..", "..", "..", "internal", "agent"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = root.Close() }()
	callRe := regexp.MustCompile(`\.(RunJob|Handle)\(`)
	// AF_UNIX in any spelling Go offers: network names, unix types and
	// constants, the x/sys/unix import and raw socket calls.
	unixRe := regexp.MustCompile(`runner\.sock|"unix(gram|packet)?"|\bnet\.(DialUnix|ListenUnix\w*|UnixAddr|UnixConn|ResolveUnixAddr)\b|\b(syscall|unix)\.(AF_UNIX|AF_LOCAL|Socket|Connect|Bind)\b|"golang\.org/x/sys/unix"`)
	// Opening any socket at all: allowed only in runnerclient (the runner)
	// and transport (the manager).
	dialRe := regexp.MustCompile(`\bnet\.(Dial|DialTimeout|DialTCP|DialUDP|DialIP|Dialer)\b`)
	// Listening is never allowed in the agent (TS §2.2; agent rule "Never").
	listenRe := regexp.MustCompile(`\bnet\.(Listen\w*|FileListener|FileConn|FilePacketConn)\b`)
	var callers []string
	var runnerSites int
	err = fs.WalkDir(root.FS(), ".", func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return err
		}
		b, err := root.ReadFile(p)
		if err != nil {
			return err
		}
		src := string(b)
		pkg := filepath.ToSlash(filepath.Dir(p))
		for _, bad := range []string{`"os/exec"`, "syscall.Exec", "syscall.ForkExec", "os.StartProcess"} {
			if strings.Contains(src, bad) {
				t.Errorf("%s contains %s", p, bad)
			}
		}
		if m := unixRe.FindAllString(src, -1); len(m) > 0 {
			if pkg == "runnerclient" {
				runnerSites += len(m)
			} else {
				t.Errorf("%s reaches the runner socket or AF_UNIX (%v): only internal/agent/runnerclient may", p, m)
			}
		}
		if m := dialRe.FindAllString(src, -1); len(m) > 0 && pkg != "runnerclient" && pkg != "transport" {
			t.Errorf("%s opens a socket (%v): only runnerclient and transport may", p, m)
		}
		if m := listenRe.FindAllString(src, -1); len(m) > 0 {
			t.Errorf("%s listens (%v): the agent never listens", p, m)
		}
		for i, line := range strings.Split(src, "\n") {
			if callRe.MatchString(line) && !strings.HasPrefix(strings.TrimSpace(line), "//") && !strings.Contains(line, "func ") {
				callers = append(callers, fmt.Sprintf("%s:%d", filepath.Base(p), i+1))
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(callers)
	for _, c := range callers {
		if !strings.HasPrefix(c, "pull.go:") && !strings.HasPrefix(c, "jobs.go:") {
			t.Errorf("RunJob or Handle called from %s", c)
		}
	}
	if len(callers) == 0 {
		t.Fatal("no caller found: the walk is wrong")
	}
	// The allowed site must really be seen, or the walk is wrong: the client
	// names runner.sock and dials "unix".
	if runnerSites < 2 {
		t.Fatalf("runnerclient shows %d runner-socket sites, want at least 2: the walk is wrong", runnerSites)
	}
}

// CHK-M4-185 via the pull: last_pull_at is set only by a pull answered 200.
func TestLastPullOnlyOn200(t *testing.T) {
	h := newPullHarness(t, func(n int, _ time.Time) reply {
		if n <= 6 {
			return reply{status: 503, typ: "about:blank"}
		}
		return reply{status: 200, body: jobsBody(t)}
	}, nil)
	// back-off 10+20+40+80+160 = 310 s: the heartbeat at +300 comes after 5 failed pulls
	for len(h.m.ops(transport.OpHeartbeat)) < 2 {
		h.clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	hb := h.m.ops(transport.OpHeartbeat)
	if len(h.m.ops(transport.OpJobs)) < 2 {
		t.Fatal("no failed pull before the second heartbeat")
	}
	if _, m := decoded(t, hb[1].req); m["last_pull_at"] != nil {
		t.Fatalf("last_pull_at %v after failed pulls only", m["last_pull_at"])
	}
	for len(h.m.ops(transport.OpJobs)) < 8 {
		h.clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	okPull := h.m.ops(transport.OpJobs)[6].at
	after := func() []call {
		var out []call
		for _, c := range h.m.ops(transport.OpHeartbeat) {
			if c.at.After(okPull) {
				out = append(out, c)
			}
		}
		return out
	}
	for len(after()) < 1 {
		h.clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	hr, _ := decoded(t, after()[0].req)
	if hr.LastPullAt == nil || hr.LastPullAt.Time().Before(okPull) {
		t.Fatalf("last_pull_at %v, want the 200 pull at or after %v", hr.LastPullAt, okPull)
	}
}

// TS §3.3 L212: a job must start before its pickup_by; one that waited past
// it behind a compliance job is refused when its turn comes.
func TestJobPickupRecheckedAtStart(t *testing.T) {
	b := &blockingHandler{release: make(chan struct{})}
	h := newPullHarness(t, func(n int, now time.Time) reply {
		if n == 1 {
			return reply{status: 200, body: jobsBody(t,
				compJob(uid(1), now.Add(time.Hour), 1, "id"),
				compJob(uid(2), now.Add(90*time.Second), 1, "id"),
			)}
		}
		return reply{status: 200, body: jobsBody(t)}
	}, b)
	deadline := time.Now().Add(5 * time.Second)
	for len(b.seen()) < 1 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	// Fail fast instead of blocking on b.release below (tester-m10c): on
	// Windows M4's state store refuses to record a seen id (the directory
	// fsync), so no job ever reaches the handler (a known Windows row).
	if len(b.seen()) < 1 {
		t.Fatal("job 1 never reached the handler")
	}
	start := h.clock.Now()
	for h.clock.Now().Sub(start) < 2*time.Minute {
		h.clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	b.release <- struct{}{}
	time.Sleep(50 * time.Millisecond)
	if s := b.seen(); len(s) != 1 {
		t.Fatalf("handled %v: job 2 started after its pickup_by", s)
	}
	if !strings.Contains(h.logs.String(), "pickup_by passed before the job could start") {
		t.Fatal("no log line for the late job")
	}
}
