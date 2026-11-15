//go:build linux && delegated

// Two jobs at once in the real delegated cgroup (TS §3.5, §3.7, §8.3
// Sandbox; owner decision 2026-11-14): ending one job never kills the
// other's plugins or deletes its temp directory, and a plugin that hid in
// the other job's cgroup dies when that job ends.
package runner

import (
	"context"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"bitscan.local/agent/internal/runner/proto"
)

func TestDelegatedTwoJobsAtOnce(t *testing.T) {
	e, _ := newExec(t, nil)
	m := mountOf(e.CG)
	const markA, markHide = "300.2241", "300.2242"
	// Job A: one plugin that records its temp directory and sleeps.
	dirFile := filepath.Join(t.TempDir(), "a-dir")
	aDone := make(chan error, 1)
	var aOut []string
	go func() {
		aDone <- e.Run(context.Background(), jobOf(1, nil, plug(1, "pwd > "+dirFile+"; sleep "+markA+" & wait", 30)),
			func(r proto.Result) error { aOut = append(aOut, r.Item().Stdout); return nil })
	}()
	// Wait until A's plugin runs.
	deadline := time.Now().Add(10 * time.Second)
	for len(sleepers(markA)) == 0 {
		if time.Now().After(deadline) {
			t.Fatal("job A's plugin did not start")
		}
		time.Sleep(20 * time.Millisecond)
	}
	aDirB, _ := os.ReadFile(dirFile) //nolint:gosec // the test's own temp file
	aDir := strings.TrimSpace(string(aDirB))
	jobADir := filepath.Dir(aDir)
	// Job B: hides a sleeper in A's plugin cgroup, then ends at once.
	hide := `own=$(cut -d: -f3 /proc/self/cgroup); own=${own%/*}; own=${own##*/}; ` +
		`for d in ` + m + `/plugins/j-*/p-*; do case "$d" in */"$own"/*) ;; *) target=$d;; esac; done; ` +
		`sh -c 'echo $$ > '"$target"'/cgroup.procs; exec sleep ` + markHide + `' >/dev/null 2>&1 & sleep 0.3`
	r := runJob(t, e, context.Background(), jobOf(1, nil, plug(2, hide, 10)), 20*time.Second, nil)
	if r.err != nil || len(r.out) != 1 {
		t.Fatalf("job B: %v, %d results", r.err, len(r.out))
	}
	// B has ended: A's plugin, A's temp directory and the sleeper hidden in
	// A's cgroup are all still there.
	if len(sleepers(markA)) == 0 {
		t.Fatal("job B's end killed job A's plugin")
	}
	if _, err := os.Stat(jobADir); err != nil { //nolint:gosec // the runner's temp directory the plugin reported
		t.Fatalf("job B's end removed job A's temp directory %s: %v", jobADir, err)
	}
	if len(sleepers(markHide)) == 0 {
		t.Fatal("the test plant failed: no sleeper hidden in job A's cgroup")
	}
	// End A: its plugin and the hidden one die, its temp directory goes.
	killSleepers(markA)
	select {
	case err := <-aDone:
		if err != nil {
			t.Fatalf("job A: %v", err)
		}
	case <-time.After(30 * time.Second):
		t.Fatal("job A did not end")
	}
	time.Sleep(200 * time.Millisecond)
	if s := sleepers(markHide); len(s) > 0 {
		t.Fatalf("the plugin hidden in job A's cgroup survived job A's end: %v", s)
	}
	if _, err := os.Stat(jobADir); err == nil { //nolint:gosec // the runner's temp directory the plugin reported
		t.Fatalf("job A's temp directory %s left after its end", jobADir)
	}
	if err := e.Idle(context.Background()); err != nil {
		t.Fatal(err)
	}
	assertNothingLeft(t, e, markA)
}

// killSleepers kills the processes sleepers lists ("<pid>: <cmdline>"),
// so a job's plugin ends normally.
func killSleepers(marker string) {
	for _, s := range sleepers(marker) {
		pid, _, _ := strings.Cut(s, ":")
		if n, err := strconv.Atoi(pid); err == nil {
			_ = syscall.Kill(n, syscall.SIGKILL)
		}
	}
}
