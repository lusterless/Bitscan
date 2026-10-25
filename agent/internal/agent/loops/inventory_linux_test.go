// CHK-M4-101, job-path half (REQ-100 (5); #35): jobs carrying a planted
// command reach the real inventory collector (inventory.CollectBody, the
// production Collector) only as a job id. Linux only: it runs the real
// dpkg-query and os_info commands. The tester runs it under
// `strace -f -e trace=execve` so every argv is recorded and checked for the
// canary (the exec counter); in-process it checks that the canary file is
// never created and never reaches the upload body.
package loops_test

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/loops"
	"bitscan.local/agent/internal/agent/state"
	"bitscan.local/agent/internal/agent/token"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/inventory"
)

type jobPathManager struct {
	mu      sync.Mutex
	clock   *fakeClock
	answers [][]byte // the n-th pull's body; then empty lists
	pulls   int
	uploads []transport.Request
	results []transport.Request
}

func (m *jobPathManager) Do(_ context.Context, r transport.Request) (transport.Response, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	switch r.Op {
	case transport.OpHeartbeat:
		return transport.Response{Status: 200, Body: hbBody(60, 2), Class: transport.Success}, nil
	case transport.OpJobs:
		m.pulls++
		body := []byte(`{"jobs":[]}`)
		if m.pulls <= len(m.answers) {
			body = m.answers[m.pulls-1]
		}
		return transport.Response{Status: 200, Body: body, Class: transport.Success}, nil
	case transport.OpInventory:
		r.Body = append([]byte(nil), r.Body...)
		m.uploads = append(m.uploads, r)
		return transport.Response{Status: 204, Class: transport.Success}, nil
	case transport.OpResults:
		m.results = append(m.results, r)
		return transport.Response{Status: 200, Body: []byte(`{"accepted":1,"duplicates":0}`), Class: transport.Success}, nil
	}
	return transport.Response{Status: 404, Class: transport.Drop, Problem: wire.Problem{Type: "about:blank", Status: 404}}, nil
}

func (m *jobPathManager) counts() (pulls, uploads, results int) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.pulls, len(m.uploads), len(m.results)
}

func TestInventoryJobPathTakesNoJobInput(t *testing.T) { // CHK-M4-101 (job path)
	dir := t.TempDir()
	canary := filepath.Join(dir, "CANARY-m4b-101")
	execute := "touch " + canary
	t.Run("valid answer: inventory job beside a compliance job with the canary", func(t *testing.T) {
		pickup := t0.Add(time.Hour)
		answer := jobsBody(t, invJob(jobA, agentID, pickup), compJob(jobB, pickup, 2, execute))
		h := runJobPath(t, [][]byte{answer})
		waitFor(t, func() bool { _, u, r := h.m.counts(); return u >= 1 && r >= 1 }, "the inventory upload and the results")
		h.m.mu.Lock()
		up := h.m.uploads[0]
		h.m.mu.Unlock()
		if up.JobID != jobA {
			t.Errorf("upload job_id %q, want %s", up.JobID, jobA)
		}
		b, js := decodeUpload(t, up.Body)
		if strings.Contains(string(js), "CANARY") {
			t.Error("the canary reached the upload body")
		}
		if len(b.Packages) == 0 {
			t.Error("the real collector listed no package")
		}
		if _, err := os.Lstat(canary); err == nil {
			t.Fatal("the planted command ran: the canary file exists")
		}
	})
	t.Run("an inventory job carrying plugins is refused whole", func(t *testing.T) {
		pickup := t0.Add(time.Hour)
		bad := invJob(jobA, agentID, pickup)
		bad["plugins"] = compJob(jobB, pickup, 1, execute)["plugins"]
		h := runJobPath(t, [][]byte{jobsBody(t, bad)})
		waitFor(t, func() bool { p, _, _ := h.m.counts(); return p >= 1 }, "the pull")
		time.Sleep(200 * time.Millisecond) // a real collection would take this long at most
		if _, u, _ := h.m.counts(); u != 0 {
			t.Errorf("%d uploads for a refused answer, want 0", u)
		}
		if _, err := os.Lstat(canary); err == nil {
			t.Fatal("the planted command ran: the canary file exists")
		}
		if strings.Contains(h.logs.String(), "CANARY") {
			t.Error("the canary is logged")
		}
	})
}

type jobPathHarness struct {
	m    *jobPathManager
	logs *logBuf
}

func runJobPath(t *testing.T, answers [][]byte) *jobPathHarness {
	t.Helper()
	clock := &fakeClock{now: t0}
	sdir := filepath.Join(t.TempDir(), "bitscan-agent")
	if err := os.Mkdir(sdir, 0o700); err != nil {
		t.Fatal(err)
	}
	st, err := state.Open(sdir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = st.Close() })
	seen, err := st.LoadSeen(clock.Now)
	if err != nil {
		t.Fatal(err)
	}
	h := &jobPathHarness{m: &jobPathManager{clock: clock, answers: answers}, logs: &logBuf{}}
	ctx, cancel := context.WithCancel(context.Background())
	run := loops.NewRun(ctx, loops.Deps{
		Client: h.m, Tokens: token.NewHolder(state.Token{Value: canaryTok}), Rotator: &fakeRotator{},
		AgentID: agentID, Version: version, Clock: clock, Rand: half{}, Log: newLogger(h.logs),
		JobPullSeconds: 60, MaxParallelPlugins: 2, CapreadSock: filepath.Join(sdir, "none.sock"),
	})
	done := make(chan struct{})
	go run.Heartbeat()
	go func() {
		defer close(done)
		(&loops.Puller{Run: run, Seen: seen, Inventory: loops.NewInventory(run, inventory.CollectBody)}).Loop()
	}()
	t.Cleanup(func() { stopAndWait(t, cancel, done, "the job-path Puller.Loop") })
	return h
}

func waitFor(t *testing.T, cond func() bool, what string) {
	t.Helper()
	deadline := time.Now().Add(30 * time.Second)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %s", what)
		}
		time.Sleep(time.Millisecond)
	}
}
