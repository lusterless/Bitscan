// TP-M10-16 (tester-m10): the compliance handler with the spool and the
// results sender, REQ-245, REQ-246, REQ-249, REQ-250; #131; PD-45.
//
// PD-45 rewrite (old → new, listed in work/reports/TASK-223-test.md):
//   - CHK-M4-220 (#74: one final batch of runner_unavailable, no runner
//     contact) → TestPD45ComplianceThroughRunner (REQ-245 (1), (5)) and
//     TestPD45RunnerUnavailableFill (REQ-245 (2), #131 (b), (c)); the "409 is
//     dropped, never retried, becomes last_error" and "nothing executed or
//     stored" assertions are kept in them.
//   - CHK-M4-221 (#74 batches of ≤ 50, only the last final, retries with the
//     same bytes) → TestPD45Batches (REQ-246 (1), with the start notice first).
//
// The runner is an in-process fake RunnerClient here; the real runnerclient
// over a Unix socket is exercised in the TASK-223 suite.
//
// Linux only (decisions "The PD-45 compliance tests are Linux-only"; TP-M10-16
// runs in WSL and CI): every accepted job is first recorded through M4's
// state store, whose directory fsync Windows refuses, so on Windows every
// pulled job is refused before a handler runs.
package loops_test

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
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

// fakeRunner is an in-process RunnerClient: it records each call and replays
// a script.
type fakeRunner struct {
	mu    sync.Mutex
	calls []fakeCall
	// results: how many of the job's plugins get a result (−1 = all).
	results int
	// fail: the error returned after the results (nil = done).
	fail  error
	clock *fakeClock
	// returned is closed when the first Run returns (set by the test).
	returned chan struct{}
}

type fakeCall struct {
	job wire.Job
	mpp int
}

func (f *fakeRunner) Run(ctx context.Context, job wire.Job, mpp int, onResult func(proto.Result) error) error {
	f.mu.Lock()
	f.calls = append(f.calls, fakeCall{job, mpp})
	n, fail := f.results, f.fail
	f.mu.Unlock()
	if n < 0 || n > len(job.Plugins) {
		n = len(job.Plugins)
	}
	for i := range n {
		code := int64(i)
		now := f.clock.Now()
		r, err := proto.NewResult(wire.ResultItem{
			PluginUUID: job.Plugins[i].PluginUUID, ExitCode: &code,
			Stdout: fmt.Sprintf("out %d", i), StartedAt: wire.NewTime(now), FinishedAt: wire.NewTime(now),
		})
		if err != nil {
			return err
		}
		if err := onResult(r); err != nil {
			return err
		}
	}
	if f.returned != nil {
		defer close(f.returned)
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	return fail
}

func (f *fakeRunner) calls_() []fakeCall {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]fakeCall(nil), f.calls...)
}

type compHarness struct {
	*pullHarness
	sp     *spool.Spool
	runner *fakeRunner
}

// startCompPull is startPull with a real spool, the real Sender and the real
// Compliance handler around a fake runner.
func startCompPull(t *testing.T, jobs func(n int, now time.Time) reply, runner *fakeRunner, other func(transport.Request) reply) *compHarness {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "bitscan-agent")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	clock := &fakeClock{now: t0}
	runner.clock = clock
	st, err := state.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = st.Close() })
	seen, err := st.LoadSeen(clock.Now)
	if err != nil {
		t.Fatal(err)
	}
	sp, _, err := spool.Open(filepath.Join(dir, "spool"), 50<<20, clock.Now)
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
		AgentID: agentID, Version: version, Clock: clock, Rand: half{},
		Log:            newLogger(h.logs),
		JobPullSeconds: 60, MaxParallelPlugins: 3, CapreadSock: filepath.Join(dir, "no-capread.sock"),
		SpoolBytes: sp.Size,
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
	return &compHarness{pullHarness: h, sp: sp, runner: runner}
}

// results decodes a results post (gzip, strict contract).
func resultsOf(t *testing.T, r transport.Request) wire.ResultsRequest {
	t.Helper()
	if !r.Gzip {
		t.Fatal("results post not gzip")
	}
	zr, err := gzip.NewReader(bytes.NewReader(r.Body))
	if err != nil {
		t.Fatal(err)
	}
	raw, err := io.ReadAll(zr)
	if err != nil {
		t.Fatal(err)
	}
	var rr wire.ResultsRequest
	if err := wire.DecodeStrict(raw, &rr); err != nil {
		t.Fatalf("results body fails the contract: %v", err)
	}
	return rr
}

// drive fires the earliest clock waiter until cond holds (bounded).
func (h *compHarness) drive(t *testing.T, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(120 * time.Second)
	for !cond() {
		if time.Now().After(deadline) {
			logs := h.logs.String()
			if len(logs) > 4000 {
				logs = logs[len(logs)-4000:]
			}
			t.Fatalf("condition not reached; %d results posts; agent log tail:\n%s", len(h.m.ops(transport.OpResults)), logs)
		}
		if h.clock.pending() >= 2 {
			h.clock.fireEarliest(t, 2)
		}
		time.Sleep(500 * time.Microsecond)
	}
}

func stateFiles(t *testing.T, dir string) map[string]string {
	t.Helper()
	out := map[string]string{}
	err := filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		b, err := fs.ReadFile(os.DirFS(filepath.Dir(p)), filepath.Base(p))
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(dir, p)
		out[filepath.ToSlash(rel)] = string(b)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// PD-45, CHK-M4-220 → REQ-245 (1), (5): start notice, results, final; one
// runner request carrying the pulled job; nothing executed or stored.
func TestPD45ComplianceThroughRunner(t *testing.T) {
	canaryFile := filepath.Join(t.TempDir(), "EXEC-CANARY-5f1c")
	execute := "touch " + canaryFile + " && cat /etc/shadow"
	runner := &fakeRunner{results: -1}
	var pulled map[string]any
	h := startCompPull(t, func(n int, now time.Time) reply {
		if n == 1 {
			pulled = compJob(uid(1), now.Add(time.Hour), 3, execute)
			return reply{status: 200, body: jobsBody(t, pulled)}
		}
		return reply{status: 200, body: jobsBody(t)}
	}, runner, nil)
	h.drive(t, func() bool {
		for _, c := range h.m.ops(transport.OpResults) {
			if resultsOf(t, c.req).Final {
				return true
			}
		}
		return false
	})
	res := h.m.ops(transport.OpResults)
	first := resultsOf(t, res[0].req)
	if first.Final || len(first.Results) != 0 {
		t.Fatalf("first post %+v, want the start notice {results: [], final: false}", first)
	}
	got := map[wire.UUID]int{}
	for i, c := range res {
		if c.req.JobID != uid(1) {
			t.Fatalf("post %d for job %s", i, c.req.JobID)
		}
		rr := resultsOf(t, c.req)
		if rr.Final && i != len(res)-1 {
			t.Fatal("a post after the final batch")
		}
		for _, it := range rr.Results {
			got[it.PluginUUID]++
			if it.Error != nil {
				t.Fatalf("item %+v has an error", it)
			}
		}
		if strings.Contains(string(c.req.Body), "CANARY") {
			t.Fatal("the plugin command is in a results body")
		}
	}
	if len(got) != 3 {
		t.Fatalf("results for %d plugins, want 3: %v", len(got), got)
	}
	for id, n := range got {
		if n != 1 {
			t.Fatalf("plugin %s posted %d times", id, n)
		}
	}
	calls := runner.calls_()
	if len(calls) != 1 {
		t.Fatalf("%d runner requests, want 1", len(calls))
	}
	if calls[0].mpp != 2 { // the last heartbeat answer (hbBody(60, 2))
		t.Fatalf("max_parallel_plugins %d, want the heartbeat's 2", calls[0].mpp)
	}
	if calls[0].job.JobID != uid(1) || len(calls[0].job.Plugins) != 3 || calls[0].job.Plugins[2].Execute != execute {
		t.Fatalf("the runner got %+v", calls[0].job)
	}
	// Nothing executed by the agent, nothing logged or stored.
	if _, err := os.Stat(canaryFile); err == nil {
		t.Fatal("the plugin command was executed")
	}
	if strings.Contains(h.logs.String(), "CANARY") || strings.Contains(h.logs.String(), "shadow") {
		t.Fatal("the plugin command was logged")
	}
	for name, body := range stateFiles(t, h.dir) {
		if strings.Contains(body, "CANARY") || strings.Contains(body, "shadow") {
			t.Fatalf("the plugin command is stored in %s", name)
		}
		if name != "seen_jobs.json" && !strings.HasPrefix(name, "spool/") {
			t.Fatalf("unexpected state file %s", name)
		}
	}
	for _, c := range h.m.calls {
		if c.req.Op != transport.OpHeartbeat && c.req.Op != transport.OpJobs && c.req.Op != transport.OpResults {
			t.Fatalf("unexpected %v call", c.req.Op)
		}
	}
}

// PD-45, CHK-M4-220 → REQ-245 (2), #131 (b), (c): a runner failure fills
// every plugin without a result as runner_unavailable at the agent's time,
// then the final batch, no second request, last_error once; a 409 is dropped
// and never retried and becomes last_error (TS §3.3 L224).
func TestPD45RunnerUnavailableFill(t *testing.T) {
	runner := &fakeRunner{results: 1, fail: &runnerclient.Failure{Word: "broken"}}
	h := startCompPull(t, func(n int, now time.Time) reply {
		if n == 1 {
			return reply{status: 200, body: jobsBody(t, compJob(uid(1), now.Add(time.Hour), 3, "id"))}
		}
		return reply{status: 200, body: jobsBody(t)}
	}, runner, nil)
	var final wire.ResultsRequest
	h.drive(t, func() bool {
		for _, c := range h.m.ops(transport.OpResults) {
			if rr := resultsOf(t, c.req); rr.Final {
				final = rr
				return true
			}
		}
		return false
	})
	var all []wire.ResultItem
	for _, c := range h.m.ops(transport.OpResults) {
		all = append(all, resultsOf(t, c.req).Results...)
	}
	if len(all) != 3 {
		t.Fatalf("%d items, want 3", len(all))
	}
	unavail := 0
	for _, it := range all {
		if it.PluginUUID == "00000000-0000-4000-8000-000000000001" {
			if it.Error != nil || it.Stdout != "out 0" {
				t.Fatalf("the received result was not kept: %+v", it)
			}
			continue
		}
		unavail++
		if it.Error == nil || *it.Error != wire.ErrRunnerUnavailable || it.ExitCode != nil || it.Stdout != "" || it.Stderr != "" ||
			it.TimedOut || it.Truncated || !it.StartedAt.Time().Equal(it.FinishedAt.Time()) {
			t.Fatalf("fill item %+v", it)
		}
	}
	// #131 (b): the job is finished and its final batch follows the fill.
	// The fill items may go in the final batch or just before it: #141 makes
	// the final batch empty when everything was already accepted (tester-m10c:
	// "final batch has items" was a timing assumption, seen red once in WSL).
	if unavail != 2 {
		t.Fatalf("%d fill items, want 2", unavail)
	}
	if res := h.m.ops(transport.OpResults); !resultsOf(t, res[len(res)-1].req).Final {
		t.Fatalf("a post after the final batch (final had %d items)", len(final.Results))
	}
	if n := len(runner.calls_()); n != 1 {
		t.Fatalf("%d runner requests, want 1 (never resent)", n)
	}
	// last_error once, then cleared.
	// Every heartbeat from the start: the first non-null last_error is the
	// #131 (c) text, and the heartbeat after it is null.
	seq := func() []string {
		var out []string
		for _, c := range h.m.ops(transport.OpHeartbeat) {
			hr, _ := decoded(t, c.req)
			if hr.LastError != nil {
				out = append(out, *hr.LastError)
			} else {
				out = append(out, "<null>")
			}
		}
		return out
	}
	idx := func(s []string) int {
		for i, v := range s {
			if v != "<null>" {
				return i
			}
		}
		return -1
	}
	h.drive(t, func() bool { s := seq(); i := idx(s); return i >= 0 && len(s) > i+1 })
	s := seq()
	i := idx(s)
	if s[i] != "runner_unavailable: broken" || s[i+1] != "<null>" {
		t.Fatalf("last_error sequence %v", s)
	}
	if strings.Contains(h.logs.String(), "out 0") {
		t.Fatal("a result's stdout was logged")
	}
}

// The M4 "409 dropped, not retried, becomes last_error" assertion of
// CHK-M4-220, kept under REQ-246 (4).
func TestPD45Results409Dropped(t *testing.T) {
	runner := &fakeRunner{results: -1}
	h := startCompPull(t, func(n int, now time.Time) reply {
		if n == 1 {
			return reply{status: 200, body: jobsBody(t, compJob(uid(1), now.Add(time.Hour), 3, "id"))}
		}
		return reply{status: 200, body: jobsBody(t)}
	}, runner, func(transport.Request) reply { return reply{status: 409, typ: "job_not_acceptable"} })
	h.drive(t, func() bool { return h.sp.Size() == 0 && len(h.m.ops(transport.OpResults)) >= 2 })
	n := len(h.m.ops(transport.OpResults))
	start := h.clock.Now()
	h.drive(t, func() bool { return h.clock.Now().Sub(start) > 10*time.Minute })
	if got := len(h.m.ops(transport.OpResults)); got != n {
		t.Fatalf("%d posts after 10 min, %d before: a 409 was retried", got, n)
	}
	found := false
	for _, c := range h.m.ops(transport.OpHeartbeat) {
		if hr, _ := decoded(t, c.req); hr.LastError != nil && *hr.LastError == "results 409 job_not_acceptable" {
			found = true
		}
	}
	if !found {
		t.Fatal("the 409 did not become last_error")
	}
}

// PD-45, CHK-M4-221 → REQ-246 (1): start notice, then batches of at most 50
// (and 1,572,864 bytes uncompressed), only the last final; a 503 retry
// carries the same results.
//
// PR #18 CI fix (old → new; work/reports/PR18-ci-fix-test.md): the retry used
// to be asserted byte-identical to the 503'd post. TASK-220 r1 (decisions
// "#140 reading", 2026-10-30) releases the batch after a failed attempt and
// rebuilds it with Next before the retry, so the bytes may change: a full
// batch posted before Finish goes as final=false and comes back as the final
// once the job has finished (50 plugins on a slow host), and a converted item
// goes as its marker. The retry must now carry exactly the 503'd post's
// plugins, each once, each with the same result or its spool_overflow
// marker, and a final copy stays final.
func TestPD45Batches(t *testing.T) {
	for _, n := range []int{1, 50, 51, 120, 5000} {
		t.Run(fmt.Sprint(n, " plugins"), func(t *testing.T) {
			if n == 5000 && testing.Short() {
				t.Skip("short")
			}
			var mu sync.Mutex
			first503 := true
			runner := &fakeRunner{results: -1, returned: make(chan struct{})}
			h := startCompPull(t, func(k int, now time.Time) reply {
				if k == 1 {
					return reply{status: 200, body: jobsBody(t, compJob(uid(1), now.Add(time.Hour), n, "true"))}
				}
				return reply{status: 200, body: jobsBody(t)}
			}, runner, func(r transport.Request) reply {
				mu.Lock()
				defer mu.Unlock()
				if first503 && bytes.Contains(gunzip(t, r.Body), []byte(`"plugin_uuid"`)) {
					first503 = false
					return reply{status: 503, typ: "about:blank"}
				}
				return reply{status: 200, body: []byte(`{"accepted":1,"duplicates":0}`)}
			})
			// Let the runner deliver every result before the clock moves, so
			// the batches are full ones (a moving clock releases partial
			// batches after 30 s, #141, which is correct but not this row).
			select {
			case <-runner.returned:
			case <-time.After(120 * time.Second):
				t.Fatal("the fake runner did not finish")
			}
			time.Sleep(50 * time.Millisecond)
			h.drive(t, func() bool {
				res := h.m.ops(transport.OpResults)
				return h.sp.Size() == 0 && len(res) > 2 && resultsOf(t, res[len(res)-1].req).Final
			})
			res := h.m.ops(transport.OpResults)
			if rr := resultsOf(t, res[0].req); rr.Final || len(rr.Results) != 0 {
				t.Fatal("the first post is not the start notice")
			}
			// The first non-empty post was answered 503: the next post carries
			// the same results (see the rewrite note above).
			retried := false
			total := 0
			seen := map[wire.UUID]bool{}
			for i := 1; i < len(res); i++ {
				rr := resultsOf(t, res[i].req)
				raw := gunzip(t, res[i].req.Body)
				if len(rr.Results) > 50 || len(raw) > 1_572_864 {
					t.Fatalf("post %d: %d items, %d bytes", i, len(rr.Results), len(raw))
				}
				if i == 1 && len(rr.Results) > 0 {
					sameResults(t, rr, resultsOf(t, res[2].req))
					retried = true
					continue // the 503'd copy
				}
				if rr.Final != (i == len(res)-1) {
					t.Fatalf("post %d of %d: final %v", i, len(res)-1, rr.Final)
				}
				for _, it := range rr.Results {
					if seen[it.PluginUUID] {
						t.Fatalf("plugin %s posted twice after acceptance", it.PluginUUID)
					}
					seen[it.PluginUUID] = true
				}
				total += len(rr.Results)
			}
			if !retried || total != n {
				t.Fatalf("retried %v, %d items for %d plugins", retried, total, n)
			}
		})
	}
}

// sameResults fails unless retry carries exactly the plugins of the 503'd
// post, each once, each with the same result or its spool_overflow marker
// (TASK-220 r1: a rebuilt batch, not a byte copy), and unless a final 503'd
// post stays final.
func sameResults(t *testing.T, failed, retry wire.ResultsRequest) {
	t.Helper()
	if failed.Final && !retry.Final {
		t.Fatal("the 503'd post was final, its retry is not")
	}
	want := map[wire.UUID]wire.ResultItem{}
	for _, it := range failed.Results {
		if _, dup := want[it.PluginUUID]; dup {
			t.Fatalf("the 503'd post holds plugin %s twice", it.PluginUUID)
		}
		want[it.PluginUUID] = it
	}
	if len(retry.Results) != len(want) {
		t.Fatalf("the retry after a 503 holds %d results, the 503'd post %d", len(retry.Results), len(want))
	}
	got := map[wire.UUID]bool{}
	for _, it := range retry.Results {
		prev, ok := want[it.PluginUUID]
		if !ok {
			t.Fatalf("the retry after a 503 holds plugin %s, which the 503'd post did not", it.PluginUUID)
		}
		if got[it.PluginUUID] {
			t.Fatalf("the retry after a 503 holds plugin %s twice", it.PluginUUID)
		}
		got[it.PluginUUID] = true
		pr, err := proto.NewResult(prev)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(it, prev) && !reflect.DeepEqual(it, proto.OverflowMarker(pr).Item()) {
			now, _ := json.Marshal(it)
			was, _ := json.Marshal(prev)
			t.Fatalf("the retry changed plugin %s's result: %s, was %s", it.PluginUUID, now, was)
		}
	}
}

func gunzip(t *testing.T, b []byte) []byte {
	t.Helper()
	zr, err := gzip.NewReader(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	raw, err := io.ReadAll(zr)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

// Lead's TASK-223 row: a nil compliance handler refuses each compliance job
// (logged, last_error set) while inventory keeps running (G2).
func TestNilComplianceHandlerRefusesButInventoryRuns(t *testing.T) {
	h := newPullHarness(t, func(n int, now time.Time) reply {
		if n <= 2 {
			return reply{status: 200, body: jobsBody(t,
				compJob(uid(10*n+1), now.Add(time.Hour), 2, "id"),
				invJob(uid(10*n+2), agentID, now.Add(time.Hour)),
				compJob(uid(10*n+3), now.Add(time.Hour), 2, "id"))}
		}
		return reply{status: 200, body: jobsBody(t)}
	}, nil)
	h.inv.waitN(t, 1)
	for len(h.m.ops(transport.OpJobs)) < 2 {
		h.clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	h.inv.waitN(t, 2)
	if ids := h.inv.ids(); ids[0] != uid(12) || ids[1] != uid(22) {
		t.Fatalf("inventory ran %v", ids)
	}
	if n := strings.Count(h.logs.String(), "no compliance handler"); n < 4 {
		t.Fatalf("%d refusal log lines for 4 compliance jobs", n)
	}
	for len(h.m.ops(transport.OpHeartbeat)) < 2 {
		h.clock.fireEarliest(t, 2)
		time.Sleep(time.Millisecond)
	}
	found := false
	for _, c := range h.m.ops(transport.OpHeartbeat)[1:] {
		if hr, _ := decoded(t, c.req); hr.LastError != nil && strings.Contains(*hr.LastError, "no compliance handler") {
			found = true
		}
	}
	if !found {
		t.Fatal("no last_error for the refused compliance jobs")
	}
	if n := len(h.m.ops(transport.OpResults)); n != 0 {
		t.Fatalf("%d results posts for refused jobs", n)
	}
	select {
	case <-h.done:
		t.Fatal("the pull loop stopped")
	default:
	}
}
