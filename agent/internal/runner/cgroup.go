package runner

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"os"
	"path"
	"strconv"
	"strings"
	"sync"
	"time"
)

// cgroup v2 handling (TS §3.5 L250, §3.7 L284; #136 (a), #138). Every name
// is relative to the runner's own cgroup directory and generated here; no
// name from a job reaches the filesystem.

const (
	supervisor = "supervisor"
	// plugins holds every plugin cgroup, so they can share one task limit.
	pluginsDir = "plugins"
	emptyWait  = 5 * time.Second
	pollEvery  = 10 * time.Millisecond
	// taskReserve is how many of the unit's tasks (TasksMax=64, TS §3.7)
	// all plugins together can never take: the runner itself uses about 10
	// (its Go runtime with GOMAXPROCS=2 from the unit's CPUQuota, plus
	// threads blocked in system calls), so 16 leaves it room to make more.
	taskReserve = 16
)

// CgroupFS is the runner's own cgroup directory: RootFS on the real one, or
// a fake tree in tests.
type CgroupFS interface {
	Mkdir(name string) error
	WriteFile(name string, data []byte) error
	ReadFile(name string) ([]byte, error)
	Remove(name string) error
	ReadDir(name string) ([]fs.DirEntry, error)
}

type rootFS struct{ r *os.Root }

// RootFS adapts an os.Root, so no path can leave the directory.
func RootFS(r *os.Root) CgroupFS { return rootFS{r} }

func (f rootFS) Mkdir(name string) error              { return f.r.Mkdir(name, 0o755) }
func (f rootFS) ReadFile(name string) ([]byte, error) { return f.r.ReadFile(name) }
func (f rootFS) Remove(name string) error             { return f.r.Remove(name) }
func (f rootFS) ReadDir(name string) ([]fs.DirEntry, error) {
	return fs.ReadDir(f.r.FS(), name)
}

func (f rootFS) WriteFile(name string, data []byte) error {
	file, err := f.r.OpenFile(name, os.O_WRONLY|os.O_TRUNC, 0)
	if err != nil {
		return err
	}
	_, err = file.Write(data)
	return errors.Join(err, file.Close())
}

// CgroupDeps are the seams of Cgroups; Open (Linux) fills them.
type CgroupDeps struct {
	FS         CgroupFS
	Base       string // own cgroup path at start, from /proc/self/cgroup
	Self       int    // own pid
	SelfCgroup func() ([]byte, error)
	// KillPid sends SIGKILL to pid through a handle that pins the process,
	// and only while still() reports it is in the cgroup swept.
	KillPid func(pid int, still func() bool) error
	Log     *slog.Logger
}

// Cgroups holds the spawn lock: while the runner sits in a plugin cgroup no
// other spawn, kill or sweep runs.
type Cgroups struct {
	d    CgroupDeps
	mu   sync.Mutex
	next uint64
	// cpuMax is the runner's own cpu.max ("<quota> <period>"), copied into
	// every plugin cgroup; nil when the runner's cgroup has no CPU limit or
	// the cpu controller could not be enabled for its children.
	cpuMax []byte
	// tasksLimited is true when plugins/pids.max holds the shared limit, so
	// plugins/pids.events counts the forks it refused.
	tasksLimited bool
}

func NewCgroups(d CgroupDeps) *Cgroups { return &Cgroups{d: d} }

// Plugin is one plugin's cgroup, "plugins/p-<n>".
type Plugin struct {
	name string
	c    *Cgroups
	// limitHits is plugins/pids.events "max" just before the plugin
	// started; watch is false when there is no shared task limit.
	limitHits uint64
	watch     bool
}

// parseSelfCgroup accepts exactly one "0::<path>" line (unified cgroup v2).
func parseSelfCgroup(b []byte) (string, error) {
	s := strings.TrimSuffix(string(b), "\n")
	p, ok := strings.CutPrefix(s, "0::")
	if !ok || strings.Contains(s, "\n") || !strings.HasPrefix(p, "/") {
		return "", errors.New("runner: /proc/self/cgroup is not a single cgroup v2 line")
	}
	return p, nil
}

func (c *Cgroups) pid() []byte { return []byte(strconv.Itoa(c.d.Self)) }

func (c *Cgroups) here() (string, error) {
	b, err := c.d.SelfCgroup()
	if err != nil {
		return "", fmt.Errorf("runner: read own cgroup: %w", err)
	}
	return parseSelfCgroup(b)
}

// Setup checks the delegated cgroup (cgroup.kill present, a child can be
// made) and moves the runner into supervisor (#137). Any failure means the
// runner refuses to start. The start-up sweep (#138 (a)) is the caller's
// next call: Setup, then Sweep.
func (c *Cgroups) Setup() error {
	entries, err := c.d.FS.ReadDir(".")
	if err != nil {
		return fmt.Errorf("runner: read own cgroup: %w", err)
	}
	if !hasEntry(entries, "cgroup.kill") {
		return errors.New("runner: own cgroup has no cgroup.kill")
	}
	if err := c.d.FS.Mkdir(supervisor); err != nil && !errors.Is(err, fs.ErrExist) {
		return fmt.Errorf("runner: create supervisor cgroup: %w", err)
	}
	if err := c.d.FS.Mkdir(pluginsDir); err != nil && !errors.Is(err, fs.ErrExist) {
		return fmt.Errorf("runner: create plugins cgroup: %w", err)
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.ensureSupervisor(); err != nil {
		return err
	}
	c.limitTasks()
	c.limitCPU()
	return nil
}

// limitTasks gives all plugins together the runner's own task limit
// (pids.max, from TasksMax=) less taskReserve, in plugins/pids.max. Every
// thread and process counts as a task: without it, plugins could take all of
// the unit's tasks, and the runner, unable to create a thread, would die and
// report every remaining plugin runner_unavailable. With it, a plugin that
// meets the limit fails to fork and the runner reports it as truncated
// (ERROR, see HitTaskLimit). It guards against mistakes, not a hostile
// plugin: plugins run as the runner's user and could rewrite the limit, as
// they can already signal the runner (TS §3.7). When the runner's cgroup has
// no numeric limit or the pids controller cannot be enabled, plugins run as
// before and the runner still starts. Callers hold c.mu.
func (c *Cgroups) limitTasks() {
	b, err := c.d.FS.ReadFile("pids.max")
	n, perr := strconv.Atoi(strings.TrimSpace(string(b)))
	switch {
	case err != nil || perr != nil:
		c.warn("runner: own cgroup has no task limit; plugins get no shared limit")
		return
	case n <= taskReserve:
		c.warn("runner: own task limit too small to share; plugins get no shared limit")
		return
	}
	if err := c.d.FS.WriteFile("cgroup.subtree_control", []byte("+pids")); err != nil {
		c.warn("runner: pids controller not enabled for plugins; they get no shared limit")
		return
	}
	if err := c.d.FS.WriteFile(pluginsDir+"/pids.max", []byte(strconv.Itoa(n-taskReserve))); err != nil {
		c.warn("runner: plugins task limit not set; plugins get no shared limit")
		return
	}
	c.tasksLimited = true
}

// limitHitCount reads the "max" counter of plugins/pids.events: how many
// forks the shared limit has refused since the runner started.
func (c *Cgroups) limitHitCount() (uint64, bool) {
	b, err := c.d.FS.ReadFile(pluginsDir + "/pids.events")
	if err != nil {
		return 0, false
	}
	for line := range bytes.Lines(b) {
		if f := bytes.Fields(line); len(f) == 2 && string(f[0]) == "max" {
			n, err := strconv.ParseUint(string(f[1]), 10, 64)
			return n, err == nil
		}
	}
	return 0, false
}

// limitCPU lets every plugin cgroup carry the runner's own CPU limit. The Go
// runtime, and other runtimes that size themselves from cgroups, read only
// the cgroup a process is in, not its parents. Without its own cpu.max, a Go
// program a plugin runs (bitscan-capread among them) sizes GOMAXPROCS to
// every CPU on the host. On a 256-CPU host its start-up garbage collection
// then starts about 64 threads, which fills the runner's TasksMax=64 and
// stops the runner creating threads. With the copied limit (25% from the
// unit) such a program starts with GOMAXPROCS=2. The parent's limit already
// caps the plugins, so the copy takes no CPU away from them.
//
// It needs the runner out of its own cgroup (it is in supervisor), plugins
// empty of processes (it only holds the plugin cgroups) and the cpu controller
// delegated, which CPUQuota= and Delegate= on the unit give.
// When either is missing, plugins start without a CPU limit of their own, as
// before; the runner still starts. Callers hold c.mu.
func (c *Cgroups) limitCPU() {
	b, err := c.d.FS.ReadFile("cpu.max")
	if err != nil {
		c.warn("runner: own cgroup has no cpu.max; plugin cgroups get no CPU limit")
		return
	}
	f := bytes.Fields(b)
	if len(f) != 2 || string(f[0]) == "max" || !digits(f[0]) || !digits(f[1]) {
		c.warn("runner: own cgroup has no CPU limit; plugin cgroups get none")
		return
	}
	for _, dir := range []string{".", pluginsDir} {
		if err := c.d.FS.WriteFile(path.Join(dir, "cgroup.subtree_control"), []byte("+cpu")); err != nil {
			c.warn("runner: cpu controller not enabled for plugin cgroups; they get no CPU limit")
			return
		}
	}
	c.cpuMax = bytes.Join(f, []byte(" "))
}

func digits(b []byte) bool {
	for _, ch := range b {
		if ch < '0' || ch > '9' {
			return false
		}
	}
	return len(b) > 0
}

func (c *Cgroups) warn(msg string) {
	if c.d.Log != nil {
		c.d.Log.Warn(msg)
	}
}

func hasEntry(entries []fs.DirEntry, name string) bool {
	for _, e := range entries {
		if e.Name() == name {
			return true
		}
	}
	return false
}

// ensureSupervisor moves the runner back into supervisor if a plugin moved
// it, and checks it is there (#138 (b)). Callers hold c.mu.
func (c *Cgroups) ensureSupervisor() error {
	want := path.Join(c.d.Base, supervisor)
	if p, err := c.here(); err == nil && p == want {
		return nil
	}
	if err := c.d.FS.WriteFile(supervisor+"/cgroup.procs", c.pid()); err != nil {
		return fmt.Errorf("runner: move into supervisor: %w", err)
	}
	if p, err := c.here(); err != nil || p != want {
		return errors.New("runner: not in supervisor after the move")
	}
	return nil
}

// NewPlugin makes a fresh plugin cgroup.
func (c *Cgroups) NewPlugin() (*Plugin, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.next++
	p := &Plugin{name: pluginsDir + "/p-" + strconv.FormatUint(c.next, 10), c: c}
	if err := c.d.FS.Mkdir(p.name); err != nil {
		return nil, fmt.Errorf("runner: create plugin cgroup: %w", err)
	}
	if c.cpuMax != nil {
		if err := c.d.FS.WriteFile(p.name+"/cpu.max", c.cpuMax); err != nil {
			return nil, errors.Join(fmt.Errorf("runner: limit plugin cgroup CPU: %w", err), p.Remove())
		}
	}
	if c.tasksLimited {
		p.limitHits, p.watch = c.limitHitCount()
	}
	return p, nil
}

// HitTaskLimit reports whether the shared plugin task limit refused a fork
// while this plugin ran: any time from just before its start to now. A fork
// the plugin needed may then have failed, and its output may be incomplete
// (an "empty" check could even pass), so the caller reports it as truncated,
// which the evaluator answers ERROR. A plugin running beside the one that
// met the limit is reported too: only the shared counter exists.
func (p *Plugin) HitTaskLimit() bool {
	if !p.watch {
		return false
	}
	now, ok := p.c.limitHitCount()
	return ok && now > p.limitHits
}

// StartIn is the cgroup hop (#136 (a)): under the lock the runner moves into
// the plugin cgroup, checks it is there, calls start (whose child is born
// there) and moves back to supervisor, even when start failed. An error
// after a successful start still leaves the child running in this cgroup;
// the caller kills it and ends the job.
func (p *Plugin) StartIn(start func() error) error {
	c := p.c
	c.mu.Lock()
	defer c.mu.Unlock()
	var err error
	if err = c.d.FS.WriteFile(p.name+"/cgroup.procs", c.pid()); err != nil {
		err = fmt.Errorf("runner: enter plugin cgroup: %w", err)
	} else if at, herr := c.here(); herr != nil || at != path.Join(c.d.Base, p.name) {
		err = errors.New("runner: not in the plugin cgroup")
	} else {
		err = start()
	}
	return errors.Join(err, c.ensureSupervisor())
}

// Kill writes cgroup.kill for the plugin cgroup, after making sure the
// runner is not inside it.
func (p *Plugin) Kill() error {
	c := p.c
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.kill(p.name)
}

func (c *Cgroups) kill(name string) error {
	if err := c.ensureSupervisor(); err != nil {
		return err
	}
	if err := c.d.FS.WriteFile(name+"/cgroup.kill", []byte("1")); err != nil {
		return fmt.Errorf("runner: cgroup.kill: %w", err)
	}
	return nil
}

// WaitEmpty polls cgroup.events until "populated 0", at most 5 s.
func (p *Plugin) WaitEmpty(ctx context.Context) error { return p.c.waitEmpty(ctx, p.name) }

// Remove deletes the (empty) plugin cgroup.
func (p *Plugin) Remove() error {
	if err := p.c.d.FS.Remove(p.name); err != nil {
		return fmt.Errorf("runner: remove plugin cgroup: %w", err)
	}
	return nil
}

func (c *Cgroups) waitEmpty(ctx context.Context, name string) error {
	ctx, cancel := context.WithTimeout(ctx, emptyWait)
	defer cancel()
	t := time.NewTicker(pollEvery)
	defer t.Stop()
	for {
		b, err := c.d.FS.ReadFile(name + "/cgroup.events")
		if err != nil {
			return fmt.Errorf("runner: read cgroup.events: %w", err)
		}
		for line := range bytes.Lines(b) {
			if f := bytes.Fields(line); len(f) == 2 && string(f[0]) == "populated" && string(f[1]) == "0" {
				return nil
			}
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("runner: cgroup not empty: %w", ctx.Err())
		case <-t.C:
		}
	}
}
