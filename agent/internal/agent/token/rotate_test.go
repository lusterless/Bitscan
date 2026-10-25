// Tests for the token holder and rotation (TS §3.2 steps 7–8 L190–L191, §6.5
// Rotate L1188; #62; decisions 2026-10-23; REQ-099; tests/m4/test-plan.md
// TP-M4-14, CHK-M4-150 to -158; mutation rows CHK-M4-347 to -349). The window
// is issued_at + max(TTL − 30 d, TTL ÷ 2) of the current token; 429 waits for
// its Retry-After, 403 forbidden for 24 h, 401 stops (REQ-099). Expected values
// come from the spec, not from the implementation.
package token_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/state"
	"bitscan.local/agent/internal/agent/token"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
)

const (
	agentID = wire.UUID("6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b")
	day     = 24 * time.Hour
)

var t0 = time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)

func tok(c byte) wire.AgentToken { return wire.AgentToken("bsa_" + strings.Repeat(string(c), 43)) }

// canary token: bsa_ + 43 base64url characters with CANARY inside
var canary = wire.AgentToken("bsa_CANARY" + strings.Repeat("x", 37))

func tokenWithTTL(v wire.AgentToken, issued time.Time, ttl time.Duration) state.Token {
	return state.Token{Value: v, IssuedAt: issued, ExpiresAt: issued.Add(ttl), TimesKnown: true}
}

// call is one rotate request as the fake manager saw it.
type call struct {
	req transport.Request
	ctx context.Context
}

// fakeManager answers rotate calls; answer returns status, problem type,
// Retry-After, a body and a transport error.
type fakeManager struct {
	mu     sync.Mutex
	calls  []call
	answer func(n int, r transport.Request) (int, string, time.Duration, []byte, error)
}

func (f *fakeManager) Do(ctx context.Context, r transport.Request) (transport.Response, error) {
	f.mu.Lock()
	f.calls = append(f.calls, call{r, ctx})
	n := len(f.calls)
	ans := f.answer
	f.mu.Unlock()
	status, typ, ra, body, err := ans(n, r)
	resp := transport.Response{Status: status, Body: body, RetryAfter: ra}
	if status != 0 && (status < 200 || status > 299) {
		resp.Problem = wire.Problem{Type: typ, Status: status}
	}
	resp.Class = transport.Classify(status, typ, err)
	return resp, err
}

func (f *fakeManager) n() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.calls)
}

func (f *fakeManager) tokens() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []string
	for _, c := range f.calls {
		out = append(out, c.req.Token)
	}
	return out
}

func rotateBody(t testing.TB, v wire.AgentToken, issued time.Time, ttl time.Duration) []byte {
	t.Helper()
	b, err := json.Marshal(map[string]string{
		"agent_token": string(v),
		"issued_at":   issued.UTC().Format(time.RFC3339),
		"expires_at":  issued.Add(ttl).UTC().Format(time.RFC3339),
	})
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// issuing answers every call with a fresh token issued at the call's time.
func issuing(t testing.TB, clock func() time.Time, ttl time.Duration, next ...wire.AgentToken) func(int, transport.Request) (int, string, time.Duration, []byte, error) {
	return func(n int, _ transport.Request) (int, string, time.Duration, []byte, error) {
		v := next[min(n-1, len(next)-1)]
		return 200, "", 0, rotateBody(t, v, clock(), ttl), nil
	}
}

// fakeStore records saves; hook runs inside SaveToken.
type fakeStore struct {
	mu    sync.Mutex
	saved []state.Token
	fail  error
	hook  func(state.Token)
}

func (s *fakeStore) SaveToken(t state.Token) error {
	if s.hook != nil {
		s.hook(t)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.fail != nil {
		return s.fail
	}
	s.saved = append(s.saved, t)
	return nil
}

func setup(t *testing.T, cur state.Token) (*fakeManager, *fakeStore, *token.Holder, *token.Rotator) {
	t.Helper()
	f := &fakeManager{}
	s := &fakeStore{}
	h := token.NewHolder(cur)
	return f, s, h, token.NewRotator(f, s, h, agentID)
}

// CHK-M4-150 (CHK-M4-348): the window per TTL, from the token's own times.
func TestRotationWindow(t *testing.T) {
	for _, tc := range []struct {
		ttl     time.Duration
		openDay int
	}{
		{365 * day, 335}, // TTL − 30 d
		{60 * day, 30},   // both 30
		{100 * day, 70},  // TTL − 30 > TTL ÷ 2
		{730 * day, 700},
		{61 * day, 31},
		{40 * day, 20}, // TTL ÷ 2 > TTL − 30
	} {
		t.Run(fmt.Sprintf("TTL %d d", tc.ttl/day), func(t *testing.T) {
			issued := t0.Add(17 * time.Hour) // not midnight: the window is from issued_at, not a calendar day
			cur := tokenWithTTL(tok('A'), issued, tc.ttl)
			open := issued.Add(time.Duration(tc.openDay) * day)
			if got := token.WindowStart(cur); !got.Equal(open) {
				t.Fatalf("WindowStart = %v, want %v", got, open)
			}
			f, s, h, r := setup(t, cur)
			now := issued
			f.answer = issuing(t, func() time.Time { return now }, tc.ttl, tok('B'))
			for _, at := range []time.Time{issued, issued.Add(day), open.Add(-day), open.Add(-time.Second)} {
				now = at
				if err := r.MaybeRotate(context.Background(), at); err != nil || f.n() != 0 {
					t.Fatalf("at %v (window %v): err %v, %d calls", at, open, err, f.n())
				}
			}
			now = open.Add(time.Second)
			if err := r.MaybeRotate(context.Background(), now); err != nil {
				t.Fatalf("in the window: %v", err)
			}
			if f.n() != 1 || h.Current().Value != tok('B') || len(s.saved) != 1 {
				t.Fatalf("in the window: %d calls, holder %v, %d saves", f.n(), h.Current().Value == tok('B'), len(s.saved))
			}
			// the new token's own window applies: no call the next day
			now = now.Add(day)
			if err := r.MaybeRotate(context.Background(), now); err != nil || f.n() != 1 {
				t.Fatalf("after the rotation: err %v, %d calls", err, f.n())
			}
		})
	}
	// unknown times (crash between token and token.json): the window is open
	f, _, _, r := setup(t, state.Token{Value: tok('A')})
	f.answer = issuing(t, func() time.Time { return t0 }, 365*day, tok('B'))
	if err := r.MaybeRotate(context.Background(), t0); err != nil || f.n() != 1 {
		t.Fatalf("unknown times: err %v, %d calls", err, f.n())
	}
}

// CHK-M4-151 (CHK-M4-349): persisted before use; every later call uses it.
func TestRotationPersistsBeforeUse(t *testing.T) {
	cur := tokenWithTTL(tok('A'), t0, 365*day)
	f, s, h, r := setup(t, cur)
	now := t0.Add(335 * day)
	f.answer = issuing(t, func() time.Time { return now }, 365*day, tok('B'), tok('C'))
	var atPersist wire.AgentToken
	s.hook = func(state.Token) { atPersist = h.Current().Value }
	if err := r.MaybeRotate(context.Background(), now); err != nil {
		t.Fatal(err)
	}
	if atPersist != tok('A') {
		t.Fatal("the holder already had the new token while it was being persisted")
	}
	got := s.saved[0]
	if got.Value != tok('B') || !got.IssuedAt.Equal(now.Truncate(time.Second)) || !got.ExpiresAt.Equal(now.Truncate(time.Second).Add(365*day)) || !got.TimesKnown {
		t.Fatalf("persisted %+v", got)
	}
	if h.Current().Value != tok('B') || !h.Current().ExpiresAt.Equal(got.ExpiresAt) {
		t.Fatal("holder not swapped to the persisted token")
	}
	// the request: OpRotate, our id, the old token, body {} only
	c := f.calls[0].req
	if c.Op != transport.OpRotate || c.AgentID != agentID || c.Token != string(tok('A')) {
		t.Fatalf("request %v id %s token old=%v", c.Op, c.AgentID, c.Token == string(tok('A')))
	}
	if b := strings.TrimSpace(string(c.Body)); b != "{}" && b != "" {
		t.Fatalf("rotate body %q, want {} or empty", b)
	}
	// next window (from B's own times) uses B
	now = now.Add(336 * day)
	if err := r.MaybeRotate(context.Background(), now); err != nil {
		t.Fatal(err)
	}
	if toks := f.tokens(); len(toks) != 2 || toks[1] != string(tok('B')) {
		t.Fatalf("second rotation sent %d calls, token B = %v", len(toks), len(toks) == 2 && toks[1] == string(tok('B')))
	}
	if h.Current().Value != tok('C') {
		t.Fatal("second rotation not applied")
	}
}

// CHK-M4-152: a lost answer (connection dropped after the manager issued a
// token) or a 5xx: the next attempt sends the old token; its fresh token is kept.
func TestRotationLostAnswer(t *testing.T) {
	for _, lost := range []struct {
		name   string
		status int
		err    error
	}{
		{"connection dropped", 0, errors.New("transport: rotate call: connection reset by peer")},
		{"503", 503, nil},
		{"500", 500, nil},
		{"answer unreadable (200 with a bse_ token)", 200, nil},
		{"answer unreadable (200, extra key)", 200, nil},
		{"answer unreadable (200, naive time)", 200, nil},
	} {
		t.Run(lost.name, func(t *testing.T) {
			cur := tokenWithTTL(tok('A'), t0, 365*day)
			f, s, h, r := setup(t, cur)
			now := t0.Add(335 * day)
			f.answer = func(n int, _ transport.Request) (int, string, time.Duration, []byte, error) {
				if n == 1 {
					switch {
					case strings.Contains(lost.name, "bse_"):
						return 200, "", 0, rotateBody(t, wire.AgentToken("bse_"+strings.Repeat("Z", 43)), now, 365*day), nil
					case strings.Contains(lost.name, "extra"):
						b := rotateBody(t, tok('Z'), now, 365*day)
						return 200, "", 0, append(b[:len(b)-1], []byte(`,"command":"id"}`)...), nil
					case strings.Contains(lost.name, "naive"):
						return 200, "", 0, []byte(`{"agent_token":"` + string(tok('Z')) + `","issued_at":"2026-12-02T00:00:00","expires_at":"2027-12-02T00:00:00Z"}`), nil
					}
					return lost.status, "about:blank", 0, nil, lost.err // the manager issued X, the agent never got it
				}
				return 200, "", 0, rotateBody(t, tok('F'), now, 365*day), nil
			}
			if err := r.MaybeRotate(context.Background(), now); err == nil {
				t.Fatal("a lost answer reported success")
			}
			if h.Current().Value != tok('A') || len(s.saved) != 0 {
				t.Fatalf("after a lost answer: holder changed %v, %d saves", h.Current().Value != tok('A'), len(s.saved))
			}
			now = now.Add(5 * time.Minute) // next heartbeat
			if err := r.MaybeRotate(context.Background(), now); err != nil {
				t.Fatal(err)
			}
			if toks := f.tokens(); len(toks) != 2 || toks[1] != string(tok('A')) {
				t.Fatalf("retry did not send the old token (%d calls)", len(toks))
			}
			if h.Current().Value != tok('F') || len(s.saved) != 1 || s.saved[0].Value != tok('F') {
				t.Fatal("the fresh token from the retry was not kept")
			}
		})
	}
}

// CHK-M4-153, -158: a failed persist (or a crash before it) leaves the old
// token current; the next attempt rotates again with the old token; the
// error holds no token.
func TestRotationPersistFailure(t *testing.T) {
	cur := tokenWithTTL(canary, t0, 365*day)
	f, s, h, r := setup(t, cur)
	now := t0.Add(335 * day)
	f.answer = issuing(t, func() time.Time { return now }, 365*day, wire.AgentToken("bsa_CANARYNEW"+strings.Repeat("y", 34)), tok('G'))
	s.fail = errors.New("state: rename .token.tmp: input/output error")
	err := r.MaybeRotate(context.Background(), now)
	if err == nil {
		t.Fatal("a failed persist reported success")
	}
	if strings.Contains(err.Error(), "CANARY") || strings.Contains(fmt.Sprintf("%+v", err), "CANARY") {
		t.Fatalf("error holds a token: %v", err)
	}
	if h.Current().Value != canary {
		t.Fatal("the holder swapped although the persist failed")
	}
	// "restart": a new holder and rotator from the old token on disk
	s.fail = nil
	h2 := token.NewHolder(cur)
	r2 := token.NewRotator(f, s, h2, agentID)
	if err := r2.MaybeRotate(context.Background(), now.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}
	if toks := f.tokens(); len(toks) != 2 || toks[1] != string(canary) {
		t.Fatal("after restart the old token was not used for the next rotation")
	}
	if h2.Current().Value != tok('G') {
		t.Fatal("rotation after restart not applied")
	}
	// the original rotator also retries (in-process, next heartbeat)
	if err := r.MaybeRotate(context.Background(), now.Add(10*time.Minute)); err != nil {
		t.Fatal(err)
	}
	if f.n() != 3 {
		t.Fatalf("in-process retry: %d calls", f.n())
	}
}

// CHK-M4-154 (CHK-M4-347): 2 to 16 goroutines triggering at the same instant
// make exactly one rotate call; repeated 200 times.
func TestRotationSingleFlight(t *testing.T) {
	for round := range 200 {
		g := 2 + round%15
		cur := tokenWithTTL(tok('A'), t0, 365*day)
		f, s, h, r := setup(t, cur)
		now := t0.Add(335 * day)
		var returned atomic.Int64
		f.answer = func(int, transport.Request) (int, string, time.Duration, []byte, error) {
			// hold the call until every other goroutine has returned (or 2 s)
			deadline := time.Now().Add(2 * time.Second)
			for returned.Load() < int64(g-1) && time.Now().Before(deadline) {
				time.Sleep(100 * time.Microsecond)
			}
			return 200, "", 0, rotateBody(t, tok('B'), now, 365*day), nil
		}
		var start, done sync.WaitGroup
		start.Add(1)
		errs := make(chan error, g)
		for range g {
			done.Add(1)
			go func() {
				defer done.Done()
				start.Wait()
				err := r.MaybeRotate(context.Background(), now)
				returned.Add(1)
				errs <- err
			}()
		}
		start.Done()
		done.Wait()
		close(errs)
		for err := range errs {
			if err != nil {
				t.Fatalf("round %d: %v", round, err)
			}
		}
		if f.n() != 1 || len(s.saved) != 1 || h.Current().Value != tok('B') {
			t.Fatalf("round %d with %d goroutines: %d rotate calls, %d saves", round, g, f.n(), len(s.saved))
		}
	}
}

// CHK-M4-155: 429 waits for Retry-After, 403 forbidden for 24 h, 401 stops.
func TestRotationRefusals(t *testing.T) {
	cur := tokenWithTTL(tok('A'), t0, 365*day)
	open := t0.Add(335 * day)
	t.Run("429 Retry-After 3600", func(t *testing.T) {
		f, _, h, r := setup(t, cur)
		f.answer = func(n int, _ transport.Request) (int, string, time.Duration, []byte, error) {
			if n == 1 {
				return 429, "rate_limited", time.Hour, nil, nil
			}
			return 200, "", 0, rotateBody(t, tok('B'), open, 365*day), nil
		}
		if err := r.MaybeRotate(context.Background(), open); err == nil {
			t.Fatal("429 reported success")
		}
		for _, d := range []time.Duration{0, time.Second, 5 * time.Minute, 59 * time.Minute, time.Hour - time.Second} {
			if err := r.MaybeRotate(context.Background(), open.Add(d)); err != nil || f.n() != 1 {
				t.Fatalf("at +%v: err %v, %d calls (want no attempt before Retry-After)", d, err, f.n())
			}
		}
		if err := r.MaybeRotate(context.Background(), open.Add(time.Hour+5*time.Minute)); err != nil || f.n() != 2 || h.Current().Value != tok('B') {
			t.Fatalf("after Retry-After: err %v, %d calls", err, f.n())
		}
	})
	// TASK-093 r1: a huge Retry-After, parsed by the client, waits at most 24 h
	// and never wraps into a short or negative wait (no rotate storm).
	for _, hdr := range []string{"86401", "9223372036854775807", "9223372036854775808", "18446744073709551616"} {
		t.Run("429 Retry-After "+hdr+" waits 24 h", func(t *testing.T) {
			f, _, h, r := setup(t, cur)
			ra := transport.RetryAfter(hdr)
			f.answer = func(n int, _ transport.Request) (int, string, time.Duration, []byte, error) {
				if n == 1 {
					return 429, "rate_limited", ra, nil, nil
				}
				return 200, "", 0, rotateBody(t, tok('B'), open, 365*day), nil
			}
			if err := r.MaybeRotate(context.Background(), open); err == nil {
				t.Fatal("429 reported success")
			}
			for _, d := range []time.Duration{0, time.Second, 5 * time.Minute, 23 * time.Hour, day - time.Second} {
				if err := r.MaybeRotate(context.Background(), open.Add(d)); err != nil || f.n() != 1 {
					t.Fatalf("Retry-After %s (%v) at +%v: err %v, %d calls (want none before 24 h)", hdr, ra, d, err, f.n())
				}
			}
			if err := r.MaybeRotate(context.Background(), open.Add(day+5*time.Minute)); err != nil || f.n() != 2 || h.Current().Value != tok('B') {
				t.Fatalf("Retry-After %s (%v) after 24 h: err %v, %d calls (want one attempt)", hdr, ra, err, f.n())
			}
		})
	}
	t.Run("403 forbidden waits 24 h", func(t *testing.T) {
		f, _, h, r := setup(t, cur)
		f.answer = func(n int, _ transport.Request) (int, string, time.Duration, []byte, error) {
			if n == 1 {
				return 403, "forbidden", 0, nil, nil
			}
			return 200, "", 0, rotateBody(t, tok('B'), open, 365*day), nil
		}
		if err := r.MaybeRotate(context.Background(), open); err == nil {
			t.Fatal("403 reported success")
		}
		for _, d := range []time.Duration{5 * time.Minute, 2 * time.Hour, 23 * time.Hour, day - time.Second} {
			if err := r.MaybeRotate(context.Background(), open.Add(d)); err != nil || f.n() != 1 {
				t.Fatalf("at +%v: err %v, %d calls (want none within 24 h)", d, err, f.n())
			}
		}
		if err := r.MaybeRotate(context.Background(), open.Add(day+5*time.Minute)); err != nil || f.n() != 2 || h.Current().Value != tok('B') {
			t.Fatalf("after 24 h: err %v, %d calls", err, f.n())
		}
	})
	for _, typ := range []string{"token_expired", "token_revoked", "unauthorized", "about:blank", ""} {
		t.Run("401 "+typ+" stops", func(t *testing.T) {
			f, s, h, r := setup(t, cur)
			f.answer = func(int, transport.Request) (int, string, time.Duration, []byte, error) {
				return 401, typ, 0, nil, nil
			}
			if err := r.MaybeRotate(context.Background(), open); !errors.Is(err, token.ErrStop) {
				t.Fatalf("401: %v, want ErrStop", err)
			}
			for _, d := range []time.Duration{5 * time.Minute, day, 30 * day, 400 * day} {
				if err := r.MaybeRotate(context.Background(), open.Add(d)); !errors.Is(err, token.ErrStop) {
					t.Fatalf("after 401, at +%v: %v", d, err)
				}
			}
			if f.n() != 1 || len(s.saved) != 0 || h.Current().Value != tok('A') {
				t.Fatalf("after 401: %d calls, %d saves", f.n(), len(s.saved))
			}
		})
	}
	// the ErrStop text tells the operator to re-enrol, with no token
	if !strings.Contains(token.ErrStop.Error(), "enrol") {
		t.Errorf("ErrStop text %q does not mention re-enrolment", token.ErrStop)
	}
}

// CHK-M4-156: a token past expires_at is still sent; its 401 stops.
func TestRotationExpiredTokenStillSent(t *testing.T) {
	cur := tokenWithTTL(tok('A'), t0, 365*day)
	f, _, _, r := setup(t, cur)
	f.answer = func(int, transport.Request) (int, string, time.Duration, []byte, error) {
		return 401, "token_expired", 0, nil, nil
	}
	late := t0.Add(400 * day) // 35 days after expires_at
	if err := r.MaybeRotate(context.Background(), late); !errors.Is(err, token.ErrStop) {
		t.Fatalf("expired token: %v", err)
	}
	if toks := f.tokens(); len(toks) != 1 || toks[0] != string(tok('A')) {
		t.Fatal("the expired token was not sent")
	}
}

// CHK-M4-157: the token never in a body, an error or printed output.
func TestRotationNoTokenInOutput(t *testing.T) {
	cur := tokenWithTTL(canary, t0, 365*day)
	h := token.NewHolder(cur)
	for _, verb := range []string{"%v", "%+v", "%#v", "%s"} {
		if out := fmt.Sprintf(verb, h.Current()); strings.Contains(out, "CANARY") {
			t.Errorf("%s of the holder's token prints it: %s", verb, out)
		}
	}
	answers := []func(int, transport.Request) (int, string, time.Duration, []byte, error){
		func(int, transport.Request) (int, string, time.Duration, []byte, error) {
			return 0, "", 0, nil, errors.New("connection refused")
		},
		func(int, transport.Request) (int, string, time.Duration, []byte, error) {
			return 503, "about:blank", 0, nil, nil
		},
		func(int, transport.Request) (int, string, time.Duration, []byte, error) {
			return 409, "about:blank", 0, nil, nil
		},
		func(int, transport.Request) (int, string, time.Duration, []byte, error) {
			return 422, "about:blank", 0, nil, nil
		},
		func(int, transport.Request) (int, string, time.Duration, []byte, error) {
			return 200, "", 0, []byte(`{"agent_token":"bsa_CANARYbad","issued_at":"x","expires_at":"y"}`), nil
		},
		func(int, transport.Request) (int, string, time.Duration, []byte, error) {
			return 401, "token_revoked", 0, nil, nil
		},
	}
	for i, a := range answers {
		f, _, _, r := setup(t, cur)
		f.answer = a
		err := r.MaybeRotate(context.Background(), t0.Add(340*day))
		if err == nil {
			t.Fatalf("answer %d: no error", i)
		}
		if strings.Contains(err.Error(), "CANARY") {
			t.Errorf("answer %d: error holds a token: %v", i, err)
		}
		if b := f.calls[0].req.Body; strings.Contains(string(b), "bsa_") {
			t.Errorf("answer %d: token in the request body", i)
		}
	}
}

// Drop answers (3xx, 400, 403 other, 404, 409, 413, 422, 418 …) keep the old
// token and wait 24 h before the next rotate attempt (user ruling 2026-10-25,
// TASK-099 r1): no call at +5 min, +23 h or +24 h − 1 s; one call with the old
// token at +24 h and later.
func TestRotationOtherAnswersKeepOldToken(t *testing.T) {
	cur := tokenWithTTL(tok('A'), t0, 365*day)
	open := t0.Add(335 * day)
	for _, tc := range []struct {
		st  int
		typ string
	}{{301, "about:blank"}, {302, "about:blank"}, {400, "invalid_request"}, {403, "machine_id_mismatch"}, {404, "about:blank"}, {409, "about:blank"}, {413, "too_large"}, {418, "about:blank"}, {422, "about:blank"}} {
		t.Run(fmt.Sprint(tc.st), func(t *testing.T) {
			f, s, h, r := setup(t, cur)
			f.answer = func(n int, _ transport.Request) (int, string, time.Duration, []byte, error) {
				if n == 1 {
					return tc.st, tc.typ, 0, nil, nil
				}
				return 200, "", 0, rotateBody(t, tok('B'), open.Add(day), 365*day), nil
			}
			if err := r.MaybeRotate(context.Background(), open); err == nil || errors.Is(err, token.ErrStop) {
				t.Fatalf("%d: %v", tc.st, err)
			}
			if len(s.saved) != 0 || h.Current().Value != tok('A') {
				t.Fatalf("%d: token changed", tc.st)
			}
			for _, d := range []time.Duration{5 * time.Minute, time.Hour, 23 * time.Hour, day - time.Second} {
				if err := r.MaybeRotate(context.Background(), open.Add(d)); err != nil || f.n() != 1 {
					t.Fatalf("%d at +%v: err %v, %d calls (want none within 24 h)", tc.st, d, err, f.n())
				}
			}
			if err := r.MaybeRotate(context.Background(), open.Add(day)); err != nil || f.n() != 2 {
				t.Fatalf("%d at +24 h: err %v, %d calls (want the second attempt)", tc.st, err, f.n())
			}
			if toks := f.tokens(); toks[1] != string(tok('A')) || h.Current().Value != tok('B') {
				t.Fatalf("%d: the attempt after 24 h did not use the old token", tc.st)
			}
		})
	}
	// Retry answers (5xx, network) and a refused 200 body are still tried at
	// the next heartbeat (not Drop: the lost-answer path)
	for _, st := range []int{500, 503, 0} {
		f, _, _, r := setup(t, cur)
		f.answer = func(n int, _ transport.Request) (int, string, time.Duration, []byte, error) {
			if n == 1 {
				if st == 0 {
					return 0, "", 0, nil, errors.New("connection reset")
				}
				return st, "about:blank", 0, nil, nil
			}
			return 200, "", 0, rotateBody(t, tok('B'), open, 365*day), nil
		}
		_ = r.MaybeRotate(context.Background(), open)
		if err := r.MaybeRotate(context.Background(), open.Add(5*time.Minute)); err != nil || f.n() != 2 {
			t.Fatalf("%d: next heartbeat: err %v, %d calls (want a retry)", st, err, f.n())
		}
	}
}

// The context given to MaybeRotate reaches the call (cancellation).
func TestRotationPassesContext(t *testing.T) {
	cur := tokenWithTTL(tok('A'), t0, 365*day)
	f, _, _, r := setup(t, cur)
	f.answer = func(int, transport.Request) (int, string, time.Duration, []byte, error) {
		return 0, "", 0, nil, context.Canceled
	}
	type key struct{}
	ctx := context.WithValue(context.Background(), key{}, "mine")
	_ = r.MaybeRotate(ctx, t0.Add(335*day))
	if f.calls[0].ctx.Value(key{}) != "mine" {
		t.Fatal("the caller's context was not passed to the call")
	}
}
