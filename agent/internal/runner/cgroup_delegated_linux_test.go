//go:build linux && delegated

// TP-M10-08 delegated rows (tester-m10): the real cgroup v2 code inside a
// delegated cgroup. Run only as
//
//	go test -c -tags delegated -o runner.test ./internal/runner/
//	systemd-run --wait --pipe --collect -p Delegate=yes -p CPUQuota=25% -p TasksMax=64 ./runner.test -test.run Delegated -test.v
//
// CPUQuota=25% and TasksMax=64 are the runner unit's own (TS §3.7); the CPU
// and task limit rows need them.
//
// (WSL Ubuntu 24.04 with cgroup2fs, or CI). Harmless payloads only: cat and
// sleep.
package runner

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

func ownCgroupPath(t *testing.T) string {
	t.Helper()
	b, err := os.ReadFile("/proc/self/cgroup")
	if err != nil {
		t.Fatal(err)
	}
	p, err := parseSelfCgroup(b)
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func pidCgroup(t *testing.T, pid int) string {
	t.Helper()
	b, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/cgroup")
	if err != nil {
		return "<gone>"
	}
	return strings.TrimSpace(strings.TrimPrefix(string(b), "0::"))
}

type stray struct {
	cmd  *exec.Cmd
	done chan struct{}
}

func startSleep(t *testing.T) *stray {
	t.Helper()
	cmd := exec.Command("/bin/sleep", "300")
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	s := &stray{cmd: cmd, done: make(chan struct{})}
	go func() { _ = cmd.Wait(); close(s.done) }()
	t.Cleanup(func() { _ = cmd.Process.Kill() })
	return s
}

func (s *stray) deadWithin(d time.Duration) bool {
	select {
	case <-s.done:
		return true
	case <-time.After(d):
		return false
	}
}

func moveTo(t *testing.T, cgdir string, pid int) {
	t.Helper()
	if err := os.MkdirAll(cgdir, 0o750); err != nil && !errors.Is(err, fs.ErrExist) {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(cgdir, "cgroup.procs"), []byte(strconv.Itoa(pid)), 0o600); err != nil {
		t.Fatalf("move %d to %s: %v", pid, cgdir, err)
	}
}

func TestDelegatedCgroups(t *testing.T) {
	base := ownCgroupPath(t)
	t.Logf("RECORDED: own cgroup at start %s", base)
	recordIdentity(t)
	mount := filepath.Join("/sys/fs/cgroup", base)
	c, err := Open(slog.New(slog.NewTextHandler(os.Stderr, nil)))
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	// REQ-238 (2) part: the runner's own cgroup ends in /supervisor.
	if got := ownCgroupPath(t); got != base+"/supervisor" {
		t.Fatalf("runner in %s, want %s/supervisor", got, base)
	}

	t.Run("plugin cgroup carries the runner's CPU limit", func(t *testing.T) {
		own, err := os.ReadFile(filepath.Join(mount, "cpu.max")) //nolint:gosec // the runner's own cgroup file
		of := strings.Fields(string(own))
		if err != nil || len(of) != 2 || of[0] == "max" {
			t.Fatalf("own cgroup cpu.max %q (%v): run with -p CPUQuota=25%% as the runner unit has", own, err)
		}
		p, err := c.NewPlugin()
		if err != nil {
			t.Fatal(err)
		}
		got, err := os.ReadFile(filepath.Join(mount, p.name, "cpu.max")) //nolint:gosec // the plugin cgroup the runner just made
		if err != nil || strings.Join(strings.Fields(string(got)), " ") != strings.Join(of, " ") {
			t.Fatalf("%s cpu.max %q (%v), want the runner's %q", p.name, got, err, own)
		}
		// A Go program started there (this binary as a probe, with only PATH
		// and the probe switch, no GOMAXPROCS) sizes itself from that limit.
		cmd := exec.Command(os.Args[0]) //nolint:gosec // this test binary, as the probe
		cmd.Env = []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin", goProbeEnv + "=1"}
		var out strings.Builder
		cmd.Stdout = &out
		if err := p.StartIn(cmd.Start); err != nil {
			t.Fatalf("StartIn: %v", err)
		}
		if err := cmd.Wait(); err != nil {
			t.Fatalf("probe: %v", err)
		}
		quota, _ := strconv.ParseFloat(of[0], 64)
		period, _ := strconv.ParseFloat(of[1], 64)
		want := min(runtime.NumCPU(), max(2, int(math.Ceil(quota/period))))
		var procs, threads int
		if _, err := fmt.Sscanf(out.String(), "gomaxprocs=%d threads=%d", &procs, &threads); err != nil {
			t.Fatalf("probe printed %q", out.String())
		}
		t.Logf("RECORDED: %d CPUs, plugin cpu.max %q: probe GOMAXPROCS=%d, %d threads", runtime.NumCPU(), strings.TrimSpace(string(got)), procs, threads)
		if procs != want {
			t.Errorf("probe GOMAXPROCS=%d, want %d from the plugin's cpu.max", procs, want)
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
	})

	t.Run("plugins share the task limit and a refused fork is seen", func(t *testing.T) {
		own, err := os.ReadFile(filepath.Join(mount, "pids.max")) //nolint:gosec // the runner's own cgroup file
		n, perr := strconv.Atoi(strings.TrimSpace(string(own)))
		if err != nil || perr != nil {
			t.Fatalf("own pids.max %q (%v): run with -p TasksMax=64 as the runner unit has", own, err)
		}
		got, err := os.ReadFile(filepath.Join(mount, "plugins", "pids.max")) //nolint:gosec // the cgroup the runner made
		if err != nil || strings.TrimSpace(string(got)) != strconv.Itoa(n-taskReserve) {
			t.Fatalf("plugins/pids.max %q (%v), want %d (own %d less %d)", got, err, n-taskReserve, n, taskReserve)
		}
		p, err := c.NewPlugin()
		if err != nil {
			t.Fatal(err)
		}
		// A plugin that tries to start more processes than the whole unit
		// allows: the shared limit refuses the excess, not the runner's.
		script := fmt.Sprintf("i=0; while [ $i -lt %d ]; do sleep 30 & i=$((i+1)); done 2>/dev/null; true", n)
		cmd := exec.Command("/bin/sh", "-c", script) //nolint:gosec // a fixed harmless payload: sleeps
		if err := p.StartIn(cmd.Start); err != nil {
			t.Fatalf("StartIn: %v", err)
		}
		_ = cmd.Wait()
		// The plugin's sleeps are still alive, holding their tasks; the
		// runner can still start a task of its own.
		if err := exec.Command("/bin/true").Run(); err != nil {
			t.Errorf("the runner could not start a process beside the full plugins cgroup: %v", err)
		}
		if !p.HitTaskLimit() {
			t.Error("HitTaskLimit false after the shared limit refused forks")
		}
		ev, _ := os.ReadFile(filepath.Join(mount, "plugins", "pids.events")) //nolint:gosec // the cgroup the runner made
		t.Logf("RECORDED: plugins/pids.max %s, plugins/pids.events %q", strings.TrimSpace(string(got)), strings.TrimSpace(string(ev)))
		if err := p.Kill(); err != nil {
			t.Fatal(err)
		}
		if err := p.WaitEmpty(context.Background()); err != nil {
			t.Fatal(err)
		}
		if err := p.Remove(); err != nil {
			t.Fatal(err)
		}
	})

	t.Run("plugin born in its own cgroup (REQ-238 (2), (3))", func(t *testing.T) {
		p, err := c.NewPlugin()
		if err != nil {
			t.Fatal(err)
		}
		cmd := exec.Command("/bin/sh", "-c", "cat /proc/self/cgroup; sleep 30 & cat /proc/$!/cgroup; wait")
		out, err := cmd.StdoutPipe()
		if err != nil {
			t.Fatal(err)
		}
		if err := p.StartIn(cmd.Start); err != nil {
			t.Fatalf("StartIn: %v", err)
		}
		if got := ownCgroupPath(t); got != base+"/supervisor" {
			t.Fatalf("runner not back in supervisor: %s", got)
		}
		sc := bufio.NewScanner(out)
		var lines []string
		for len(lines) < 2 && sc.Scan() {
			lines = append(lines, strings.TrimPrefix(sc.Text(), "0::"))
		}
		want := base + "/" + p.name
		if len(lines) != 2 || lines[0] != want || lines[1] != want {
			t.Fatalf("plugin and its first fork in %q, want both %s", lines, want)
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
		werr := make(chan error, 1)
		go func() { werr <- cmd.Wait() }()
		select {
		case <-werr:
		case <-time.After(3 * time.Second):
			t.Fatal("the plugin shell outlived cgroup.kill")
		}
		if _, err := os.Stat(filepath.Join(mount, p.name)); !errors.Is(err, fs.ErrNotExist) {
			t.Fatal("the plugin cgroup is still there")
		}
	})

	t.Run("sweep kills strays everywhere (CHK-M10-103)", func(t *testing.T) {
		s1 := startSleep(t) // born in supervisor
		s2 := startSleep(t)
		moveTo(t, filepath.Join(mount, "supervisor", "x"), s2.cmd.Process.Pid)
		s3 := startSleep(t)
		moveTo(t, filepath.Join(mount, "p-77"), s3.cmd.Process.Pid)
		s4 := startSleep(t)
		moveTo(t, filepath.Join(mount, "p-77", "child"), s4.cmd.Process.Pid)
		s5 := startSleep(t)
		moveTo(t, filepath.Join(mount, "q", "r"), s5.cmd.Process.Pid)
		s7 := startSleep(t)
		moveTo(t, filepath.Join(mount, "plugins", "p-99"), s7.cmd.Process.Pid)
		s6 := startSleep(t)
		rootMove := os.WriteFile(filepath.Join(mount, "cgroup.procs"), []byte(strconv.Itoa(s6.cmd.Process.Pid)), 0o600)
		t.Logf("RECORDED: moving a stray into the service root: %v (cgroup %s)", rootMove, pidCgroup(t, s6.cmd.Process.Pid))
		if err := c.Sweep(context.Background()); err != nil {
			t.Fatalf("Sweep: %v", err)
		}
		for i, s := range []*stray{s1, s2, s3, s4, s5, s6, s7} {
			if !s.deadWithin(3 * time.Second) {
				t.Errorf("stray %d survived the sweep (cgroup %s)", i+1, pidCgroup(t, s.cmd.Process.Pid))
			}
		}
		ents, err := os.ReadDir(mount)
		if err != nil {
			t.Fatal(err)
		}
		var dirs []string
		for _, e := range ents {
			if e.IsDir() {
				dirs = append(dirs, e.Name())
			}
		}
		if strings.Join(dirs, ",") != "plugins,supervisor" {
			t.Fatalf("service subtree after the sweep: %v (REQ-238 (4))", dirs)
		}
		for _, keep := range []string{"supervisor", "plugins"} {
			sub, _ := os.ReadDir(filepath.Join(mount, keep))
			for _, e := range sub {
				if e.IsDir() {
					t.Fatalf("a cgroup left under %s: %s", keep, e.Name())
				}
			}
		}
		if got := ownCgroupPath(t); got != base+"/supervisor" {
			t.Fatalf("runner in %s after the sweep", got)
		}
		if err := syscall.Kill(os.Getpid(), 0); err != nil {
			t.Fatal("the runner is not alive")
		}
	})

	t.Run("runner moved by a plugin is moved back (CHK-M10-104)", func(t *testing.T) {
		moveTo(t, filepath.Join(mount, "p-88"), os.Getpid())
		if got := ownCgroupPath(t); got != base+"/p-88" {
			t.Fatalf("setup: runner in %s", got)
		}
		s := startSleep(t) // born beside the runner in p-88
		if err := c.Sweep(context.Background()); err != nil {
			t.Fatalf("Sweep: %v", err)
		}
		if got := ownCgroupPath(t); got != base+"/supervisor" {
			t.Fatalf("runner in %s, want supervisor", got)
		}
		if !s.deadWithin(3 * time.Second) {
			t.Fatal("the plugin beside the moved runner survived")
		}
	})

	t.Run("kill a forked tree (CHK-M10-105)", func(t *testing.T) {
		p, err := c.NewPlugin()
		if err != nil {
			t.Fatal(err)
		}
		cmd := exec.Command("/bin/sh", "-c", "sleep 300 & sleep 300 & (sleep 300 &) ; wait")
		if err := p.StartIn(cmd.Start); err != nil {
			t.Fatal(err)
		}
		time.Sleep(200 * time.Millisecond) // let the shell fork (only for the test's own children)
		if err := p.Kill(); err != nil {
			t.Fatal(err)
		}
		start := time.Now()
		if err := p.WaitEmpty(context.Background()); err != nil {
			t.Fatal(err)
		}
		t.Logf("RECORDED: populated 0 after %v", time.Since(start))
		if err := p.Remove(); err != nil {
			t.Fatal(err)
		}
		_ = cmd.Wait()
	})
}

// recordIdentity logs the uid, gid and capability sets the test runs with,
// so the evidence shows whether a row ran as root or as the unit's user.
func recordIdentity(t *testing.T) {
	t.Helper()
	b, _ := os.ReadFile("/proc/self/status")
	var caps []string
	for _, l := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(l, "Cap") || strings.HasPrefix(l, "NoNewPrivs") {
			caps = append(caps, strings.ReplaceAll(l, "\t", " "))
		}
	}
	t.Logf("RECORDED: uid %d euid %d gid %d; %s", os.Getuid(), os.Geteuid(), os.Getgid(), strings.Join(caps, "; "))
}
