// Per-job cgroups and the per-job sweep (TS §3.5, §3.7, §8.3 Agent; owner
// decision 2026-11-14): ending one job kills only that job's subtree and
// strays outside every running job, never another running job's plugins.
package runner

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"testing"
)

func cgroupDirs(f *fakeCG) []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	var dirs []string
	for d := range f.dirs {
		dirs = append(dirs, d)
	}
	sort.Strings(dirs)
	return dirs
}

// Names come from the runner only: plugins/j-<n> for jobs, so every job's
// plugins share the plugins task limit, and plugins/j-<n>/p-<m> for their
// plugins, numbered per job.
func TestCgroupJobNames(t *testing.T) {
	f := newFakeCG()
	c := f.cg()
	if err := c.Setup(); err != nil {
		t.Fatal(err)
	}
	j1, err := c.NewJob()
	if err != nil {
		t.Fatal(err)
	}
	j2, _ := c.NewJob()
	p1, _ := j1.NewPlugin()
	p2, _ := j1.NewPlugin()
	q1, _ := j2.NewPlugin()
	got := fmt.Sprint(j1.name, " ", j2.name, " ", p1.name, " ", p2.name, " ", q1.name)
	if got != "plugins/j-1 plugins/j-2 plugins/j-1/p-1 plugins/j-1/p-2 plugins/j-2/p-1" {
		t.Fatalf("names %s", got)
	}
}

// Ending job 1 while job 2 runs: job 1's plugins, cgroup and its nested
// cgroups die and go; strays in the root, in supervisor or in cgroups no
// running job owns die and go; job 2's plugins and cgroups are untouched.
// A process that moved into job 2's cgroup survives until job 2 ends.
func TestCgroupJobSweepSparesOtherJobs(t *testing.T) {
	f := newFakeCG()
	c := f.cg()
	if err := c.Setup(); err != nil {
		t.Fatal(err)
	}
	j1, _ := c.NewJob()
	j2, _ := c.NewJob()
	p1, _ := j1.NewPlugin()
	p2, _ := j2.NewPlugin()
	f.spawnAt(301, p1.name)           // job 1's plugin
	f.spawnAt(302, p1.name+"/nest")   // a cgroup it made under its own
	f.spawnAt(311, p2.name)           // job 2's plugin
	f.spawnAt(312, j2.name+"/mine")   // a cgroup job 2's plugin made in job 2
	f.spawnAt(321, "supervisor")      // a plugin that moved into supervisor
	f.spawnAt(322, "")                // into the service root
	f.spawnAt(323, "supervisor/evil") // nested under supervisor
	f.spawnAt(324, "hide")            // a cgroup made in the root
	f.spawnAt(325, "plugins/j-99")    // a job-like name no running job owns
	f.spawnAt(326, "plugins")         // into plugins itself
	f.spawnAt(327, "plugins/stray")   // a cgroup made in plugins
	f.spawnAt(331, p2.name+"/moved")  // job 1's plugin hid in job 2's cgroup
	if err := j1.JobSweep(context.Background()); err != nil {
		t.Fatal(err)
	}
	for _, pid := range []int{301, 302, 321, 322, 323, 324, 325, 326, 327} {
		if !f.dead[pid] {
			t.Errorf("pid %d survived job 1's end", pid)
		}
	}
	for _, pid := range []int{311, 312, 331} {
		if f.dead[pid] {
			t.Errorf("pid %d of the running job 2 was killed by job 1's end", pid)
		}
	}
	if cg, ok := f.where(100); !ok || cg != "supervisor" {
		t.Fatalf("runner in %q alive %v", cg, ok)
	}
	dirs := cgroupDirs(f)
	for _, gone := range []string{j1.name, p1.name, "supervisor/evil", "hide", "plugins/j-99", "plugins/stray"} {
		if slices.Contains(dirs, gone) {
			t.Errorf("cgroup %s left after job 1's end: %q", gone, dirs)
		}
	}
	for _, kept := range []string{j2.name, p2.name, j2.name + "/mine", p2.name + "/moved"} {
		if !slices.Contains(dirs, kept) {
			t.Errorf("cgroup %s of the running job 2 removed: %q", kept, dirs)
		}
	}
	// Job 2's end takes everything left, the hidden process included.
	if err := j2.JobSweep(context.Background()); err != nil {
		t.Fatal(err)
	}
	for _, pid := range []int{311, 312, 331} {
		if !f.dead[pid] {
			t.Errorf("pid %d survived job 2's end", pid)
		}
	}
	if got := fmt.Sprint(cgroupDirs(f)); got != "[ plugins supervisor]" {
		t.Fatalf("cgroups left after both jobs: %s", got)
	}
}

// The full sweep, when no job runs, still removes every job cgroup.
func TestCgroupFullSweepTakesJobCgroups(t *testing.T) {
	f := newFakeCG()
	c := f.cg()
	if err := c.Setup(); err != nil {
		t.Fatal(err)
	}
	j, _ := c.NewJob()
	p, _ := j.NewPlugin()
	f.spawnAt(401, p.name)
	if err := c.Sweep(context.Background()); err != nil {
		t.Fatal(err)
	}
	if !f.dead[401] {
		t.Fatal("a job's plugin survived the full sweep")
	}
	if got := fmt.Sprint(cgroupDirs(f)); got != "[ plugins supervisor]" {
		t.Fatalf("cgroups left: %s", got)
	}
}

// A job's plugin keeps main's limits (decisions 2026-11-13): the job cgroup
// passes the cpu controller on, the plugin gets the runner's cpu.max, and
// the shared plugins/pids.max covers it, since the job sits inside plugins.
func TestCgroupJobPluginKeepsLimits(t *testing.T) {
	f := newFakeCG()
	f.ownCPUMax, f.ownPidsMax = "25000 100000\n", "64\n"
	c := f.cg()
	if err := c.Setup(); err != nil {
		t.Fatal(err)
	}
	j, err := c.NewJob()
	if err != nil {
		t.Fatal(err)
	}
	p, err := j.NewPlugin()
	if err != nil {
		t.Fatal(err)
	}
	if got := f.cpuMax[p.name]; got != "25000 100000" {
		t.Errorf("%s cpu.max %q", p.name, got)
	}
	if got := f.pidsMax["plugins"]; got != "48" {
		t.Errorf("plugins/pids.max %q", got)
	}
	if !p.watch {
		t.Error("the job's plugin does not watch the shared task limit")
	}
}

// Without a CPU limit no controller is passed on and the job still starts.
func TestCgroupJobWithoutCPULimit(t *testing.T) {
	f := newFakeCG()
	c := f.cg()
	if err := c.Setup(); err != nil {
		t.Fatal(err)
	}
	j, err := c.NewJob()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := j.NewPlugin(); err != nil {
		t.Fatal(err)
	}
	if f.ctl[j.name]["cpu"] {
		t.Error("cpu passed on with no CPU limit")
	}
}
