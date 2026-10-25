package inventory

// TP-M4-06 (TASK-091; REQ-102; TS §3.4 L239, #80, lead ruling 2026-10-24 on
// IN_Q_OVERFLOW). Real inotify on a temporary directory; the debounce runs on
// a fake clock. Expected values come from #80, not from the code:
//   - a change (IN_MOVED_TO or IN_CLOSE_WRITE on the name "status") starts a
//     60 s quiet period, restarted by each further change;
//   - when quiet, signal if at least 10 min 30 s have passed since the previous
//     signal (none before: at once), otherwise when that hold-off ends;
//   - one signal per burst, a change during the hold-off is never lost, two
//     signals are never less than 10 min 30 s apart;
//   - other names cause nothing; a watch that cannot be set is an error.
//
// Synchronisation without sleeps on the debounce: the fake clock reports every
// After(d) call, so each change taken by the debouncer is observed with the
// exact deadline it computed. Readiness of the watch is read from
// /proc/self/fdinfo (the kernel's own record of the inotify watch and mask).

import (
	"bufio"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"
)

const (
	wtQuiet   = 60 * time.Second                // #80
	wtHoldOff = 10*time.Minute + 30*time.Second // #80: 10 min + 30 s margin
	wtWait    = 3 * time.Second                 // real-time bound for an expected event
	wtNone    = 250 * time.Millisecond          // real-time window for "nothing happens"
	inMovedTo = 0x80                            // IN_MOVED_TO
	inClose   = 0x08                            // IN_CLOSE_WRITE
)

// ---- fake clock ---------------------------------------------------------

type wtTimer struct {
	at time.Time
	ch chan time.Time
}

type wtClock struct {
	mu     sync.Mutex
	now    time.Time
	timers []wtTimer
	afters chan time.Duration // one value per After call
	nows   chan struct{}      // one value per Now call
}

func newWTClock() *wtClock {
	return &wtClock{
		now:    time.Date(2026, 10, 24, 12, 0, 0, 0, time.UTC),
		afters: make(chan time.Duration, 1<<16),
		nows:   make(chan struct{}, 1<<16),
	}
}

func (c *wtClock) Now() time.Time {
	c.mu.Lock()
	n := c.now
	c.mu.Unlock()
	select {
	case c.nows <- struct{}{}:
	default:
	}
	return n
}

func (c *wtClock) After(d time.Duration) <-chan time.Time {
	ch := make(chan time.Time, 1)
	c.mu.Lock()
	if d <= 0 {
		ch <- c.now
	} else {
		c.timers = append(c.timers, wtTimer{at: c.now.Add(d), ch: ch})
	}
	c.mu.Unlock()
	c.afters <- d
	return ch
}

func (c *wtClock) advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.now = c.now.Add(d)
	keep := c.timers[:0]
	for _, t := range c.timers {
		if !t.at.After(c.now) {
			t.ch <- c.now
		} else {
			keep = append(keep, t)
		}
	}
	c.timers = keep
}

func (c *wtClock) current() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}

func (c *wtClock) drainNows() {
	for {
		select {
		case <-c.nows:
		default:
			return
		}
	}
}

// ---- harness ------------------------------------------------------------

type wtRun struct {
	t        *testing.T
	dir      string
	clk      *wtClock
	out      chan struct{}
	done     chan error
	cancel   context.CancelFunc
	start    time.Time
	finished bool
	signals  []time.Duration // fake time since start of each received signal
	n        int
}

func wtStartIn(t *testing.T, dir string) *wtRun {
	t.Helper()
	clk := newWTClock()
	ctx, cancel := context.WithCancel(context.Background())
	r := &wtRun{t: t, dir: dir, clk: clk, out: make(chan struct{}), done: make(chan error, 1), cancel: cancel, start: clk.current()}
	go func() { r.done <- NewWatcher(dir, clk).Run(ctx, r.out) }()
	t.Cleanup(func() {
		cancel()
		if !r.finished {
			select {
			case <-r.done:
			case <-time.After(5 * time.Second):
				t.Error("Run did not return within 5 s after its context was cancelled")
			}
		}
	})
	return r
}

// wtStart starts a watcher on a fresh directory holding a status file and
// returns once the kernel shows the watch; it checks the watch mask.
func wtStart(t *testing.T) *wtRun {
	t.Helper()
	dir := t.TempDir()
	wtWrite(t, filepath.Join(dir, "status"), "Package: base-files\n")
	r := wtStartIn(t, dir)
	mask := wtWatchMask(t, dir, true)
	if mask&(inMovedTo|inClose) != inMovedTo|inClose {
		t.Fatalf("inotify watch mask %#x lacks IN_MOVED_TO|IN_CLOSE_WRITE (%#x)", mask, inMovedTo|inClose)
	}
	return r
}

func (r *wtRun) wait(timeout time.Duration) (error, bool) {
	select {
	case err := <-r.done:
		r.finished = true
		return err, true
	case <-time.After(timeout):
		return nil, false
	}
}

func (r *wtRun) elapsed() time.Duration { return r.clk.current().Sub(r.start) }

func (r *wtRun) expectAfter(want time.Duration, what string) {
	r.t.Helper()
	select {
	case d := <-r.clk.afters:
		if d != want {
			r.t.Fatalf("%s at t=%v: debouncer deadline in %v, want %v (#80)", what, r.elapsed(), d, want)
		}
	case <-time.After(wtWait):
		r.t.Fatalf("%s at t=%v: the debouncer took no change within %v (no After call)", what, r.elapsed(), wtWait)
	}
}

func (r *wtRun) noAfter(what string) {
	r.t.Helper()
	select {
	case d := <-r.clk.afters:
		r.t.Fatalf("%s at t=%v: the debouncer took a change (After(%v)); want nothing (REQ-102 (5))", what, r.elapsed(), d)
	case <-time.After(wtNone):
	}
}

func (r *wtRun) noSignal(what string) {
	r.t.Helper()
	select {
	case <-r.out:
		r.t.Fatalf("%s: unexpected signal at t=%v", what, r.elapsed())
	case <-time.After(wtNone):
	}
}

func (r *wtRun) recv(what string) {
	r.t.Helper()
	select {
	case <-r.out:
		r.signals = append(r.signals, r.elapsed())
	case <-time.After(wtWait):
		r.t.Fatalf("%s: no signal within %v real time (fake t=%v)", what, wtWait, r.elapsed())
	}
	// let the debouncer read the clock after the send (its record of the
	// signal time) before the test moves the clock again; not an assertion
	select {
	case <-r.clk.nows:
	case <-time.After(time.Second):
	}
}

// fire advances the clock by d and expects exactly the signal that makes due.
func (r *wtRun) fire(d time.Duration, what string) {
	r.t.Helper()
	r.clk.drainNows()
	r.clk.advance(d)
	r.recv(what)
}

func (r *wtRun) rename() { // as dpkg: write status-new, keep status-old, rename onto status
	r.t.Helper()
	r.n++
	p := filepath.Join(r.dir, "status")
	wtWrite(r.t, p+"-new", fmt.Sprintf("Package: p%d\n", r.n))
	_ = os.Remove(p + "-old")
	if err := os.Link(p, p+"-old"); err != nil && !errors.Is(err, os.ErrNotExist) {
		r.t.Fatal(err)
	}
	if err := os.Rename(p+"-new", p); err != nil {
		r.t.Fatal(err)
	}
}

func (r *wtRun) closeWrite() {
	r.t.Helper()
	r.n++
	f, err := os.OpenFile(filepath.Join(r.dir, "status"), os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o600)
	if err != nil {
		r.t.Fatal(err)
	}
	if _, err := fmt.Fprintf(f, "Package: q%d\n", r.n); err != nil {
		r.t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		r.t.Fatal(err)
	}
}

func wtWrite(t *testing.T, path, s string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(s), 0o600); err != nil {
		t.Fatal(err)
	}
}

// wtWatchMask returns the mask of this process's inotify watch on dir, read
// from /proc/self/fdinfo; with wait it polls until the watch exists.
func wtWatchMask(t *testing.T, dir string, wait bool) uint64 {
	t.Helper()
	var st syscall.Stat_t
	if err := syscall.Stat(dir, &st); err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(wtWait)
	for {
		if m, ok := wtFindWatch(st.Ino); ok {
			return m
		}
		if !wait {
			return 0
		}
		if time.Now().After(deadline) {
			t.Fatalf("no inotify watch on %s appeared within %v", dir, wtWait)
		}
		time.Sleep(5 * time.Millisecond)
	}
}

func wtFindWatch(ino uint64) (uint64, bool) {
	fds, _ := os.ReadDir("/proc/self/fd")
	for _, e := range fds {
		if l, err := os.Readlink("/proc/self/fd/" + e.Name()); err != nil || l != "anon_inode:inotify" {
			continue
		}
		f, err := os.Open("/proc/self/fdinfo/" + e.Name())
		if err != nil {
			continue
		}
		sc := bufio.NewScanner(f)
		for sc.Scan() {
			var wd, sdev, mask uint64
			var gotIno uint64
			if _, err := fmt.Sscanf(sc.Text(), "inotify wd:%x ino:%x sdev:%x mask:%x", &wd, &gotIno, &sdev, &mask); err == nil && gotIno == ino {
				_ = f.Close()
				return mask, true
			}
		}
		_ = f.Close()
	}
	return 0, false
}

func wtFDCount(t *testing.T) int {
	t.Helper()
	fds, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		t.Fatal(err)
	}
	return len(fds)
}

// ---- CHK-M4-060 / -061: one change, one signal after 60 s of quiet --------

func TestWatchRenameOntoStatusSignalsOnceAfterQuiet(t *testing.T) { // CHK-M4-060
	r := wtStart(t)
	r.rename()
	r.expectAfter(wtQuiet, "rename onto status")
	r.clk.advance(59 * time.Second)
	r.noSignal("59 s after the rename")
	r.fire(time.Second, "60 s after the rename")
	if r.signals[0] != wtQuiet {
		t.Fatalf("signal at t=%v, want %v", r.signals[0], wtQuiet)
	}
	r.clk.advance(2 * time.Hour)
	r.noSignal("2 h later, no further change")
	r.noAfter("2 h later, no further change")
}

func TestWatchCloseWriteSignalsOnceAfterQuiet(t *testing.T) { // CHK-M4-061
	r := wtStart(t)
	r.closeWrite()
	r.expectAfter(wtQuiet, "write and close of status")
	r.clk.advance(59 * time.Second)
	r.noSignal("59 s after the close")
	r.fire(time.Second, "60 s after the close")
	r.clk.advance(2 * time.Hour)
	r.noSignal("2 h later")

	// IN_MODIFY without a close is not a change; the close is.
	f, err := os.OpenFile(filepath.Join(r.dir, "status"), os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.WriteString("Package: half-written\n"); err != nil {
		t.Fatal(err)
	}
	r.noAfter("status written but still open (IN_MODIFY only)")
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	r.expectAfter(wtQuiet, "close after the write (hold-off long past)")
}

// ---- CHK-M4-062: storms, hold-off, whole timeline ------------------------

func TestWatchStormFromIdleSignalsOnce(t *testing.T) { // CHK-M4-062 (a)
	r := wtStart(t)
	for i := 0; i < 50; i++ {
		if i > 0 {
			r.clk.advance(12 * time.Second)
		}
		if i%2 == 0 {
			r.rename()
		} else {
			r.closeWrite()
		}
		r.expectAfter(wtQuiet, fmt.Sprintf("storm change %d", i+1))
	}
	// last change at 588 s; 50 changes within 10 minutes
	r.clk.advance(59 * time.Second)
	r.noSignal("59 s after the last storm change")
	r.fire(time.Second, "60 s after the last storm change")
	if want := 588*time.Second + wtQuiet; r.signals[0] != want {
		t.Fatalf("storm signal at t=%v, want %v", r.signals[0], want)
	}
	r.clk.advance(3 * time.Hour)
	r.noSignal("3 h after the storm")
	if len(r.signals) != 1 {
		t.Fatalf("%d signals for one storm, want 1", len(r.signals))
	}
}

func TestWatchStormAfterSignalSignalsOncePlusOnceAfterHoldOff(t *testing.T) { // CHK-M4-062 (b), TASK-091 acceptance
	r := wtStart(t)
	r.closeWrite()
	r.expectAfter(wtQuiet, "first change")
	r.fire(wtQuiet, "first signal") // S1 at 60 s
	s1 := r.signals[0]
	for i := 1; i <= 50; i++ { // changes at 72 .. 660 s
		r.clk.advance(12 * time.Second)
		now := r.elapsed()
		if i%2 == 0 {
			r.rename()
		} else {
			r.closeWrite()
		}
		at := max(now+wtQuiet, s1+wtHoldOff)
		r.expectAfter(at-now, fmt.Sprintf("storm change %d at %v", i, now))
	}
	r.noSignal("during the storm (hold-off ended at 690 s, quiet not reached)")
	r.clk.advance(59 * time.Second)
	r.noSignal("59 s after the last storm change")
	r.fire(time.Second, "end of quiet after the storm")
	if want := 660*time.Second + wtQuiet; r.signals[1] != want {
		t.Fatalf("second signal at t=%v, want %v", r.signals[1], want)
	}
	if gap := r.signals[1] - r.signals[0]; gap < wtHoldOff {
		t.Fatalf("signals %v apart, want at least %v", gap, wtHoldOff)
	}
	r.clk.advance(3 * time.Hour)
	r.noSignal("3 h later")
	if len(r.signals) != 2 {
		t.Fatalf("%d signals, want 2 (one, then one after the hold-off)", len(r.signals))
	}
}

func TestWatchChangeDuringHoldOffSignalsWhenItEnds(t *testing.T) { // CHK-M4-062 (c)
	r := wtStart(t)
	r.rename()
	r.expectAfter(wtQuiet, "first change")
	r.fire(wtQuiet, "first signal") // 60 s
	r.clk.advance(60 * time.Second) // 120 s, inside the hold-off
	r.closeWrite()
	r.expectAfter(60*time.Second+wtHoldOff-120*time.Second, "change at 120 s (inside the hold-off)") // 570 s
	r.clk.advance(569 * time.Second)
	r.noSignal("1 s before the hold-off ends")
	r.fire(time.Second, "hold-off end")
	if r.signals[1] != 60*time.Second+wtHoldOff {
		t.Fatalf("signal at t=%v, want %v (hold-off end)", r.signals[1], 60*time.Second+wtHoldOff)
	}
	// a change at the instant of a signal waits a whole hold-off
	r.rename()
	r.expectAfter(wtHoldOff, "change right after the second signal")
	r.clk.advance(wtHoldOff - time.Second)
	r.noSignal("1 s before the third signal")
	r.fire(time.Second, "third signal")
	if gap := r.signals[2] - r.signals[1]; gap != wtHoldOff {
		t.Fatalf("third signal %v after the second, want %v", gap, wtHoldOff)
	}
}

// A receiver that is slow to take a signal loses neither the signal nor the
// changes made meanwhile, and the hold-off counts from the delivery.
func TestWatchSlowReceiverNothingLostHoldOffFromDelivery(t *testing.T) { // CHK-M4-062 (e)
	r := wtStart(t)
	r.rename()
	r.expectAfter(wtQuiet, "first change")
	r.clk.drainNows()
	r.clk.advance(wtQuiet) // due now; nobody reads yet
	// let the debouncer wake and block on the send before the clock moves on,
	// so a signal time taken before the send would be 60 s, not 6 min
	time.Sleep(wtNone)
	r.clk.advance(5 * time.Minute)
	r.closeWrite()
	r.rename()
	time.Sleep(wtNone) // the watcher's reader takes both events meanwhile
	r.recv("delayed delivery 5 min after due")
	if r.signals[0] != wtQuiet+5*time.Minute {
		t.Fatalf("delivered at t=%v, want %v", r.signals[0], wtQuiet+5*time.Minute)
	}
	r.expectAfter(wtHoldOff, "changes made while the signal waited (hold-off from the delivery)")
	r.noAfter("the two waiting changes are one pending change")
	r.clk.advance(wtHoldOff - time.Second)
	r.noSignal("1 s before the hold-off from delivery ends")
	r.fire(time.Second, "signal for the changes made while waiting")
	if gap := r.signals[1] - r.signals[0]; gap != wtHoldOff {
		t.Fatalf("gap %v, want %v", gap, wtHoldOff)
	}
}

// Model test: a seeded random timeline of changes and clock moves is checked
// against an independent #80 model, signal by signal and deadline by deadline.
func TestWatchTimelineAgainstModel(t *testing.T) { // CHK-M4-062 (d)
	for _, seed := range []uint64{1, 2, 3, 20261024} {
		t.Run(fmt.Sprintf("seed_%d", seed), func(t *testing.T) {
			rng := &wtRNG{s: seed}
			r := wtStart(t)
			var (
				pending          bool
				fireAt, lastSig  time.Duration
				hasLast          bool
				changes, signals []time.Duration
			)
			advance := func(d time.Duration) {
				now := r.elapsed()
				if pending && fireAt <= now+d {
					r.fire(fireAt-now, fmt.Sprintf("model signal due at %v", fireAt))
					if got := r.signals[len(r.signals)-1]; got != fireAt {
						t.Fatalf("signal at %v, model %v", got, fireAt)
					}
					signals = append(signals, fireAt)
					lastSig, hasLast, pending = fireAt, true, false
					r.clk.advance(now + d - fireAt)
					return
				}
				r.clk.advance(d)
			}
			for step := 0; step < 120; step++ {
				if rng.IntN(10) < 6 {
					now := r.elapsed()
					if rng.IntN(2) == 0 {
						r.rename()
					} else {
						r.closeWrite()
					}
					pending = true
					fireAt = now + wtQuiet
					if hasLast && lastSig+wtHoldOff > fireAt {
						fireAt = lastSig + wtHoldOff
					}
					r.expectAfter(fireAt-now, fmt.Sprintf("step %d change", step))
					changes = append(changes, now)
				}
				var d time.Duration
				switch rng.IntN(4) {
				case 0:
					d = time.Duration(1+rng.IntN(59)) * time.Second
				case 1:
					d = time.Duration(55+rng.IntN(10)) * time.Second
				case 2:
					d = time.Duration(100+rng.IntN(800)) * time.Second
				default:
					d = time.Duration(1+rng.IntN(15)) * time.Second
				}
				advance(d)
			}
			advance(2 * time.Hour)
			r.noSignal("after the timeline")
			for i := 1; i < len(signals); i++ {
				if signals[i]-signals[i-1] < wtHoldOff {
					t.Fatalf("signals %d and %d only %v apart", i-1, i, signals[i]-signals[i-1])
				}
			}
			if len(changes) > 0 {
				if len(signals) == 0 || signals[len(signals)-1] < changes[len(changes)-1]+wtQuiet {
					t.Fatalf("last change at %v not followed by a signal (signals %v)", changes[len(changes)-1], signals)
				}
			}
			t.Logf("seed %d: %d changes, %d signals", seed, len(changes), len(signals))
		})
	}
}

// ---- CHK-M4-063: other names and other events cause nothing --------------

func TestWatchOtherNamesAndEventsCauseNothing(t *testing.T) { // CHK-M4-063
	r := wtStart(t)
	d := r.dir
	p := func(n string) string { return filepath.Join(d, n) }
	for _, n := range []string{"status-old", "status-new", "available", "lock", "status.tmp", "Status", "STATUS", "status2", ".status", "statu", "status~", "status ", "xstatus", "lock-frontend", "diversions"} {
		wtWrite(t, p(n), "x\n")
		r.noAfter("write and close of " + strconv.Quote(n))
	}
	wtWrite(t, p("avail-new"), "x\n")
	r.noAfter("avail-new written")
	if err := os.Rename(p("avail-new"), p("available")); err != nil {
		t.Fatal(err)
	}
	r.noAfter("rename onto available")
	if err := os.Rename(p("status.tmp"), p("status-old")); err != nil {
		t.Fatal(err)
	}
	r.noAfter("rename onto status-old")
	if err := os.MkdirAll(p("info"), 0o700); err != nil {
		t.Fatal(err)
	}
	r.noAfter("mkdir info")
	wtWrite(t, p("info/foo.list"), "/usr/bin/foo\n")
	wtWrite(t, p("info/status"), "x\n")
	if err := os.Rename(p("info/status"), p("info/status2")); err != nil {
		t.Fatal(err)
	}
	r.noAfter("writes and a rename inside info/ (also a file named status there)")
	f, err := os.Open(p("status"))
	if err != nil {
		t.Fatal(err)
	}
	buf := make([]byte, 8)
	_, _ = f.Read(buf)
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	r.noAfter("status opened read-only and closed (IN_CLOSE_NOWRITE)")
	if err := os.Chmod(p("status"), 0o400); err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	if err := os.Chtimes(p("status"), now, now); err != nil {
		t.Fatal(err)
	}
	r.noAfter("chmod and utime on status (IN_ATTRIB)")
	if err := os.Remove(p("status-old")); err != nil {
		t.Fatal(err)
	}
	r.noAfter("unlink status-old")
	if err := os.Rename(p("status"), p("status-moved")); err != nil {
		t.Fatal(err)
	}
	r.noAfter("status renamed away (IN_MOVED_FROM status)")
	if err := os.Remove(p("status-moved")); err != nil {
		t.Fatal(err)
	}
	r.noAfter("unlink")
	r.clk.advance(2 * time.Hour)
	r.noSignal("2 h after the other-name events")
	// positive control on the same watcher: the watch is alive
	r.closeWrite() // creates status again
	r.expectAfter(wtQuiet, "status written again (positive control)")
}

// ---- CHK-M4-064: a watch that cannot be set, or that fails --------------

func TestWatchSetFailuresReturnError(t *testing.T) { // CHK-M4-064
	run := func(t *testing.T, dir string) error {
		t.Helper()
		r := wtStartIn(t, dir)
		err, ok := r.wait(time.Second)
		if !ok {
			t.Fatalf("Run(%s) did not return within 1 s; want an error at once", dir)
		}
		if err == nil {
			t.Fatalf("Run(%s) returned nil; want an error the caller can log", dir)
		}
		select {
		case <-r.out:
			t.Fatal("signal sent by a watcher that could not be set")
		default:
		}
		return err
	}
	t.Run("missing_directory", func(t *testing.T) {
		err := run(t, filepath.Join(t.TempDir(), "missing"))
		if !errors.Is(err, syscall.ENOENT) {
			t.Fatalf("error %q does not wrap ENOENT", err)
		}
	})
	t.Run("regular_file_instead_of_directory", func(t *testing.T) {
		f := filepath.Join(t.TempDir(), "dpkg")
		wtWrite(t, f, "not a directory\n")
		_ = run(t, f)
	})
	t.Run("injected_inotify_limit", func(t *testing.T) {
		limit := errors.New("inotify_add_watch: no space left on device (max_user_watches)")
		saved := openWatch
		openWatch = func(string) (dirWatch, error) { return nil, fmt.Errorf("inventory: watch: %w", limit) }
		t.Cleanup(func() { openWatch = saved })
		err := run(t, t.TempDir())
		if !errors.Is(err, limit) {
			t.Fatalf("error %q does not wrap the watch error", err)
		}
	})
}

// As a non-root user, a directory the user cannot read cannot be watched
// (EACCES). Root bypasses the permission check, so this case runs as the
// unprivileged tester user (W-u) and is skipped by name as root.
func TestWatchPermissionDeniedReturnsError(t *testing.T) { // CHK-M4-064 (W-u)
	if os.Geteuid() == 0 {
		t.Skip("CHK-M4-064 W-u: needs a non-root user; run this test as bstester")
	}
	dir := filepath.Join(t.TempDir(), "dpkg")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(dir, 0); err != nil {
		t.Fatal(err)
	}
	r := wtStartIn(t, dir)
	err, ok := r.wait(time.Second)
	if !ok || err == nil {
		t.Fatalf("Run on an unreadable directory: returned=%v err=%v; want an error at once", ok, err)
	}
	if !errors.Is(err, syscall.EACCES) {
		t.Fatalf("error %q does not wrap EACCES", err)
	}
}

func TestWatchDirectoryRemovedEndsRunWithError(t *testing.T) { // CHK-M4-064 (failure after start)
	r := wtStart(t)
	if err := os.RemoveAll(r.dir); err != nil {
		t.Fatal(err)
	}
	err, ok := r.wait(2 * time.Second)
	if !ok {
		t.Fatal("Run kept running after its directory was removed (watch gone); want an error")
	}
	if err == nil || errors.Is(err, context.Canceled) {
		t.Fatalf("Run returned %v; want a watch error", err)
	}
}

// ---- CHK-M4-065: stops on cancel, no fd or goroutine left -----------------

func TestWatchStopsOnCancelWithoutLeaks(t *testing.T) { // CHK-M4-065
	cases := []struct {
		name  string
		setup func(r *wtRun)
	}{
		{"idle", func(*wtRun) {}},
		{"change_pending", func(r *wtRun) { r.rename(); r.expectAfter(wtQuiet, "pending change") }},
		{"blocked_sending", func(r *wtRun) {
			r.rename()
			r.expectAfter(wtQuiet, "change")
			r.clk.advance(wtQuiet) // due; the receiver never reads
			time.Sleep(wtNone)
		}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			runtime.GC()
			fds, gs := wtFDCount(t), runtime.NumGoroutine()
			r := wtStart(t)
			c.setup(r)
			t0 := time.Now()
			r.cancel()
			err, ok := r.wait(time.Second)
			if !ok {
				t.Fatal("Run did not return within 1 s of cancel")
			}
			if !errors.Is(err, context.Canceled) {
				t.Fatalf("Run returned %v; want context.Canceled", err)
			}
			if el := time.Since(t0); el > time.Second {
				t.Fatalf("Run took %v to stop", el)
			}
			if m := wtWatchMask(t, r.dir, false); m != 0 {
				t.Fatalf("inotify watch on the directory still open after Run returned (mask %#x)", m)
			}
			deadline := time.Now().Add(2 * time.Second)
			for {
				nf, ng := wtFDCount(t), runtime.NumGoroutine()
				if nf <= fds && ng <= gs {
					break
				}
				if time.Now().After(deadline) {
					t.Fatalf("after Run: %d fds (baseline %d), %d goroutines (baseline %d)", nf, fds, ng, gs)
				}
				time.Sleep(10 * time.Millisecond)
			}
		})
	}
}

// ---- CHK-M4-066: constants, injected path and clock -----------------------

func TestWatchConstantsAndInjectedInputs(t *testing.T) { // CHK-M4-066
	if DpkgDir != "/var/lib/dpkg" {
		t.Errorf("DpkgDir = %q, want /var/lib/dpkg (TS §3.4 L239)", DpkgDir)
	}
	if Quiet != wtQuiet {
		t.Errorf("Quiet = %v, want %v (#80)", Quiet, wtQuiet)
	}
	if HoldOff != wtHoldOff {
		t.Errorf("HoldOff = %v, want %v (#80)", HoldOff, wtHoldOff)
	}
	root := wtModuleRoot(t)
	fset := token.NewFileSet()
	err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		f, err := parser.ParseFile(fset, path, nil, 0)
		if err != nil {
			return err
		}
		ast.Inspect(f, func(n ast.Node) bool {
			call, ok := n.(*ast.CallExpr)
			if !ok {
				return true
			}
			name := ""
			switch fn := call.Fun.(type) {
			case *ast.Ident:
				name = fn.Name
			case *ast.SelectorExpr:
				name = fn.Sel.Name
			}
			if name != "NewWatcher" || len(call.Args) == 0 {
				return true
			}
			ok = false
			switch a := call.Args[0].(type) {
			case *ast.Ident:
				ok = a.Name == "DpkgDir"
			case *ast.SelectorExpr:
				ok = a.Sel.Name == "DpkgDir"
			}
			if !ok {
				t.Errorf("%s: NewWatcher's path is not the DpkgDir constant (no path from any other input)", fset.Position(call.Pos()))
			}
			return true
		})
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	// the watcher uses only the injected clock and reads no environment
	for _, name := range []string{"watch.go", "watch_linux.go"} {
		src, err := fs.ReadFile(os.DirFS("."), name)
		if err != nil {
			t.Fatal(err)
		}
		for _, bad := range []string{"time.Now(", "time.After(", "time.Sleep(", "time.NewTimer(", "time.Tick(", "time.NewTicker(", "time.AfterFunc(", "time.Since(", "time.Until(", "os.Getenv(", "os.LookupEnv(", "os.Environ("} {
			if strings.Contains(string(src), bad) {
				t.Errorf("%s uses %s; the watcher must use only the injected clock and no environment", name, bad)
			}
		}
	}
}

func wtModuleRoot(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("go.mod not found")
		}
		dir = parent
	}
}

// ---- CHK-M4-067: event parsing, overflow counts as a change ---------------

// wtEvent builds one inotify_event record (wd as its raw 32-bit pattern, so
// 0xffffffff is -1), with the name NUL-terminated and padded to 16 or 32
// bytes as the kernel does.
func wtEvent(wd, mask uint32, name string) []byte {
	var nb []byte
	var l uint32
	switch {
	case name == "":
	case len(name) < 16:
		l = 16
	case len(name) < 32:
		l = 32
	default:
		panic("wtEvent: name too long for the test helper")
	}
	nb = make([]byte, l)
	copy(nb, name)
	b := make([]byte, syscall.SizeofInotifyEvent, syscall.SizeofInotifyEvent+len(nb))
	binary.NativeEndian.PutUint32(b[0:4], wd)
	binary.NativeEndian.PutUint32(b[4:8], mask)
	binary.NativeEndian.PutUint32(b[8:12], 0)
	binary.NativeEndian.PutUint32(b[12:16], l)
	return append(b, nb...)
}

// wtRNG is a deterministic splitmix64 generator for reproducible timelines
// and byte noise (not a security use).
type wtRNG struct{ s uint64 }

func (r *wtRNG) next() uint64 {
	r.s += 0x9e3779b97f4a7c15
	z := r.s
	z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9
	z = (z ^ (z >> 27)) * 0x94d049bb133111eb
	return z ^ (z >> 31)
}

// IntN returns a value in [0, n) for 0 < n <= 1<<20.
func (r *wtRNG) IntN(n int) int {
	return int(r.next()>>44) % n // 20 random bits fit any int
}

func TestWatchScanEvents(t *testing.T) { // CHK-M4-067 (and the name/mask filter)
	cat := func(bs ...[]byte) []byte {
		var o []byte
		for _, b := range bs {
			o = append(o, b...)
		}
		return o
	}
	cases := []struct {
		name    string
		in      []byte
		changed bool
		err     bool
	}{
		{"overflow", wtEvent(0xffffffff, syscall.IN_Q_OVERFLOW, ""), true, false},
		{"overflow_after_other", cat(wtEvent(1, syscall.IN_CLOSE_WRITE, "lock"), wtEvent(0xffffffff, syscall.IN_Q_OVERFLOW, "")), true, false},
		{"moved_to_status", wtEvent(1, syscall.IN_MOVED_TO, "status"), true, false},
		{"close_write_status", wtEvent(1, syscall.IN_CLOSE_WRITE, "status"), true, false},
		{"status_name_16_padding", wtEvent(1, syscall.IN_CLOSE_WRITE, "status"), true, false},
		{"modify_status", wtEvent(1, syscall.IN_MODIFY, "status"), false, false},
		{"moved_from_status", wtEvent(1, syscall.IN_MOVED_FROM, "status"), false, false},
		{"delete_status", wtEvent(1, syscall.IN_DELETE, "status"), false, false},
		{"create_status", wtEvent(1, syscall.IN_CREATE, "status"), false, false},
		{"attrib_status", wtEvent(1, syscall.IN_ATTRIB, "status"), false, false},
		{"close_nowrite_status", wtEvent(1, syscall.IN_CLOSE_NOWRITE, "status"), false, false},
		{"moved_to_status_old", wtEvent(1, syscall.IN_MOVED_TO, "status-old"), false, false},
		{"close_write_statu", wtEvent(1, syscall.IN_CLOSE_WRITE, "statu"), false, false},
		{"close_write_status_dot", wtEvent(1, syscall.IN_CLOSE_WRITE, "status."), false, false},
		{"close_write_Status", wtEvent(1, syscall.IN_CLOSE_WRITE, "Status"), false, false},
		{"empty_name_close_write", wtEvent(1, syscall.IN_CLOSE_WRITE, ""), false, false},
		{"batch_other_then_status", cat(wtEvent(1, syscall.IN_CLOSE_WRITE, "status-new"), wtEvent(1, syscall.IN_MOVED_TO, "status")), true, false},
		{"batch_only_others", cat(wtEvent(1, syscall.IN_CLOSE_WRITE, "status-new"), wtEvent(1, syscall.IN_MOVED_TO, "available"), wtEvent(1, syscall.IN_MODIFY, "status")), false, false},
		{"ignored", wtEvent(1, syscall.IN_IGNORED, ""), false, true},
		{"truncated_name", wtEvent(1, syscall.IN_CLOSE_WRITE, "status")[:20], false, false},
		{"short_header", wtEvent(1, syscall.IN_CLOSE_WRITE, "status")[:10], false, false},
		{"empty", nil, false, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			changed, err := scanEvents(c.in)
			if changed != c.changed || (err != nil) != c.err {
				t.Fatalf("scanEvents = (%v, %v), want changed=%v err=%v", changed, err, c.changed, c.err)
			}
		})
	}
}

func TestWatchScanEventsHostileBytesNoPanic(t *testing.T) { // CHK-M4-067 (robustness)
	rng := &wtRNG{s: 7}
	for i := 0; i < 20000; i++ {
		b := make([]byte, rng.IntN(200)+8)
		for j := 0; j+8 <= len(b); j += 8 {
			binary.LittleEndian.PutUint64(b[j:j+8], rng.next())
		}
		b = b[:rng.IntN(len(b)+1)]
		if rng.IntN(3) == 0 && len(b) >= 16 { // a huge name length, or one just past the end
			if rng.IntN(2) == 0 {
				binary.NativeEndian.PutUint32(b[12:16], 0xfffffff0)
			} else {
				binary.NativeEndian.PutUint32(b[12:16], 16)
			}
		}
		func() {
			defer func() {
				if p := recover(); p != nil {
					t.Fatalf("scanEvents panicked on %x: %v", b, p)
				}
			}()
			_, _ = scanEvents(b)
		}()
	}
}
