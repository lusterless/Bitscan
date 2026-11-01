package runner

import (
	"context"
	"errors"
	"fmt"
	"path"
	"slices"
	"strconv"
	"strings"
	"time"
)

// Sweep kills every process in the runner's subtree except the runner (TS
// §3.5 L250, §3.7 L284; #138 (a)), after every job and at start-up:
//   - other pids in the subtree root and in supervisor (the runner's
//     ancestors, which cannot be killed whole) get SIGKILL through a pidfd;
//   - every other cgroup, supervisor's children included, gets cgroup.kill,
//     is waited empty and removed, children first.
//
// Passes repeat until one finds nothing, so a process that moved between
// cgroups during a pass is caught by the next; after 5 s the sweep fails and
// the runner must exit (systemd then kills the whole service cgroup).
func (c *Cgroups) Sweep(ctx context.Context) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	ctx, cancel := context.WithTimeout(ctx, emptyWait)
	defer cancel()
	for {
		busy, err := c.sweepOnce(ctx)
		if err != nil || !busy {
			return err
		}
		select {
		case <-ctx.Done():
			return errors.New("runner: sweep: processes left in the subtree")
		case <-time.After(pollEvery):
		}
	}
}

func (c *Cgroups) sweepOnce(ctx context.Context) (bool, error) {
	if err := c.ensureSupervisor(); err != nil {
		return false, err
	}
	busy := false
	for _, dir := range []string{".", supervisor} {
		killed, err := c.killPids(dir)
		if err != nil {
			return false, err
		}
		subs, err := c.subdirs(dir)
		if err != nil {
			return false, err
		}
		busy = busy || killed
		for _, sub := range subs {
			if dir == "." && sub == supervisor {
				continue
			}
			if err := c.killTree(ctx, path.Join(dir, sub)); err != nil {
				return false, err
			}
			busy = true
		}
	}
	return busy, nil
}

// subdirs lists child cgroups. Entries that are not plain directories
// (symlinks included) or have an unusable name are never followed.
func (c *Cgroups) subdirs(dir string) ([]string, error) {
	entries, err := c.d.FS.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("runner: list cgroup: %w", err)
	}
	var out []string
	for _, e := range entries {
		n := e.Name()
		if e.IsDir() && n != "" && n != "." && n != ".." && !strings.ContainsAny(n, `/\`) {
			out = append(out, n)
		}
	}
	return out, nil
}

func (c *Cgroups) killPids(dir string) (bool, error) {
	procs := path.Join(dir, "cgroup.procs")
	b, err := c.d.FS.ReadFile(procs)
	if err != nil {
		return false, fmt.Errorf("runner: read cgroup.procs: %w", err)
	}
	killed := false
	for _, f := range strings.Fields(string(b)) {
		pid, err := strconv.Atoi(f)
		if err != nil || pid == c.d.Self || pid <= 0 {
			continue
		}
		still := func() bool {
			now, err := c.d.FS.ReadFile(procs)
			return err == nil && slices.Contains(strings.Fields(string(now)), f)
		}
		// A failed kill (the process already gone) is seen by the next pass.
		_ = c.d.KillPid(pid, still)
		killed = true
	}
	return killed, nil
}

// killTree kills cgroup dir with everything below it, waits for it to
// empty, then removes it, children first.
func (c *Cgroups) killTree(ctx context.Context, dir string) error {
	if err := c.kill(dir); err != nil {
		return err
	}
	if err := c.waitEmpty(ctx, dir); err != nil {
		return err
	}
	return c.removeTree(dir)
}

func (c *Cgroups) removeTree(dir string) error {
	subs, err := c.subdirs(dir)
	if err != nil {
		return err
	}
	for _, sub := range subs {
		if err := c.removeTree(path.Join(dir, sub)); err != nil {
			return err
		}
	}
	if err := c.d.FS.Remove(dir); err != nil {
		return fmt.Errorf("runner: remove cgroup: %w", err)
	}
	return nil
}
