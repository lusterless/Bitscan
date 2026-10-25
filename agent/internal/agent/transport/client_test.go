// Tests for the agent HTTP client and the response classes (TS §3.2 L189,
// L194; §3.3 L224, L226; §6.1, §6.5 L1159–L1190; #59, #75; REQ-094, REQ-095;
// tests/m4/test-plan.md TP-M4-08, CHK-M4-080 to -089; mutation rows CHK-M4-327
// to -329, -336, -337, -339). Paths and methods come from the shared contract
// manifest (manager/tests/contract/fixtures/manifest.json "routes"); classes
// from the TS §3.3 L224 table and #75, not from the implementation.
package transport_test

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
)

const (
	machineID = "0123456789abcdef0123456789abcdef"
	agentID   = "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"
	jobID     = "c1a4e5f6-0718-4293-a4b5-c6d7e8f9a0b1"
	// canary tokens: bsa_/bse_ + 43 base64url characters with CANARY inside
	bsaCanary = "bsa_CANARY0123456789abcdef_CANARY0123456789abcd"
	bseCanary = "bse_CANARY0123456789abcdef_CANARY0123456789abcd"
)

// recorded is one request as the fake manager saw it.
type recorded struct {
	method, path, rawQuery string
	header                 http.Header
	body                   []byte
}

// fakeManager is a TLS server whose handler records every request and answers
// with the function the test sets.
type fakeManager struct {
	*httptest.Server
	mu     sync.Mutex
	reqs   []recorded
	answer func(w http.ResponseWriter, r *http.Request)
	caFile string
	pki    *pki
}

func newFakeManager(t *testing.T) *fakeManager {
	t.Helper()
	return newFakeManagerPKI(t, newPKI(t))
}

// newFakeManagerPKI serves p's good leaf, so two managers can share one CA.
func newFakeManagerPKI(t *testing.T, p *pki) *fakeManager {
	t.Helper()
	f := &fakeManager{caFile: p.aFile, pki: p}
	f.Server = httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		f.mu.Lock()
		f.reqs = append(f.reqs, recorded{r.Method, r.URL.Path, r.URL.RawQuery, r.Header.Clone(), b})
		ans := f.answer
		f.mu.Unlock()
		if ans != nil {
			ans(w, r)
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{}`))
	}))
	f.TLS = &tls.Config{Certificates: []tls.Certificate{p.good.tls}}
	f.Config.ErrorLog = log.New(io.Discard, "", 0)
	f.StartTLS()
	t.Cleanup(f.Close)
	return f
}

func (f *fakeManager) setAnswer(a func(w http.ResponseWriter, r *http.Request)) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.answer = a
}

func (f *fakeManager) requests() []recorded {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]recorded(nil), f.reqs...)
}

func (f *fakeManager) client(t *testing.T) *transport.Client {
	t.Helper()
	return clientFor(t, f.URL, f.caFile)
}

func clientFor(t *testing.T, url, caFile string) *transport.Client {
	t.Helper()
	cfg, err := transport.NewTLSConfig(caFile, "", "")
	if err != nil {
		t.Fatal(err)
	}
	c, err := transport.NewClient(url, cfg, wire.MachineID(machineID))
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func problem(status int, typ string) func(w http.ResponseWriter, r *http.Request) {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/problem+json")
		w.WriteHeader(status)
		_, _ = fmt.Fprintf(w, `{"type":%q,"title":"t","status":%d,"detail":"d","instance":"/x"}`, typ, status)
	}
}

type route struct {
	Method string `json:"method"`
	Path   string `json:"path"`
}

func manifestRoutes(t *testing.T) map[string]route {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	for ; ; dir = filepath.Dir(dir) {
		p := filepath.Join(dir, "manager", "tests", "contract", "fixtures", "manifest.json")
		if b, err := os.ReadFile(filepath.Clean(p)); err == nil {
			var m struct {
				Routes map[string]route `json:"routes"`
			}
			if err := json.Unmarshal(b, &m); err != nil {
				t.Fatal(err)
			}
			return m.Routes
		}
		if filepath.Dir(dir) == dir {
			t.Fatal("manifest.json not found above the package directory")
		}
	}
}

// CHK-M4-080 (CHK-M4-329): path, method and exact headers per operation.
func TestClientRoutesAndHeaders(t *testing.T) {
	f := newFakeManager(t)
	c := f.client(t)
	routes := manifestRoutes(t)
	cases := []struct {
		name  string
		req   transport.Request
		query string
	}{
		{"enrol", transport.Request{Op: transport.OpEnrol, Token: bseCanary, Body: []byte(`{"a":1}`)}, ""},
		{"heartbeat", transport.Request{Op: transport.OpHeartbeat, Token: bsaCanary, AgentID: agentID, Body: []byte(`{"a":1}`)}, ""},
		{"jobs", transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID}, ""},
		{"results", transport.Request{Op: transport.OpResults, Token: bsaCanary, AgentID: agentID, JobID: jobID, Body: []byte(`{"a":1}`)}, ""},
		{"inventory", transport.Request{Op: transport.OpInventory, Token: bsaCanary, AgentID: agentID, Body: []byte{0x1f, 0x8b, 0}, Gzip: true}, ""},
		{"inventory", transport.Request{Op: transport.OpInventory, Token: bsaCanary, AgentID: agentID, JobID: jobID, Body: []byte{0x1f, 0x8b, 1}, Gzip: true}, "job_id=" + jobID},
		{"rotate", transport.Request{Op: transport.OpRotate, Token: bsaCanary, AgentID: agentID, Body: []byte(`{}`)}, ""},
	}
	allowed := map[string]bool{"Authorization": true, "X-Bitscan-Machine-Id": true, "Content-Type": true, "Content-Encoding": true, "Content-Length": true, "User-Agent": true}
	for i, tc := range cases {
		resp, err := c.Do(context.Background(), tc.req)
		if err != nil || resp.Class != transport.Success || resp.Status != 200 || string(resp.Body) != "{}" {
			t.Fatalf("%s: resp %+v err %v", tc.name, resp, err)
		}
		got := f.requests()[i]
		want := routes[tc.name]
		wantPath := strings.NewReplacer("{id}", agentID, "{job_id}", jobID).Replace(want.Path)
		if got.method != want.Method || got.path != wantPath || got.rawQuery != tc.query {
			t.Errorf("%s: %s %s?%s, want %s %s?%s", tc.name, got.method, got.path, got.rawQuery, want.Method, wantPath, tc.query)
		}
		if a := got.header.Values("Authorization"); len(a) != 1 || a[0] != "Bearer "+tc.req.Token {
			t.Errorf("%s: %d Authorization values, or not the given token", tc.name, len(a))
		}
		mid := got.header.Values("X-Bitscan-Machine-Id")
		if tc.req.Op == transport.OpEnrol {
			if len(mid) != 0 {
				t.Errorf("enrol sends X-Bitscan-Machine-Id %v", mid)
			}
		} else if len(mid) != 1 || mid[0] != machineID {
			t.Errorf("%s: X-Bitscan-Machine-Id %v", tc.name, mid)
		}
		ct := got.header.Values("Content-Type")
		if (tc.req.Body != nil) != (len(ct) == 1 && ct[0] == "application/json") || len(ct) > 1 {
			t.Errorf("%s: Content-Type %v", tc.name, ct)
		}
		ce := got.header.Values("Content-Encoding")
		if (tc.req.Op == transport.OpInventory) != (len(ce) == 1 && ce[0] == "gzip") {
			t.Errorf("%s: Content-Encoding %v", tc.name, ce)
		}
		if !bytes.Equal(got.body, tc.req.Body) && (tc.req.Body != nil || len(got.body) != 0) {
			t.Errorf("%s: body changed in transit", tc.name)
		}
		for k := range got.header {
			if !allowed[k] {
				t.Errorf("%s: unexpected header %s", tc.name, k)
			}
		}
	}
	if len(routes) != 6 {
		t.Errorf("manifest has %d routes", len(routes))
	}
}

// CHK-M4-081 (CHK-M4-327): no redirect is followed; the class is Drop.
func TestClientNoRedirects(t *testing.T) {
	f := newFakeManager(t)
	second := newFakeManagerPKI(t, f.pki) // same CA: a followed redirect would succeed
	c := f.client(t)
	for _, code := range []int{301, 302, 303, 307, 308} {
		f.setAnswer(func(w http.ResponseWriter, r *http.Request) {
			http.Redirect(w, r, second.URL+"/api/v1/agent/redirected", code)
		})
		for _, op := range []transport.Request{
			{Op: transport.OpHeartbeat, Token: bsaCanary, AgentID: agentID, Body: []byte(`{}`)},
			{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID},
		} {
			resp, err := c.Do(context.Background(), op)
			if err != nil {
				t.Fatalf("%d: %v", code, err)
			}
			if resp.Status != code || resp.Class != transport.Drop {
				t.Fatalf("%d %s: status %d class %v, want %d drop", code, op.Op, resp.Status, resp.Class, code)
			}
		}
	}
	if n := len(second.requests()); n != 0 {
		t.Fatalf("redirect target received %d requests", n)
	}
	if n := len(f.requests()); n != 10 {
		t.Fatalf("manager received %d requests, want 10", n)
	}
}

// CHK-M4-082 (CHK-M4-328): proxy variables are ignored. TestMain sets
// HTTPS_PROXY, HTTP_PROXY, ALL_PROXY (both cases) to a recording proxy for the
// whole process, before any client exists (net/http reads them once).
func TestClientIgnoresProxyEnvironment(t *testing.T) {
	if os.Getenv("HTTPS_PROXY") != proxyURL || os.Getenv("https_proxy") != proxyURL {
		t.Fatal("TestMain did not set the proxy variables")
	}
	f := newFakeManager(t)
	c := f.client(t)
	resp, err := c.Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID})
	if err != nil || resp.Class != transport.Success || len(f.requests()) != 1 {
		t.Fatalf("call with proxy variables set: %+v %v", resp, err)
	}
	// a non-loopback name (Go never proxies loopback): the agent tries the
	// name itself and fails; the proxy sees nothing
	before := proxyConns.Load()
	far := clientFor(t, "https://bitscan-manager.invalid:8443", f.caFile)
	resp, err = far.Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID})
	if err == nil || resp.Class != transport.Retry {
		t.Fatalf("unresolvable manager: %+v %v", resp, err)
	}
	if n := proxyConns.Load() - before; n != 0 {
		t.Fatalf("the environment proxy saw %d connections from the agent client", n)
	}
	// control: a client that does use the environment reaches the proxy, so
	// the check above can fail
	ctl := &http.Client{Transport: &http.Transport{Proxy: http.ProxyFromEnvironment}, Timeout: 10 * time.Second}
	if r, err := ctl.Get("https://bitscan-manager.invalid:8443/"); err == nil {
		_ = r.Body.Close()
	}
	if proxyConns.Load()-before == 0 {
		t.Fatal("control: the environment proxy is not reachable, so the check proves nothing")
	}
}

// CHK-M4-083: the response size cap (32 MiB): exactly the cap accepted, cap+1
// refused; a Content-Length over the cap refused without reading the body.
func TestClientResponseCap(t *testing.T) {
	const limit = transport.MaxResponse
	if limit != 32<<20 {
		t.Fatalf("MaxResponse %d, want 32 MiB (plan)", limit)
	}
	f := newFakeManager(t)
	c := f.client(t)
	var written atomic.Int64
	serve := func(n int, chunked bool) func(w http.ResponseWriter, r *http.Request) {
		return func(w http.ResponseWriter, _ *http.Request) {
			written.Store(0)
			if !chunked {
				w.Header().Set("Content-Length", strconv.Itoa(n))
			}
			w.WriteHeader(200)
			buf := bytes.Repeat([]byte("a"), 64<<10)
			for left := n; left > 0; {
				k := min(left, len(buf))
				m, err := w.Write(buf[:k])
				written.Add(int64(m))
				if err != nil {
					return
				}
				if chunked {
					if fl, ok := w.(http.Flusher); ok {
						fl.Flush()
					}
				}
				left -= k
			}
		}
	}
	for _, tc := range []struct {
		name    string
		n       int
		chunked bool
		ok      bool
	}{
		{"exactly the cap, Content-Length", limit, false, true},
		{"exactly the cap, chunked", limit, true, true},
		{"cap+1, chunked", limit + 1, true, false},
		{"cap+1, Content-Length", limit + 1, false, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f.setAnswer(serve(tc.n, tc.chunked))
			resp, err := c.Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID})
			if tc.ok {
				if err != nil || resp.Class != transport.Success || len(resp.Body) != tc.n {
					t.Fatalf("refused: class %v len %d err %v", resp.Class, len(resp.Body), err)
				}
				return
			}
			if !errors.Is(err, transport.ErrTooLarge) || resp.Class != transport.Drop || resp.Body != nil {
				t.Fatalf("accepted: class %v len %d err %v", resp.Class, len(resp.Body), err)
			}
		})
	}
	// a huge Content-Length is refused before the body is read: the server
	// cannot write more than its socket buffers hold
	f.setAnswer(serve(1<<30, false))
	start := time.Now()
	_, err := c.Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID})
	if !errors.Is(err, transport.ErrTooLarge) {
		t.Fatalf("1 GiB Content-Length: %v", err)
	}
	time.Sleep(200 * time.Millisecond)
	if w := written.Load(); w > 16<<20 {
		t.Fatalf("server wrote %d bytes before the client gave up (body was read)", w)
	}
	if el := time.Since(start); el > 10*time.Second {
		t.Fatalf("refusal took %v", el)
	}
	// a chunked 1 GiB body is cut at the cap + 1: the client reads at most that
	f.setAnswer(serve(1<<30, true))
	if _, err := c.Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID}); !errors.Is(err, transport.ErrTooLarge) {
		t.Fatalf("chunked 1 GiB: %v", err)
	}
	time.Sleep(200 * time.Millisecond)
	if w := written.Load(); w > limit+(16<<20) {
		t.Fatalf("server wrote %d bytes for a chunked body (cap %d)", w, limit)
	}
}

// CHK-M4-084: a context cancel aborts at once; the caller's deadline is kept.
func TestClientContextAndDeadline(t *testing.T) {
	f := newFakeManager(t)
	release := make(chan struct{})
	t.Cleanup(func() { close(release) })
	f.setAnswer(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-release:
		case <-r.Context().Done():
		}
	})
	c := f.client(t)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		_, err := c.Do(ctx, transport.Request{Op: transport.OpHeartbeat, Token: bsaCanary, AgentID: agentID, Body: []byte(`{}`)})
		done <- err
	}()
	time.Sleep(300 * time.Millisecond)
	t0 := time.Now()
	cancel()
	select {
	case err := <-done:
		if err == nil || !errors.Is(err, context.Canceled) {
			t.Fatalf("cancelled call: %v", err)
		}
		if el := time.Since(t0); el > 200*time.Millisecond {
			t.Fatalf("cancel took %v", el)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("cancel did not abort the call")
	}
	ctx2, cancel2 := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel2()
	t0 = time.Now()
	resp, err := c.Do(ctx2, transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID})
	if err == nil || resp.Class != transport.Retry || time.Since(t0) > 3*time.Second {
		t.Fatalf("deadline: class %v err %v after %v", resp.Class, err, time.Since(t0))
	}
}

// CHK-M4-084: the client's own time limit (60 s per call, TASK-093 plan)
// ends a call to a server that never answers, and one that stalls mid-body,
// without any caller deadline. Real time, bounded by the test.
func TestClientOwnTimeLimit(t *testing.T) {
	t.Parallel() // a real 60 s wait: overlap it with the other tests
	f := newFakeManager(t)
	release := make(chan struct{})
	t.Cleanup(func() { close(release) })
	f.setAnswer(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet { // jobs: headers and part of the body, then a stall
			w.Header().Set("Content-Length", "100")
			w.WriteHeader(200)
			_, _ = w.Write([]byte(`{"jobs":`))
			w.(http.Flusher).Flush()
		}
		select {
		case <-release:
		case <-r.Context().Done():
		}
	})
	c := f.client(t)
	type result struct {
		op   transport.Request
		resp transport.Response
		err  error
		el   time.Duration
	}
	ops := []transport.Request{
		{Op: transport.OpHeartbeat, Token: bsaCanary, AgentID: agentID, Body: []byte(`{}`)}, // never answers
		{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID},                          // stalls mid-body
	}
	results := make(chan result, len(ops)) // buffered: a late call never blocks after the test ends
	for _, op := range ops {
		go func() {
			t0 := time.Now()
			resp, err := c.Do(context.Background(), op)
			results <- result{op, resp, err, time.Since(t0)}
		}()
	}
	// The test bounds its own wait, so a client without its own time limit fails here
	// for that reason, not through the package timeout.
	deadline := time.After(90 * time.Second)
	for i := range ops {
		select {
		case r := <-results:
			if r.err == nil || r.resp.Class != transport.Retry {
				t.Errorf("%s: class %v err %v", r.op.Op, r.resp.Class, r.err)
			}
			if r.el < 55*time.Second || r.el > 75*time.Second {
				t.Errorf("%s: ended after %v, want about 60 s", r.op.Op, r.el)
			}
			if r.err != nil && strings.Contains(r.err.Error(), "CANARY") {
				t.Errorf("%s: error holds the token: %v", r.op.Op, r.err)
			}
		case <-deadline:
			t.Fatalf("%d of %d calls still running after 90 s: the client has no time limit of its own", len(ops)-i, len(ops))
		}
	}
}

// CHK-M4-085 (CHK-M4-336, -337): the class table over every status and type.
func TestClassifyTable(t *testing.T) {
	types := []string{"", "about:blank", "pending_approval", "enrollment_rejected", "token_revoked", "token_expired", "machine_id_mismatch", "job_not_acceptable", "too_large", "rate_limited", "unauthorized", "forbidden", "invalid_request", "PENDING_APPROVAL", "pending_approval "}
	for status := 100; status <= 599; status++ {
		for _, typ := range types {
			var want transport.Class
			switch {
			case status >= 200 && status <= 299:
				want = transport.Success
			case status == 401:
				want = transport.Stop
			case status == 403 && typ == "pending_approval":
				want = transport.Wait
			case status == 429 || status >= 500:
				want = transport.Retry
			default:
				want = transport.Drop // 1xx, 3xx, 400, 402, 403 other, 404, 405, 409, 410, 413, 418, 422 …
			}
			if got := transport.Classify(status, typ, nil); got != want {
				t.Errorf("Classify(%d, %q) = %v, want %v", status, typ, got, want)
			}
		}
	}
	for _, e := range []error{errors.New("connection refused"), context.DeadlineExceeded, io.ErrUnexpectedEOF, transport.ErrPinMismatch} {
		for _, status := range []int{0, 200, 401, 403} {
			if got := transport.Classify(status, "pending_approval", e); got != transport.Retry {
				t.Errorf("network error %v (status %d) = %v, want retry", e, status, got)
			}
		}
	}
	names := map[transport.Class]string{transport.Success: "success", transport.Drop: "drop", transport.Stop: "stop", transport.Wait: "wait", transport.Retry: "retry"}
	for c, n := range names {
		if c.String() != n {
			t.Errorf("%d.String() = %q", c, c.String())
		}
	}
}

// CHK-M4-085: classes through real answers, problem types decoded from
// application/problem+json bodies, Retry-After in seconds.
func TestClientAnswers(t *testing.T) {
	f := newFakeManager(t)
	c := f.client(t)
	do := func() (transport.Response, error) {
		return c.Do(context.Background(), transport.Request{Op: transport.OpHeartbeat, Token: bsaCanary, AgentID: agentID, Body: []byte(`{}`)})
	}
	cases := []struct {
		status   int
		typ      string
		class    transport.Class
		wantType string
	}{
		{401, "token_revoked", transport.Stop, "token_revoked"},
		{401, "token_expired", transport.Stop, "token_expired"},
		{401, "enrollment_rejected", transport.Stop, "enrollment_rejected"},
		{401, "unauthorized", transport.Stop, "unauthorized"},
		{403, "pending_approval", transport.Wait, "pending_approval"},
		{403, "machine_id_mismatch", transport.Drop, "machine_id_mismatch"},
		{403, "forbidden", transport.Drop, "forbidden"},
		{400, "invalid_request", transport.Drop, "invalid_request"},
		{404, "about:blank", transport.Drop, "about:blank"},
		{409, "job_not_acceptable", transport.Drop, "job_not_acceptable"},
		{413, "too_large", transport.Drop, "too_large"},
		{422, "about:blank", transport.Drop, "about:blank"},
		{429, "rate_limited", transport.Retry, "rate_limited"},
		{500, "about:blank", transport.Retry, "about:blank"},
		{503, "about:blank", transport.Retry, "about:blank"},
	}
	for _, tc := range cases {
		f.setAnswer(problem(tc.status, tc.typ))
		resp, err := do()
		if err != nil || resp.Status != tc.status || resp.Class != tc.class || resp.Problem.Type != tc.wantType || resp.Problem.Status != tc.status {
			t.Errorf("%d %s: status %d class %v problem %+v err %v", tc.status, tc.typ, resp.Status, resp.Class, resp.Problem, err)
		}
	}
	// 401 and 403 without a body or with a non-problem body
	for _, tc := range []struct {
		status int
		body   string
		class  transport.Class
	}{{401, "", transport.Stop}, {403, "", transport.Drop}, {403, "<html>forbidden</html>", transport.Drop}, {401, "null", transport.Stop}, {403, `{"type":"pending_approval"`, transport.Drop}} {
		f.setAnswer(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(tc.status)
			_, _ = w.Write([]byte(tc.body))
		})
		resp, err := do()
		if err != nil || resp.Class != tc.class || resp.Problem.Type != "about:blank" {
			t.Errorf("%d %q: class %v type %q err %v", tc.status, tc.body, resp.Class, resp.Problem.Type, err)
		}
	}
	// a 2xx carries no problem
	f.setAnswer(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(204) })
	if resp, err := do(); err != nil || resp.Class != transport.Success || resp.Problem.Type != "" || resp.Status != 204 {
		t.Errorf("204: %+v %v", resp, err)
	}
	// Retry-After: delta-seconds only (RFC 9110 1*DIGIT, so "+5" is not one);
	// TASK-093 r1 (lead ruling 2026-10-25): never above 24 h and never an
	// overflow into a short or negative wait, whatever the size of the number.
	for _, tc := range []struct {
		h    string
		want time.Duration
	}{
		{"42", 42 * time.Second}, {"3600", time.Hour}, {"0", 0}, {"-5", 0}, {"abc", 0}, {"Wed, 21 Oct 2026 07:28:00 GMT", 0}, {"", 0},
		{"+5", 0},
		{"86399", 86399 * time.Second},
		{"86400", 24 * time.Hour},
		{"86401", 24 * time.Hour},
		{"9223372036", 24 * time.Hour},           // about where seconds × 1e9 overflows int64
		{"9223372036854775807", 24 * time.Hour},  // 2^63 − 1
		{"9223372036854775808", 24 * time.Hour},  // 2^63
		{"18446744073709551615", 24 * time.Hour}, // 2^64 − 1
		{"18446744073709551616", 24 * time.Hour}, // 2^64 (too large for uint64)
		{"99999999999999999999999999999", 24 * time.Hour},
	} {
		f.setAnswer(func(w http.ResponseWriter, r *http.Request) {
			if tc.h != "" {
				w.Header().Set("Retry-After", tc.h)
			}
			problem(429, "rate_limited")(w, r)
		})
		resp, err := do()
		if err != nil || resp.RetryAfter != tc.want || resp.Class != transport.Retry {
			t.Errorf("Retry-After %q: %v class %v err %v", tc.h, resp.RetryAfter, resp.Class, err)
		}
	}
}

// CHK-M4-085: network and TLS failures are Retry; IsVerifyError tells them apart.
func TestClientNetworkErrors(t *testing.T) {
	// refused connection: a port that was just closed
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := ln.Addr().String()
	_ = ln.Close()
	p := newPKI(t)
	c := clientFor(t, "https://"+addr, p.aFile)
	resp, err := c.Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID})
	if err == nil || resp.Class != transport.Retry || transport.IsVerifyError(err) {
		t.Fatalf("refused connection: class %v verify %v err %v", resp.Class, transport.IsVerifyError(err), err)
	}
	// reset mid-answer: a server that hijacks and closes
	f := newFakeManager(t)
	f.setAnswer(func(w http.ResponseWriter, _ *http.Request) {
		conn, _, err := w.(http.Hijacker).Hijack()
		if err == nil {
			_ = conn.Close()
		}
	})
	resp, err = f.client(t).Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID})
	if err == nil || resp.Class != transport.Retry {
		t.Fatalf("reset: class %v err %v", resp.Class, err)
	}
	// DNS failure (.invalid never resolves, RFC 6761)
	c = clientFor(t, "https://bitscan-manager.invalid:8443", p.aFile)
	resp, err = c.Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID})
	if err == nil || resp.Class != transport.Retry {
		t.Fatalf("DNS failure: class %v err %v", resp.Class, err)
	}
	// TLS verification failure: untrusted CA, wrong pin
	untrusted := newServer(t, p.fromB, 0, 0, tls.NoClientCert)
	resp, err = clientFor(t, untrusted.URL, p.aFile).Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID})
	if err == nil || resp.Class != transport.Retry || !transport.IsVerifyError(err) {
		t.Fatalf("untrusted CA: class %v verify %v err %v", resp.Class, transport.IsVerifyError(err), err)
	}
	good := newServer(t, p.good, 0, 0, tls.NoClientCert)
	cfg, err := transport.NewTLSConfig(p.aFile, pinOf(p.fromB.cert), "")
	if err != nil {
		t.Fatal(err)
	}
	pc, err := transport.NewClient(good.URL, cfg, machineID)
	if err != nil {
		t.Fatal(err)
	}
	resp, err = pc.Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID})
	if err == nil || resp.Class != transport.Retry || !transport.IsVerifyError(err) || !errors.Is(err, transport.ErrPinMismatch) {
		t.Fatalf("wrong pin: class %v verify %v err %v", resp.Class, transport.IsVerifyError(err), err)
	}
	wrongHost := newServer(t, p.wrongHost, 0, 0, tls.NoClientCert)
	_, err = clientFor(t, wrongHost.URL, p.aFile).Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID})
	if !transport.IsVerifyError(err) {
		t.Fatalf("wrong host is not a verify error: %v", err)
	}
	if good.calls.Load() != 0 || untrusted.calls.Load() != 0 || wrongHost.calls.Load() != 0 {
		t.Fatal("a refused handshake reached a handler")
	}
	if transport.IsVerifyError(nil) || transport.IsVerifyError(errors.New("x")) || transport.IsVerifyError(context.Canceled) {
		t.Fatal("IsVerifyError true for a non-TLS error")
	}
}

// CHK-M4-086 (CHK-M4-339): no token and no body in any error or printed request.
func TestClientNoSecretsInErrors(t *testing.T) {
	p := newPKI(t)
	f := newFakeManager(t)
	c := f.client(t)
	body := []byte(`{"secret":"BODY-CANARY-77"}`)
	reqs := []transport.Request{
		{Op: transport.OpEnrol, Token: bseCanary, Body: body},
		{Op: transport.OpHeartbeat, Token: bsaCanary, AgentID: agentID, Body: body},
		{Op: transport.OpInventory, Token: bsaCanary, AgentID: agentID, JobID: jobID, Body: body, Gzip: true},
	}
	check := func(what string, err error) {
		t.Helper()
		if err == nil {
			return
		}
		s := err.Error() + fmt.Sprintf("%+v %#v", err, err)
		if strings.Contains(s, "CANARY") {
			t.Errorf("%s: error holds a secret: %s", what, s)
		}
	}
	for _, r := range reqs {
		for _, verb := range []string{"%v", "%+v", "%s"} {
			if s := fmt.Sprintf(verb, r); strings.Contains(s, "CANARY") {
				t.Errorf("%s of a request prints a secret: %s", verb, s)
			}
		}
		// 5xx, redirect, oversize, cancel
		for _, ans := range []func(http.ResponseWriter, *http.Request){
			problem(503, "about:blank"),
			func(w http.ResponseWriter, r *http.Request) {
				http.Redirect(w, r, "https://elsewhere.invalid/", http.StatusFound)
			},
			func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Content-Length", strconv.Itoa(transport.MaxResponse+1))
				w.WriteHeader(200)
			},
		} {
			f.setAnswer(ans)
			_, err := c.Do(context.Background(), r)
			check(r.Op.String()+" answer", err)
		}
		ctx, cancel := context.WithTimeout(context.Background(), time.Millisecond)
		_, err := c.Do(ctx, r)
		cancel()
		check(r.Op.String()+" deadline", err)
		// TLS failure
		untrusted := newServer(t, p.fromB, 0, 0, tls.NoClientCert)
		_, err = clientFor(t, untrusted.URL, p.aFile).Do(context.Background(), r)
		check(r.Op.String()+" tls", err)
	}
	// a token with a bad character never reaches an error text
	badTok := strings.Join([]string{"bsa_CANARY", "X"}, "\n")
	_, err := c.Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: badTok, AgentID: agentID})
	check("bad header token", err)
}

// CHK-M4-087: the token is the one given to each call (rotation affects every loop).
func TestClientTokenPerCall(t *testing.T) {
	f := newFakeManager(t)
	c := f.client(t)
	t1 := "bsa_" + strings.Repeat("A", 43)
	t2 := "bsa_" + strings.Repeat("B", 43)
	for _, tok := range []string{t1, t2, t1} {
		if _, err := c.Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: tok, AgentID: agentID}); err != nil {
			t.Fatal(err)
		}
	}
	got := f.requests()
	for i, want := range []string{t1, t2, t1} {
		if got[i].header.Get("Authorization") != "Bearer "+want {
			t.Fatalf("call %d used the wrong token", i)
		}
	}
}

// CHK-M4-088: ids in paths are lowercase UUIDs; anything else is refused
// before any call.
func TestClientPathIDs(t *testing.T) {
	f := newFakeManager(t)
	c := f.client(t)
	upper := strings.ToUpper(agentID)
	upperJob := strings.ToUpper(jobID)
	if _, err := c.Do(context.Background(), transport.Request{Op: transport.OpResults, Token: bsaCanary, AgentID: wire.UUID(upper), JobID: wire.UUID(upperJob), Body: []byte(`{}`)}); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Do(context.Background(), transport.Request{Op: transport.OpInventory, Token: bsaCanary, AgentID: wire.UUID(upper), JobID: wire.UUID(upperJob), Body: []byte{1}, Gzip: true}); err != nil {
		t.Fatal(err)
	}
	got := f.requests()
	if got[0].path != "/api/v1/agent/"+agentID+"/jobs/"+jobID+"/results" || got[1].rawQuery != "job_id="+jobID || got[1].path != "/api/v1/agent/"+agentID+"/inventory" {
		t.Fatalf("paths %q %q?%q", got[0].path, got[1].path, got[1].rawQuery)
	}
	bad := []string{"../x", "..", agentID + "/..", agentID + "?x=1", agentID + "#f", "%2e%2e", strings.ReplaceAll(agentID, "-", ""), "{" + agentID + "}", "urn:uuid:" + agentID, agentID + "/heartbeat", " " + agentID, "", agentID[:35] + "/"}
	n := len(f.requests())
	for _, id := range bad {
		for _, r := range []transport.Request{
			{Op: transport.OpHeartbeat, Token: bsaCanary, AgentID: wire.UUID(id), Body: []byte(`{}`)},
			{Op: transport.OpResults, Token: bsaCanary, AgentID: agentID, JobID: wire.UUID(id), Body: []byte(`{}`)},
			{Op: transport.OpInventory, Token: bsaCanary, AgentID: agentID, JobID: wire.UUID(id + "x"), Body: []byte{1}, Gzip: true},
		} {
			if r.Op == transport.OpResults && id == "" {
				continue // checked below: results without a job id
			}
			resp, err := c.Do(context.Background(), r)
			if err == nil || resp.Class != transport.Drop {
				t.Errorf("%s with id %q: class %v err %v", r.Op, id, resp.Class, err)
			}
		}
	}
	if resp, err := c.Do(context.Background(), transport.Request{Op: transport.OpResults, Token: bsaCanary, AgentID: agentID, Body: []byte(`{}`)}); err == nil || resp.Class != transport.Drop {
		t.Errorf("results without a job id: %v %v", resp.Class, err)
	}
	if resp, err := c.Do(context.Background(), transport.Request{Op: transport.Op(99), Token: bsaCanary, AgentID: agentID}); err == nil || resp.Class != transport.Drop {
		t.Errorf("unknown op: %v %v", resp.Class, err)
	}
	if m := len(f.requests()); m != n {
		t.Fatalf("%d refused requests reached the manager", m-n)
	}
	// a path prefix in manager_url is kept
	pc := clientFor(t, f.URL+"/prefix", f.caFile)
	if _, err := pc.Do(context.Background(), transport.Request{Op: transport.OpJobs, Token: bsaCanary, AgentID: agentID}); err != nil {
		t.Fatal(err)
	}
	if last := f.requests()[len(f.requests())-1]; last.path != "/prefix/api/v1/agent/"+agentID+"/jobs" {
		t.Fatalf("prefix path %q", last.path)
	}
}

// CHK-M4-089: only an https:// base URL and a valid machine id build a client.
func TestNewClientRefusals(t *testing.T) {
	cfg, err := transport.NewTLSConfig("", "", "")
	if err != nil {
		t.Fatal(err)
	}
	for _, u := range []string{"http://mgr.example:8443", "ftp://mgr.example", "//mgr.example", "mgr.example:8443", "", "https://", "https:///x", "ws://mgr.example"} {
		if c, err := transport.NewClient(u, cfg, machineID); err == nil || c != nil {
			t.Errorf("NewClient(%q) accepted", u)
		}
	}
	for _, m := range []wire.MachineID{"", "0123456789ABCDEF0123456789ABCDEF", "0123456789abcdef0123456789abcde", "0123456789abcdef0123456789abcdef0", "01234567-89ab-cdef-0123-456789abcdef"} {
		if c, err := transport.NewClient("https://mgr.example", cfg, m); err == nil || c != nil {
			t.Errorf("machine id %q accepted", m)
		}
	}
	if _, err := transport.NewClient("https://mgr.example:8443", cfg, machineID); err != nil {
		t.Errorf("good client refused: %v", err)
	}
}

// The client source opens no listener and builds no proxy (static, CHK-M4-082).
func TestClientSourceStatic(t *testing.T) {
	_, file, _, _ := runtime.Caller(0)
	src, err := os.ReadFile(filepath.Join(filepath.Dir(file), "client.go"))
	if err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{"ProxyFromEnvironment", "ProxyURL", "InsecureSkipVerify", "net.Listen", "log.", "slog."} {
		if bytes.Contains(src, []byte(bad)) {
			t.Errorf("client.go contains %s", bad)
		}
	}
}
