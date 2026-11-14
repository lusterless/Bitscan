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
// §3.5 L250, §3.7 L284; #138 (a)), when no job runs and at start-up:
//   - other pids in the subtree root, in supervisor (the runner's ancestors,
//     which cannot be killed whole) and in plugins (kept for its shared task
//     limit) get SIGKILL through a pidfd;
//   - every other cgroup, the children of supervisor and plugins included,
//     gets cgroup.kill, is waited empty and removed, children first.
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

// JobSweep is the end of one job while other jobs may run (TS §3.5, §3.7;
// owner decision 2026-11-14). It kills, waits empty and removes the job's
// cgroup subtree and every other cgroup in the runner's subtree that is not
// supervisor, plugins or a running job's (one a plugin made to hide in, under
// the root, supervisor or plugins), and kills any process other than the
// runner in the root, supervisor or plugins, where no plugin of a running job
// can be (each is born in its own cgroup under the spawn lock). Only a plugin that moved
// itself into another running job's cgroup survives; that job's end, or the
// full Sweep when no job runs, kills it (TS §8.1, accepted). Passes repeat
// until one finds nothing; after 5 s it fails and the runner must exit.
func (j *Job) JobSweep(ctx context.Context) error {
	c := j.c
	c.mu.Lock()
	defer c.mu.Unlock()
	delete(c.live, j.name)
	ctx, cancel := context.WithTimeout(ctx, emptyWait)
	defer cancel()
	for {
		busy, err := c.jobSweepOnce(ctx)
		if err != nil || !busy {
			return err
		}
		select {
		case <-ctx.Done():
			return errors.New("runner: job sweep: processes left")
		case <-time.After(pollEvery):
		}
	}
}

// jobSweepOnce is sweepOnce that spares the cgroups of running jobs.
// Callers hold c.mu.
func (c *Cgroups) jobSweepOnce(ctx context.Context) (bool, error) {
	if err := c.ensureSupervisor(); err != nil {
		return false, err
	}
	busy := false
	for _, dir := range []string{".", supervisor, pluginsDir} {
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
			if dir == "." && (sub == supervisor || sub == pluginsDir) {
				continue
			}
			if dir == pluginsDir && c.live[path.Join(dir, sub)] {
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

func (c *Cgroups) sweepOnce(ctx context.Context) (bool, error) {
	if err := c.ensureSupervisor(); err != nil {
		return false, err
	}
	busy := false
	for _, dir := range []string{".", supervisor, pluginsDir} {
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
			if dir == "." && (sub == supervisor || sub == pluginsDir) {
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
