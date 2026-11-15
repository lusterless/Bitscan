// Parallel jobs in the serve loop (TS §3.7, §8.3 Agent; owner decision
// 2026-11-14): up to DefaultMaxJobs connections are served at once, one
// more is refused busy with its request unread, and the idle cleanup runs
// only when the last running job ends, with no job starting meanwhile.
package runner

import (
	"context"
	"errors"
	"net"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
)

// gateExec holds each job until its gate is released, and records when the
// idle cleanup runs relative to the jobs.
type gateExec struct {
	mu      sync.Mutex
	gates   map[wire.UUID]chan struct{}
	started chan wire.UUID
	running atomic.Int32
	idles   atomic.Int32
	// idleWhileRunning counts idle cleanups that saw a job running: must
	// stay 0.
	idleWhileRunning atomic.Int32
	idleHold         chan struct{} // if set, Idle waits on it
	idleErr          error
}

func newGateExec() *gateExec {
	return &gateExec{gates: map[wire.UUID]chan struct{}{}, started: make(chan wire.UUID, 16)}
}

func (g *gateExec) gate(id wire.UUID) chan struct{} {
	g.mu.Lock()
	defer g.mu.Unlock()
	c, ok := g.gates[id]
	if !ok {
		c = make(chan struct{})
		g.gates[id] = c
	}
	return c
}

func (g *gateExec) Run(ctx context.Context, req proto.Request, emit func(proto.Result) error) error {
	g.running.Add(1)
	defer g.running.Add(-1)
	g.started <- req.Job.JobID
	select {
	case <-g.gate(req.Job.JobID):
	case <-ctx.Done():
	}
	return nil
}

func (g *gateExec) Idle(context.Context) error {
	if g.running.Load() != 0 {
		g.idleWhileRunning.Add(1)
	}
	if g.idleHold != nil {
		<-g.idleHold
	}
	g.idles.Add(1)
	return g.idleErr
}

func sendJob(t *testing.T, h *srvHarness, n int) (*net.UnixConn, wire.UUID) {
	t.Helper()
	c := h.dial(t)
	id := jobN(n)
	if err := proto.WriteRequest(c, srvReq(id, nil)); err != nil {
		t.Fatal(err)
	}
	return c, id
}

func waitStarted(t *testing.T, g *gateExec, n int) {
	t.Helper()
	for i := range n {
		select {
		case <-g.started:
		case <-time.After(10 * time.Second):
			t.Fatalf("only %d of %d jobs started", i, n)
		}
	}
}

// Four jobs run at once; a fifth connection is refused busy at once, its
// request unread, and runs nothing.
func TestServeParallelJobs(t *testing.T) {
	g := newGateExec()
	h := startServerN(t, g, 0)
	var conns []*net.UnixConn
	var ids []wire.UUID
	for i := range DefaultMaxJobs {
		c, id := sendJob(t, h, 2240+i)
		conns, ids = append(conns, c), append(ids, id)
	}
	waitStarted(t, g, DefaultMaxJobs)
	if n := h.srv.Active(); n != DefaultMaxJobs {
		t.Fatalf("active %d, want %d", n, DefaultMaxJobs)
	}
	c5 := h.dial(t)
	if err := proto.WriteRequest(c5, srvReq(jobN(2249), nil)); err != nil {
		t.Logf("RECORDED: the busy client's write failed (%v): the runner never reads it", err)
	}
	start := time.Now()
	reps, err := readAll(t, c5, 5*time.Second)
	if err != nil || kinds(reps) != "refused busy" {
		t.Fatalf("fifth connection: %s, %v", kinds(reps), err)
	}
	if d := time.Since(start); d > time.Second {
		t.Fatalf("busy refusal after %v, want at once", d)
	}
	if n := g.running.Load(); n != DefaultMaxJobs {
		t.Fatalf("%d jobs running after the fifth connection, want %d", n, DefaultMaxJobs)
	}
	for _, id := range ids {
		close(g.gate(id))
	}
	for i, c := range conns {
		reps, err := readAll(t, c, 10*time.Second)
		if err != nil || kinds(reps) != "accepted,done" {
			t.Fatalf("job %d: %s, %v", i, kinds(reps), err)
		}
	}
	waitFor(t, func() bool { return h.srv.Active() == 0 })
	if n := g.idleWhileRunning.Load(); n != 0 {
		t.Fatalf("idle cleanup ran %d times while a job ran", n)
	}
	if n := g.idles.Load(); n < 1 {
		t.Fatal("no idle cleanup after the last job ended")
	}
}

// The idle cleanup runs when the last job ends, not when an earlier one
// does; a connection made during it starts only after it.
func TestServeIdleOnlyAfterLastJob(t *testing.T) {
	g := newGateExec()
	g.idleHold = make(chan struct{})
	h := startServerN(t, g, 0)
	c1, id1 := sendJob(t, h, 2250)
	c2, id2 := sendJob(t, h, 2251)
	waitStarted(t, g, 2)
	close(g.gate(id1))
	if reps, err := readAll(t, c1, 10*time.Second); err != nil || kinds(reps) != "accepted,done" {
		t.Fatalf("first job: %s, %v", kinds(reps), err)
	}
	time.Sleep(100 * time.Millisecond)
	if n := g.idles.Load(); n != 0 {
		t.Fatalf("idle cleanup ran %d times while the second job still ran", n)
	}
	close(g.gate(id2))
	if reps, err := readAll(t, c2, 10*time.Second); err != nil || kinds(reps) != "accepted,done" {
		t.Fatalf("second job: %s, %v", kinds(reps), err)
	}
	// The idle cleanup is now held: a new job must not start until it ends.
	c3, id3 := sendJob(t, h, 2252)
	select {
	case <-g.started:
		t.Fatal("a job started during the idle cleanup")
	case <-time.After(300 * time.Millisecond):
	}
	close(g.idleHold)
	waitStarted(t, g, 1)
	close(g.gate(id3))
	if reps, err := readAll(t, c3, 10*time.Second); err != nil || kinds(reps) != "accepted,done" {
		t.Fatalf("third job: %s, %v", kinds(reps), err)
	}
	waitFor(t, func() bool { return g.idles.Load() == 2 })
	if n := g.idleWhileRunning.Load(); n != 0 {
		t.Fatalf("idle cleanup ran %d times while a job ran", n)
	}
}

// A failed idle cleanup is fatal: Serve returns its error and runs nothing
// more.
func TestServeIdleFailureIsFatal(t *testing.T) {
	g := newGateExec()
	g.idleErr = errors.New("sweep failed")
	h := startServerN(t, g, 0)
	c1, id1 := sendJob(t, h, 2260)
	waitStarted(t, g, 1)
	close(g.gate(id1))
	if reps, err := readAll(t, c1, 10*time.Second); err != nil || kinds(reps) != "accepted,done" {
		t.Fatalf("job: %s, %v", kinds(reps), err)
	}
	select {
	case err := <-h.errCh:
		if err == nil || err.Error() != "sweep failed" {
			t.Fatalf("Serve returned %v, want the idle error", err)
		}
		h.errCh <- err // for the cleanup's wait
	case <-time.After(10 * time.Second):
		t.Fatal("Serve did not stop after a failed idle cleanup")
	}
}

func waitFor(t *testing.T, ok func() bool) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for !ok() {
		if time.Now().After(deadline) {
			t.Fatal("condition not met within 10 s")
		}
		time.Sleep(5 * time.Millisecond)
	}
}
