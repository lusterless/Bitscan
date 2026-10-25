// Tests for enrolment and the start-up decision (TS §3.2 steps 2–5 and 8
// L182–L191, §3.1 L162, §6.5 Enrol L1161; #76, #81; REQ-096; tests/m4/
// test-plan.md TP-M4-13, CHK-M4-140 to -148; mutation row CHK-M4-341). The
// state store is the real one on a temporary directory; the manager is a fake
// Doer, and for the header check the real transport client against a TLS
// test server. Expected values come from the spec and #76/#81.
package enrol_test

import (
	"bytes"
	"context"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/enrol"
	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/state"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
)

const (
	machineID = "0123456789abcdef0123456789abcdef"
	agentUp   = "6F1C2B3A-4D5E-4F60-8A7B-9C0D1E2F3A4B"
	agentLow  = "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"
	osRelease = "PRETTY_NAME=\"Ubuntu 24.04.1 LTS\"\nNAME=\"Ubuntu\"\nVERSION_ID=\"24.04\"\nID=ubuntu\nID_LIKE=debian\n"
	stopText  = "enrolment refused; the host needs a new enrolment token"
)

var (
	bse    = "bse_CANARY" + strings.Repeat("e", 37) // 43 characters after the prefix
	newTok = wire.AgentToken("bsa_CANARY" + strings.Repeat("a", 37))
	oldTok = wire.AgentToken("bsa_" + strings.Repeat("o", 43))
	t0     = time.Date(2026, 10, 24, 8, 0, 0, 0, time.UTC)
)

type answer struct {
	status int
	typ    string
	body   []byte
	err    error
}

// fakeManager is the enrol endpoint: it records each request and returns the
// next answer (the last one repeats).
type fakeManager struct {
	mu      sync.Mutex
	reqs    []transport.Request
	answers []answer
}

func (f *fakeManager) Do(_ context.Context, r transport.Request) (transport.Response, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.reqs = append(f.reqs, r)
	a := f.answers[min(len(f.reqs), len(f.answers))-1]
	resp := transport.Response{Status: a.status, Body: a.body}
	if a.status != 0 && (a.status < 200 || a.status > 299) {
		resp.Problem = wire.Problem{Type: a.typ, Status: a.status}
	}
	resp.Class = transport.Classify(a.status, a.typ, a.err)
	return resp, a.err
}

func enrolBody(t testing.TB, status string) []byte {
	t.Helper()
	b, err := json.Marshal(map[string]string{
		"agent_id": agentUp, "agent_token": string(newTok),
		"issued_at": "2026-10-24T08:00:00Z", "expires_at": "2027-10-24T08:00:00+00:00", "status": status,
	})
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// fakeClock fires every After at once and records the delays.
type fakeClock struct {
	mu     sync.Mutex
	delays []time.Duration
}

func (c *fakeClock) Now() time.Time { return t0 }
func (c *fakeClock) After(d time.Duration) <-chan time.Time {
	c.mu.Lock()
	c.delays = append(c.delays, d)
	c.mu.Unlock()
	ch := make(chan time.Time, 1)
	ch <- t0.Add(d)
	return ch
}

type half struct{}

func (half) Float64() float64 { return 0.5 }

type env struct {
	dir   string
	store *state.Store
	f     *fakeManager
	clock *fakeClock
	e     *enrol.Enroller
}

func newEnv(t *testing.T, answers ...answer) *env {
	t.Helper()
	parent := t.TempDir()
	dir := filepath.Join(parent, "bitscan-agent")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	st, err := state.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = st.Close() })
	osr := filepath.Join(parent, "os-release")
	writeFile(t, osr, osRelease, 0o644)
	f := &fakeManager{answers: answers}
	c := &fakeClock{}
	return &env{dir: dir, store: st, f: f, clock: c, e: &enrol.Enroller{
		Client: f, Store: st, MachineID: machineID, AgentVersion: "0.1.0~pre1",
		Clock: c, Backoff: schedule.NewBackoff(half{}),
		Hostname: func() (string, error) { return "web-01.example.org", nil }, OSReleasePath: osr,
	}}
}

func writeFile(t testing.TB, p, s string, mode os.FileMode) {
	t.Helper()
	if err := os.WriteFile(p, []byte(s), mode); err != nil {
		t.Fatal(err)
	}
}

func (v *env) writeEnrolToken(t *testing.T, s string) {
	t.Helper()
	writeFile(t, filepath.Join(v.dir, "enroll.token"), s, 0o600)
}

func (v *env) files(t *testing.T) []string {
	t.Helper()
	entries, err := os.ReadDir(v.dir)
	if err != nil {
		t.Fatal(err)
	}
	var out []string
	for _, e := range entries {
		out = append(out, e.Name())
	}
	sort.Strings(out)
	return out
}

func (v *env) read(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Clean(filepath.Join(v.dir, name)))
	if err != nil {
		t.Fatalf("read %s: %v", name, err)
	}
	return string(b)
}

func mode(t *testing.T, p string) os.FileMode {
	t.Helper()
	st, err := os.Stat(p)
	if err != nil {
		t.Fatal(err)
	}
	return st.Mode().Perm()
}

// CHK-M4-140, -141 (CHK-M4-341): enrolled and awaiting_approval both persist
// the identity as REQ-093 (1) and remove enroll.token.
func TestEnrolSuccess(t *testing.T) {
	for _, status := range []string{"enrolled", "awaiting_approval"} {
		t.Run(status, func(t *testing.T) {
			v := newEnv(t, answer{status: 200, body: enrolBody(t, status)})
			v.writeEnrolToken(t, bse+"\n")
			res, err := v.e.Start(context.Background())
			if err != nil {
				t.Fatalf("Start: %v", err)
			}
			if string(res.Status) != status || res.AgentID != agentLow || res.Token.Value != newTok || !res.Token.TimesKnown {
				t.Fatalf("result %+v", res)
			}
			if !res.Token.IssuedAt.Equal(t0) || !res.Token.ExpiresAt.Equal(t0.AddDate(1, 0, 0)) {
				t.Fatalf("times %v %v", res.Token.IssuedAt, res.Token.ExpiresAt)
			}
			if len(v.f.reqs) != 1 {
				t.Fatalf("%d enrol calls, want 1", len(v.f.reqs))
			}
			r := v.f.reqs[0]
			if r.Op != transport.OpEnrol || r.Token != bse || r.AgentID != "" {
				t.Fatalf("request op %v token-is-bse %v agent %q", r.Op, r.Token == bse, r.AgentID)
			}
			var body map[string]any
			if err := json.Unmarshal(r.Body, &body); err != nil {
				t.Fatal(err)
			}
			want := map[string]any{"hostname": "web-01.example.org", "machine_id": machineID, "agent_version": "0.1.0~pre1", "os_id": "ubuntu", "os_version_id": "24.04", "os_pretty_name": "Ubuntu 24.04.1 LTS"}
			if fmt.Sprint(body) != fmt.Sprint(want) {
				t.Fatalf("body %v, want %v", body, want)
			}
			if got := v.files(t); strings.Join(got, ",") != "agent_id,token,token.json" {
				t.Fatalf("state files %v (enroll.token must be gone)", got)
			}
			if v.read(t, "agent_id") != agentLow+"\n" || v.read(t, "token") != string(newTok)+"\n" {
				t.Fatal("agent_id or token content wrong")
			}
			for name, m := range map[string]os.FileMode{"agent_id": 0o644, "token": 0o600, "token.json": 0o600} {
				if got := mode(t, filepath.Join(v.dir, name)); got != m {
					t.Errorf("%s mode %04o, want %04o", name, got, m)
				}
			}
			// the stored state reads back as the result
			tk, err := v.store.Token()
			if err != nil || tk.Value != newTok || !tk.TimesKnown || !tk.ExpiresAt.Equal(res.Token.ExpiresAt) {
				t.Fatalf("stored token %+v %v", tk, err)
			}
		})
	}
}

// CHK-M4-140: os-release absent or values out of bounds give null os_* keys,
// which are still present.
func TestEnrolBodyNulls(t *testing.T) {
	v := newEnv(t, answer{status: 200, body: enrolBody(t, "enrolled")})
	v.writeEnrolToken(t, bse)
	v.e.OSReleasePath = filepath.Join(v.dir, "absent-os-release")
	if _, err := v.e.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	var body map[string]any
	if err := json.Unmarshal(v.f.reqs[0].Body, &body); err != nil {
		t.Fatal(err)
	}
	for _, k := range []string{"os_id", "os_version_id", "os_pretty_name"} {
		if val, ok := body[k]; !ok || val != nil {
			t.Fatalf("%s = %v (present %v), want null", k, val, ok)
		}
	}
	if len(body) != 6 {
		t.Fatalf("body keys %v", body)
	}
	v2 := newEnv(t, answer{status: 200, body: enrolBody(t, "enrolled")})
	v2.writeEnrolToken(t, bse)
	writeFile(t, v2.e.OSReleasePath, "ID=ubuntu\nPRETTY_NAME=\""+strings.Repeat("x", 200)+"\"\n", 0o644)
	if _, err := v2.e.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	body = nil
	if err := json.Unmarshal(v2.f.reqs[0].Body, &body); err != nil {
		t.Fatal(err)
	}
	if body["os_pretty_name"] != nil || body["os_id"] != "ubuntu" || body["os_version_id"] != nil {
		t.Fatalf("over-long PRETTY_NAME / absent VERSION_ID: %v", body)
	}
}

// CHK-M4-140: through the real client: Authorization: Bearer <bse_>, no
// X-Bitscan-Machine-Id, POST /api/v1/agent/enroll.
func TestEnrolHeadersThroughClient(t *testing.T) {
	var mu sync.Mutex
	var got *http.Request
	var gotBody []byte
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		mu.Lock()
		got, gotBody = r.Clone(context.Background()), b
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(enrolBody(t, "enrolled"))
	}))
	t.Cleanup(srv.Close)
	caFile := filepath.Join(t.TempDir(), "ca.pem")
	writeFile(t, caFile, string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw})), 0o600)
	cfg, err := transport.NewTLSConfig(caFile, "", "")
	if err != nil {
		t.Fatal(err)
	}
	c, err := transport.NewClient(srv.URL, cfg, machineID)
	if err != nil {
		t.Fatal(err)
	}
	v := newEnv(t)
	v.e.Client = c
	v.writeEnrolToken(t, bse+"\n")
	if _, err := v.e.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	mu.Lock()
	defer mu.Unlock()
	if got.Method != http.MethodPost || got.URL.Path != "/api/v1/agent/enroll" || got.URL.RawQuery != "" {
		t.Fatalf("%s %s?%s", got.Method, got.URL.Path, got.URL.RawQuery)
	}
	if a := got.Header.Values("Authorization"); len(a) != 1 || a[0] != "Bearer "+bse {
		t.Fatal("Authorization is not exactly Bearer <bse_>")
	}
	if m := got.Header.Values("X-Bitscan-Machine-Id"); len(m) != 0 {
		t.Fatalf("enrol sent X-Bitscan-Machine-Id %v", m)
	}
	if !bytes.Contains(gotBody, []byte(`"machine_id":"`+machineID+`"`)) {
		t.Fatal("machine_id not in the body")
	}
}

// CHK-M4-142: a 401 of any type keeps enroll.token byte-identical, writes
// nothing, makes no retry and returns the stop text.
func TestEnrol401Stops(t *testing.T) {
	for _, typ := range []string{"enrollment_rejected", "unauthorized", "about:blank", ""} {
		t.Run("type "+typ, func(t *testing.T) {
			v := newEnv(t, answer{status: 401, typ: typ}, answer{status: 200, body: enrolBody(t, "enrolled")})
			v.writeEnrolToken(t, bse+"\n")
			before := v.read(t, "enroll.token")
			_, err := v.e.Start(context.Background())
			if !errors.Is(err, enrol.ErrStop) || err.Error() != stopText {
				t.Fatalf("err %v, want exactly %q", err, stopText)
			}
			if len(v.f.reqs) != 1 || len(v.clock.delays) != 0 {
				t.Fatalf("%d calls, %d waits after a 401", len(v.f.reqs), len(v.clock.delays))
			}
			if got := v.files(t); strings.Join(got, ",") != "enroll.token" || v.read(t, "enroll.token") != before {
				t.Fatalf("state after 401: %v", got)
			}
			if strings.Contains(err.Error(), "CANARY") {
				t.Fatal("stop text holds the token")
			}
		})
	}
}

// CHK-M4-143: 429, 503 and network errors are retried with back-off (10, 20,
// 40 s …) with the same token and body; other answers are not retried.
func TestEnrolRetries(t *testing.T) {
	v := newEnv(t,
		answer{status: 429, typ: "rate_limited"},
		answer{status: 503, typ: "about:blank"},
		answer{err: errors.New("dial tcp: connection refused")},
		answer{status: 500, typ: "about:blank"},
		answer{status: 403, typ: "pending_approval"},
		answer{status: 200, body: enrolBody(t, "enrolled")},
	)
	v.writeEnrolToken(t, bse)
	res, err := v.e.Start(context.Background())
	if err != nil || res.Status != wire.StatusEnrolled {
		t.Fatalf("after retries: %+v %v", res, err)
	}
	want := []time.Duration{10 * time.Second, 20 * time.Second, 40 * time.Second, 80 * time.Second, 160 * time.Second}
	if fmt.Sprint(v.clock.delays) != fmt.Sprint(want) {
		t.Fatalf("back-off delays %v, want %v", v.clock.delays, want)
	}
	if len(v.f.reqs) != 6 {
		t.Fatalf("%d calls, want 6", len(v.f.reqs))
	}
	for i, r := range v.f.reqs {
		if r.Token != bse || !bytes.Equal(r.Body, v.f.reqs[0].Body) {
			t.Fatalf("call %d: a different token or body (#76: the same each time)", i+1)
		}
	}
	for _, st := range []int{302, 400, 403, 404, 409, 413, 422, 418} {
		t.Run(fmt.Sprint(st), func(t *testing.T) {
			typ := "about:blank"
			if st == 403 {
				typ = "forbidden"
			}
			v := newEnv(t, answer{status: st, typ: typ}, answer{status: 200, body: enrolBody(t, "enrolled")})
			v.writeEnrolToken(t, bse)
			_, err := v.e.Start(context.Background())
			if err == nil || errors.Is(err, enrol.ErrStop) {
				t.Fatalf("%d: err %v, want a non-stop error", st, err)
			}
			if len(v.f.reqs) != 1 || len(v.clock.delays) != 0 {
				t.Fatalf("%d: %d calls, %d waits (want no retry)", st, len(v.f.reqs), len(v.clock.delays))
			}
			if got := v.files(t); strings.Join(got, ",") != "enroll.token" {
				t.Fatalf("%d: state %v", st, got)
			}
			if strings.Contains(err.Error(), "CANARY") {
				t.Fatalf("%d: error holds the token: %v", st, err)
			}
		})
	}
}

// CHK-M4-143: a cancelled context ends the back-off wait.
func TestEnrolCancelDuringBackoff(t *testing.T) {
	v := newEnv(t, answer{status: 503, typ: "about:blank"})
	v.writeEnrolToken(t, bse)
	v.e.Clock = schedule.RealClock{} // a real 10 s wait, ended by the cancel
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		_, err := v.e.Start(ctx)
		done <- err
	}()
	time.Sleep(200 * time.Millisecond)
	t1 := time.Now()
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("err %v", err)
		}
		if time.Since(t1) > 500*time.Millisecond {
			t.Fatalf("cancel took %v", time.Since(t1))
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the back-off ignored the context")
	}
	if got := v.files(t); strings.Join(got, ",") != "enroll.token" {
		t.Fatalf("state %v", got)
	}
}

// CHK-M4-144: /etc/machine-id values.
func TestReadMachineID(t *testing.T) {
	dir := t.TempDir()
	cases := map[string]bool{
		machineID + "\n":                         true,
		machineID:                                true,
		machineID[:31] + "\n":                    false,
		machineID + "0\n":                        false,
		strings.ToUpper(machineID) + "\n":        false,
		"01234567-89ab-cdef-0123-456789abcdef\n": false,
		"":                                       false,
		"\n":                                     false,
		machineID + " \n":                        false,
		machineID + "  ":                         false,
		" " + machineID + "\n":                   false,
		machineID + "\n\n":                       false,
		machineID + "\r\n":                       false,
		"0123456789abcdef0123456789abcdeg\n":     false,
		machineID + "\n" + machineID + "\n":      false,
		"uninitialized\n":                        false,
	}
	i := 0
	for content, ok := range cases {
		i++
		p := filepath.Join(dir, fmt.Sprintf("machine-id-%d", i))
		writeFile(t, p, content, 0o444)
		id, err := enrol.ReadMachineID(p)
		if ok && (err != nil || id != machineID) {
			t.Errorf("%q refused: %v", content, err)
		}
		if !ok {
			if err == nil {
				t.Errorf("%q accepted as %q", content, id)
			} else if !strings.Contains(err.Error(), "/etc/machine-id") || strings.Contains(err.Error(), "\n") {
				t.Errorf("%q: error %q does not name /etc/machine-id in one line", content, err)
			}
		}
	}
	if _, err := enrol.ReadMachineID(filepath.Join(dir, "absent")); err == nil {
		t.Error("missing machine-id accepted")
	}
	if _, err := enrol.ReadMachineID(dir); err == nil {
		t.Error("a directory accepted as machine-id")
	}
	big := filepath.Join(dir, "big")
	writeFile(t, big, machineID+strings.Repeat("0", 1<<20), 0o444)
	if _, err := enrol.ReadMachineID(big); err == nil {
		t.Error("a 1 MiB machine-id accepted")
	}
	if enrol.MachineIDPath != "/etc/machine-id" || enrol.OSReleasePath != "/etc/os-release" {
		t.Errorf("production paths %q %q", enrol.MachineIDPath, enrol.OSReleasePath)
	}
}

// CHK-M4-145: the #81 (c) start-up decision.
func TestStartupDecision(t *testing.T) {
	t.Run("enroll.token and token: enrol, new files replace the old", func(t *testing.T) {
		v := newEnv(t, answer{status: 200, body: enrolBody(t, "awaiting_approval")})
		if err := v.store.SaveEnrolment("11111111-2222-4333-8444-555555555555", state.Token{Value: oldTok, IssuedAt: t0.AddDate(-1, 0, 0), ExpiresAt: t0.AddDate(0, 1, 0)}); err != nil {
			t.Fatal(err)
		}
		v.writeEnrolToken(t, bse)
		res, err := v.e.Start(context.Background())
		if err != nil || len(v.f.reqs) != 1 {
			t.Fatalf("err %v, %d calls", err, len(v.f.reqs))
		}
		if v.read(t, "agent_id") != agentLow+"\n" || v.read(t, "token") != string(newTok)+"\n" || res.Token.Value != newTok {
			t.Fatal("re-enrolment did not replace agent_id and token")
		}
		tk, _ := v.store.Token()
		if !tk.TimesKnown || !tk.IssuedAt.Equal(t0) {
			t.Fatalf("token.json not replaced: %+v", tk)
		}
		if _, err := os.Stat(filepath.Join(v.dir, "enroll.token")); !errors.Is(err, fs.ErrNotExist) {
			t.Fatal("enroll.token not removed")
		}
	})
	t.Run("only token: no call", func(t *testing.T) {
		v := newEnv(t, answer{status: 500})
		tk := state.Token{Value: oldTok, IssuedAt: t0, ExpiresAt: t0.AddDate(1, 0, 0)}
		if err := v.store.SaveEnrolment(agentUp, tk); err != nil {
			t.Fatal(err)
		}
		res, err := v.e.Start(context.Background())
		if err != nil || len(v.f.reqs) != 0 {
			t.Fatalf("err %v, %d calls", err, len(v.f.reqs))
		}
		if res.AgentID != agentLow || res.Token.Value != oldTok || res.Status != "" || !res.Token.TimesKnown {
			t.Fatalf("result %+v", res)
		}
	})
	t.Run("neither: refused naming both, no call", func(t *testing.T) {
		v := newEnv(t, answer{status: 200, body: enrolBody(t, "enrolled")})
		_, err := v.e.Start(context.Background())
		if !errors.Is(err, enrol.ErrNoCredentials) || len(v.f.reqs) != 0 {
			t.Fatalf("err %v, %d calls", err, len(v.f.reqs))
		}
		if msg := err.Error(); !strings.Contains(msg, "token") || !strings.Contains(msg, "enroll.token") || strings.Count(msg, "token") < 2 {
			t.Fatalf("message %q does not name both files", msg)
		}
	})
	t.Run("token without agent_id: refused, no call", func(t *testing.T) {
		v := newEnv(t, answer{status: 200, body: enrolBody(t, "enrolled")})
		writeFile(t, filepath.Join(v.dir, "token"), string(oldTok)+"\n", 0o600)
		if _, err := v.e.Start(context.Background()); err == nil || len(v.f.reqs) != 0 {
			t.Fatalf("err %v, %d calls", err, len(v.f.reqs))
		}
	})
	for name, content := range map[string]string{
		"empty enroll.token":     "",
		"blank enroll.token":     " \n",
		"a bsa_ in enroll.token": string(oldTok),
		"short bse_":             "bse_abc",
		"bse_ with a space":      "bse_" + strings.Repeat("a", 20) + " " + strings.Repeat("a", 22),
		"bse_ with a newline":    "bse_" + strings.Repeat("a", 20) + "\n" + strings.Repeat("a", 23),
		"44 characters":          "bse_" + strings.Repeat("a", 44),
	} {
		t.Run(name+": refused before any call, no fallback to token", func(t *testing.T) {
			v := newEnv(t, answer{status: 200, body: enrolBody(t, "enrolled")})
			if err := v.store.SaveEnrolment(agentUp, state.Token{Value: oldTok, IssuedAt: t0, ExpiresAt: t0.AddDate(1, 0, 0)}); err != nil {
				t.Fatal(err)
			}
			v.writeEnrolToken(t, content)
			res, err := v.e.Start(context.Background())
			if err == nil || len(v.f.reqs) != 0 || res.Token.Value != "" {
				t.Fatalf("err %v, %d calls, result token set %v", err, len(v.f.reqs), res.Token.Value != "")
			}
			if strings.Contains(err.Error(), "aaaa") || strings.Contains(err.Error(), string(oldTok)) {
				t.Fatalf("error echoes the file: %v", err)
			}
		})
	}
	t.Run("host name unreadable: no call", func(t *testing.T) {
		v := newEnv(t, answer{status: 200, body: enrolBody(t, "enrolled")})
		v.writeEnrolToken(t, bse)
		v.e.Hostname = func() (string, error) { return "", errors.New("uname failed") }
		if _, err := v.e.Start(context.Background()); err == nil || len(v.f.reqs) != 0 {
			t.Fatalf("err %v, %d calls", err, len(v.f.reqs))
		}
	})
}

// CHK-M4-146: a lost answer (#76): the retry sends the same token; a later
// 401 stops; a 200 awaiting_approval (a held re-enrolment) writes the files.
func TestEnrolLostAnswer(t *testing.T) {
	lost := answer{err: errors.New("read tcp: connection reset by peer")}
	v := newEnv(t, lost, answer{status: 401, typ: "enrollment_rejected"})
	v.writeEnrolToken(t, bse)
	if _, err := v.e.Start(context.Background()); !errors.Is(err, enrol.ErrStop) {
		t.Fatalf("lost then 401: %v", err)
	}
	if len(v.f.reqs) != 2 || v.f.reqs[1].Token != bse || !bytes.Equal(v.f.reqs[0].Body, v.f.reqs[1].Body) {
		t.Fatal("the retry after a lost answer did not resend the same token and body")
	}
	if got := v.files(t); strings.Join(got, ",") != "enroll.token" {
		t.Fatalf("state %v", got)
	}
	v2 := newEnv(t, lost, answer{status: 200, body: enrolBody(t, "awaiting_approval")})
	v2.writeEnrolToken(t, bse)
	res, err := v2.e.Start(context.Background())
	if err != nil || res.Status != wire.StatusAwaitingApproval || len(v2.f.reqs) != 2 {
		t.Fatalf("lost then held: %+v %v (%d calls)", res, err, len(v2.f.reqs))
	}
	if got := v2.files(t); strings.Join(got, ",") != "agent_id,token,token.json" {
		t.Fatalf("state %v", got)
	}
}

// failingStore wraps the real store and fails one step, like a crash there.
type failingStore struct {
	*state.Store
	failSave, failDelete bool
}

func (s *failingStore) SaveEnrolment(id wire.UUID, t state.Token) error {
	if s.failSave {
		return errors.New("state: rename .token.tmp: injected crash")
	}
	return s.Store.SaveEnrolment(id, t)
}

func (s *failingStore) DeleteEnrolToken() error {
	if s.failDelete {
		return errors.New("state: delete enroll.token: injected crash")
	}
	return s.Store.DeleteEnrolToken()
}

// CHK-M4-147: write the state before deleting enroll.token; a crash between
// them leaves both, and the next start enrols again.
func TestEnrolCrashOrder(t *testing.T) {
	v := newEnv(t, answer{status: 200, body: enrolBody(t, "enrolled")})
	v.writeEnrolToken(t, bse)
	fs1 := &failingStore{Store: v.store, failDelete: true}
	v.e.Store = fs1
	if _, err := v.e.Start(context.Background()); err == nil {
		t.Fatal("a failed delete reported success")
	}
	if got := v.files(t); strings.Join(got, ",") != "agent_id,enroll.token,token,token.json" {
		t.Fatalf("after a crash before the delete: %v", got)
	}
	fs1.failDelete = false
	res, err := v.e.Start(context.Background())
	if err != nil || len(v.f.reqs) != 2 || res.Status != wire.StatusEnrolled {
		t.Fatalf("next start: %+v %v (%d calls, want a second enrol)", res, err, len(v.f.reqs))
	}
	if got := v.files(t); strings.Join(got, ",") != "agent_id,token,token.json" {
		t.Fatalf("after the second enrol: %v", got)
	}
	// a failed state write keeps enroll.token and does not delete it
	v2 := newEnv(t, answer{status: 200, body: enrolBody(t, "enrolled")})
	v2.writeEnrolToken(t, bse)
	v2.e.Store = &failingStore{Store: v2.store, failSave: true}
	if _, err := v2.e.Start(context.Background()); err == nil {
		t.Fatal("a failed save reported success")
	}
	if got := v2.files(t); strings.Join(got, ",") != "enroll.token" {
		t.Fatalf("after a failed save: %v", got)
	}
}

// CHK-M4-148: an answer that is not a valid EnrolResponse writes nothing.
func TestEnrolBadAnswer(t *testing.T) {
	good := map[string]any{"agent_id": agentUp, "agent_token": string(newTok), "issued_at": "2026-10-24T08:00:00Z", "expires_at": "2027-10-24T08:00:00Z", "status": "enrolled"}
	mutate := func(f func(m map[string]any)) []byte {
		m := map[string]any{}
		for k, v := range good {
			m[k] = v
		}
		f(m)
		b, _ := json.Marshal(m)
		return b
	}
	cases := map[string][]byte{
		"bse_ agent_token":    mutate(func(m map[string]any) { m["agent_token"] = bse }),
		"short agent_token":   mutate(func(m map[string]any) { m["agent_token"] = "bsa_short" }),
		"extra key":           mutate(func(m map[string]any) { m["command"] = "id" }),
		"missing expires_at":  mutate(func(m map[string]any) { delete(m, "expires_at") }),
		"naive issued_at":     mutate(func(m map[string]any) { m["issued_at"] = "2026-10-24T08:00:00" }),
		"status other":        mutate(func(m map[string]any) { m["status"] = "approved" }),
		"agent_id not a UUID": mutate(func(m map[string]any) { m["agent_id"] = "../../etc" }),
		"agent_id 32 hex":     mutate(func(m map[string]any) { m["agent_id"] = strings.ReplaceAll(agentLow, "-", "") }),
		"null agent_token":    mutate(func(m map[string]any) { m["agent_token"] = nil }),
		"not JSON":            []byte("<html>ok</html>"),
		"empty body":          nil,
		"array":               []byte("[]"),
		"trailing data":       append(mutate(func(map[string]any) {}), []byte(" {}")...),
		"expires_at number":   mutate(func(m map[string]any) { m["expires_at"] = 1792800000 }),
		"agent_token with spaces": mutate(func(m map[string]any) {
			m["agent_token"] = "bsa_" + strings.Repeat("a", 21) + " " + strings.Repeat("a", 21)
		}),
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			v := newEnv(t, answer{status: 200, body: body})
			v.writeEnrolToken(t, bse)
			before := v.read(t, "enroll.token")
			_, err := v.e.Start(context.Background())
			if err == nil {
				t.Fatal("accepted")
			}
			if got := v.files(t); strings.Join(got, ",") != "enroll.token" || v.read(t, "enroll.token") != before {
				t.Fatalf("state %v", got)
			}
			if strings.Contains(err.Error(), "CANARY") {
				t.Fatalf("error holds a token: %v", err)
			}
		})
	}
}

// No token in any error or printed result (canaries in bse_ and bsa_).
func TestEnrolNoTokenInOutput(t *testing.T) {
	v := newEnv(t, answer{status: 200, body: enrolBody(t, "enrolled")})
	v.writeEnrolToken(t, bse)
	res, err := v.e.Start(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	for _, verb := range []string{"%v", "%+v", "%#v", "%s"} {
		if out := fmt.Sprintf(verb, res); strings.Contains(out, "CANARY") {
			t.Errorf("%s of the result prints a token: %s", verb, out)
		}
	}
	if strings.Contains(enrol.ErrNoCredentials.Error(), "CANARY") || strings.Contains(enrol.ErrStop.Error(), "bse_") {
		t.Error("fixed texts hold a token")
	}
}
