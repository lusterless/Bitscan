// TP-M10-13 (tester-m10c): the results sender (TASK-220 r1), REQ-246 (1)–(6);
// TS §3.3 L222–L226; #139 (d), (e); #141; decisions "#140 reading: in-flight
// protection covers only an outstanding HTTP attempt". The real Sender over a
// real spool in a temporary directory, the fake clock (only clock.After
// waiters move time) and a fake manager. Portable (Windows and Linux).
package loops_test

import (
	"bytes"
	"compress/gzip"
	"context"
	"fmt"
	"io"
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
	"bitscan.local/agent/internal/runner/proto"
	"bitscan.local/agent/internal/spool"
)

const sendJob = wire.UUID("cccccccc-1111-4000-8000-000000000220")

func sp(n int) wire.UUID { return wire.UUID(fmt.Sprintf("dddddddd-0000-4000-8000-%012d", n)) }

type sendH struct {
	clock *fakeClock
	m     *pullManager
	sp    *spool.Spool
	s     *loops.Sender
	run   *loops.Run
	logs  *logBuf
	stop  context.CancelFunc
	done  chan struct{}
}

// startSender runs the real Sender over a real spool of maxBytes; other
// answers every results post (nil: 200).
func startSender(t *testing.T, maxBytes int64, other func(transport.Request) reply) *sendH {
	t.Helper()
	clock := &fakeClock{now: t0}
	s, _, err := spool.Open(filepath.Join(t.TempDir(), "spool"), maxBytes, clock.Now)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = s.Close() })
	h := &sendH{clock: clock, m: &pullManager{clock: clock, other: other}, sp: s, logs: &logBuf{}, done: make(chan struct{})}
	ctx, cancel := context.WithCancel(context.Background())
	h.stop = cancel
	h.run = loops.NewRun(ctx, loops.Deps{
		Client: h.m, Tokens: token.NewHolder(state.Token{Value: canaryTok}), Rotator: &fakeRotator{},
		AgentID: agentID, Version: version, Clock: clock, Rand: half{}, Log: newLogger(h.logs),
		JobPullSeconds: 60, MaxParallelPlugins: 2, CapreadSock: filepath.Join(t.TempDir(), "no.sock"), SpoolBytes: s.Size,
	})
	h.s = loops.NewSender(h.run, s)
	go func() { defer close(h.done); h.s.Loop() }()
	t.Cleanup(func() {
		cancel()
		select {
		case <-h.done:
		case <-time.After(5 * time.Second):
			t.Error("the sender did not stop")
		}
	})
	return h
}

func item(t testing.TB, id wire.UUID, stdout, stderr string, at time.Time) proto.Result {
	t.Helper()
	code := int64(0)
	r, err := proto.NewResult(wire.ResultItem{PluginUUID: id, ExitCode: &code, Stdout: stdout, Stderr: stderr,
		StartedAt: wire.NewTime(at), FinishedAt: wire.NewTime(at)})
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func ids(n int) []wire.UUID {
	out := make([]wire.UUID, n)
	for i := range out {
		out[i] = sp(i + 1)
	}
	return out
}

// job records a job of n plugins, puts one result each, finishes it and
// wakes the sender.
func (h *sendH) job(t *testing.T, n int, stdout string, finish bool) {
	t.Helper()
	if err := h.sp.StartJob(sendJob, ids(n)); err != nil {
		t.Fatal(err)
	}
	for i := 1; i <= n; i++ {
		if err := h.sp.Put(sendJob, item(t, sp(i), stdout, "", h.clock.Now())); err != nil {
			t.Fatal(err)
		}
	}
	if finish {
		if err := h.sp.Finish(sendJob); err != nil {
			t.Fatal(err)
		}
	}
	h.s.Wake()
}

type post struct {
	at  time.Time
	raw []byte
	gz  []byte
	req wire.ResultsRequest
}

func ungz(t testing.TB, b []byte) []byte {
	t.Helper()
	zr, err := gzip.NewReader(bytes.NewReader(b))
	if err != nil {
		t.Fatalf("results body is not gzip: %v", err)
	}
	raw, err := io.ReadAll(zr)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func (h *sendH) posts(t *testing.T) []post {
	t.Helper()
	var out []post
	for _, c := range h.m.ops(transport.OpResults) {
		if !c.req.Gzip {
			t.Fatal("a results post without Content-Encoding: gzip")
		}
		raw := ungz(t, c.req.Body)
		var rr wire.ResultsRequest
		if err := wire.DecodeStrict(raw, &rr); err != nil {
			t.Fatalf("a results body fails the contract: %v", err)
		}
		if c.req.JobID != sendJob {
			t.Fatalf("post for job %s", c.req.JobID)
		}
		out = append(out, post{at: c.at, raw: raw, gz: c.req.Body, req: rr})
	}
	return out
}

// until waits (real time, bounded) for cond, firing the sender's clock
// waiters when fire is set.
func (h *sendH) until(t *testing.T, fire bool, cond func([]post) bool) []post {
	t.Helper()
	deadline := time.Now().Add(20 * time.Second)
	last, lastN := time.Now(), -1
	for {
		p := h.posts(t)
		if cond(p) {
			return p
		}
		if time.Now().After(deadline) {
			t.Fatalf("condition not reached: %d posts; log %s", len(p), h.logs.String())
		}
		if len(p) != lastN {
			last, lastN = time.Now(), len(p)
		}
		// Fire the earliest waiter only once the sender has been quiet for
		// 30 ms, so a post in progress is recorded at the time it was due.
		if fire && h.clock.pending() > 0 && time.Since(last) > 30*time.Millisecond {
			h.clock.fireEarliest(t, 1)
			last = time.Now()
		}
		time.Sleep(time.Millisecond)
	}
}

// waitWaiter waits until some loop sleeps for exactly d on the clock.
func (h *sendH) waitWaiter(t *testing.T, d time.Duration) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		h.clock.mu.Lock()
		for _, w := range h.clock.waiters {
			if w.d == d {
				h.clock.mu.Unlock()
				return
			}
		}
		h.clock.mu.Unlock()
		time.Sleep(200 * time.Microsecond)
	}
	t.Fatalf("no loop sleeps %v", d)
}

func hasFinal(p []post) bool { return len(p) > 0 && p[len(p)-1].req.Final }

func sizes(p []post) string {
	var s []string
	for _, x := range p {
		f := ""
		if x.req.Final {
			f = "F"
		}
		s = append(s, fmt.Sprint(len(x.req.Results))+f)
	}
	return strings.Join(s, ",")
}

// CHK-M10-065 (REQ-246 (1); -360, -368): a finished job of 120 → the start
// notice first, then 50, 50, 20, only the last final; each item once, in order.
func TestSenderBatches(t *testing.T) {
	h := startSender(t, 50<<20, nil)
	h.job(t, 120, "out", true)
	p := h.until(t, false, hasFinal)
	if got := sizes(p); got != "0,50,50,20F" {
		t.Fatalf("posts %s, want 0,50,50,20F (start notice, then batches of at most 50)", got)
	}
	if !bytes.Equal(p[0].raw, []byte(`{"results":[],"final":false}`)) {
		t.Fatalf("start notice body %s", p[0].raw)
	}
	n := 0
	for _, x := range p {
		for _, it := range x.req.Results {
			n++
			if it.PluginUUID != sp(n) {
				t.Fatalf("item %d is %s: out of order or repeated", n, it.PluginUUID)
			}
		}
	}
	time.Sleep(50 * time.Millisecond)
	if len(h.posts(t)) != 4 {
		t.Fatal("a post after the final batch")
	}
}

// CHK-M10-066 (REQ-246 (2); -361): no body over 1,572,864 bytes of
// uncompressed JSON, with JSON-escaped output and with maximal items.
func TestSenderByteBound(t *testing.T) {
	for _, tc := range []struct {
		name           string
		n              int
		stdout, stderr string
	}{
		{"50 items of about 40 KiB, escaped", 50, strings.Repeat("\"\\\x01é", 8192), ""},
		{"maximal items (6 bytes per char escaped)", 8, strings.Repeat("\x01", 65536), strings.Repeat("\x02", 16384)},
	} {
		t.Run(tc.name, func(t *testing.T) {
			h := startSender(t, 50<<20, nil)
			if err := h.sp.StartJob(sendJob, ids(tc.n)); err != nil {
				t.Fatal(err)
			}
			for i := 1; i <= tc.n; i++ {
				if err := h.sp.Put(sendJob, item(t, sp(i), tc.stdout, tc.stderr, t0)); err != nil {
					t.Fatal(err)
				}
			}
			_ = h.sp.Finish(sendJob)
			h.s.Wake()
			p := h.until(t, false, hasFinal)
			total := 0
			for _, x := range p {
				if len(x.raw) > 1_572_864 {
					t.Fatalf("a body of %d bytes uncompressed (bound 1,572,864); posts %s", len(x.raw), sizes(p))
				}
				total += len(x.req.Results)
			}
			if total != tc.n {
				t.Fatalf("%d items posted, want %d", total, tc.n)
			}
			t.Logf("RECORDED: posts %s", sizes(p))
		})
	}
}

func classOf(status int, typ string) func(transport.Request) reply {
	return func(transport.Request) reply { return reply{status: status, typ: typ} }
}

// CHK-M10-068 (REQ-246 (4); -362, -363): the answer classes of TS §3.3 L224.
func TestSenderAnswerClasses(t *testing.T) {
	t.Run("503 ×3 then 200: back-off 10, 20, 40 s, stored once", func(t *testing.T) {
		var mu sync.Mutex
		n := 0
		h := startSender(t, 50<<20, func(r transport.Request) reply {
			mu.Lock()
			defer mu.Unlock()
			if strings.Contains(string(ungz(t, r.Body)), `"plugin_uuid"`) {
				n++
				if n <= 3 {
					return reply{status: 503, typ: "about:blank"}
				}
			}
			return reply{status: 200, body: []byte(`{"accepted":3,"duplicates":0}`)}
		})
		h.job(t, 3, "out", true)
		p := h.until(t, true, func(p []post) bool { return len(p) == 5 })
		var gaps []time.Duration
		for i := 2; i < 5; i++ {
			gaps = append(gaps, p[i].at.Sub(p[i-1].at))
		}
		if fmt.Sprint(gaps) != "[10s 20s 40s]" {
			t.Fatalf("retry gaps %v, want [10s 20s 40s]", gaps)
		}
		time.Sleep(50 * time.Millisecond)
		if len(h.posts(t)) != 5 {
			t.Fatal("posted again after the 200")
		}
	})
	t.Run("429 kept and retried (CHK-M10-363)", func(t *testing.T) {
		var mu sync.Mutex
		n := 0
		h := startSender(t, 50<<20, func(r transport.Request) reply {
			mu.Lock()
			defer mu.Unlock()
			n++
			if n == 2 {
				return reply{status: 429, typ: "rate_limited"}
			}
			return reply{status: 200, body: []byte(`{"accepted":1,"duplicates":0}`)}
		})
		h.job(t, 2, "out", true)
		p := h.until(t, true, func(p []post) bool { return len(p) == 3 })
		if !bytes.Equal(p[1].raw, p[2].raw) || len(p[2].req.Results) != 2 || p[2].at.Sub(p[1].at) != 10*time.Second {
			t.Fatalf("after a 429: posts %s, gap %v", sizes(p), p[2].at.Sub(p[1].at))
		}
	})
	for _, tc := range []struct {
		status int
		typ    string
	}{{409, "job_not_acceptable"}, {400, "about:blank"}, {404, "about:blank"}, {413, "too_large"}, {422, "about:blank"}, {403, "rate_limited"}, {403, "forbidden"}} {
		t.Run(fmt.Sprintf("%d %s on batch 2: dropped, batch 3 still posted, last_error (CHK-M10-362)", tc.status, tc.typ), func(t *testing.T) {
			var mu sync.Mutex
			n := 0
			h := startSender(t, 50<<20, func(r transport.Request) reply {
				mu.Lock()
				defer mu.Unlock()
				n++
				if n == 3 { // start notice, batch 1, batch 2
					return reply{status: tc.status, typ: tc.typ}
				}
				return reply{status: 200, body: []byte(`{"accepted":50,"duplicates":0}`)}
			})
			h.job(t, 150, "out", true)
			p := h.until(t, true, hasFinal)
			if got := sizes(p); got != "0,50,50,50F" {
				t.Fatalf("posts %s, want 0,50,50,50F with batch 2 sent once", got)
			}
			if p[3].req.Results[0].PluginUUID != sp(101) {
				t.Fatal("batch 2 was retried instead of dropped")
			}
			for h.clock.pending() > 0 {
				h.clock.fire(t)
				time.Sleep(time.Millisecond)
			}
			if len(h.posts(t)) != 4 {
				t.Fatalf("a dropped batch was retried: %s", sizes(h.posts(t)))
			}
			// last_error is set by Run.Call with the line it logs (heartbeat
			// suite: the next heartbeat carries it).
			if l := h.logs.String(); !strings.Contains(l, fmt.Sprintf("results %d %s", tc.status, tc.typ)) || !strings.Contains(l, "not retried") {
				t.Fatalf("no last_error line for the drop: %s", l)
			}
			if h.sp.Size() != 0 {
				t.Fatalf("spool not empty: %d", h.sp.Size())
			}
		})
	}
	t.Run("403 pending_approval kept with back-off", func(t *testing.T) {
		var mu sync.Mutex
		n := 0
		h := startSender(t, 50<<20, func(transport.Request) reply {
			mu.Lock()
			defer mu.Unlock()
			n++
			if n == 2 || n == 3 {
				return reply{status: 403, typ: "pending_approval"}
			}
			return reply{status: 200, body: []byte(`{"accepted":2,"duplicates":0}`)}
		})
		h.job(t, 2, "out", true)
		p := h.until(t, true, func(p []post) bool { return len(p) == 4 })
		if !bytes.Equal(p[1].raw, p[3].raw) || p[3].at.Sub(p[1].at) != 30*time.Second {
			t.Fatalf("pending_approval: posts %s, %v after the first try", sizes(p), p[3].at.Sub(p[1].at))
		}
	})
	t.Run("401 stops the sender", func(t *testing.T) {
		h := startSender(t, 50<<20, classOf(401, "token_revoked"))
		h.job(t, 2, "out", true)
		select {
		case <-h.done:
		case <-time.After(5 * time.Second):
			t.Fatal("the sender did not stop after a 401")
		}
		if n := len(h.posts(t)); n != 1 {
			t.Fatalf("%d posts, want 1 (the 401'd start notice)", n)
		}
	})
	t.Run("back-off capped at 5 min", func(t *testing.T) {
		h := startSender(t, 50<<20, classOf(503, "about:blank"))
		h.job(t, 1, "out", true)
		p := h.until(t, true, func(p []post) bool { return len(p) == 9 })
		var gaps []time.Duration
		for i := 1; i < len(p); i++ {
			gaps = append(gaps, p[i].at.Sub(p[i-1].at))
		}
		if fmt.Sprint(gaps) != "[10s 20s 40s 1m20s 2m40s 5m0s 5m0s 5m0s]" {
			t.Fatalf("gaps %v", gaps)
		}
	})
}

// CHK-M10-069 (REQ-246 (5)): three results of a running job, then silence →
// posted 30 s after the first, not before.
func TestSenderThirtySeconds(t *testing.T) {
	h := startSender(t, 50<<20, nil)
	_ = h.sp.StartJob(sendJob, ids(10))
	h.s.Wake()
	h.until(t, false, func(p []post) bool { return len(p) == 1 })
	start := h.clock.Now()
	for i := 1; i <= 3; i++ {
		_ = h.sp.Put(sendJob, item(t, sp(i), "out", "", h.clock.Now()))
		h.s.Wake()
	}
	time.Sleep(50 * time.Millisecond)
	if d := h.clock.next(t); d != 30*time.Second {
		t.Fatalf("the sender waits %v, want 30 s", d)
	}
	h.clock.advance(29 * time.Second)
	time.Sleep(50 * time.Millisecond)
	if n := len(h.posts(t)); n != 1 {
		t.Fatalf("%d posts at 29 s", n)
	}
	p := h.until(t, true, func(p []post) bool { return len(p) == 2 })
	if p[1].at.Sub(start) != 30*time.Second || len(p[1].req.Results) != 3 || p[1].req.Final {
		t.Fatalf("posted %v after the first result with %s", p[1].at.Sub(start), sizes(p))
	}
}

// TASK-220's documented limit: a Wake with nothing new arms the 30 s timer
// early; a result spooled later goes out at most 30 s after the rule.
func TestSenderLatePostLimit(t *testing.T) {
	h := startSender(t, 50<<20, nil)
	_ = h.sp.StartJob(sendJob, ids(5))
	h.s.Wake()
	h.until(t, false, func(p []post) bool { return len(p) == 1 })
	h.s.Wake() // nothing new: arms the timer
	time.Sleep(50 * time.Millisecond)
	h.clock.advance(20 * time.Second)
	put := h.clock.Now()
	_ = h.sp.Put(sendJob, item(t, sp(1), "out", "", put))
	h.s.Wake()
	p := h.until(t, true, func(p []post) bool { return len(p) == 2 })
	late := p[1].at.Sub(put)
	t.Logf("RECORDED: the result was posted %v after it was spooled (rule 30 s)", late)
	if late < 30*time.Second || late > 60*time.Second {
		t.Fatalf("posted %v after it was spooled, want 30–60 s (at most 30 s late)", late)
	}
}

// CHK-M10-070 (REQ-246 (6)): the final batch never goes before every earlier
// entry of the job was answered; posts are strictly ordered.
func TestSenderFinalWaitsForEarlier(t *testing.T) {
	var mu sync.Mutex
	n := 0
	h := startSender(t, 50<<20, func(transport.Request) reply {
		mu.Lock()
		defer mu.Unlock()
		n++
		if n == 3 || n == 4 { // batch 2, twice
			return reply{status: 503, typ: "about:blank"}
		}
		return reply{status: 200, body: []byte(`{"accepted":50,"duplicates":0}`)}
	})
	h.job(t, 150, "out", true)
	p := h.until(t, true, hasFinal)
	if got := sizes(p); got != "0,50,50,50,50,50F" {
		t.Fatalf("posts %s, want 0,50,50(503),50(503),50,50F", got)
	}
	for i := 2; i <= 4; i++ {
		if p[i].req.Results[0].PluginUUID != sp(51) {
			t.Fatalf("post %d is not batch 2: the final went before batch 2 was answered", i)
		}
	}
}

// CHK-M10-071: Wake sends a finished job's batches without waiting for the
// tick; many Wakes never post twice.
func TestSenderWake(t *testing.T) {
	h := startSender(t, 50<<20, nil)
	h.job(t, 3, "out", true)
	var wg sync.WaitGroup
	for range 100 {
		wg.Add(1)
		go func() { defer wg.Done(); h.s.Wake() }()
	}
	wg.Wait()
	p := h.until(t, false, hasFinal)
	if got := sizes(p); got != "0,3F" {
		t.Fatalf("posts %s, want 0,3F", got)
	}
	if !h.clock.now.Equal(t0) {
		t.Fatal("the clock moved: the batch waited for a tick")
	}
	time.Sleep(50 * time.Millisecond)
	if len(h.posts(t)) != 2 {
		t.Fatal("posted twice")
	}
}

// CHK-M10-072: no body or stdout canary in any log record, on success and
// on a drop.
func TestSenderLogsNoOutput(t *testing.T) {
	h := startSender(t, 50<<20, classOf(409, "job_not_acceptable"))
	h.job(t, 2, "M10SENDCANARY-stdout", true)
	h.until(t, true, func(p []post) bool { return len(p) >= 2 })
	if l := h.logs.String(); strings.Contains(l, "M10SENDCANARY") || strings.Contains(l, "bsa_") {
		t.Fatalf("output or token in the log: %s", l)
	}
}

// TASK-220 r1: a failed attempt releases its batch; overflow converts its
// (oldest) items during the back-off, and the retry is a fresh body that
// carries their markers.
func TestSenderRetryIsFresh(t *testing.T) {
	var mu sync.Mutex
	n := 0
	h := startSender(t, 300_000, func(r transport.Request) reply {
		mu.Lock()
		defer mu.Unlock()
		if strings.Contains(string(ungz(t, r.Body)), `"plugin_uuid"`) {
			n++
			if n == 1 {
				return reply{status: 503, typ: "about:blank"}
			}
		}
		return reply{status: 200, body: []byte(`{"accepted":5,"duplicates":0}`)}
	})
	// As TASK-223 drives it: a wake after StartJob and after each Put.
	_ = h.sp.StartJob(sendJob, ids(5))
	h.s.Wake()
	h.until(t, false, func(p []post) bool { return len(p) == 1 })
	for i := 1; i <= 4; i++ {
		_ = h.sp.Put(sendJob, item(t, sp(i), strings.Repeat("f", 65536), "", t0))
		h.s.Wake()
	}
	// the running job's 4 items go out after 30 s and are answered 503
	h.until(t, true, func(p []post) bool { return len(p) == 2 })
	h.waitWaiter(t, 10*time.Second) // released, in its 10 s back-off
	// During the back-off a result for plugin 5 needs room: only the
	// released items can be converted.
	if err := h.sp.Put(sendJob, item(t, sp(5), strings.Repeat("g", 65536), "", h.clock.Now())); err != nil {
		t.Fatalf("Put during the back-off: %v", err)
	}
	if err := h.sp.Finish(sendJob); err != nil {
		t.Fatal(err)
	}
	h.s.Wake()
	p := h.until(t, true, hasFinal)
	first, retry := p[1].req, p[2].req
	if bytes.Equal(p[1].raw, p[2].raw) {
		t.Fatal("the retry resent the old body")
	}
	if len(first.Results) != 4 || first.Results[0].Error != nil {
		t.Fatalf("the first attempt: %+v", first.Results)
	}
	var got []string
	for _, it := range retry.Results {
		e := "whole"
		if it.Error != nil {
			e = string(*it.Error)
		}
		got = append(got, fmt.Sprintf("%s:%s", string(it.PluginUUID)[33:], e))
	}
	if retry.Results[0].Error == nil || *retry.Results[0].Error != wire.ErrSpoolOverflow || retry.Results[0].PluginUUID != sp(1) {
		t.Fatalf("retry %v: the converted oldest item must go as its spool_overflow marker", got)
	}
	if last := retry.Results[len(retry.Results)-1]; last.PluginUUID != sp(5) || last.Error != nil {
		t.Fatalf("retry %v: the newest result must stay whole", got)
	}
	t.Logf("RECORDED: retry %v", got)
}
