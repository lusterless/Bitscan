// TP-M10-08 (tester-m10): cgroup v2 handling on a fake tree, REQ-238 (1),
// REQ-240 (sweep), #136 (a), #137, #138. The fake models the kernel rules
// the code relies on: a pid is in exactly one cgroup, cgroup.procs moves a
// whole process, cgroup.kill kills every process in the cgroup's subtree
// (the runner too, if it is there), rmdir needs an empty cgroup without
// children. Pure: Windows and Linux. Expected operations come from REQ-238
// (1) and plan TASK-215 §2–§4.
package runner

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"path"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

const fakeBase = "/system.slice/bitscan-runner.service"

type fakeCG struct {
	mu       sync.Mutex
	dirs     map[string]bool // "" is the own cgroup
	links    map[string]bool // symlink entries (never directories)
	procs    map[int]string  // pid → cgroup
	self     int
	dead     map[int]bool
	ops      []string
	noKill   bool // own cgroup without cgroup.kill
	mkdirErr error
	failMove map[string]bool // cgroups whose cgroup.procs refuses writes
	lie      bool            // SelfCgroup reports supervisor whatever happens
	onKill   func(pid int)   // called before a pid is killed
}

func newFakeCG() *fakeCG {
	return &fakeCG{dirs: map[string]bool{"": true}, links: map[string]bool{}, procs: map[int]string{100: ""},
		self: 100, dead: map[int]bool{}, failMove: map[string]bool{}}
}

func norm(name string) string {
	n := path.Clean(name)
	if n == "." {
		return ""
	}
	return n
}

func (f *fakeCG) op(s string) { f.ops = append(f.ops, s) }

func (f *fakeCG) Mkdir(name string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	n := norm(name)
	if f.mkdirErr != nil {
		return f.mkdirErr
	}
	if f.dirs[n] {
		return fs.ErrExist
	}
	if !f.dirs[norm(path.Dir(n))] {
		return fs.ErrNotExist
	}
	f.dirs[n] = true
	f.op("mkdir " + n)
	return nil
}

func under(cg, dir string) bool { return dir == "" || cg == dir || strings.HasPrefix(cg, dir+"/") }

func (f *fakeCG) WriteFile(name string, data []byte) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	n := norm(name)
	dir, file := norm(path.Dir(n)), path.Base(n)
	if !f.dirs[dir] {
		return fs.ErrNotExist
	}
	switch file {
	case "cgroup.procs":
		if f.failMove[dir] {
			return errors.New("EBUSY")
		}
		pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
		if err != nil {
			return err
		}
		if _, ok := f.procs[pid]; !ok {
			return errors.New("ESRCH")
		}
		f.procs[pid] = dir
		f.op(fmt.Sprintf("write %s %d", n, pid))
	case "cgroup.kill":
		if dir == "" && f.noKill {
			return fs.ErrNotExist
		}
		f.op("write " + n + " " + string(data))
		for pid, cg := range f.procs {
			if under(cg, dir) {
				delete(f.procs, pid)
				f.dead[pid] = true
			}
		}
	default:
		return fs.ErrPermission
	}
	return nil
}

func (f *fakeCG) ReadFile(name string) ([]byte, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	n := norm(name)
	dir, file := norm(path.Dir(n)), path.Base(n)
	if !f.dirs[dir] {
		return nil, fs.ErrNotExist
	}
	switch file {
	case "cgroup.procs":
		var pids []int
		for pid, cg := range f.procs {
			if cg == dir {
				pids = append(pids, pid)
			}
		}
		sort.Ints(pids)
		var b strings.Builder
		for _, p := range pids {
			fmt.Fprintln(&b, p)
		}
		return []byte(b.String()), nil
	case "cgroup.events":
		pop := 0
		for _, cg := range f.procs {
			if under(cg, dir) {
				pop = 1
			}
		}
		return []byte(fmt.Sprintf("populated %d\nfrozen 0\n", pop)), nil
	}
	return nil, fs.ErrPermission
}

func (f *fakeCG) Remove(name string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	n := norm(name)
	if !f.dirs[n] || n == "" {
		return fs.ErrNotExist
	}
	for d := range f.dirs {
		if d != n && under(d, n) {
			return errors.New("EBUSY: has children")
		}
	}
	for _, cg := range f.procs {
		if cg == n {
			return errors.New("EBUSY: populated")
		}
	}
	delete(f.dirs, n)
	f.op("rmdir " + n)
	return nil
}

type fakeEntry struct {
	name string
	dir  bool
	link bool
}

func (e fakeEntry) Name() string { return e.name }
func (e fakeEntry) IsDir() bool  { return e.dir }
func (e fakeEntry) Type() fs.FileMode {
	switch {
	case e.link:
		return fs.ModeSymlink
	case e.dir:
		return fs.ModeDir
	}
	return 0
}
func (e fakeEntry) Info() (fs.FileInfo, error) { return nil, errors.New("no info") }

func (f *fakeCG) ReadDir(name string) ([]fs.DirEntry, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	n := norm(name)
	if !f.dirs[n] {
		return nil, fs.ErrNotExist
	}
	out := []fs.DirEntry{fakeEntry{name: "cgroup.procs"}, fakeEntry{name: "cgroup.events"}}
	if n != "" || !f.noKill {
		out = append(out, fakeEntry{name: "cgroup.kill"})
	}
	for d := range f.dirs {
		if d != "" && norm(path.Dir(d)) == n {
			out = append(out, fakeEntry{name: path.Base(d), dir: true})
		}
	}
	for l := range f.links {
		if norm(path.Dir(l)) == n {
			out = append(out, fakeEntry{name: path.Base(l), link: true})
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name() < out[j].Name() })
	return out, nil
}

func (f *fakeCG) selfCgroup() ([]byte, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.lie {
		return []byte("0::" + fakeBase + "/supervisor\n"), nil
	}
	cg, ok := f.procs[f.self]
	if !ok {
		return nil, errors.New("runner is dead")
	}
	return []byte("0::" + path.Join(fakeBase, cg) + "\n"), nil
}

func (f *fakeCG) killPid(pid int, still func() bool) error {
	if f.onKill != nil {
		f.onKill(pid)
	}
	if !still() {
		return nil
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if pid == f.self {
		panic("the runner was asked to kill itself")
	}
	delete(f.procs, pid)
	f.dead[pid] = true
	f.op(fmt.Sprintf("pidkill %d", pid))
	return nil
}

func (f *fakeCG) cg() *Cgroups {
	return NewCgroups(CgroupDeps{FS: f, Base: fakeBase, Self: f.self, SelfCgroup: f.selfCgroup, KillPid: f.killPid})
}

func (f *fakeCG) where(pid int) (string, bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	cg, ok := f.procs[pid]
	return cg, ok
}

func (f *fakeCG) spawnAt(pid int, cg string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.dirs[cg] = true
	f.procs[pid] = cg
}

func (f *fakeCG) opsSince(i int) []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return slices.Clone(f.ops[i:])
}

// CHK-M10-100: REQ-238 (1) the exact operations, and the child born in its
// own cgroup.
func TestCgroupExactOperations(t *testing.T) {
	f := newFakeCG()
	c := f.cg()
	if err := c.Setup(); err != nil {
		t.Fatal(err)
	}
	p, err := c.NewPlugin()
	if err != nil {
		t.Fatal(err)
	}
	var bornIn string
	if err := p.StartIn(func() error {
		f.mu.Lock()
		bornIn = f.procs[f.self] // a child is created in the runner's cgroup
		f.procs[200] = bornIn
		f.mu.Unlock()
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if bornIn != "p-1" {
		t.Fatalf("child born in %q, want p-1", bornIn)
	}
	if err := p.Kill(); err != nil {
		t.Fatal(err)
	}
	if err := p.WaitEmpty(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := p.Remove(); err != nil {
		t.Fatal(err)
	}
	want := []string{
		"mkdir supervisor", "write supervisor/cgroup.procs 100",
		"mkdir p-1", "write p-1/cgroup.procs 100", "write supervisor/cgroup.procs 100",
		"write p-1/cgroup.kill 1", "rmdir p-1",
	}
	if !slices.Equal(f.ops, want) {
		t.Fatalf("operations:\n got %q\nwant %q", f.ops, want)
	}
	if cg, ok := f.where(100); !ok || cg != "supervisor" {
		t.Fatalf("runner in %q alive %v", cg, ok)
	}
	if !f.dead[200] {
		t.Fatal("the plugin child survived its cgroup.kill")
	}
	// Distinct names, never from a job.
	p2, _ := c.NewPlugin()
	p3, _ := c.NewPlugin()
	if p2.name != "p-2" || p3.name != "p-3" {
		t.Fatalf("names %s %s", p2.name, p3.name)
	}
}

// CHK-M10-101: start-up refusals and /proc/self/cgroup parsing (#137).
func TestCgroupSetupRefusals(t *testing.T) {
	for _, in := range []string{"", "0::/a\n0::/b\n", "1:name=systemd:/x\n0::/y\n", "12:memory:/x\n", "0::relative\n", "0:/x\n", "0::\n"} {
		if _, err := parseSelfCgroup([]byte(in)); err == nil {
			t.Errorf("parseSelfCgroup(%q) accepted", in)
		}
	}
	if p, err := parseSelfCgroup([]byte("0::" + fakeBase + "\n")); err != nil || p != fakeBase {
		t.Errorf("valid line: %q %v", p, err)
	}
	f := newFakeCG()
	f.noKill = true
	if err := f.cg().Setup(); err == nil {
		t.Error("Setup accepted a cgroup without cgroup.kill")
	}
	f = newFakeCG()
	f.mkdirErr = fs.ErrPermission
	if err := f.cg().Setup(); err == nil {
		t.Error("Setup accepted a cgroup where supervisor can't be made (not delegated)")
	}
	f = newFakeCG()
	f.dirs["supervisor"] = true // EEXIST is fine
	if err := f.cg().Setup(); err != nil {
		t.Errorf("existing supervisor: %v", err)
	}
	f = newFakeCG()
	f.dirs["supervisor"] = true
	f.failMove["supervisor"] = true
	if err := f.cg().Setup(); err == nil {
		t.Error("Setup accepted a failed move into supervisor")
	}
}

// CHK-M10-103: the sweep kills every stray wherever it sits; the runner
// stays alive in supervisor; only supervisor is left (REQ-240, #138 (a)).
func TestCgroupSweepKillsEveryStray(t *testing.T) {
	f := newFakeCG()
	c := f.cg()
	if err := c.Setup(); err != nil {
		t.Fatal(err)
	}
	f.spawnAt(201, "supervisor")            // a plugin that moved into supervisor
	f.spawnAt(202, "")                      // into the service root
	f.dirs["supervisor/x"] = true           // nested under supervisor
	f.spawnAt(203, "supervisor/x/y")        // and deeper
	f.spawnAt(204, "p-3")                   // a leftover plugin cgroup
	f.spawnAt(205, "p-3/child")             // a cgroup a plugin made under its own
	f.dirs["q"] = true                      // a cgroup a plugin made in the root
	f.spawnAt(206, "q/r")                   //
	f.spawnAt(207, "supervisor/supervisor") // a nested supervisor
	f.links["p-9"] = true                   // a symlink entry is never followed
	if err := c.Sweep(context.Background()); err != nil {
		t.Fatal(err)
	}
	for pid := 201; pid <= 207; pid++ {
		if !f.dead[pid] {
			t.Errorf("pid %d survived the sweep", pid)
		}
	}
	if cg, ok := f.where(100); !ok || cg != "supervisor" {
		t.Fatalf("runner in %q alive %v", cg, ok)
	}
	var dirs []string
	for d := range f.dirs {
		dirs = append(dirs, d)
	}
	sort.Strings(dirs)
	if fmt.Sprint(dirs) != "[ supervisor]" {
		t.Fatalf("cgroups left: %q", dirs)
	}
	for _, o := range f.ops {
		if strings.Contains(o, "p-9") {
			t.Fatalf("the symlink entry was touched: %s", o)
		}
	}
}

// CHK-M10-104: #138 (b) a plugin moved the runner into its cgroup: the sweep
// and Kill move it back first and it survives.
func TestCgroupRunnerMovedBack(t *testing.T) {
	f := newFakeCG()
	c := f.cg()
	_ = c.Setup()
	p, _ := c.NewPlugin()
	_ = p.StartIn(func() error { f.spawnAt(300, "p-1"); return nil })
	f.spawnAt(100, "p-1") // the plugin writes the runner's pid into its own cgroup.procs
	if err := p.Kill(); err != nil {
		t.Fatal(err)
	}
	if cg, ok := f.where(100); !ok || cg != "supervisor" {
		t.Fatalf("after Kill the runner is in %q alive %v (it killed itself)", cg, ok)
	}
	if !f.dead[300] {
		t.Fatal("plugin survived")
	}
	f.dirs["z"] = true
	f.spawnAt(100, "z")
	f.spawnAt(301, "z")
	if err := c.Sweep(context.Background()); err != nil {
		t.Fatal(err)
	}
	if cg, ok := f.where(100); !ok || cg != "supervisor" || !f.dead[301] {
		t.Fatalf("after Sweep: runner %q alive %v; stray dead %v", cg, ok, f.dead[301])
	}
}

// StartIn fails closed: no start when the hop failed or the runner is not in
// the plugin cgroup after it; always back in supervisor.
func TestCgroupStartInFailsClosed(t *testing.T) {
	f := newFakeCG()
	c := f.cg()
	_ = c.Setup()
	p, _ := c.NewPlugin()
	f.failMove["p-1"] = true
	called := false
	if err := p.StartIn(func() error { called = true; return nil }); err == nil || called {
		t.Fatalf("hop failed: err %v, start called %v", err, called)
	}
	if cg, _ := f.where(100); cg != "supervisor" {
		t.Fatalf("runner left in %q", cg)
	}
	// The kernel accepted the write but /proc/self/cgroup says otherwise.
	f2 := newFakeCG()
	c2 := f2.cg()
	_ = c2.Setup()
	p2, _ := c2.NewPlugin()
	f2.lie = true
	called = false
	if err := p2.StartIn(func() error { called = true; return nil }); err == nil || called {
		t.Fatalf("not in the plugin cgroup: err %v, start called %v", err, called)
	}
	// start's error is returned and the runner still goes back.
	f3 := newFakeCG()
	c3 := f3.cg()
	_ = c3.Setup()
	p3, _ := c3.NewPlugin()
	if err := p3.StartIn(func() error { return errors.New("exec failed") }); err == nil {
		t.Fatal("start error lost")
	}
	if cg, _ := f3.where(100); cg != "supervisor" {
		t.Fatalf("runner left in %q after a failed start", cg)
	}
}

// CHK-M10-105 (fake): WaitEmpty gives up at its bound or the caller's ctx.
func TestCgroupWaitEmptyBound(t *testing.T) {
	f := newFakeCG()
	c := f.cg()
	_ = c.Setup()
	p, _ := c.NewPlugin()
	f.spawnAt(400, "p-1")
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	start := time.Now()
	if err := p.WaitEmpty(ctx); err == nil {
		t.Fatal("WaitEmpty returned nil for a populated cgroup")
	}
	if d := time.Since(start); d > 2*time.Second {
		t.Fatalf("WaitEmpty ignored the caller's deadline: %v", d)
	}
	if emptyWait != 5*time.Second {
		t.Fatalf("emptyWait %v, want 5 s (#138 (a))", emptyWait)
	}
	if err := p.Remove(); err == nil {
		t.Fatal("a populated cgroup was removed")
	}
}

// A stray that keeps escaping between passes is caught by a later pass; a
// stray that can't be killed makes the sweep fail (the runner then exits).
func TestCgroupSweepRepeatsAndFailsClosed(t *testing.T) {
	f := newFakeCG()
	c := f.cg()
	_ = c.Setup()
	moved := 0
	f.spawnAt(500, "supervisor")
	f.onKill = func(pid int) {
		if pid == 500 && moved < 3 { // it moves to a new cgroup just before the kill
			moved++
			f.spawnAt(500, fmt.Sprintf("m-%d", moved))
		}
	}
	if err := c.Sweep(context.Background()); err != nil {
		t.Fatal(err)
	}
	if !f.dead[500] {
		t.Fatal("an escaping stray survived")
	}
	// Unkillable: KillPid never removes it.
	g := newFakeCG()
	cg := NewCgroups(CgroupDeps{FS: g, Base: fakeBase, Self: g.self, SelfCgroup: g.selfCgroup,
		KillPid: func(int, func() bool) error { return nil }})
	_ = cg.Setup()
	g.spawnAt(600, "supervisor")
	start := time.Now()
	if err := cg.Sweep(context.Background()); err == nil {
		t.Fatal("the sweep reported success with a process left")
	}
	if d := time.Since(start); d < 4*time.Second || d > 8*time.Second {
		t.Fatalf("the sweep gave up after %v, want about 5 s", d)
	}
}

// CHK-M10-106: the spawn lock: no sweep, kill or other hop while the runner
// sits in a plugin cgroup.
func TestCgroupSpawnLock(t *testing.T) {
	f := newFakeCG()
	c := f.cg()
	_ = c.Setup()
	p, _ := c.NewPlugin()
	q, _ := c.NewPlugin()
	inHop := make(chan struct{})
	release := make(chan struct{})
	var mark int
	go func() {
		_ = p.StartIn(func() error {
			f.mu.Lock()
			mark = len(f.ops)
			f.mu.Unlock()
			close(inHop)
			<-release
			return nil
		})
	}()
	<-inHop
	done := make(chan struct{})
	go func() {
		defer close(done)
		_ = c.Sweep(context.Background())
		_ = q.StartIn(func() error { return nil })
		_ = q.Kill()
	}()
	time.Sleep(50 * time.Millisecond) // give the other calls a chance to run (they must not)
	if got := f.opsSince(mark); len(got) != 0 {
		t.Fatalf("operations during an open hop: %q", got)
	}
	close(release)
	<-done
}
