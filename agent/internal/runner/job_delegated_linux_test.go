//go:build linux && delegated

// TP-M10-17 delegated rows (tester-m10c): the job executor (TASK-224 r1)
// through JobExecutor.Run on the real kernel, REQ-239 (6), REQ-240 (1)–(10),
// REQ-241 (3), (5); TS §3.5 L249–L250, §3.7 L284; #135 (c), #136 (f), #138.
// Run in the delegated binary as bitscan-runner (builder checklist 21) with
// PrivateTmp=yes and StateDirectory=m10c-job (see deleg.sh). Harmless
// payloads only: sleep, echo, date, mkdir and writes into the test's own
// delegated cgroup and private /tmp.
package runner

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
)

// mountOf is the delegated cgroup directory that holds supervisor.
func mountOf(c *Cgroups) string { return filepath.Join("/sys/fs/cgroup", c.d.Base) }

// subtreePids lists every pid in the service subtree except this process.
func subtreePids(t *testing.T, c *Cgroups) []int {
	t.Helper()
	var pids []int
	_ = filepath.WalkDir(mountOf(c), func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || d.Name() != "cgroup.procs" {
			return nil //nolint:nilerr // a cgroup removed mid-walk
		}
		b, _ := os.ReadFile(p) //nolint:gosec // cgroupfs
		for _, f := range strings.Fields(string(b)) {
			if pid, _ := strconv.Atoi(f); pid != 0 && pid != os.Getpid() {
				pids = append(pids, pid)
			}
		}
		return nil
	})
	sort.Ints(pids)
	return pids
}

// sleepers lists this uid's processes whose command line holds marker.
func sleepers(marker string) []string {
	var out []string
	ents, _ := os.ReadDir("/proc")
	for _, e := range ents {
		pid, err := strconv.Atoi(e.Name())
		if err != nil || pid == os.Getpid() {
			continue
		}
		var st syscall.Stat_t
		if syscall.Stat("/proc/"+e.Name(), &st) != nil || int(st.Uid) != os.Getuid() {
			continue
		}
		b, _ := os.ReadFile("/proc/" + e.Name() + "/cmdline")
		if cl := strings.ReplaceAll(string(b), "\x00", " "); strings.Contains(cl, marker) {
			out = append(out, e.Name()+": "+cl)
		}
	}
	return out
}

// killLeftovers is the test's own safety net after a failed row.
func killLeftovers(t *testing.T, c *Cgroups) {
	for _, pid := range subtreePids(t, c) {
		_ = syscall.Kill(pid, syscall.SIGKILL)
	}
	_ = c.Sweep(context.Background())
}

func newExec(t *testing.T, tmp []string) (*JobExecutor, *jobLog) {
	t.Helper()
	c := sharedCgroups(t)
	if err := c.Sweep(context.Background()); err != nil { // the start-up sweep (TASK-228 order)
		t.Fatalf("Sweep: %v", err)
	}
	logs := &jobLog{}
	t.Cleanup(func() { killLeftovers(t, c) })
	return &JobExecutor{CG: c, Spawn: Spawn, Now: time.Now, TmpDirs: tmp,
		Log: slog.New(slog.NewJSONHandler(logs, &slog.HandlerOptions{Level: slog.LevelDebug}))}, logs
}

func pid(n int) wire.UUID { return wire.UUID(fmt.Sprintf("eeeeeeee-0000-4000-8000-%012d", n)) }

func jobOf(mpp int, patterns []string, specs ...wire.PluginSpec) proto.Request {
	return proto.Request{V: 1, MaxParallelPlugins: mpp, Job: wire.Job{
		JobID: "dddddddd-0000-4000-8000-000000000224", AgentID: "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b",
		Kind: wire.KindCompliance, PickupBy: wire.NewTime(time.Now().Add(time.Hour)),
		Plugins: specs, RedactionPatterns: patterns,
	}}
}

func plug(n int, execute string, timeout int) wire.PluginSpec {
	return wire.PluginSpec{PluginUUID: pid(n), Execute: execute, TimeoutS: timeout}
}

type emitted struct {
	item wire.ResultItem
	at   time.Duration // since Run started
}

type jobRun struct {
	out     []emitted
	err     error
	elapsed time.Duration
	hung    bool
}

// runJob runs req under ctx. onEmit (optional) runs inside emit, before the
// item is recorded. If Run has not returned after limit the row fails: the
// test kills the subtree by pid and waits for Run to come back.
func runJob(t *testing.T, e *JobExecutor, ctx context.Context, req proto.Request, limit time.Duration, onEmit func(wire.ResultItem)) jobRun {
	t.Helper()
	var mu sync.Mutex
	var r jobRun
	start := time.Now()
	done := make(chan error, 1)
	go func() {
		done <- e.Run(ctx, req, func(res proto.Result) error {
			it := res.Item()
			if onEmit != nil {
				onEmit(it)
			}
			mu.Lock()
			r.out = append(r.out, emitted{it, time.Since(start)})
			mu.Unlock()
			return nil
		})
	}()
	select {
	case r.err = <-done:
	case <-time.After(limit):
		r.hung = true
		t.Errorf("Run did not return within %v: plugins in the subtree %v; killing them by pid", limit, subtreePids(t, e.CG))
		for _, p := range subtreePids(t, e.CG) {
			_ = syscall.Kill(p, syscall.SIGKILL)
		}
		select {
		case r.err = <-done:
		case <-time.After(30 * time.Second):
			t.Fatal("Run still blocked after its plugins were killed")
		}
	}
	r.elapsed = time.Since(start)
	mu.Lock()
	defer mu.Unlock()
	return r
}

func (r jobRun) byID(t *testing.T) map[wire.UUID]wire.ResultItem {
	t.Helper()
	m := map[wire.UUID]wire.ResultItem{}
	for _, e := range r.out {
		if _, dup := m[e.item.PluginUUID]; dup {
			t.Errorf("plugin %s emitted twice", e.item.PluginUUID)
		}
		m[e.item.PluginUUID] = e.item
	}
	return m
}

func exitOf(it wire.ResultItem) string {
	if it.ExitCode == nil {
		return "null"
	}
	return strconv.FormatInt(*it.ExitCode, 10)
}

func assertNothingLeft(t *testing.T, e *JobExecutor, marker string) {
	t.Helper()
	time.Sleep(200 * time.Millisecond)
	if p := subtreePids(t, e.CG); len(p) > 0 {
		t.Errorf("processes left in the subtree after the job: %v (REQ-240)", p)
	}
	if s := sleepers(marker); len(s) > 0 {
		t.Errorf("plugin processes alive after the job: %v", s)
	}
	ents, _ := os.ReadDir(mountOf(e.CG))
	for _, d := range ents {
		if d.IsDir() && d.Name() != "supervisor" && d.Name() != "plugins" {
			t.Errorf("cgroup %s left in the subtree (REQ-238 (4))", d.Name())
		}
	}
	for _, keep := range []string{"supervisor", "plugins"} {
		sub, _ := os.ReadDir(filepath.Join(mountOf(e.CG), keep))
		for _, d := range sub {
			if d.IsDir() {
				t.Errorf("cgroup %s/%s left", keep, d.Name())
			}
		}
	}
	if got := ownCgroupPath(t); !strings.HasSuffix(got, "/supervisor") {
		t.Errorf("runner in %s after the job, want supervisor", got)
	}
}

// CHK-M10-147 (REQ-240 (1)–(6); plants -336, -337, -338, -339): no plugin
// outlives its job. With max_parallel_plugins 1, each plugin whose
// processes stay in its own cgroup must be gone when its result is emitted
// (cgroup.kill at exit); the ones that moved out are left to the after-job
// sweep, so after Run nothing is left anywhere.
func TestDelegatedJobNoSurvivors(t *testing.T) {
	e, _ := newExec(t, []string{t.TempDir()})
	recordIdentity(t)
	m := mountOf(e.CG)
	const mk = "300.147"
	inOwn := []string{
		"sleep " + mk + " &",                              // REQ-240 (1) background child
		"setsid nohup sleep " + mk + " >/dev/null 2>&1 &", // (2) new session
		"(sh -c 'sleep " + mk + " &' &)",                  // (3) double fork
		"trap '' TERM; sleep " + mk,                       // (6) ignores SIGTERM, timeout 2
		`cg=/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup); mkdir $cg/nest && sh -c "echo \$\$ > $cg/nest/cgroup.procs; exec sleep ` + mk + `" >/dev/null 2>&1 &`, // (5) nested under its own p-<n>
	}
	movedOut := []string{
		"sh -c 'echo $$ > " + m + "/supervisor/cgroup.procs; exec sleep " + mk + "' >/dev/null 2>&1 &",                                         // (4) into supervisor
		"mkdir " + m + "/supervisor/evil && sh -c 'echo $$ > " + m + "/supervisor/evil/cgroup.procs; exec sleep " + mk + "' >/dev/null 2>&1 &", // (5) nested under supervisor
		"sh -c 'echo $$ > " + m + "/cgroup.procs; exec sleep " + mk + "' >/dev/null 2>&1 &",                                                    // the service root
	}
	var specs []wire.PluginSpec
	for i, x := range append(append([]string{}, inOwn...), movedOut...) {
		to := 10
		if strings.HasPrefix(x, "trap") {
			to = 2
		}
		specs = append(specs, plug(i+1, x+"\nsleep 0.3", to))
	}
	r := runJob(t, e, context.Background(), jobOf(1, nil, specs...), 60*time.Second, func(it wire.ResultItem) {
		n, _ := strconv.Atoi(string(it.PluginUUID)[len(it.PluginUUID)-3:])
		if n <= len(inOwn) {
			if p := subtreePids(t, e.CG); len(p) > 0 {
				t.Errorf("plugin %d: processes %v still alive when its result is emitted (cgroup.kill at exit, TS §3.5 L250)", n, p)
			}
		}
	})
	if r.err != nil {
		t.Fatalf("Run: %v", r.err)
	}
	got := r.byID(t)
	if len(got) != len(specs) {
		t.Fatalf("%d results, want %d", len(got), len(specs))
	}
	for i, s := range specs {
		it := got[s.PluginUUID]
		want := "0"
		if s.TimeoutS == 2 {
			want = "137"
			if !it.TimedOut {
				t.Errorf("plugin %d: timed_out false", i+1)
			}
		}
		if exitOf(it) != want {
			t.Errorf("plugin %d: exit %s, want %s (stderr %q)", i+1, exitOf(it), want, it.Stderr)
		}
	}
	assertNothingLeft(t, e, mk)
}

// CHK-M10-148 (REQ-240 (7); plant -343): sleep 100 with timeout_s 2 → its
// result within 3 s of the start, timed_out, exit 137.
func TestDelegatedJobTimeout(t *testing.T) {
	e, _ := newExec(t, []string{t.TempDir()})
	r := runJob(t, e, context.Background(), jobOf(1, nil, plug(1, "sleep 100.148", 2)), 15*time.Second, nil)
	if r.err != nil || len(r.out) != 1 {
		t.Fatalf("Run: %v, %d results", r.err, len(r.out))
	}
	it := r.out[0]
	if !it.item.TimedOut || exitOf(it.item) != "137" || it.at > 3*time.Second || it.at < 2*time.Second {
		t.Fatalf("result after %v: timed_out %v exit %s, want within 2–3 s, true, 137", it.at, it.item.TimedOut, exitOf(it.item))
	}
	assertNothingLeft(t, e, "100.148")
}

// TASK-224 r1 row (reviewer-m10c; decisions "TASK-224 r1: always kill the
// shell when a plugin is stopped"): a shell that moves itself out of its
// cgroup survives cgroup.kill; the timeout must still stop it.
func TestDelegatedJobMovedShellTimeout(t *testing.T) {
	e, _ := newExec(t, []string{t.TempDir()})
	recordIdentity(t)
	exe := "echo $$ > " + mountOf(e.CG) + "/supervisor/cgroup.procs; exec sleep 100000"
	r := runJob(t, e, context.Background(), jobOf(1, nil, plug(1, exe, 2)), 10*time.Second, nil)
	if r.hung {
		t.Fatal("Run blocked on the moved shell (the timeout was not enforced)")
	}
	if r.err != nil || len(r.out) != 1 {
		t.Fatalf("Run: %v, %d results", r.err, len(r.out))
	}
	if it := r.out[0].item; !it.TimedOut || exitOf(it) != "137" {
		t.Fatalf("timed_out %v exit %s, want true, 137", it.TimedOut, exitOf(it))
	}
	t.Logf("RECORDED: Run returned after %v", r.elapsed)
	assertNothingLeft(t, e, "sleep 100000")
}

// CHK-M10-149 (REQ-240 (8), #138 (b), (c)): a plugin moves the runner into
// its own cgroup; the runner survives, is back in supervisor and the next
// job still runs.
func TestDelegatedJobRunnerMoved(t *testing.T) {
	e, _ := newExec(t, []string{t.TempDir()})
	exe := "echo $PPID > /sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup)/cgroup.procs; sleep 0.5; echo moved"
	r := runJob(t, e, context.Background(), jobOf(1, nil, plug(1, exe, 10)), 20*time.Second, nil)
	if r.err != nil {
		t.Fatalf("Run: %v (recorded: #138 (c) accepts a runner exit; this one did not exit)", r.err)
	}
	if got := ownCgroupPath(t); !strings.HasSuffix(got, "/supervisor") {
		t.Fatalf("runner in %s after the job", got)
	}
	t.Logf("RECORDED: the moving plugin's result: exit %s stdout %q", exitOf(r.out[0].item), r.out[0].item.Stdout)
	r2 := runJob(t, e, context.Background(), jobOf(1, nil, plug(2, "echo ok", 10)), 20*time.Second, nil)
	if r2.err != nil || len(r2.out) != 1 || r2.out[0].item.Stdout != "ok\n" || exitOf(r2.out[0].item) != "0" {
		t.Fatalf("the next job: %v %+v", r2.err, r2.out)
	}
	assertNothingLeft(t, e, "moved")
}

// isMount reports whether path is a mount point of this mount namespace.
func isMount(t *testing.T, path string) bool {
	t.Helper()
	b, err := os.ReadFile("/proc/self/mountinfo")
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range strings.Split(string(b), "\n") {
		if f := strings.Fields(l); len(f) > 4 && f[4] == path {
			return true
		}
	}
	return false
}

// CHK-M10-150 (REQ-240 (9), #135 (c); plant -342): the private /tmp and
// /var/tmp are emptied after the job, without following a symlink out; and
// TmpDirs has no default (decisions "TASK-224 (job) and TASK-225 (serve)
// design points" (3)).
func TestDelegatedJobTmpEmptied(t *testing.T) {
	if !isMount(t, "/tmp") || !isMount(t, "/var/tmp") {
		t.Fatal("refusing to empty /tmp and /var/tmp: they are not private mounts (run with PrivateTmp=yes)")
	}
	const state = "/var/lib/m10c-job"
	if got := os.Getenv("STATE_DIRECTORY"); got != state {
		t.Fatalf("STATE_DIRECTORY %q, want %s (run with StateDirectory=m10c-job)", got, state)
	}
	const outside = state + "/outside"
	_ = os.RemoveAll(outside)
	if err := os.Mkdir(outside, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(outside, "keep"), []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Run("no default: TmpDirs nil leaves /tmp alone", func(t *testing.T) {
		e, _ := newExec(t, nil)
		marker := "/tmp/m10c-nodefault-marker"
		r := runJob(t, e, context.Background(), jobOf(1, nil, plug(1, "echo x > "+marker, 10)), 20*time.Second, nil)
		if r.err != nil {
			t.Fatal(r.err)
		}
		if _, err := os.Stat(marker); err != nil {
			t.Fatalf("with no TmpDirs the job removed %s: %v", marker, err)
		}
		_ = os.Remove(marker)
	})
	t.Run("the private /tmp and /var/tmp are emptied", func(t *testing.T) {
		e, _ := newExec(t, []string{"/tmp", "/var/tmp"})
		exe := "mkdir -p /tmp/x/deep && echo a > /tmp/x/deep/f && echo b > /var/tmp/y && ln -s " + outside +
			" /tmp/link && mkdir /var/tmp/locked && echo c > /var/tmp/locked/g && chmod 000 /var/tmp/locked && echo .hidden > /tmp/.h"
		r := runJob(t, e, context.Background(), jobOf(1, nil, plug(1, exe, 10)), 20*time.Second, nil)
		if r.err != nil || len(r.out) != 1 || exitOf(r.out[0].item) != "0" {
			t.Fatalf("Run: %v %+v", r.err, r.out)
		}
		for _, d := range []string{"/tmp", "/var/tmp"} {
			ents, err := os.ReadDir(d)
			if err != nil {
				t.Fatal(err)
			}
			if len(ents) != 0 {
				var names []string
				for _, x := range ents {
					names = append(names, x.Name())
				}
				t.Errorf("%s not empty after the job: %v", d, names)
			}
		}
		if fi, err := os.Stat(outside); err != nil || fi.Mode().Perm() != 0o700 {
			t.Errorf("the symlink target outside: %v %v", fi, err)
		}
		if _, err := os.Stat(filepath.Join(outside, "keep")); err != nil {
			t.Error("a file outside /tmp was removed through the symlink")
		}
	})
	t.Run("a failed cleanup is Run's error (fatal), after every result", func(t *testing.T) {
		e, logs := newExec(t, []string{"/nonexistent-m10c"})
		r := runJob(t, e, context.Background(), jobOf(1, nil, plug(1, "echo x", 10)), 20*time.Second, nil)
		if r.err == nil || len(r.out) != 1 {
			t.Fatalf("Run: %v, %d results; want an error after 1 result", r.err, len(r.out))
		}
		if !strings.Contains(logs.String(), "after-job cleanup failed") {
			t.Errorf("no cleanup log line: %s", logs.String())
		}
	})
}

// CHK-M10-151 (REQ-240 (10); plant -391): the connection closes (ctx
// cancelled) mid-job → Run returns, nothing more is emitted and 1 s later no
// plugin process exists.
func TestDelegatedJobCancel(t *testing.T) {
	e, _ := newExec(t, []string{t.TempDir()})
	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		deadline := time.Now().Add(10 * time.Second)
		for len(sleepers("300.151")) < 2 && time.Now().Before(deadline) {
			time.Sleep(20 * time.Millisecond)
		}
		cancel()
	}()
	r := runJob(t, e, ctx, jobOf(2, nil, plug(1, "sleep 300.151", 600), plug(2, "sleep 300.151", 600), plug(3, "echo never", 600)), 20*time.Second, nil)
	if r.err != nil {
		t.Fatalf("Run: %v", r.err)
	}
	if len(r.out) != 0 {
		t.Fatalf("%d results emitted after the cancel: %+v", len(r.out), r.out)
	}
	time.Sleep(time.Second)
	if s := sleepers("300.151"); len(s) > 0 {
		t.Fatalf("plugins alive 1 s after Run returned: %v", s)
	}
	assertNothingLeft(t, e, "300.151")
}

func stamps(t *testing.T, it wire.ResultItem) (float64, float64) {
	t.Helper()
	f := strings.Fields(it.Stdout)
	if len(f) != 2 {
		t.Fatalf("stdout %q", it.Stdout)
	}
	a, _ := strconv.ParseFloat(f[0], 64)
	b, _ := strconv.ParseFloat(f[1], 64)
	return a, b
}

func maxOverlap(t *testing.T, r jobRun) int {
	t.Helper()
	type ev struct {
		at    float64
		delta int
	}
	var evs []ev
	for _, e := range r.out {
		a, b := stamps(t, e.item)
		evs = append(evs, ev{a, 1}, ev{b, -1})
	}
	sort.Slice(evs, func(i, j int) bool {
		if evs[i].at != evs[j].at {
			return evs[i].at < evs[j].at
		}
		return evs[i].delta < evs[j].delta
	})
	cur, top := 0, 0
	for _, e := range evs {
		cur += e.delta
		top = max(top, cur)
	}
	return top
}

// CHK-M10-152 (REQ-239 (6)): eight `sleep 2` with max_parallel_plugins 3 →
// never more than 3 running, three rounds; with 1 → strictly sequential.
func TestDelegatedJobParallelCap(t *testing.T) {
	e, _ := newExec(t, []string{t.TempDir()})
	stamp := "date +%s.%N; sleep SLEEP; date +%s.%N"
	var specs []wire.PluginSpec
	for i := range 8 {
		specs = append(specs, plug(i+1, strings.Replace(stamp, "SLEEP", "2", 1), 30))
	}
	r := runJob(t, e, context.Background(), jobOf(3, nil, specs...), 60*time.Second, nil)
	if r.err != nil || len(r.out) != 8 {
		t.Fatalf("Run: %v, %d results", r.err, len(r.out))
	}
	if top := maxOverlap(t, r); top != 3 {
		t.Errorf("at most %d plugins ran at once, want exactly 3", top)
	}
	if r.elapsed < 6*time.Second || r.elapsed > 8*time.Second {
		t.Errorf("8 × sleep 2 at 3 at once took %v, want three rounds (6–8 s)", r.elapsed)
	}
	var seq []wire.PluginSpec
	for i := range 3 {
		seq = append(seq, plug(i+1, strings.Replace(stamp, "SLEEP", "0.5", 1), 30))
	}
	r1 := runJob(t, e, context.Background(), jobOf(1, nil, seq...), 30*time.Second, nil)
	if r1.err != nil || len(r1.out) != 3 {
		t.Fatalf("Run: %v, %d results", r1.err, len(r1.out))
	}
	if top := maxOverlap(t, r1); top != 1 {
		t.Errorf("with 1 at once, %d overlapped", top)
	}
}

// countingSpawn wraps Spawn: call k (1-based) fails as fail says.
type countingSpawn struct {
	mu    sync.Mutex
	calls int
	failK int
	fail  error
}

func (s *countingSpawn) spawn(p *Plugin, execute string, now func() time.Time) (*Spawned, error) {
	s.mu.Lock()
	s.calls++
	k := s.calls
	s.mu.Unlock()
	if k == s.failK {
		return nil, s.fail
	}
	return Spawn(p, execute, now)
}

func (s *countingSpawn) n() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls
}

func isUnavailable(it wire.ResultItem) bool {
	return it.Error != nil && *it.Error == wire.ErrRunnerUnavailable && it.ExitCode == nil &&
		it.Stdout == "" && it.Stderr == "" && !it.TimedOut && !it.Truncated
}

// CHK-M10-153 (REQ-241 (5), #136 (f)): an exec failure costs that plugin
// only; a cgroup failure stops the job, and every plugin not yet started is
// runner_unavailable with no further process started (exec counter).
func TestDelegatedJobStartFailures(t *testing.T) {
	t.Run("exec failure: that plugin only", func(t *testing.T) {
		e, _ := newExec(t, []string{t.TempDir()})
		cs := &countingSpawn{failK: 2, fail: fmt.Errorf("%w: planted", ErrExec)}
		e.Spawn = cs.spawn
		r := runJob(t, e, context.Background(), jobOf(1, nil, plug(1, "echo one", 10), plug(2, "echo two", 10), plug(3, "echo three", 10)), 20*time.Second, nil)
		got := r.byID(t)
		if r.err != nil || len(got) != 3 || cs.n() != 3 {
			t.Fatalf("Run: %v, %d results, %d spawns", r.err, len(got), cs.n())
		}
		if got[pid(1)].Stdout != "one\n" || got[pid(3)].Stdout != "three\n" || !isUnavailable(got[pid(2)]) {
			t.Fatalf("results %+v", got)
		}
	})
	t.Run("cgroup failure: the job stops", func(t *testing.T) {
		e, _ := newExec(t, []string{t.TempDir()})
		cs := &countingSpawn{failK: 2, fail: fmt.Errorf("%w: planted", ErrCgroup)}
		e.Spawn = cs.spawn
		r := runJob(t, e, context.Background(), jobOf(1, nil, plug(1, "echo one", 10), plug(2, "echo two", 10), plug(3, "echo three", 10), plug(4, "echo four", 10)), 20*time.Second, nil)
		got := r.byID(t)
		if r.err != nil || len(got) != 4 {
			t.Fatalf("Run: %v, %d results", r.err, len(got))
		}
		if cs.n() != 2 {
			t.Fatalf("%d spawn calls after a cgroup failure at the 2nd, want 2 (no further start)", cs.n())
		}
		if got[pid(1)].Stdout != "one\n" {
			t.Fatalf("plugin 1: %+v", got[pid(1)])
		}
		for _, n := range []int{2, 3, 4} {
			if !isUnavailable(got[pid(n)]) {
				t.Fatalf("plugin %d: %+v, want runner_unavailable", n, got[pid(n)])
			}
		}
	})
}

// CHK-M10-154 (REQ-241 (3) at unit level): exit codes and completion order.
func TestDelegatedJobExitCodesAndOrder(t *testing.T) {
	e, _ := newExec(t, []string{t.TempDir()})
	r := runJob(t, e, context.Background(), jobOf(4, nil,
		plug(1, "sleep 1; exit 3", 10), plug(2, "sleep 0.5; kill -9 $$", 10),
		plug(3, "sleep 0.7; no-such-command-m10c", 10), plug(4, "sleep 0.1; echo fast", 10)), 20*time.Second, nil)
	got := r.byID(t)
	if r.err != nil || len(got) != 4 {
		t.Fatalf("Run: %v, %d results", r.err, len(got))
	}
	want := map[int]string{1: "3", 2: "137", 3: "127", 4: "0"}
	for n, w := range want {
		if exitOf(got[pid(n)]) != w {
			t.Errorf("plugin %d: exit %s, want %s", n, exitOf(got[pid(n)]), w)
		}
	}
	var order []wire.UUID
	for _, x := range r.out {
		order = append(order, x.item.PluginUUID)
	}
	if fmt.Sprint(order) != fmt.Sprint([]wire.UUID{pid(4), pid(2), pid(3), pid(1)}) {
		t.Errorf("emit order %v, want completion order 4, 2, 3, 1", order)
	}
}

// CHK-M10-155 (REQ-242 through the real path; plant -382): a bsa_ canary and
// 3 MiB of filler → [REDACTED], no token body, ≤ 65,536 bytes, truncated;
// the canary in no log record.
func TestDelegatedJobRedaction(t *testing.T) {
	e, logs := newExec(t, []string{t.TempDir()})
	token := "bsa_M10CANARY" + strings.Repeat("Q", 34)
	exe := "printf 'start " + token + " end\\n'; head -c 3145728 /dev/zero | tr '\\0' 'x'; printf '" + token + "' >&2"
	r := runJob(t, e, context.Background(), jobOf(1, specDefaults(t), plug(1, exe, 30)), 30*time.Second, nil)
	if r.err != nil || len(r.out) != 1 {
		t.Fatalf("Run: %v, %d results", r.err, len(r.out))
	}
	it := r.out[0].item
	if !strings.HasPrefix(it.Stdout, "start [REDACTED] end\n") || strings.Contains(it.Stdout, "M10CANARY") ||
		len(it.Stdout) > 65536 || !it.Truncated || it.Stderr != "[REDACTED]" {
		t.Fatalf("stdout %d bytes prefix %q truncated %v stderr %q", len(it.Stdout), it.Stdout[:min(40, len(it.Stdout))], it.Truncated, it.Stderr)
	}
	if strings.Contains(logs.String(), "M10CANARY") || strings.Contains(logs.String(), "xxxxxxxx") {
		t.Fatalf("plugin output or command in the runner log: %s", logs.String())
	}
	if !strings.Contains(logs.String(), `"plugin_uuid":"`+string(pid(1))+`"`) {
		t.Errorf("no per-plugin log line: %s", logs.String())
	}
}

// CHK-M10-156 (plants -341 executor half, cgroup Remove dropped): each
// plugin's temp directory and its p-<n> are gone before its result is
// emitted.
func TestDelegatedJobCleanupBeforeEmit(t *testing.T) {
	e, _ := newExec(t, []string{t.TempDir()})
	var specs []wire.PluginSpec
	for i := range 3 {
		specs = append(specs, plug(i+1, "pwd; touch inside", 10))
	}
	r := runJob(t, e, context.Background(), jobOf(1, nil, specs...), 20*time.Second, func(it wire.ResultItem) {
		dir := strings.TrimSpace(it.Stdout)
		if !strings.HasPrefix(dir, "/tmp/bitscan-p-") {
			t.Errorf("pwd %q", dir)
		} else if _, err := os.Lstat(dir); !errors.Is(err, fs.ErrNotExist) {
			t.Errorf("temp dir %s still there when its result is emitted", dir)
		}
		ents, _ := os.ReadDir(filepath.Join(mountOf(e.CG), "plugins"))
		for _, d := range ents {
			if d.IsDir() && strings.HasPrefix(d.Name(), "p-") {
				t.Errorf("cgroup %s still there when the result is emitted", d.Name())
			}
		}
	})
	if r.err != nil || len(r.out) != 3 {
		t.Fatalf("Run: %v, %d results", r.err, len(r.out))
	}
}

// TASK-224 r2 (decisions "TASK-224 r2: a stderr-only read error also sets
// truncated"): a stream cut short by a read error is never sent as whole;
// either stream's error sets truncated, so the manager answers ERROR
// (evaluate.py: truncated → STDOUT_TRUNCATED, test_evaluate.py L155–L165).
func TestDelegatedJobCaptureErrorTruncated(t *testing.T) {
	e, _ := newExec(t, []string{t.TempDir()})
	m := mountOf(e.CG)
	// The plugin waits until its child has left for supervisor, so the
	// child (not cgroup.kill) holds the stream when the plugin exits.
	const waitMoved = " while ! grep -q /supervisor /proc/$!/cgroup; do sleep 0.02; done; echo ok"
	one := func(t *testing.T, exe string) wire.ResultItem {
		t.Helper()
		r := runJob(t, e, context.Background(), jobOf(1, nil, plug(1, exe, 20)), 30*time.Second, nil)
		if r.err != nil || len(r.out) != 1 {
			t.Fatalf("Run: %v, %d results", r.err, len(r.out))
		}
		return r.out[0].item
	}
	t.Run("stdout held open by a child that left the cgroup", func(t *testing.T) {
		it := one(t, "sh -c 'echo $$ > "+m+"/supervisor/cgroup.procs; exec sleep 300.2241' 2>/dev/null &"+waitMoved)
		if !it.Truncated || it.Stdout != "ok\n" || exitOf(it) != "0" {
			t.Fatalf("truncated %v stdout %q exit %s, want true, ok, 0", it.Truncated, it.Stdout, exitOf(it))
		}
		assertNothingLeft(t, e, "300.2241")
	})
	t.Run("stderr only held open", func(t *testing.T) {
		it := one(t, "sh -c 'echo $$ > "+m+"/supervisor/cgroup.procs; exec sleep 300.2242' >/dev/null &"+waitMoved)
		if !it.Truncated || it.Stdout != "ok\n" {
			t.Fatalf("truncated %v stdout %q, want true, ok", it.Truncated, it.Stdout)
		}
		assertNothingLeft(t, e, "300.2242")
	})
	t.Run("control: no read error, truncated false", func(t *testing.T) {
		if it := one(t, "echo ok; echo e >&2"); it.Truncated || it.Stdout != "ok\n" || it.Stderr != "e\n" {
			t.Fatalf("%+v", it)
		}
	})
	for _, stream := range []string{"stdout", "stderr"} {
		t.Run("unit: a "+stream+" read that fails (EISDIR)", func(t *testing.T) {
			e.Spawn = func(p *Plugin, execute string, now func() time.Time) (*Spawned, error) {
				s, err := Spawn(p, execute, now)
				if err != nil {
					return s, err
				}
				d, derr := os.Open(t.TempDir()) // a directory: every read is EISDIR
				if derr != nil {
					t.Fatal(derr)
				}
				if stream == "stdout" {
					_ = s.Stdout.Close()
					s.Stdout = d
				} else {
					_ = s.Stderr.Close()
					s.Stderr = d
				}
				return s, nil
			}
			defer func() { e.Spawn = Spawn }()
			if it := one(t, "true"); !it.Truncated {
				t.Fatalf("a failed %s read: truncated %v, want true", stream, it.Truncated)
			}
		})
	}
}
