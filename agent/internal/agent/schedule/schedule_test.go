// Tests for the back-off and the jittered loop intervals (TS §3.3 L202–L206,
// L226; REQ-095, REQ-097, REQ-098; tests/m4/test-plan.md TP-M4-05, CHK-M4-050
// to -055; mutation row CHK-M4-338). Expected values come from the spec and the
// lead ruling of 2026-10-24 (back-off jitter ±10 % of 10/20/40/80/160/300 s,
// never above 330 s), not from the implementation.
package schedule_test

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/schedule"
)

// constSource returns the same value every time (u = 0 and u → 1 give the edges).
type constSource float64

func (c constSource) Float64() float64 { return float64(c) }

// seeded is a deterministic Source for the statistical checks (splitmix64,
// so no math/rand in the tests either).
type seeded struct{ x uint64 }

func newSeeded(seed uint64) *seeded { return &seeded{seed} }

func (s *seeded) Float64() float64 {
	s.x += 0x9e3779b97f4a7c15
	z := s.x
	z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9
	z = (z ^ (z >> 27)) * 0x94d049bb133111eb
	z ^= z >> 31
	return float64(z>>11) / (1 << 53)
}

const almostOne = constSource(1 - 1e-12)

var nominal = []time.Duration{10 * time.Second, 20 * time.Second, 40 * time.Second, 80 * time.Second, 160 * time.Second, 300 * time.Second, 300 * time.Second, 300 * time.Second}

func within(d, nom time.Duration) bool {
	lo := time.Duration(float64(nom) * 0.9)
	hi := time.Duration(float64(nom) * 1.1)
	return d >= lo && d <= hi
}

// CHK-M4-050: nominal 10, 20, 40, 80, 160, 300, 300 … s, each within ±10 %;
// never above 330 s, never 0 or negative; the edges are exact.
func TestBackoffSequenceAndBounds(t *testing.T) {
	for _, tc := range []struct {
		name string
		src  schedule.Source
		want []time.Duration // exact, when the source is constant
	}{
		{"u=0.5 gives the nominal steps", constSource(0.5), nominal},
		{"u=0 gives -10 %", constSource(0), []time.Duration{9 * time.Second, 18 * time.Second, 36 * time.Second, 72 * time.Second, 144 * time.Second, 270 * time.Second, 270 * time.Second}},
		{"u->1 gives +10 %", almostOne, nil},
	} {
		t.Run(tc.name, func(t *testing.T) {
			b := schedule.NewBackoff(tc.src)
			for i := range 8 {
				d := b.Next()
				if !within(d, nominal[i]) {
					t.Fatalf("delay %d = %v, want %v ± 10 %%", i+1, d, nominal[i])
				}
				if i < len(tc.want) && tc.want != nil && d != tc.want[i] {
					t.Fatalf("delay %d = %v, want exactly %v", i+1, d, tc.want[i])
				}
			}
		})
	}
	// +10 % edge: just under 11, 22, 44, 88, 176, 330 s
	b := schedule.NewBackoff(almostOne)
	for i, hi := range []time.Duration{11, 22, 44, 88, 176, 330, 330} {
		d := b.Next()
		if d > hi*time.Second || d < hi*time.Second-time.Millisecond {
			t.Errorf("u->1 delay %d = %v, want just under %v", i+1, d, hi*time.Second)
		}
	}
}

// CHK-M4-050 (CHK-M4-338): 100 and 10,000 consecutive failures stay capped,
// with no overflow (no negative, zero or huge delay).
func TestBackoffNeverOverflows(t *testing.T) {
	for _, src := range []schedule.Source{constSource(0), constSource(0.5), almostOne, newSeeded(7)} {
		b := schedule.NewBackoff(src)
		for i := range 10000 {
			d := b.Next()
			if d <= 0 || d > 330*time.Second {
				t.Fatalf("failure %d: delay %v outside (0, 330 s]", i+1, d)
			}
			if i >= 5 && !within(d, 300*time.Second) {
				t.Fatalf("failure %d: delay %v, want 300 s ± 10 %% (cap)", i+1, d)
			}
		}
	}
}

// CHK-M4-050: seeded jitter: every delay inside its bound, and the jitter
// really varies (not a constant factor).
func TestBackoffJitterVaries(t *testing.T) {
	seen := map[time.Duration]bool{}
	for run := range 200 {
		b := schedule.NewBackoff(newSeeded(uint64(run)))
		d := b.Next()
		if !within(d, 10*time.Second) {
			t.Fatalf("first delay %v not 10 s ± 10 %%", d)
		}
		seen[d] = true
	}
	if len(seen) < 150 {
		t.Fatalf("only %d distinct first delays over 200 seeds: jitter missing", len(seen))
	}
}

// CHK-M4-051: one success resets: the next failure is back at 10 s (± 10 %),
// from any step.
func TestBackoffReset(t *testing.T) {
	for steps := 1; steps <= 12; steps++ {
		b := schedule.NewBackoff(constSource(0.5))
		for range steps {
			b.Next()
		}
		b.Reset()
		if d := b.Next(); d != 10*time.Second {
			t.Fatalf("after %d failures and a reset: %v, want 10 s", steps, d)
		}
		if d := b.Next(); d != 20*time.Second {
			t.Fatalf("after reset, second failure: %v, want 20 s", d)
		}
	}
	// a reset before any failure is harmless
	b := schedule.NewBackoff(constSource(0.5))
	b.Reset()
	if d := b.Next(); d != 10*time.Second {
		t.Fatalf("reset on a fresh back-off: %v", d)
	}
}

// CHK-M4-052: 1,000 heartbeat intervals in [270 s, 330 s]; both ends reached
// (min < 276 s, max > 324 s), mean 300 ± 3 s; two seeds differ.
func TestHeartbeatIntervalUniform(t *testing.T) {
	draw := func(seed uint64) []time.Duration {
		src := newSeeded(seed)
		out := make([]time.Duration, 1000)
		for i := range out {
			out[i] = schedule.HeartbeatInterval(src)
		}
		return out
	}
	a := draw(1)
	lo, hi, sum := a[0], a[0], time.Duration(0)
	for _, d := range a {
		if d < 270*time.Second || d > 330*time.Second {
			t.Fatalf("heartbeat interval %v outside 270..330 s", d)
		}
		lo, hi, sum = min(lo, d), max(hi, d), sum+d
	}
	if lo >= 276*time.Second || hi <= 324*time.Second {
		t.Fatalf("jitter does not span the range: min %v max %v", lo, hi)
	}
	mean := sum / time.Duration(len(a))
	if mean < 297*time.Second || mean > 303*time.Second {
		t.Fatalf("mean %v, want 300 ± 3 s", mean)
	}
	b := draw(2)
	same := 0
	for i := range a {
		if a[i] == b[i] {
			same++
		}
	}
	if same > 10 {
		t.Fatalf("two seeds give %d equal intervals out of 1000", same)
	}
	// edges with constant sources
	if d := schedule.HeartbeatInterval(constSource(0)); d != 270*time.Second {
		t.Errorf("u=0: %v, want 270 s", d)
	}
	if d := schedule.HeartbeatInterval(almostOne); d > 330*time.Second || d < 330*time.Second-time.Millisecond {
		t.Errorf("u->1: %v, want just under 330 s", d)
	}
	if schedule.Heartbeat != 300*time.Second || schedule.Jitter != 30*time.Second {
		t.Errorf("constants: heartbeat %v jitter %v", schedule.Heartbeat, schedule.Jitter)
	}
}

// CHK-M4-053: pull interval p ± 30 s for p = 60, 300, 3,600, and the clamp
// 60..3,600 at both ends (0, −5, 59 → 60; 3,601, 10^9 → 3,600).
func TestPullIntervalAndClamp(t *testing.T) {
	cases := map[int]int{60: 60, 300: 300, 3600: 3600, 59: 60, 0: 60, -5: 60, -1 << 40: 60, 3601: 3600, 1_000_000_000: 3600, 61: 61, 3599: 3599}
	for in, want := range cases {
		if got := schedule.ClampPull(in); got != want {
			t.Errorf("ClampPull(%d) = %d, want %d", in, got, want)
		}
		p := time.Duration(want) * time.Second
		src := newSeeded(uint64(in & 0xffff))
		var lo, hi time.Duration = 1 << 62, 0
		for range 1000 {
			d := schedule.PullInterval(in, src)
			if d < p-30*time.Second || d > p+30*time.Second {
				t.Fatalf("PullInterval(%d) = %v, want %v ± 30 s", in, d, p)
			}
			lo, hi = min(lo, d), max(hi, d)
		}
		if lo > p-24*time.Second || hi < p+24*time.Second {
			t.Errorf("PullInterval(%d): jitter does not span: %v..%v", in, lo, hi)
		}
		if d := schedule.PullInterval(in, constSource(0)); d != p-30*time.Second {
			t.Errorf("PullInterval(%d, u=0) = %v, want %v", in, d, p-30*time.Second)
		}
	}
	if schedule.PullMin != 60 || schedule.PullMax != 3600 {
		t.Errorf("PullMin %d PullMax %d", schedule.PullMin, schedule.PullMax)
	}
}

// fakeClock fires After only when the test advances it.
type fakeClock struct {
	mu      sync.Mutex
	now     time.Time
	waiters []waiter
}

type waiter struct {
	at time.Time
	ch chan time.Time
}

func (c *fakeClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}

func (c *fakeClock) After(d time.Duration) <-chan time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	ch := make(chan time.Time, 1)
	c.waiters = append(c.waiters, waiter{c.now.Add(d), ch})
	return ch
}

func (c *fakeClock) advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.now = c.now.Add(d)
	kept := c.waiters[:0]
	for _, w := range c.waiters {
		if !w.at.After(c.now) {
			w.ch <- c.now
		} else {
			kept = append(kept, w)
		}
	}
	c.waiters = kept
}

// CHK-M4-054, -055: Sleep waits on the injected clock only, and returns
// ctx's error promptly when the context is cancelled.
func TestSleepUsesClockAndContext(t *testing.T) {
	start := time.Now()
	c := &fakeClock{now: time.Date(2026, 10, 24, 0, 0, 0, 0, time.UTC)}
	done := make(chan error, 1)
	go func() { done <- schedule.Sleep(context.Background(), c, 300*time.Second) }()
	waitFor(t, func() bool { return c.pending() == 1 })
	select {
	case err := <-done:
		t.Fatalf("Sleep returned before the clock moved: %v", err)
	case <-time.After(50 * time.Millisecond):
	}
	c.advance(299 * time.Second)
	select {
	case err := <-done:
		t.Fatalf("Sleep returned at 299 s: %v", err)
	case <-time.After(20 * time.Millisecond):
	}
	c.advance(time.Second)
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Sleep: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Sleep did not return after the clock reached 300 s")
	}

	ctx, cancel := context.WithCancel(context.Background())
	go func() { done <- schedule.Sleep(ctx, c, 300*time.Second) }()
	time.Sleep(20 * time.Millisecond)
	t0 := time.Now()
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("cancelled Sleep returned %v, want context.Canceled", err)
		}
		if el := time.Since(t0); el > 100*time.Millisecond {
			t.Fatalf("cancelled Sleep took %v", el)
		}
	case <-time.After(time.Second):
		t.Fatal("Sleep ignored the context")
	}
	// an already-cancelled context returns at once even with a zero wait pending
	if err := schedule.Sleep(ctx, c, time.Hour); !errors.Is(err, context.Canceled) {
		t.Fatalf("Sleep on a done context: %v", err)
	}
	if el := time.Since(start); el > 3*time.Second {
		t.Fatalf("fake-clock test needed %v of real time", el)
	}
}

func (c *fakeClock) pending() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return len(c.waiters)
}

func waitFor(t *testing.T, cond func() bool) {
	t.Helper()
	for range 200 {
		if cond() {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("condition not reached")
}

// CHK-M4-054: no wall-clock or global-randomness call in non-test schedule
// code other than RealClock's two methods.
func TestNoWallClockInSchedule(t *testing.T) {
	files, err := filepath.Glob("*.go")
	if err != nil {
		t.Fatal(err)
	}
	banned := regexp.MustCompile(`time\.(Sleep|Tick|NewTimer|NewTicker|AfterFunc|Since|Until)\(|math/rand|"math/rand/v2"`)
	n := 0
	for _, fn := range files {
		if strings.HasSuffix(fn, "_test.go") {
			continue
		}
		n++
		b, err := os.ReadFile(filepath.Clean(fn))
		if err != nil {
			t.Fatal(err)
		}
		for i, line := range strings.Split(string(b), "\n") {
			if banned.MatchString(line) {
				t.Errorf("%s:%d: %s", fn, i+1, strings.TrimSpace(line))
			}
			if (strings.Contains(line, "time.Now()") || strings.Contains(line, "time.After(")) && !strings.HasPrefix(strings.TrimSpace(line), "func (RealClock)") {
				t.Errorf("%s:%d: wall clock outside RealClock: %s", fn, i+1, strings.TrimSpace(line))
			}
		}
	}
	if n == 0 {
		t.Fatal("no non-test source found")
	}
}

// CryptoSource stays in [0, 1).
func TestCryptoSourceRange(t *testing.T) {
	var src schedule.CryptoSource
	distinct := map[float64]bool{}
	for range 10000 {
		u := src.Float64()
		if u < 0 || u >= 1 {
			t.Fatalf("CryptoSource gave %v", u)
		}
		distinct[u] = true
	}
	if len(distinct) < 9990 {
		t.Fatalf("CryptoSource: only %d distinct values in 10,000", len(distinct))
	}
}
