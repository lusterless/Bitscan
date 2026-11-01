// TASK-223 r1 (tester-m10c): after any Put error the handler stores a
// spool_overflow marker for every plugin of the job without a stored result;
// if even that fails it logs the job id and the count only and sets
// last_error "spool: results not kept" (decisions "#140 reading …",
// TASK-223 r1). Linux only, like compliance_linux_test.go (M4's state store
// on Windows).
package loops_test

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/loops"
	"bitscan.local/agent/internal/agent/runnerclient"
	"bitscan.local/agent/internal/agent/state"
	"bitscan.local/agent/internal/agent/token"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
	"bitscan.local/agent/internal/spool"
)

// scriptRunner plays a script against onResult: each step is a result to
// deliver, or a wait on a channel.
type scriptRunner struct {
	mu    sync.Mutex
	calls int
	steps func(job wire.Job, now time.Time) []any // proto.Result or <-chan struct{}
	clock *fakeClock
	err   error // what onResult returned, if anything
}

func (s *scriptRunner) Run(ctx context.Context, job wire.Job, _ int, onResult func(proto.Result) error) error {
	s.mu.Lock()
	s.calls++
	s.mu.Unlock()
	for _, st := range s.steps(job, s.clock.Now()) {
		switch v := st.(type) {
		case proto.Result:
			if err := onResult(v); err != nil {
				s.mu.Lock()
				s.err = err
				s.mu.Unlock()
				return err
			}
		case chan struct{}:
			select {
			case <-v:
			case <-ctx.Done():
				return ctx.Err()
			}
		}
	}
	return nil
}

func bigResult(t *testing.T, id wire.UUID, now time.Time) proto.Result {
	t.Helper()
	code := int64(0)
	r, err := proto.NewResult(wire.ResultItem{PluginUUID: id, ExitCode: &code, Stdout: "M10R1CANARY " + strings.Repeat("x", 60000),
		StartedAt: wire.NewTime(now), FinishedAt: wire.NewTime(now)})
	if err != nil {
		t.Fatal(err)
	}
	return r
}

// startCompMax is startCompPull with a spool of maxBytes and any runner.
func startCompMax(t *testing.T, maxBytes int64, jobs func(int, time.Time) reply, runner loops.RunnerClient, clock *fakeClock, other func(transport.Request) reply) *compHarness {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "bitscan-agent")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	st, err := state.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = st.Close() })
	seen, err := st.LoadSeen(clock.Now)
	if err != nil {
		t.Fatal(err)
	}
	sp, _, err := spool.Open(filepath.Join(dir, "spool"), maxBytes, clock.Now)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = sp.Close() })
	h := &pullHarness{clock: clock, m: &pullManager{clock: clock, jobs: jobs, other: other}, inv: &invRunner{clock: clock}, logs: &logBuf{}, dir: dir, store: st, seen: seen}
	ctx, cancel := context.WithCancel(context.Background())
	h.stop = cancel
	t.Cleanup(cancel)
	h.run = loops.NewRun(ctx, loops.Deps{
		Client: h.m, Tokens: token.NewHolder(state.Token{Value: canaryTok}), Rotator: &fakeRotator{},
		AgentID: agentID, Version: version, Clock: clock, Rand: half{}, Log: newLogger(h.logs),
		JobPullSeconds: 60, MaxParallelPlugins: 3, CapreadSock: filepath.Join(dir, "no-capread.sock"), SpoolBytes: sp.Size,
	})
	sender := loops.NewSender(h.run, sp)
	comp := &loops.Compliance{Run: h.run, Spool: sp, Sender: sender, Runner: runner}
	h.done = make(chan struct{})
	go h.run.Heartbeat()
	go sender.Loop()
	go func() {
		defer close(h.done)
		(&loops.Puller{Run: h.run, Seen: seen, Inventory: h.inv, Compliance: comp}).Loop()
	}()
	return &compHarness{pullHarness: h, sp: sp}
}

func oneJob(t *testing.T) func(int, time.Time) reply {
	return func(n int, now time.Time) reply {
		if n == 1 {
			return reply{status: 200, body: jobsBody(t, compJob(uid(1), now.Add(time.Hour), 3, "id"))}
		}
		return reply{status: 200, body: jobsBody(t)}
	}
}

func allItems(t *testing.T, h *compHarness) map[wire.UUID]wire.ResultItem {
	t.Helper()
	m := map[wire.UUID]wire.ResultItem{}
	for _, c := range h.m.ops(transport.OpResults) {
		for _, it := range resultsOf(t, c.req).Results {
			m[it.PluginUUID] = it
		}
	}
	return m
}

const notInJob = wire.UUID("99999999-0000-4000-8000-000000000999")

// A Put error that leaves room for markers (the result names a plugin not in
// the job, ErrUnknownPlugin): the job is finished, its final batch holds
// result 1 plus spool_overflow markers for 2 and 3; no last_error.
func TestR1PutErrorFillsMarkers(t *testing.T) {
	clock := &fakeClock{now: t0}
	runner := &scriptRunner{clock: clock, steps: func(job wire.Job, now time.Time) []any {
		return []any{bigResult(t, job.Plugins[0].PluginUUID, now), bigResult(t, notInJob, now)}
	}}
	h := startCompMax(t, 50<<20, oneJob(t), runner, clock, nil)
	h.drive(t, func() bool {
		for _, c := range h.m.ops(transport.OpResults) {
			if resultsOf(t, c.req).Final {
				return true
			}
		}
		return false
	})
	if runner.err == nil {
		t.Fatal("the runner's second result was not refused by the spool")
	}
	got := allItems(t, h)
	if len(got) != 3 {
		t.Fatalf("%d plugins posted, want 3: %v", len(got), got)
	}
	if it := got[uid1p(1)]; it.Error != nil || !strings.HasPrefix(it.Stdout, "M10R1CANARY") {
		t.Fatalf("result 1 not kept: %+v", it.Error)
	}
	for _, n := range []int{2, 3} {
		it := got[uid1p(n)]
		if it.Error == nil || *it.Error != wire.ErrSpoolOverflow || it.ExitCode != nil || it.Stdout != "" || it.Stderr != "" {
			t.Fatalf("plugin %d: %+v, want a spool_overflow marker", n, it)
		}
	}
	if _, ok := got[notInJob]; ok {
		t.Fatal("the foreign plugin's result was posted (CHK-M10-392)")
	}
	l := h.logs.String()
	if !strings.Contains(l, "plugins without a stored result are reported spool_overflow") || strings.Contains(l, "M10R1CANARY") {
		t.Fatalf("log %s", l)
	}
	if strings.Contains(l, "spool: results not kept") {
		t.Fatal("last_error set although every plugin was reported")
	}
}

func uid1p(n int) wire.UUID {
	// compJob's plugin uuids (pull_test.go)
	return wire.UUID(fmt.Sprintf("00000000-0000-4000-8000-%012d", n))
}

// No room even for markers (result 1 is in an outstanding post, so it can't
// be converted, and the bound leaves no space): the handler logs the job id
// and the count only, and the next heartbeat carries "spool: results not
// kept"; nothing about plugins 2 and 3 is posted.
func TestR1MarkersCannotBeStored(t *testing.T) {
	clock := &fakeClock{now: t0}
	// The bound: the manifest plus result 1, plus less than one marker.
	probe, _, err := spool.Open(filepath.Join(t.TempDir(), "probe"), 50<<20, clock.Now)
	if err != nil {
		t.Fatal(err)
	}
	ids := []wire.UUID{uid1p(1), uid1p(2), uid1p(3)}
	_ = probe.StartJob(uid(1), ids)
	_ = probe.Put(uid(1), bigResult(t, ids[0], t0))
	bound := probe.Size() + 100
	_ = probe.Close()
	proceed := make(chan struct{})
	inPost := make(chan struct{})
	var once sync.Once
	release := make(chan struct{})
	runner := &scriptRunner{clock: clock, steps: func(job wire.Job, now time.Time) []any {
		return []any{bigResult(t, job.Plugins[0].PluginUUID, now), proceed, bigResult(t, notInJob, now)}
	}}
	h := startCompMax(t, bound, oneJob(t), runner, clock, func(r transport.Request) reply {
		if strings.Contains(string(gunzip(t, r.Body)), `"plugin_uuid"`) {
			once.Do(func() { close(inPost) })
			<-release // result 1 stays in flight
		}
		return reply{status: 200, body: []byte(`{"accepted":1,"duplicates":0}`)}
	})
	// Drive the clock until result 1's batch is being posted (30 s hold).
	deadline := time.Now().Add(60 * time.Second)
	for {
		select {
		case <-inPost:
		default:
			if time.Now().After(deadline) {
				t.Fatal("result 1 was never posted")
			}
			if h.clock.pending() >= 2 {
				h.clock.fireEarliest(t, 2)
			}
			time.Sleep(500 * time.Microsecond)
			continue
		}
		break
	}
	close(proceed)
	for !strings.Contains(h.logs.String(), "not even as markers") {
		if time.Now().After(deadline) {
			close(release)
			t.Fatalf("no lost-results line: %s", h.logs.String())
		}
		time.Sleep(time.Millisecond)
	}
	close(release)
	l := h.logs.String()
	line := ""
	for _, x := range strings.Split(l, "\n") {
		if strings.Contains(x, "not even as markers") {
			line = x
		}
	}
	if !strings.Contains(line, string(uid(1))) || !strings.Contains(line, `"count":2`) || strings.Contains(l, "M10R1CANARY") {
		t.Fatalf("lost line %q (want job_id and count 2, no output)", line)
	}
	h.drive(t, func() bool {
		for _, c := range h.m.ops(transport.OpHeartbeat) {
			if hr, _ := decoded(t, c.req); hr.LastError != nil && *hr.LastError == "spool: results not kept" {
				return true
			}
		}
		return false
	})
	got := allItems(t, h)
	if _, ok := got[uid1p(2)]; ok {
		t.Fatal("plugin 2 posted although its marker could not be stored")
	}
	if it, ok := got[uid1p(1)]; !ok || it.Error != nil {
		t.Fatalf("result 1: %+v %v", it, ok)
	}
	if h.sp.Size() > bound {
		t.Fatalf("spool %d over its bound %d", h.sp.Size(), bound)
	}
}

// CHK-M10-074 (REQ-245 (2), #131 (b), (c)) per failure word through the
// handler: the received result kept, the rest runner_unavailable in the
// final batch, one runner request, last_error "runner_unavailable: <word>".
func TestHandlerFailureWords(t *testing.T) {
	for _, w := range []string{"connect", "timeout", "broken", "protocol", "refused_busy", "refused_foreign_agent", "refused_replayed", "refused_malformed"} {
		t.Run(w, func(t *testing.T) {
			runner := &fakeRunner{results: 1, fail: &runnerclient.Failure{Word: w}}
			h := startCompPull(t, oneJob(t), runner, nil)
			h.drive(t, func() bool {
				final := false
				for _, c := range h.m.ops(transport.OpResults) {
					final = final || resultsOf(t, c.req).Final
				}
				for _, c := range h.m.ops(transport.OpHeartbeat) {
					if hr, _ := decoded(t, c.req); final && hr.LastError != nil && *hr.LastError == "runner_unavailable: "+w {
						return true
					}
				}
				return false
			})
			got := allItems(t, h.compHarness())
			if len(got) != 3 || got[uid1p(1)].Error != nil {
				t.Fatalf("%d items, first %+v", len(got), got[uid1p(1)])
			}
			for _, n := range []int{2, 3} {
				if it := got[uid1p(n)]; it.Error == nil || *it.Error != wire.ErrRunnerUnavailable {
					t.Fatalf("plugin %d: %+v", n, it)
				}
			}
			if c := len(runner.calls_()); c != 1 {
				t.Fatalf("%d runner requests, want 1 (never resent, CHK-M10-358)", c)
			}
		})
	}
}

func (h *compHarness) compHarness() *compHarness { return h }

// concRunner counts how many Runs are in progress at once.
type concRunner struct {
	mu       sync.Mutex
	cur, top int
	calls    int
	release  chan struct{}
	clock    *fakeClock
}

func (c *concRunner) Run(ctx context.Context, job wire.Job, _ int, onResult func(proto.Result) error) error {
	c.mu.Lock()
	c.cur++
	c.calls++
	c.top = max(c.top, c.cur)
	c.mu.Unlock()
	defer func() { c.mu.Lock(); c.cur--; c.mu.Unlock() }()
	select {
	case <-c.release:
	case <-ctx.Done():
		return ctx.Err()
	}
	for _, p := range job.Plugins {
		code := int64(0)
		now := wire.NewTime(c.clock.Now())
		res, err := proto.NewResult(wire.ResultItem{PluginUUID: p.PluginUUID, ExitCode: &code, Stdout: "ok", StartedAt: now, FinishedAt: now})
		if err != nil {
			return err
		}
		if err := onResult(res); err != nil {
			return err
		}
	}
	return nil
}

// CHK-M10-369 (REQ-245, TS §3.3 L222): two compliance jobs are never handed
// to the runner at once; they run one after the other, in pull order.
func TestHandlerOneJobAtATime(t *testing.T) {
	clock := &fakeClock{now: t0}
	r := &concRunner{release: make(chan struct{}), clock: clock}
	h := startCompMax(t, 50<<20, func(n int, now time.Time) reply {
		if n == 1 {
			return reply{status: 200, body: jobsBody(t, compJob(uid(1), now.Add(time.Hour), 1, "id"), compJob(uid(2), now.Add(time.Hour), 1, "id"))}
		}
		return reply{status: 200, body: jobsBody(t)}
	}, r, clock, nil)
	deadline := time.Now().Add(10 * time.Second)
	for {
		r.mu.Lock()
		calls := r.calls
		r.mu.Unlock()
		if calls >= 1 || time.Now().After(deadline) {
			break
		}
		if h.clock.pending() >= 2 {
			h.clock.fireEarliest(t, 2)
		}
		time.Sleep(time.Millisecond)
	}
	time.Sleep(100 * time.Millisecond)
	r.mu.Lock()
	held := r.calls
	r.mu.Unlock()
	if held != 1 {
		t.Fatalf("%d runner calls while the first job is held, want 1", held)
	}
	close(r.release)
	h.drive(t, func() bool {
		finals := 0
		for _, c := range h.m.ops(transport.OpResults) {
			if resultsOf(t, c.req).Final {
				finals++
			}
		}
		return finals == 2
	})
	if r.top != 1 || r.calls != 2 {
		t.Fatalf("at most %d jobs at once over %d calls, want 1 and 2", r.top, r.calls)
	}
}

// CHK-M10-079 (REQ-250 (1), (3); -367, -384): heartbeat spool_bytes is the
// spool's size while results wait; heartbeat answers never reach the runner.
func TestHandlerSpoolBytesAndNoRunnerFromHeartbeat(t *testing.T) {
	clock := &fakeClock{now: t0}
	runner := &scriptRunner{clock: clock, steps: func(job wire.Job, now time.Time) []any {
		var out []any
		for _, p := range job.Plugins {
			out = append(out, bigResult(t, p.PluginUUID, now))
		}
		return out
	}}
	h := startCompMax(t, 50<<20, oneJob(t), runner, clock, func(r transport.Request) reply {
		if strings.Contains(string(gunzip(t, r.Body)), `"plugin_uuid"`) {
			return reply{status: 503, typ: "about:blank"} // results wait in the spool
		}
		return reply{status: 200, body: []byte(`{"accepted":0,"duplicates":0}`)}
	})
	var got int64
	h.drive(t, func() bool {
		for _, c := range h.m.ops(transport.OpHeartbeat) {
			if hr, _ := decoded(t, c.req); hr.SpoolBytes > 180_000 {
				got = hr.SpoolBytes
				return true
			}
		}
		return false
	})
	if size := h.sp.Size(); got != size {
		t.Fatalf("heartbeat spool_bytes %d, Spool.Size() %d (both unchanged since the job finished)", got, size)
	}
	if runner.calls != 1 {
		t.Fatalf("%d runner calls, want 1", runner.calls)
	}
	// Further heartbeats, with any answer values, make no runner contact.
	n := len(h.m.ops(transport.OpHeartbeat))
	for len(h.m.ops(transport.OpHeartbeat)) < n+3 {
		h.clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	if runner.calls != 1 {
		t.Fatalf("a heartbeat answer made the agent contact the runner (%d calls)", runner.calls)
	}
}
