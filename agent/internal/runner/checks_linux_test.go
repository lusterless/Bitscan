// TP-M10-06 Linux row (tester-m10): a FIFO at the agent_id path is refused at
// once and never blocks the runner (#132 (a); builder checklist 14).
package runner

import (
	"path/filepath"
	"syscall"
	"testing"
	"time"

	"bitscan.local/agent/internal/runner/proto"
)

func TestChecksAgentIDFIFOLinux(t *testing.T) {
	p := filepath.Join(t.TempDir(), "agent_id")
	if err := syscall.Mkfifo(p, 0o600); err != nil {
		t.Fatal(err)
	}
	done := make(chan proto.Reason, 1)
	go func() {
		got, _ := NewChecks(p).Check(req(jobN(1), nil), now0)
		done <- got
	}()
	select {
	case got := <-done:
		if got != proto.ReasonAgentIDUnreadable {
			t.Fatalf("FIFO: %q, want agent_id_unreadable", got)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("a FIFO at the agent_id path blocked the check")
	}
}
