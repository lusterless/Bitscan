// Tests for the inventory job and watcher uploads (TS §3.4 L239–L240, L244;
// §3.3 L224–L226; §6.5 L1186; #72 (a), (e); #80; lead ruling Q2; REQ-100 (5),
// REQ-101, REQ-102; tests/m4/test-plan.md TP-M4-19, CHK-M4-235 to -241 and
// CHK-M4-101's job-path half; mutation rows CHK-M4-350, -351, -352, -337).
// Expected values come from the spec, #80 and the plan, not from the code:
// back-off 10 s doubling to 300 s (±10 %, exact with the half source), 10 min
// 30 s between two accepted unscheduled uploads, a job upload retried for 30
// minutes after the job was received, list_sha256 recomputed here from the
// TS §6.5 L1186 definition.
package loops_test

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"bitscan.local/agent/internal/agent/loops"
	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/state"
	"bitscan.local/agent/internal/agent/token"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/inventory"
)

// holdOff is #80's minimum distance between two accepted unscheduled uploads.
const holdOff = 10*time.Minute + 30*time.Second

const jobB = wire.UUID("d2b5f6a7-1829-4304-b5c6-d7e8f9a0b1c2")

// ---- clock helpers (fakeClock is in heartbeat_test.go) ----

// earliest is the due time of the first pending waiter.
func (c *fakeClock) earliest() (time.Time, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.waiters) == 0 {
		return time.Time{}, false
	}
	at := c.waiters[0].at
	for _, w := range c.waiters[1:] {
		if w.at.Before(at) {
			at = w.at
		}
	}
	return at, true
}

// setNow moves the clock forward to t without waking anyone.
func (c *fakeClock) setNow(t time.Time) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if t.After(c.now) {
		c.now = t
	}
}

// waitPending waits (real time, bounded) for n pending waiters.
func (c *fakeClock) waitPending(t *testing.T, n int) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for c.pending() < n {
		if time.Now().After(deadline) {
			t.Fatalf("%d waiters on the clock, want %d", c.pending(), n)
		}
		time.Sleep(200 * time.Microsecond)
	}
}

// ---- the fake manager for inventory ----

type invCall struct {
	at   time.Time
	req  transport.Request
	resp reply
}

type invManager struct {
	mu    sync.Mutex
	clock *fakeClock
	calls []invCall
	hbs   []transport.Request
	reply func(n int, r transport.Request) reply // n-th inventory call, from 1
}

func (m *invManager) Do(_ context.Context, r transport.Request) (transport.Response, error) {
	now := m.clock.Now()
	m.mu.Lock()
	var a reply
	switch r.Op {
	case transport.OpHeartbeat:
		m.hbs = append(m.hbs, r)
		a = reply{status: 200, body: hbBody(300, 2)}
	case transport.OpInventory:
		a = m.reply(len(m.calls)+1, r)
		r.Body = append([]byte(nil), r.Body...)
		m.calls = append(m.calls, invCall{at: now, req: r, resp: a})
	default:
		a = reply{status: 404, typ: "about:blank"}
	}
	m.mu.Unlock()
	resp := transport.Response{Status: a.status, Body: a.body}
	if a.status != 0 && (a.status < 200 || a.status > 299) {
		resp.Problem = wire.Problem{Type: a.typ, Status: a.status}
	}
	resp.Class = transport.Classify(a.status, a.typ, a.err)
	return resp, a.err
}

func (m *invManager) got() []invCall {
	m.mu.Lock()
	defer m.mu.Unlock()
	return append([]invCall(nil), m.calls...)
}

func (m *invManager) heartbeats() []transport.Request {
	m.mu.Lock()
	defer m.mu.Unlock()
	return append([]transport.Request(nil), m.hbs...)
}

func (m *invManager) waitCalls(t *testing.T, n int) []invCall {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for len(m.got()) < n {
		if time.Now().After(deadline) {
			t.Fatalf("%d inventory uploads, want %d", len(m.got()), n)
		}
		time.Sleep(200 * time.Microsecond)
	}
	return m.got()
}

func always(a reply) func(int, transport.Request) reply {
	return func(int, transport.Request) reply { return a }
}

// replies answers the n-th upload with as[n-1], then with the last one.
func replies(as ...reply) func(int, transport.Request) reply {
	return func(n int, _ transport.Request) reply { return as[min(n, len(as))-1] }
}

var (
	r204 = reply{status: 204}
	r503 = reply{status: 503, typ: "about:blank"}
	r429 = reply{status: 429, typ: "rate_limited"}
)

// ---- the collector: a valid gzip body whose state marker is the version of
// the m4b-state package ----

type stateCollector struct {
	state atomic.Int64
	calls atomic.Int64
	fail  error
}

func (s *stateCollector) collect(ctx context.Context) ([]byte, error) {
	s.calls.Add(1)
	if s.fail != nil {
		return nil, s.fail
	}
	return buildBody(fmt.Sprintf("m4b-state\t1.%d\tall\tinstall ok installed\t\t1\n", s.state.Load()))
}

func testInfo() wire.OsInfo {
	p := func(s string) *string { return &s }
	n := func(v int64) *int64 { return &v }
	return wire.OsInfo{OsID: p("ubuntu"), OsVersionID: p("24.04"), OsPrettyName: p("Ubuntu 24.04.5 LTS"),
		KernelRelease: p("6.8.0-45-generic"), Architecture: p("x86_64"), CPUCount: n(4), MemoryMB: n(7962),
		IPAddresses: []wire.IPAddress{"10.0.0.5/24"}, UptimeS: n(3600), Raw: map[string]any{}}
}

func buildBody(dpkg string) ([]byte, error) {
	return inventory.BuildBody(testInfo(), inventory.ParseDpkg([]byte(dpkg)))
}

// decodeUpload gunzips one upload body and decodes it strictly.
func decodeUpload(t *testing.T, gz []byte) (wire.InventoryBody, []byte) {
	t.Helper()
	if len(gz) < 2 || gz[0] != 0x1f || gz[1] != 0x8b {
		t.Fatalf("the upload body is not gzip (starts %x)", gz[:min(len(gz), 4)])
	}
	zr, err := gzip.NewReader(bytes.NewReader(gz))
	if err != nil {
		t.Fatalf("gzip: %v", err)
	}
	js, err := io.ReadAll(zr)
	if err != nil {
		t.Fatalf("gunzip: %v", err)
	}
	var b wire.InventoryBody
	if err := wire.DecodeStrict(js, &b); err != nil {
		t.Fatalf("the upload fails the InventoryBody contract: %v", err)
	}
	return b, js
}

func stateOf(t *testing.T, gz []byte) int {
	t.Helper()
	b, _ := decodeUpload(t, gz)
	for _, p := range b.Packages {
		if p.Name == "m4b-state" {
			var n int
			if _, err := fmt.Sscanf(p.Version, "1.%d", &n); err != nil {
				t.Fatalf("state marker %q", p.Version)
			}
			return n
		}
	}
	t.Fatal("no state marker in the upload")
	return -1
}

// specListSHA256 is TS §6.5 L1186, written here from the spec: the lines
// name\tversion\tarchitecture\tstatus\n sorted by their UTF-8 bytes,
// concatenated, SHA-256, lowercase hex.
func specListSHA256(items []wire.PackageItem) string {
	lines := make([]string, 0, len(items))
	for _, p := range items {
		lines = append(lines, p.Name+"\t"+p.Version+"\t"+p.Architecture+"\t"+p.Status+"\n")
	}
	sort.Strings(lines) // Go strings compare by bytes
	sum := sha256.Sum256([]byte(strings.Join(lines, "")))
	return hex.EncodeToString(sum[:])
}

// ---- harness ----

type invHarness struct {
	clock *fakeClock
	m     *invManager
	logs  *logBuf
	run   *loops.Run
	inv   *loops.Inventory
	col   *stateCollector
	ctx   context.Context
}

func newInvHarness(t *testing.T, rep func(int, transport.Request) reply, rnd schedule.Source) *invHarness {
	t.Helper()
	if rnd == nil {
		rnd = half{}
	}
	clock := &fakeClock{now: t0}
	h := &invHarness{clock: clock, m: &invManager{clock: clock, reply: rep}, logs: &logBuf{}, col: &stateCollector{}}
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	h.ctx = ctx
	h.run = loops.NewRun(ctx, loops.Deps{
		Client: h.m, Tokens: token.NewHolder(state.Token{Value: canaryTok, IssuedAt: t0, ExpiresAt: t0.AddDate(1, 0, 0), TimesKnown: true}),
		Rotator: &fakeRotator{}, AgentID: agentID, Version: version, Clock: clock, Rand: rnd,
		Log:            newLogger(h.logs),
		JobPullSeconds: 300, MaxParallelPlugins: 2, CapreadSock: filepath.Join(t.TempDir(), "none.sock"),
	})
	h.inv = loops.NewInventory(h.run, h.col.collect)
	return h
}

// async runs f in a goroutine; the returned channel closes when it returns.
func async(f func()) chan struct{} {
	done := make(chan struct{})
	go func() { defer close(done); f() }()
	return done
}

func returned(done chan struct{}) bool {
	select {
	case <-done:
		return true
	default:
		return false
	}
}

// stopAndWait cancels and waits (bounded) for done, for t.Cleanup: a loop
// that never returns fails this test instead of hanging the package.
func stopAndWait(t *testing.T, cancel context.CancelFunc, done chan struct{}, what string) {
	t.Helper()
	cancel()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Errorf("%s did not return within 5 s of cancel", what)
	}
}

// watcherOut receives (bounded) the out channel the fake watcher was given.
func watcherOut(t *testing.T, w *fakeWatcher) chan<- struct{} {
	t.Helper()
	select {
	case out := <-w.out:
		return out
	case <-time.After(5 * time.Second):
		t.Fatal("Watch never started the watcher")
		return nil
	}
}

func waitDone(t *testing.T, done chan struct{}, what string) {
	t.Helper()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatalf("%s did not return", what)
	}
}

// lastErrorOfNextHeartbeat runs the heartbeat loop until its first call and
// returns that heartbeat's last_error.
func (h *invHarness) lastErrorOfNextHeartbeat(t *testing.T) *string {
	t.Helper()
	n := len(h.m.heartbeats())
	go h.run.Heartbeat()
	deadline := time.Now().Add(5 * time.Second)
	for len(h.m.heartbeats()) <= n {
		if time.Now().After(deadline) {
			t.Fatal("no heartbeat was sent")
		}
		time.Sleep(200 * time.Microsecond)
	}
	hb, _ := decoded(t, h.m.heartbeats()[n])
	return hb.LastError
}

func logLines(t *testing.T, l *logBuf) []map[string]any {
	t.Helper()
	var out []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(l.String()), "\n") {
		if line == "" {
			continue
		}
		var m map[string]any
		if err := json.Unmarshal([]byte(line), &m); err != nil {
			t.Fatalf("log line is not JSON: %q", line)
		}
		out = append(out, m)
	}
	return out
}

// ---- CHK-M4-101 (type half for the job path), REQ-100 (5) ----

// The job path hands the inventory runner only the job id, and the collector
// takes only a context: no job, heartbeat or answer value can reach it.
func TestInventoryJobPathSignatures(t *testing.T) {
	ctxT := reflect.TypeOf((*context.Context)(nil)).Elem()
	ct := reflect.TypeOf(loops.Collector(nil))
	if ct.NumIn() != 1 || ct.In(0) != ctxT {
		t.Errorf("loops.Collector is %v; want func(context.Context) ([]byte, error)", ct)
	}
	m, ok := reflect.TypeOf((*loops.InventoryRunner)(nil)).Elem().MethodByName("RunJob")
	if !ok || m.Type.NumIn() != 2 || m.Type.In(0) != ctxT || m.Type.In(1) != reflect.TypeOf(wire.UUID("")) {
		t.Errorf("InventoryRunner.RunJob is %v; want func(context.Context, wire.UUID)", m.Type)
	}
	if ft := reflect.TypeOf(inventory.CollectBody); ft.NumIn() != 1 || ft.In(0) != ctxT {
		t.Errorf("inventory.CollectBody is %v", ft)
	}
	var _ loops.Collector = inventory.CollectBody // production collector fits the type
}

// ---- CHK-M4-235: the upload over HTTPS (real transport.Client) ----

var (
	invSchemaOnce sync.Once
	invSchema     *jsonschema.Schema
	invSchemaErr  error
)

func inventorySchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	invSchemaOnce.Do(func() {
		dir, err := os.Getwd()
		if err != nil {
			invSchemaErr = err
			return
		}
		for {
			if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
				break
			}
			if filepath.Dir(dir) == dir {
				invSchemaErr = errors.New("go.mod not found")
				return
			}
			dir = filepath.Dir(dir)
		}
		data, err := os.ReadFile(filepath.Join(filepath.Dir(dir), "manager", "openapi.json"))
		if err != nil {
			invSchemaErr = err
			return
		}
		doc, err := jsonschema.UnmarshalJSON(bytes.NewReader(data))
		if err != nil {
			invSchemaErr = err
			return
		}
		const url = "file:///bitscan/manager/openapi.json"
		c := jsonschema.NewCompiler()
		c.DefaultDraft(jsonschema.Draft2020)
		c.AssertFormat()
		if invSchemaErr = c.AddResource(url, doc); invSchemaErr != nil {
			return
		}
		invSchema, invSchemaErr = c.Compile(url + "#/components/schemas/InventoryBody")
	})
	if invSchemaErr != nil {
		t.Fatalf("openapi.json InventoryBody: %v", invSchemaErr)
	}
	return invSchema
}

type seenRequest struct {
	method, path, rawQuery, jobID string
	encoding, ctype, auth         string
	body                          []byte
}

func TestInventoryUploadOverHTTPS(t *testing.T) {
	var mu sync.Mutex
	var seen []seenRequest
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		mu.Lock()
		seen = append(seen, seenRequest{r.Method, r.URL.Path, r.URL.RawQuery, r.URL.Query().Get("job_id"),
			r.Header.Get("Content-Encoding"), r.Header.Get("Content-Type"), r.Header.Get("Authorization"), b})
		mu.Unlock()
		w.WriteHeader(http.StatusNoContent)
	}))
	t.Cleanup(srv.Close)
	tlsCfg := srv.Client().Transport.(*http.Transport).TLSClientConfig.Clone()
	client, err := transport.NewClient(srv.URL, tlsCfg, wire.MachineID("0123456789abcdef0123456789abcdef"))
	if err != nil {
		t.Fatal(err)
	}
	l := func(f ...string) string { return strings.Join(f, "\t") + "\n" }
	// byte order (Zz before apt), non-ASCII names, multi-arch duplicates by
	// name, a package with no source
	dpkg := l("apt", "2.7.14build2", "amd64", "install ok installed", "", "4156") +
		l("Zz-upper", "1.0", "all", "install ok installed", "zz", "1") +
		l("libc6", "2.39-0ubuntu8.3", "amd64", "install ok installed", "glibc", "12976") +
		l("libc6", "2.39-0ubuntu8.3", "i386", "install ok installed", "glibc", "12000") +
		l("libé-ünïcödé", "1:0.9~rc1", "amd64", "hold ok installed", "libe", "12") +
		l("名前", "1", "all", "deinstall ok config-files", "", "7") +
		l("zlib1g", "1:1.3.dfsg-3.1ubuntu2", "amd64", "install ok installed", "zlib", "164")
	clock := &fakeClock{now: t0}
	logs := &logBuf{}
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	run := loops.NewRun(ctx, loops.Deps{
		Client: client, Tokens: token.NewHolder(state.Token{Value: canaryTok, IssuedAt: t0, ExpiresAt: t0.AddDate(1, 0, 0), TimesKnown: true}),
		Rotator: &fakeRotator{}, AgentID: agentID, Version: version, Clock: clock, Rand: half{},
		Log: newLogger(logs), JobPullSeconds: 300, MaxParallelPlugins: 2, CapreadSock: filepath.Join(t.TempDir(), "none.sock"),
	})
	inv := loops.NewInventory(run, func(context.Context) ([]byte, error) { return buildBody(dpkg) })
	inv.RunJob(ctx, jobA)
	inv.Unscheduled(ctx)

	mu.Lock()
	got := append([]seenRequest(nil), seen...)
	mu.Unlock()
	if len(got) != 2 {
		t.Fatalf("%d requests, want 2 (one job upload, one unscheduled)", len(got))
	}
	wantPath := "/api/v1/agent/" + string(agentID) + "/inventory"
	for i, r := range got {
		if r.method != http.MethodPut || r.path != wantPath {
			t.Errorf("request %d: %s %s, want PUT %s", i, r.method, r.path, wantPath)
		}
		if !strings.EqualFold(r.encoding, "gzip") {
			t.Errorf("request %d: Content-Encoding %q, want gzip (REQ-101 (2))", i, r.encoding)
		}
		if r.ctype != "application/json" {
			t.Errorf("request %d: Content-Type %q", i, r.ctype)
		}
		if r.auth != "Bearer "+string(canaryTok) {
			t.Errorf("request %d: not sent with the agent token", i)
		}
		b, js := decodeUpload(t, r.body)
		inst, err := jsonschema.UnmarshalJSON(bytes.NewReader(js))
		if err != nil {
			t.Fatal(err)
		}
		if err := inventorySchema(t).Validate(inst); err != nil {
			t.Errorf("request %d: body fails the openapi InventoryBody schema: %v", i, err)
		}
		if len(b.Packages) != 7 {
			t.Errorf("request %d: %d packages, want 7", i, len(b.Packages))
		}
		if want := specListSHA256(b.Packages); string(b.ListSHA256) != want {
			t.Errorf("request %d: list_sha256 %s, recomputed from the body %s (REQ-101 (1))", i, b.ListSHA256, want)
		}
	}
	if got[0].jobID != strings.ToLower(string(jobA)) || got[0].rawQuery != "job_id="+strings.ToLower(string(jobA)) {
		t.Errorf("job upload query %q, want job_id=%s", got[0].rawQuery, jobA)
	}
	if got[1].rawQuery != "" {
		t.Errorf("unscheduled upload query %q, want none (no job_id)", got[1].rawQuery)
	}
	// the empty list: e3b0c442… (TS §6.5 L1186 over no lines)
	if s := specListSHA256(nil); s != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" {
		t.Fatalf("oracle self-check %s", s)
	}
	gz, err := buildBody("")
	if err != nil {
		t.Fatal(err)
	}
	if b, _ := decodeUpload(t, gz); b.ListSHA256 != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" || len(b.Packages) != 0 {
		t.Errorf("empty list: list_sha256 %s, %d packages", b.ListSHA256, len(b.Packages))
	}
	for _, leak := range []string{string(canaryTok), "zlib1g", "Ubuntu 24.04.5"} {
		if strings.Contains(logs.String(), leak) {
			t.Errorf("the logs hold %q", leak)
		}
	}
}

// ---- CHK-M4-236: a job upload retried on 503 (and the other retry classes) ----

func TestInventoryJobRetried(t *testing.T) {
	t.Run("503 503 204", func(t *testing.T) {
		h := newInvHarness(t, replies(r503, r503, r204), nil)
		done := async(func() { h.inv.RunJob(h.ctx, jobA) })
		h.m.waitCalls(t, 1)
		if d := h.clock.fire(t); d != 10*time.Second {
			t.Errorf("first back-off %v, want 10s", d)
		}
		h.m.waitCalls(t, 2)
		if d := h.clock.fire(t); d != 20*time.Second {
			t.Errorf("second back-off %v, want 20s", d)
		}
		waitDone(t, done, "RunJob after 204")
		calls := h.m.got()
		if len(calls) != 3 {
			t.Fatalf("%d uploads, want 3", len(calls))
		}
		for i, c := range calls {
			if c.req.JobID != jobA {
				t.Errorf("upload %d job_id %q, want %s", i, c.req.JobID, jobA)
			}
			if !c.req.Gzip {
				t.Errorf("upload %d not marked gzip", i)
			}
			if !bytes.Equal(c.req.Body, calls[0].req.Body) {
				t.Errorf("upload %d body differs from the first: a retry sends the same bytes", i)
			}
		}
		if got := []time.Duration{calls[1].at.Sub(calls[0].at), calls[2].at.Sub(calls[1].at)}; got[0] != 10*time.Second || got[1] != 20*time.Second {
			t.Errorf("retry gaps %v, want [10s 20s]", got)
		}
		if n := h.col.calls.Load(); n != 1 {
			t.Errorf("collected %d times, want 1 (the body is built once)", n)
		}
		if p := h.clock.pending(); p != 0 {
			t.Errorf("%d waiters after the 204: no retry after success", p)
		}
	})
	for _, c := range []struct {
		name string
		r    reply
	}{
		{"429", r429},
		{"500", reply{status: 500, typ: "about:blank"}},
		{"502", reply{status: 502, typ: "about:blank"}},
		{"403 pending_approval", reply{status: 403, typ: "pending_approval"}},
		{"network error", reply{err: errors.New("connection refused")}},
	} {
		t.Run(c.name+" then 204", func(t *testing.T) {
			h := newInvHarness(t, replies(c.r, r204), nil)
			done := async(func() { h.inv.RunJob(h.ctx, jobA) })
			h.m.waitCalls(t, 1)
			if d := h.clock.fire(t); d != 10*time.Second {
				t.Errorf("back-off %v, want 10s", d)
			}
			waitDone(t, done, "RunJob")
			if calls := h.m.got(); len(calls) != 2 || calls[1].req.JobID != jobA {
				t.Errorf("%d uploads, want 2 with the same job_id", len(calls))
			}
			if lastErr := h.lastErrorOfNextHeartbeat(t); lastErr != nil {
				t.Errorf("a retried upload sets last_error %q", *lastErr)
			}
		})
	}
}

// ---- CHK-M4-237, -337: 409, 413, 422 (and the other drops) are not retried ----

func TestInventoryDropNotRetried(t *testing.T) {
	for _, c := range []struct {
		r    reply
		want string
	}{
		{reply{status: 409, typ: "conflict"}, "inventory 409 conflict"},
		{reply{status: 413, typ: "too_large"}, "inventory 413 too_large"},
		{reply{status: 422, typ: "about:blank"}, "inventory 422 about:blank"},
		{reply{status: 400, typ: "invalid_request"}, "inventory 400 invalid_request"},
		{reply{status: 404, typ: "about:blank"}, "inventory 404 about:blank"},
		{reply{status: 403, typ: "forbidden"}, "inventory 403 forbidden"},
	} {
		for _, kind := range []string{"job", "unscheduled"} {
			t.Run(fmt.Sprintf("%d %s", c.r.status, kind), func(t *testing.T) {
				h := newInvHarness(t, always(c.r), nil)
				var done chan struct{}
				if kind == "job" {
					done = async(func() { h.inv.RunJob(h.ctx, jobA) })
				} else {
					done = async(func() { h.inv.Unscheduled(h.ctx) })
				}
				waitDone(t, done, "the upload")
				time.Sleep(5 * time.Millisecond)
				if n := len(h.m.got()); n != 1 {
					t.Errorf("%d uploads, want 1 (no retry)", n)
				}
				if p := h.clock.pending(); p != 0 {
					t.Errorf("%d waiters: a dropped upload must not wait to retry", p)
				}
				lastErr := h.lastErrorOfNextHeartbeat(t)
				if lastErr == nil || *lastErr != c.want {
					t.Errorf("last_error %v, want %q", lastErr, c.want)
				}
			})
		}
	}
}

// ---- CHK-M4-238, -352: unscheduled uploads ----

// Two unscheduled uploads back to back: the second waits until 10 min 30 s
// after the first was accepted; neither carries a job_id.
func TestInventoryUnscheduledHoldOff(t *testing.T) {
	h := newInvHarness(t, always(r204), nil)
	waitDone(t, async(func() { h.inv.Unscheduled(h.ctx) }), "first Unscheduled")
	done := async(func() { h.inv.Unscheduled(h.ctx) })
	h.clock.waitPending(t, 1)
	if n := len(h.m.got()); n != 1 {
		t.Fatalf("%d uploads before the hold-off ended, want 1", n)
	}
	h.clock.setNow(t0.Add(holdOff - time.Second))
	time.Sleep(5 * time.Millisecond)
	if n := len(h.m.got()); n != 1 {
		t.Fatalf("an upload was sent before the hold-off ended")
	}
	h.clock.fire(t)
	waitDone(t, done, "second Unscheduled")
	calls := h.m.got()
	if len(calls) != 2 {
		t.Fatalf("%d uploads, want 2", len(calls))
	}
	if gap := calls[1].at.Sub(calls[0].at); gap < holdOff {
		t.Errorf("two accepted unscheduled uploads %v apart, want at least %v", gap, holdOff)
	}
	for i, c := range calls {
		if c.req.JobID != "" {
			t.Errorf("unscheduled upload %d has job_id %s", i, c.req.JobID)
		}
	}
}

// A 429 on an unscheduled upload is retried with the back-off (10 s, 20 s);
// the hold-off then counts from the accepted retry.
func TestInventoryUnscheduled429(t *testing.T) {
	h := newInvHarness(t, replies(r429, r429, r204, r204), nil)
	done := async(func() { h.inv.Unscheduled(h.ctx) })
	h.m.waitCalls(t, 1)
	if d := h.clock.fire(t); d != 10*time.Second {
		t.Errorf("first back-off %v, want 10s", d)
	}
	h.m.waitCalls(t, 2)
	if d := h.clock.fire(t); d != 20*time.Second {
		t.Errorf("second back-off %v, want 20s", d)
	}
	waitDone(t, done, "Unscheduled after 204")
	accepted := h.m.got()[2].at
	done = async(func() { h.inv.Unscheduled(h.ctx) })
	h.clock.waitPending(t, 1)
	h.clock.fire(t)
	waitDone(t, done, "next Unscheduled")
	calls := h.m.got()
	if len(calls) != 4 {
		t.Fatalf("%d uploads, want 4", len(calls))
	}
	if gap := calls[3].at.Sub(accepted); gap < holdOff {
		t.Errorf("accepted uploads %v apart after 429 retries, want at least %v", gap, holdOff)
	}
	if gap := calls[3].at.Sub(calls[0].at); gap < holdOff {
		t.Errorf("the first 429 attempt and the next accepted upload are %v apart", gap)
	}
}

// fakeWatcher: Run hands the test's signals to the inventory loop.
type fakeWatcher struct {
	out     chan chan<- struct{}
	failNow error
	failAt  chan error
}

func newFakeWatcher() *fakeWatcher {
	return &fakeWatcher{out: make(chan chan<- struct{}, 1), failAt: make(chan error, 1)}
}

func (w *fakeWatcher) Run(ctx context.Context, out chan<- struct{}) error {
	if w.failNow != nil {
		return w.failNow
	}
	w.out <- out
	select {
	case <-ctx.Done():
		return ctx.Err()
	case err := <-w.failAt:
		return err
	}
}

// signal sends one dpkg change; it returns when the inventory loop took it.
func signalWithin(t *testing.T, out chan<- struct{}) {
	t.Helper()
	select {
	case out <- struct{}{}:
	case <-time.After(5 * time.Second):
		t.Fatal("the inventory loop did not take the signal")
	}
}

// A signal during a 429 back-off makes the retry collect again, so the latest
// state is sent; a signal during the hold-off replaces the pending one (one
// upload, the latest state).
func TestInventoryWatchLatestState(t *testing.T) {
	h := newInvHarness(t, replies(r429, r204, r204, r204), nil)
	w := newFakeWatcher()
	ctx, cancel := context.WithCancel(h.ctx)
	done := async(func() { h.inv.Watch(ctx, w) })
	t.Cleanup(func() { stopAndWait(t, cancel, done, "Watch") })
	out := watcherOut(t, w)

	h.col.state.Store(1)
	signalWithin(t, out)
	h.m.waitCalls(t, 1) // 429
	h.clock.waitPending(t, 1)
	h.col.state.Store(2)
	signalWithin(t, out) // during the back-off
	h.clock.fire(t)
	calls := h.m.waitCalls(t, 2)
	if s := stateOf(t, calls[1].req.Body); s != 2 {
		t.Errorf("the retry after a signal sent state %d, want the latest (2)", s)
	}
	// hold-off: two more changes, one upload with the last state
	h.col.state.Store(3)
	signalWithin(t, out)
	h.clock.waitPending(t, 1)
	h.clock.setNow(t0.Add(5 * time.Minute))
	h.col.state.Store(4)
	signalWithin(t, out)
	h.clock.fire(t)
	calls = h.m.waitCalls(t, 3)
	time.Sleep(5 * time.Millisecond)
	if n := len(h.m.got()); n != 3 {
		t.Fatalf("%d uploads, want 3 (two signals in one hold-off give one upload)", n)
	}
	if s := stateOf(t, calls[2].req.Body); s != 4 {
		t.Errorf("the upload after the hold-off sent state %d, want 4", s)
	}
	if gap := calls[2].at.Sub(calls[1].at); gap < holdOff {
		t.Errorf("accepted uploads %v apart, want at least %v", gap, holdOff)
	}
	for i, c := range h.m.got() {
		if c.req.JobID != "" {
			t.Errorf("watcher upload %d has job_id %s", i, c.req.JobID)
		}
	}
}

// 30 signals at random times over 2 h, every third upload answered 429:
// accepted uploads are never closer than 10 min 30 s, none carries a job_id,
// and the last state is always sent.
func TestInventoryWatchStorm(t *testing.T) {
	for _, seed := range []uint64{1, 7, 42} {
		t.Run(fmt.Sprintf("seed %d", seed), func(t *testing.T) {
			rnd := &splitmix{x: seed}
			h := newInvHarness(t, func(n int, _ transport.Request) reply {
				if n%3 == 0 {
					return r429
				}
				return r204
			}, rnd)
			w := newFakeWatcher()
			ctx, cancel := context.WithCancel(h.ctx)
			done := async(func() { h.inv.Watch(ctx, w) })
			t.Cleanup(func() { stopAndWait(t, cancel, done, "Watch") })
			out := watcherOut(t, w)

			times := make([]time.Duration, 30)
			for i := range times {
				times[i] = time.Duration(rnd.Float64() * float64(2*time.Hour))
			}
			sort.Slice(times, func(i, j int) bool { return times[i] < times[j] })
			advanceTo := func(at time.Time) {
				for {
					due, ok := h.clock.earliest()
					if !ok || due.After(at) {
						h.clock.setNow(at)
						return
					}
					n := len(h.m.got())
					h.clock.fire(t)
					h.m.waitCalls(t, n+1) // a fired hold-off or back-off always uploads
				}
			}
			for i, d := range times {
				advanceTo(t0.Add(d))
				h.col.state.Store(int64(i + 1))
				signalWithin(t, out)
			}
			// drain: until an accepted upload carries the last state
			for k := 0; ; k++ {
				calls := h.m.got()
				var last *invCall
				for j := range calls {
					if calls[j].resp.status == 204 {
						last = &calls[j]
					}
				}
				if last != nil && stateOf(t, last.req.Body) == 30 && h.clock.pending() == 0 {
					break
				}
				if k > 50 {
					t.Fatal("the last state was never sent")
				}
				h.clock.waitPending(t, 1)
				n := len(calls)
				h.clock.fire(t)
				h.m.waitCalls(t, n+1)
			}
			var accepted []time.Time
			for i, c := range h.m.got() {
				if c.req.JobID != "" {
					t.Errorf("upload %d has job_id %s", i, c.req.JobID)
				}
				if c.resp.status == 204 {
					accepted = append(accepted, c.at)
				}
			}
			for i := 1; i < len(accepted); i++ {
				if gap := accepted[i].Sub(accepted[i-1]); gap < holdOff {
					t.Errorf("accepted uploads %d and %d are %v apart, want at least %v", i-1, i, gap, holdOff)
				}
			}
			if max := int(2*time.Hour/holdOff) + 2; len(accepted) > max || len(accepted) < 2 {
				t.Errorf("%d accepted uploads for 30 signals over 2 h, want 2..%d", len(accepted), max)
			}
			t.Logf("%d uploads, %d accepted", len(h.m.got()), len(accepted))
		})
	}
}

// ---- CHK-M4-239: a job upload's retries end 30 minutes after the job came ----

func TestInventoryJobWindow(t *testing.T) {
	h := newInvHarness(t, always(r503), nil)
	done := async(func() { h.inv.RunJob(h.ctx, jobA) })
	for k := 0; ; k++ {
		h.m.waitCalls(t, k+1)
		time.Sleep(2 * time.Millisecond)
		if returned(done) {
			break
		}
		if k > 40 {
			t.Fatal("RunJob never gave up")
		}
		h.clock.waitPending(t, 1)
		h.clock.fire(t)
	}
	waitDone(t, done, "RunJob")
	// 0, 10, 30, 70, 150, 310, 610, 910, 1210, 1510 s; the next (1810 s) is
	// past 30 minutes and is not made
	want := []time.Duration{0, 10, 30, 70, 150, 310, 610, 910, 1210, 1510}
	calls := h.m.got()
	if len(calls) != len(want) {
		t.Errorf("%d attempts, want %d", len(calls), len(want))
	}
	for i, c := range calls {
		if i < len(want) && c.at.Sub(t0) != want[i]*time.Second {
			t.Errorf("attempt %d at +%v, want +%v", i, c.at.Sub(t0), want[i]*time.Second)
		}
		if c.at.After(t0.Add(30 * time.Minute)) {
			t.Errorf("attempt %d at +%v, after the 30-minute window", i, c.at.Sub(t0))
		}
	}
	h.clock.setNow(t0.Add(2 * time.Hour))
	time.Sleep(5 * time.Millisecond)
	if n := len(h.m.got()); n != len(calls) {
		t.Errorf("uploads continued after RunJob gave up")
	}
	var warns int
	for _, m := range logLines(t, h.logs) {
		if m["job_id"] == string(jobA) {
			warns++
			if m["level"] != "WARN" {
				t.Errorf("give-up line level %v", m["level"])
			}
		}
	}
	if warns != 1 {
		t.Errorf("%d log lines with the job_id, want exactly 1 (the give-up line)\n%s", warns, h.logs.String())
	}
}

// With random jitter the window still holds, and a second job queued behind
// the first keeps its own window from the time it was received.
func TestInventoryJobWindowJitterAndQueue(t *testing.T) {
	h := newInvHarness(t, always(r503), &splitmix{x: 3})
	doneA := async(func() { h.inv.RunJob(h.ctx, jobA) })
	h.m.waitCalls(t, 1)
	h.clock.setNow(t0.Add(5 * time.Second))
	receivedB := h.clock.Now()
	doneB := async(func() { h.inv.RunJob(h.ctx, jobB) })
	for k := 0; ; k++ {
		if k > 80 {
			t.Fatal("the jobs never gave up")
		}
		time.Sleep(2 * time.Millisecond)
		if returned(doneA) && returned(doneB) {
			break
		}
		h.clock.waitPending(t, 1)
		h.clock.fire(t)
	}
	var a, b int
	for _, c := range h.m.got() {
		switch c.req.JobID {
		case jobA:
			a++
			if c.at.After(t0.Add(30 * time.Minute)) {
				t.Errorf("job A attempt at +%v, after its window", c.at.Sub(t0))
			}
		case jobB:
			b++
			if c.at.After(receivedB.Add(30 * time.Minute)) {
				t.Errorf("job B attempt at +%v, after its window", c.at.Sub(t0))
			}
		}
	}
	if a < 2 || b < 1 {
		t.Errorf("job A %d attempts, job B %d", a, b)
	}
}

// ---- CHK-M4-240: a watcher that cannot start leaves job uploads working ----

func TestInventoryWatchFailureKeepsJobs(t *testing.T) {
	t.Run("fails at start", func(t *testing.T) {
		h := newInvHarness(t, always(r204), nil)
		w := newFakeWatcher()
		w.failNow = errors.New("inotify_add_watch: CANARY-watch-error")
		waitDone(t, async(func() { h.inv.Watch(h.ctx, w) }), "Watch with a failing watcher")
		waitDone(t, async(func() { h.inv.RunJob(h.ctx, jobA) }), "RunJob")
		calls := h.m.got()
		if len(calls) != 1 || calls[0].req.JobID != jobA {
			t.Fatalf("%d uploads, want the job upload", len(calls))
		}
		var warns int
		for _, m := range logLines(t, h.logs) {
			if m["level"] == "WARN" {
				warns++
			}
		}
		if warns != 1 {
			t.Errorf("%d WARN lines, want 1 for the failed watch", warns)
		}
		if strings.Contains(h.logs.String(), "CANARY-watch-error") {
			t.Error("the watcher's error text is logged")
		}
	})
	t.Run("fails later", func(t *testing.T) {
		h := newInvHarness(t, always(r204), nil)
		w := newFakeWatcher()
		done := async(func() { h.inv.Watch(h.ctx, w) })
		out := watcherOut(t, w)
		signalWithin(t, out)
		h.m.waitCalls(t, 1)
		w.failAt <- errors.New("watch lost")
		waitDone(t, done, "Watch after the watcher failed")
		waitDone(t, async(func() { h.inv.RunJob(h.ctx, jobA) }), "RunJob")
		calls := h.m.got()
		if len(calls) != 2 || calls[0].req.JobID != "" || calls[1].req.JobID != jobA {
			t.Fatalf("uploads %d, want the watcher's and then the job's", len(calls))
		}
	})
	t.Run("ends with ctx", func(t *testing.T) {
		h := newInvHarness(t, always(r204), nil)
		w := newFakeWatcher()
		ctx, cancel := context.WithCancel(h.ctx)
		done := async(func() { h.inv.Watch(ctx, w) })
		watcherOut(t, w)
		cancel()
		waitDone(t, done, "Watch after cancel")
		if strings.Contains(h.logs.String(), "WARN") {
			t.Errorf("a normal stop is logged as a failure: %s", h.logs.String())
		}
	})
}

// ---- CHK-M4-241: a 401 on an upload stops every loop ----

func TestInventory401StopsAll(t *testing.T) {
	for _, kind := range []string{"job", "unscheduled"} {
		t.Run(kind, func(t *testing.T) {
			h := newInvHarness(t, always(reply{status: 401, typ: "token_revoked"}), nil)
			hbDone := async(h.run.Heartbeat)
			deadline := time.Now().Add(5 * time.Second)
			for len(h.m.heartbeats()) < 1 {
				if time.Now().After(deadline) {
					t.Fatal("no heartbeat")
				}
				time.Sleep(200 * time.Microsecond)
			}
			h.clock.waitPending(t, 1) // the heartbeat loop sleeps 300 s
			if kind == "job" {
				waitDone(t, async(func() { h.inv.RunJob(h.ctx, jobA) }), "RunJob")
			} else {
				waitDone(t, async(func() { h.inv.Unscheduled(h.ctx) }), "Unscheduled")
			}
			waitDone(t, hbDone, "the heartbeat loop after a 401 on an upload")
			if !h.run.Stopped() {
				t.Error("the Run is not stopped after a 401")
			}
			if n := len(h.m.got()); n != 1 {
				t.Errorf("%d uploads, want 1 (no retry after 401)", n)
			}
			waitDone(t, async(func() { h.inv.RunJob(h.ctx, jobB) }), "RunJob after stop")
			waitDone(t, async(func() { h.inv.Unscheduled(h.ctx) }), "Unscheduled after stop")
			if n := len(h.m.got()); n != 1 {
				t.Errorf("%d uploads after the stop, want none sent", n-1)
			}
			if hb := len(h.m.heartbeats()); hb != 1 {
				t.Errorf("%d heartbeats, want 1", hb)
			}
			if strings.Contains(h.logs.String(), string(canaryTok)) {
				t.Error("the token is logged")
			}
		})
	}
}

// ---- lead ruling Q2: a failed collection uploads nothing ----

func TestInventoryCollectionFailure(t *testing.T) {
	for _, kind := range []string{"job", "unscheduled"} {
		t.Run(kind, func(t *testing.T) {
			h := newInvHarness(t, always(r204), nil)
			h.col.fail = errors.New("dpkg-query: CANARY-collect-error")
			if kind == "job" {
				waitDone(t, async(func() { h.inv.RunJob(h.ctx, jobA) }), "RunJob")
			} else {
				waitDone(t, async(func() { h.inv.Unscheduled(h.ctx) }), "Unscheduled")
			}
			if n := len(h.m.got()); n != 0 {
				t.Errorf("%d uploads after a failed collection, want 0", n)
			}
			if p := h.clock.pending(); p != 0 {
				t.Errorf("%d waiters after a failed collection", p)
			}
			lastErr := h.lastErrorOfNextHeartbeat(t)
			if lastErr == nil || *lastErr != "inventory collection failed" {
				t.Errorf("last_error %v, want \"inventory collection failed\"", lastErr)
			}
			if strings.Contains(h.logs.String(), "CANARY-collect-error") {
				t.Error("the collection error text is logged")
			}
		})
	}
}
