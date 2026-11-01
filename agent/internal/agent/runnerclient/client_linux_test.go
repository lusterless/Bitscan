// TP-M10-11 Linux row (tester-m10): a bound Unix socket with no listener
// (ECONNREFUSED) → connect. Linux only: syscall.Bind of AF_UNIX fails with
// "invalid argument" on Windows (reviewer-m10, TASK-218 finding 1).
package runnerclient_test

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/runnerclient"
	"bitscan.local/agent/internal/runner/proto"
)

// CHK-M10-052 (ECONNREFUSED part).
func TestConnectRefusedLinux(t *testing.T) {
	p := filepath.Join(t.TempDir(), "dead.sock")
	fd, err := syscall.Socket(syscall.AF_UNIX, syscall.SOCK_STREAM, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = syscall.Close(fd) }()
	if err := syscall.Bind(fd, &syscall.SockaddrUnix{Name: p}); err != nil {
		t.Fatal(err)
	}
	c := &runnerclient.Client{Socket: p, Clock: newClock()}
	if w := word(c.Run(context.Background(), job(1), 1, func(proto.Result) error { return nil })); w != "connect" {
		t.Fatalf("%s", w)
	}
}

// TestEACCESChild is the child side of TestConnectPermissionDeniedLinux; it
// does nothing unless RC_EACCES_SOCK is set. It runs as nobody.
func TestEACCESChild(t *testing.T) {
	sock := os.Getenv("RC_EACCES_SOCK")
	if sock == "" {
		return
	}
	c := &runnerclient.Client{Socket: sock} // the real clock: a busy retry would take 30 s
	n := 0
	start := time.Now()
	err := c.Run(context.Background(), job(1), 1, func(proto.Result) error { n++; return nil })
	var f *runnerclient.Failure
	fmt.Printf("WORD=%s FAILURE=%v CTX=%v RESULTS=%d UID=%d SECONDS=%.1f\n", word(err), errors.As(err, &f),
		errors.Is(err, context.Canceled), n, os.Getuid(), time.Since(start).Seconds())
	os.Exit(0)
}

// Builder checklist 21 (lead's TASK-218 r1 row): a peer that can't open the
// 0660 root-owned socket (EACCES) gets connect: a Failure, not a ctx stop,
// no result, not retried as busy.
func TestConnectPermissionDeniedLinux(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Fatal("needs root to run the client as nobody")
	}
	r := newRunner(t, []step{reply(accepted), res(t, 1), reply(done)})
	if err := os.Chmod(r.path, 0o660); err != nil { //nolint:gosec // the runner socket mode under test
		t.Fatal(err)
	}
	if err := os.Chmod(filepath.Dir(r.path), 0o755); err != nil { //nolint:gosec // nobody must reach the socket file
		t.Fatal(err)
	}
	// A copy of this test binary nobody can execute.
	bdir, err := os.MkdirTemp("", "rc-bin-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(bdir) })
	_ = os.Chmod(bdir, 0o755)           //nolint:gosec // nobody must execute the copy
	src, err := os.ReadFile(os.Args[0]) //nolint:gosec // the test binary itself
	if err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(bdir, "rc.test")
	if err := os.WriteFile(bin, src, 0o755); err != nil { //nolint:gosec // an executable copy for nobody
		t.Fatal(err)
	}
	cmd := exec.Command("setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", bin, "-test.run", "^TestEACCESChild$") //nolint:gosec // the test binary copy
	cmd.Env = append(os.Environ(), "RC_EACCES_SOCK="+r.path)
	cmd.Dir = bdir
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("child: %v %s", err, out)
	}
	s := string(out)
	t.Logf("RECORDED: %s", strings.TrimSpace(strings.Split(s, "\n")[0]))
	if !strings.Contains(s, "WORD=connect FAILURE=true CTX=false RESULTS=0 UID=65534") {
		t.Fatalf("child output %q", s)
	}
	i := strings.Index(s, "SECONDS=")
	secs, _ := strconv.ParseFloat(strings.Fields(s[i+8:])[0], 64)
	if secs > 5 {
		t.Fatalf("returned after %.1f s: retried as busy", secs)
	}
	if r.connections() != 0 {
		t.Fatalf("%d connections reached the runner", r.connections())
	}
}
