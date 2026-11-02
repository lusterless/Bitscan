// TP-M10-07 Linux rows (tester-m10): real processes. Harmless payloads only.
package runner

import (
	"context"
	"os/exec"
	"sync"
	"syscall"
	"testing"
	"time"

	"bitscan.local/agent/internal/redact"
)

// CHK-M10-046 (real wait statuses) and REQ-241 (3) at unit level.
func TestExitCodeRealProcessesLinux(t *testing.T) {
	for script, want := range map[string]int64{
		"exit 0": 0, "exit 3": 3, "exit 126": 126, "exit 255": 255,
		"kill -9 $$": 137, "kill -15 $$": 143, "kill -11 $$": 139,
		"no-such-command-m10": 127,
	} {
		cmd := exec.Command("/bin/sh", "-c", script) //nolint:gosec // fixed test scripts from the table above
		_ = cmd.Run()
		ws, ok := cmd.ProcessState.Sys().(syscall.WaitStatus)
		if !ok {
			t.Fatal("no wait status")
		}
		if got := ExitCode(ws); got != want {
			t.Errorf("%q: %d, want %d", script, got, want)
		}
	}
}

// CHK-M10-045: a process writing 3 MiB to stderr, then 3 MiB to stdout, ends
// when both pipes are captured concurrently (bounded by a 30 s test timeout,
// not a spec time).
func TestCaptureRealProcessBothPipesLinux(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "/bin/sh", "-c", "head -c 3145728 /dev/zero >&2; head -c 3145728 /dev/zero")
	so, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	se, err := cmd.StderrPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	var out, errc redact.Captured
	wg.Add(2)
	go func() { defer wg.Done(); out, _ = Capture(so) }()
	go func() { defer wg.Done(); errc, _ = Capture(se) }()
	wg.Wait()
	if err := cmd.Wait(); err != nil {
		t.Fatalf("the writer did not finish cleanly: %v", err)
	}
	if ctx.Err() != nil {
		t.Fatal("blocked until the test timeout")
	}
	if len(out.Data) != redact.ReadLimit || !out.Overflow || len(errc.Data) != redact.ReadLimit || !errc.Overflow {
		t.Fatalf("stdout %d %v stderr %d %v", len(out.Data), out.Overflow, len(errc.Data), errc.Overflow)
	}
}
