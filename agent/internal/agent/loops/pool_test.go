// Parallel compliance jobs (TS §3.3, §8.3 Agent; owner decision 2026-11-14):
// at most max_parallel_jobs at once, started in pull order; a job sharing a
// plugin_uuid with a running job waits and is never overtaken by a newer job
// of the same policy; max_parallel_jobs from the heartbeat is applied.
package loops_test

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/loops"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
)

// gateHandler holds each job until released and records start order and the
// most jobs running at once.
type gateHandler struct {
	mu      sync.Mutex
	gates   map[wire.UUID]chan struct{}
	started []wire.UUID
	running int
	most    int
	notify  chan wire.UUID
}

func newGateHandler() *gateHandler {
	return &gateHandler{gates: map[wire.UUID]chan struct{}{}, notify: make(chan wire.UUID, 32)}
}

func (g *gateHandler) gate(id wire.UUID) chan struct{} {
	g.mu.Lock()
	defer g.mu.Unlock()
	c, ok := g.gates[id]
	if !ok {
		c = make(chan struct{})
		g.gates[id] = c
	}
	return c
}

func (g *gateHandler) Handle(ctx context.Context, job wire.Job) {
	gate := g.gate(job.JobID)
	g.mu.Lock()
	g.started = append(g.started, job.JobID)
	g.running++
	g.most = max(g.most, g.running)
	g.mu.Unlock()
	g.notify <- job.JobID
	select {
	case <-gate:
	case <-ctx.Done():
	}
	g.mu.Lock()
	g.running--
	g.mu.Unlock()
}

func (g *gateHandler) next(t *testing.T) wire.UUID {
	t.Helper()
	select {
	case id := <-g.notify:
		return id
	case <-time.After(10 * time.Second):
		t.Fatal("no job started within 10 s")
		return ""
	}
}

func (g *gateHandler) none(t *testing.T) {
	t.Helper()
	select {
	case id := <-g.notify:
		t.Fatalf("job %s started, want none", id)
	case <-time.After(200 * time.Millisecond):
	}
}

func (g *gateHandler) mostRunning() int {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.most
}

// policyJob is a compliance job whose plugin ids belong to policy p.
func policyJob(id wire.UUID, pickup time.Time, p int) map[string]any {
	j := compJob(id, pickup, 2, "true")
	plugins := j["plugins"].([]map[string]any)
	for i := range plugins {
		plugins[i]["plugin_uuid"] = fmt.Sprintf("00000000-0000-4000-8%03d-%012d", p, i+1)
	}
	return j
}

func pullOnce(t *testing.T, jobs ...map[string]any) func(int, time.Time) reply {
	return func(n int, _ time.Time) reply {
		if n == 1 {
			return reply{status: 200, body: jobsBody(t, jobs...)}
		}
		return reply{status: 200, body: jobsBody(t)}
	}
}

// Five jobs of five policies with max_parallel_jobs 2: two run at once, in
// pull order, and each end starts the next; all five run.
func TestPoolTwoAtOnceInPullOrder(t *testing.T) {
	g := newGateHandler()
	pickup := t0.Add(time.Hour)
	var jobs []map[string]any
	for i := 1; i <= 5; i++ {
		jobs = append(jobs, policyJob(uid(700+i), pickup, i))
	}
	newPullHarness(t, pullOnce(t, jobs...), g)
	if a, b := g.next(t), g.next(t); a != uid(701) || b != uid(702) {
		t.Fatalf("first two started %s %s, want 701 702", a, b)
	}
	g.none(t)
	for i := 1; i <= 3; i++ {
		close(g.gate(uid(700 + i)))
		if got := g.next(t); got != uid(702+i) {
			t.Fatalf("after job %d ended, %s started, want %s", 700+i, got, uid(702+i))
		}
	}
	close(g.gate(uid(704)))
	close(g.gate(uid(705)))
	if m := g.mostRunning(); m != 2 {
		t.Fatalf("at most %d jobs ran at once, want 2", m)
	}
}

// Same policy never twice at once, and never overtaken by a newer job of
// that policy; another policy may start first.
func TestPoolSamePolicyWaits(t *testing.T) {
	g := newGateHandler()
	pickup := t0.Add(time.Hour)
	// A1 (policy 1), B (policy 2), A2 (policy 1), C (policy 3), A3 (policy 1)
	newPullHarness(t, pullOnce(t,
		policyJob(uid(711), pickup, 1), policyJob(uid(712), pickup, 2), policyJob(uid(713), pickup, 1),
		policyJob(uid(714), pickup, 3), policyJob(uid(715), pickup, 1)), g)
	if a, b := g.next(t), g.next(t); a != uid(711) || b != uid(712) {
		t.Fatalf("started %s %s, want 711 712", a, b)
	}
	// B ends: A2 still waits for A1, so C (another policy) starts.
	close(g.gate(uid(712)))
	if got := g.next(t); got != uid(714) {
		t.Fatalf("after B ended %s started, want C (714)", got)
	}
	g.none(t)
	// A1 ends: A2 starts, never A3 before it.
	close(g.gate(uid(711)))
	if got := g.next(t); got != uid(713) {
		t.Fatalf("after A1 ended %s started, want A2 (713)", got)
	}
	g.none(t)
	close(g.gate(uid(714)))
	g.none(t) // A3 still waits for A2
	close(g.gate(uid(713)))
	if got := g.next(t); got != uid(715) {
		t.Fatalf("after A2 ended %s started, want A3 (715)", got)
	}
	close(g.gate(uid(715)))
}

// A retry shares its original's plugin ids, so it waits like the same
// policy; jobs with overlapping plugin lists never run together.
func TestPoolRetryWaitsForOriginal(t *testing.T) {
	g := newGateHandler()
	pickup := t0.Add(time.Hour)
	orig := policyJob(uid(721), pickup, 1)
	retry := policyJob(uid(722), pickup, 1)
	retry["plugins"] = retry["plugins"].([]map[string]any)[1:] // a subset
	newPullHarness(t, pullOnce(t, orig, retry), g)
	if got := g.next(t); got != uid(721) {
		t.Fatalf("%s started first", got)
	}
	g.none(t)
	close(g.gate(uid(721)))
	if got := g.next(t); got != uid(722) {
		t.Fatalf("%s started second", got)
	}
	close(g.gate(uid(722)))
}

// max_parallel_jobs 1 restores one job at a time; raising it starts the
// waiting job at once.
func TestPoolLimitChanges(t *testing.T) {
	g := newGateHandler()
	pickup := t0.Add(time.Hour)
	ready := make(chan struct{})
	h := newPullHarness(t, func(n int, _ time.Time) reply {
		if n == 1 {
			<-ready // the limit is set before the jobs arrive
			return reply{status: 200, body: jobsBody(t, policyJob(uid(731), pickup, 1), policyJob(uid(732), pickup, 2))}
		}
		return reply{status: 200, body: jobsBody(t)}
	}, g)
	h.run.SetMaxParallelJobs(1)
	close(ready)
	if got := g.next(t); got != uid(731) {
		t.Fatalf("%s started first", got)
	}
	g.none(t)
	h.run.SetMaxParallelJobs(2)
	if got := g.next(t); got != uid(732) {
		t.Fatalf("raising the limit started %s, want 732", got)
	}
	close(g.gate(uid(731)))
	close(g.gate(uid(732)))
}

// The heartbeat answer's max_parallel_jobs is applied and clamped; an answer
// without it (an older manager, or an agent below 0.5.0) leaves the value; out of 1–4 the whole
// answer is refused by the contract check.
func TestHeartbeatAppliesMaxParallelJobs(t *testing.T) {
	answers := []string{
		`{"job_pull_seconds":300,"max_parallel_plugins":2,"max_parallel_jobs":3,"server_time":"2026-10-24T08:00:00Z"}`,
		`{"job_pull_seconds":300,"max_parallel_plugins":2,"server_time":"2026-10-24T08:00:00Z"}`,
		`{"job_pull_seconds":300,"max_parallel_plugins":2,"max_parallel_jobs":9,"server_time":"2026-10-24T08:00:00Z"}`,
		`{"job_pull_seconds":300,"max_parallel_plugins":2,"max_parallel_jobs":null,"server_time":"2026-10-24T08:00:00Z"}`,
		`{"job_pull_seconds":300,"max_parallel_plugins":2,"max_parallel_jobs":1,"server_time":"2026-10-24T08:00:00Z"}`,
	}
	h := newHarness(t, func(n int, _ transport.Request) reply {
		return reply{status: 200, body: []byte(answers[min(n, len(answers))-1])}
	})
	if got := h.run.MaxParallelJobs(); got != loops.DefaultMaxParallelJobs {
		t.Fatalf("initial %d", got)
	}
	h.start()
	want := []int{3, 3, 3, 3, 1}
	for i, w := range want {
		h.waitCalls(t, i+1)
		h.clock.next(t)
		if got := h.run.MaxParallelJobs(); got != w {
			t.Fatalf("after answer %d: max_parallel_jobs %d, want %d", i+1, got, w)
		}
		if i+1 < len(want) {
			h.clock.fire(t)
		}
	}
	for _, c := range [][2]int{{0, 2}, {-1, 1}, {9, 4}, {1 << 30, 4}} {
		h.run.SetMaxParallelJobs(c[0])
		if got := h.run.MaxParallelJobs(); got != c[1] {
			t.Fatalf("SetMaxParallelJobs(%d) = %d, want %d", c[0], got, c[1])
		}
	}
}
