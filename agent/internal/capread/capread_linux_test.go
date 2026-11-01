// TP-M10-14 (tester-m10): the capread helper server, REQ-252 (1)–(4); #142;
// TS §3.7 L484, L493. Internal test (package capread): the two-name table is
// swapped for harmless test commands. Wall time is used only for the spec's
// 10 s timeout and the lead's "cut off after about 10 s" row.
package capread

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log/slog"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/sdsock"
)

type unixL struct{ *net.UnixListener }

func (u unixL) Accept() (*net.UnixConn, error) { return u.AcceptUnix() }

type lockedBuf struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (l *lockedBuf) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.b.Write(p)
}
func (l *lockedBuf) String() string { l.mu.Lock(); defer l.mu.Unlock(); return l.b.String() }

// withTable swaps the command table for the test.
func withTable(t *testing.T, table map[string][]string) {
	t.Helper()
	old := commands
	commands = table
	t.Cleanup(func() { commands = old })
}

func sh(script string) []string { return []string{"/bin/sh", "-c", script} }

// serveTest runs Serve on a fresh socket and returns its path and logs.
func serveTest(t *testing.T) (string, *lockedBuf) {
	t.Helper()
	dir, err := os.MkdirTemp("", "capread-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	path := filepath.Join(dir, "capread.sock")
	ln, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	logs := &lockedBuf{}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { defer close(done); _ = Serve(ctx, unixL{ln}, slog.New(slog.NewTextHandler(logs, nil))) }()
	t.Cleanup(func() { cancel(); <-done })
	return path, logs
}

// ask sends raw request bytes and returns the whole answer.
func ask(t *testing.T, path string, req string) string {
	t.Helper()
	c, err := net.Dial("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close() }()
	_ = c.SetDeadline(time.Now().Add(40 * time.Second))
	if req != "" {
		if _, err := c.Write([]byte(req)); err != nil {
			t.Fatal(err)
		}
	}
	if uc, ok := c.(*net.UnixConn); ok {
		_ = uc.CloseWrite()
	}
	b, _ := io.ReadAll(c)
	return string(b)
}

// CHK-M10-137: REQ-252 (1) the two names run their fixed argv with an empty
// environment; the answer is "ok" + stdout; stderr is never sent.
func TestNamesRunFixedArgvEmptyEnv(t *testing.T) {
	marker := filepath.Join(t.TempDir(), "argv")
	withTable(t, map[string][]string{
		"nft_ruleset": sh(`echo "$0 $*" > ` + marker + `; echo NFT-OUT; echo NFT-ERR >&2`),
		"audit_rules": sh(`echo AUDIT-OUT; pwd`),
		"env":         {"/usr/bin/env"}, // no shell: prints exactly the environment it got
	})
	t.Setenv("M10CANARY_ENV", "leak")
	path, logs := serveTest(t)
	got := ask(t, path, "nft_ruleset\n")
	if got != "ok\nNFT-OUT\n" {
		t.Fatalf("nft_ruleset answer %q (want ok + stdout only, no env, no stderr)", got)
	}
	argv, _ := os.ReadFile(marker) //nolint:gosec // test path
	if strings.TrimSpace(string(argv)) != "/bin/sh" {
		t.Fatalf("argv seen by the command: %q (no request text may reach it)", argv)
	}
	if got := ask(t, path, "audit_rules\n"); got != "ok\nAUDIT-OUT\n/\n" {
		t.Fatalf("audit_rules answer %q", got)
	}
	if got := ask(t, path, "env\n"); got != "ok\n" {
		t.Fatalf("the command's environment is not empty: %q (CHK-M10-373)", got)
	}
	if strings.Contains(logs.String(), "NFT-OUT") || strings.Contains(logs.String(), "CANARY") {
		t.Fatal("output or environment in the log")
	}
}

func TestRealTableIsTheSpecs(t *testing.T) {
	want := map[string]string{"nft_ruleset": "/usr/sbin/nft -j list ruleset", "audit_rules": "/usr/sbin/auditctl -l"}
	if len(commands) != 2 {
		t.Fatalf("%d entries", len(commands))
	}
	for k, v := range want {
		if strings.Join(commands[k], " ") != v || !Known(k) {
			t.Fatalf("%s → %q", k, commands[k])
		}
	}
	if Known("NFT_RULESET") || Known("") || Known("nft") {
		t.Fatal("Known accepts another name")
	}
	if Socket != "/run/bitscan/capread.sock" {
		t.Fatal(Socket)
	}
}

// CHK-M10-138: REQ-252 (1) refusals: error unknown_request and nothing run
// (CHK-M10-371, -372).
func TestRefusedRequests(t *testing.T) {
	ran := filepath.Join(t.TempDir(), "ran")
	withTable(t, map[string][]string{
		"nft_ruleset": sh("touch " + ran),
		"audit_rules": sh("touch " + ran),
	})
	path, _ := serveTest(t)
	for _, req := range []string{
		"nft_ruleset x\n", "NFT_RULESET\n", "../nft\n", "/usr/sbin/nft\n", "\n", strings.Repeat("a", 33),
		strings.Repeat("a", 32) + "\n", "nft_ruleset", "nft_ruleset\r\n", "audit_rules\nnft_ruleset\n", "bitscan_status\n",
		"nft_ruleset\x00\n", " nft_ruleset\n", "nft_ruleset \n", "",
	} {
		if got := ask(t, path, req); got != "error unknown_request\n" {
			t.Errorf("%q → %q", req, got)
		}
	}
	if _, err := os.Stat(ran); err == nil {
		t.Fatal("a refused request ran a command")
	}
}

// CHK-M10-140: REQ-252 (3) timeout, the 1 MiB cap, exit codes, a missing or
// non-executable binary (lead's row (b)).
func TestOutcomes(t *testing.T) {
	noexec := filepath.Join(t.TempDir(), "noexec")
	if err := os.WriteFile(noexec, []byte("#!/bin/sh\necho x\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	withTable(t, map[string][]string{
		"exact":       sh(`head -c 1048576 /dev/zero | tr '\0' 'a'`),
		"over":        sh(`head -c 1048577 /dev/zero | tr '\0' 'b'`),
		"fail3":       sh("echo partial; exit 3"),
		"killed":      sh("kill -9 $$"),
		"missing":     {"/usr/sbin/no-such-binary-m10", "-l"},
		"noexec":      {noexec},
		"slow":        sh("sleep 60"),
		"nft_ruleset": sh("true"),
	})
	path, _ := serveTest(t)
	if got := ask(t, path, "exact\n"); got != "ok\n"+strings.Repeat("a", 1048576) {
		t.Fatalf("exactly 1 MiB: %d bytes, prefix %q", len(got), got[:min(len(got), 10)])
	}
	if got := ask(t, path, "over\n"); got != "error too_large\n" {
		t.Fatalf("1 MiB + 1: %q… (%d bytes; none of the output may be sent)", got[:min(len(got), 20)], len(got))
	}
	if got := ask(t, path, "fail3\n"); got != "error failed 3\n" {
		t.Fatalf("exit 3: %q", got)
	}
	if got := ask(t, path, "killed\n"); got != "error failed 137\n" {
		t.Fatalf("SIGKILL: %q", got)
	}
	if got := ask(t, path, "missing\n"); got != "error not_installed\n" {
		t.Fatalf("missing binary: %q", got)
	}
	if got := ask(t, path, "noexec\n"); got != "error failed 126\n" {
		t.Fatalf("non-executable binary: %q", got)
	}
	start := time.Now()
	got := ask(t, path, "slow\n")
	d := time.Since(start)
	if got != "error timeout\n" || d < 9*time.Second || d > 12*time.Second {
		t.Fatalf("sleep 60: %q after %v (want error timeout at 10 s)", got, d)
	}
	if runTimeout != 10*time.Second || maxOutput != 1<<20 || maxRequest != 32 || readTimeout != 5*time.Second {
		t.Fatal("constants changed")
	}
}

// CHK-M10-141: REQ-252 (4) two clients at once are served one after another.
func TestSequential(t *testing.T) {
	stamp := filepath.Join(t.TempDir(), "stamps")
	withTable(t, map[string][]string{
		"nft_ruleset": sh(`echo start $(date +%s.%N) >> ` + stamp + `; sleep 1; echo end $(date +%s.%N) >> ` + stamp),
	})
	path, _ := serveTest(t)
	var wg sync.WaitGroup
	for range 2 {
		wg.Add(1)
		go func() { defer wg.Done(); _ = ask(t, path, "nft_ruleset\n") }()
	}
	wg.Wait()
	b, _ := os.ReadFile(stamp) //nolint:gosec // test path
	lines := strings.Fields(string(b))
	// start t1 end t2 start t3 end t4: ordered and not overlapping
	if len(lines) != 8 || lines[0] != "start" || lines[2] != "end" || lines[4] != "start" || lines[6] != "end" {
		t.Fatalf("stamps %q", lines)
	}
	e1, _ := strconv.ParseFloat(lines[3], 64)
	s2, _ := strconv.ParseFloat(lines[5], 64)
	if s2 < e1 {
		t.Fatalf("the second request started (%f) before the first ended (%f)", s2, e1)
	}
}

// CHK-M10-142: the request must arrive within 5 s; then the next client is
// served.
func TestRequestDeadline(t *testing.T) {
	withTable(t, map[string][]string{"nft_ruleset": sh("echo fine")})
	path, _ := serveTest(t)
	idle, err := net.Dial("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = idle.Close() }()
	start := time.Now()
	got := ask(t, path, "nft_ruleset\n")
	if got != "ok\nfine\n" || time.Since(start) > 8*time.Second {
		t.Fatalf("after an idle client: %q in %v", got, time.Since(start))
	}
	b := make([]byte, 64)
	_ = idle.SetReadDeadline(time.Now().Add(time.Second))
	if n, _ := idle.Read(b); n != 0 {
		t.Fatalf("the idle client got %q", b[:n])
	}
}

// Lead's row (a): a client that sends a request and never reads the reply is
// cut off after about 10 s, and the next client is then served.
func TestStalledReaderCutOff(t *testing.T) {
	withTable(t, map[string][]string{
		"big":         sh(`head -c 1000000 /dev/zero | tr '\0' 'c'`),
		"nft_ruleset": sh("echo next"),
	})
	path, _ := serveTest(t)
	stalled, err := net.Dial("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = stalled.Close() }()
	if _, err := stalled.Write([]byte("big\n")); err != nil {
		t.Fatal(err)
	}
	time.Sleep(200 * time.Millisecond) // the stalled client's request is first in line
	start := time.Now()
	ch := make(chan string, 1)
	go func() { ch <- ask(t, path, "nft_ruleset\n") }()
	select {
	case got := <-ch:
		d := time.Since(start)
		if got != "ok\nnext\n" || d < 8*time.Second || d > 15*time.Second {
			t.Fatalf("next client got %q after %v (want after about 10 s)", got, d)
		}
		t.Logf("RECORDED: the next client was served %v after the stalled one", d)
	case <-time.After(25 * time.Second):
		t.Fatal("a stalled reader held the helper (no write deadline)")
	}
}

// CHK-M10-139: REQ-252 (2) the peer check through the real sdsock (the child
// gets fd 3 like the systemd socket): uid 0 and any uid but the expected one
// are closed without a reply (CHK-M10-374).
func TestCapreadChild(t *testing.T) {
	if os.Getenv("CAPREAD_CHILD") != "1" {
		return
	}
	uid, _ := strconv.ParseUint(os.Getenv("CAPREAD_UID"), 10, 32)
	commands = map[string][]string{"nft_ruleset": sh("echo served"), "audit_rules": sh("echo served")}
	l, err := sdsock.FromSystemd(uint32(uid), slog.New(slog.NewTextHandler(os.Stderr, nil)))
	if err != nil {
		fmt.Println("REFUSED", err)
		os.Exit(1)
	}
	fmt.Println("READY")
	_ = Serve(context.Background(), l, slog.New(slog.NewTextHandler(os.Stderr, nil)))
	os.Exit(0)
}

func TestPeerCheckThroughSdsock(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Fatal("needs root (setpriv)")
	}
	dir, err := os.MkdirTemp("", "capread-peer-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	_ = os.Chmod(dir, 0o755) //nolint:gosec // peers of other uids
	path := filepath.Join(dir, "capread.sock")
	ln, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = ln.Close() }()
	_ = os.Chmod(path, 0o777) //nolint:gosec // reachable by every test uid
	f, err := ln.(*net.UnixListener).File()
	if err != nil {
		t.Fatal(err)
	}
	const runnerUID = 64990
	cmd := exec.Command("/bin/sh", "-c", `LISTEN_PID=$$ LISTEN_FDS=1 exec "$0" -test.run '^TestCapreadChild$' -test.count=1`, os.Args[0]) //nolint:gosec // the test binary
	cmd.Env = append(os.Environ(), "CAPREAD_CHILD=1", "CAPREAD_UID="+strconv.Itoa(runnerUID))
	cmd.ExtraFiles = []*os.File{f}
	out, errb := &lockedBuf{}, &lockedBuf{}
	cmd.Stdout, cmd.Stderr = out, errb
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = cmd.Process.Kill(); _ = cmd.Wait() })
	deadline := time.Now().Add(10 * time.Second)
	for !strings.Contains(out.String(), "READY") {
		if time.Now().After(deadline) {
			t.Fatalf("child: %q %q", out, errb)
		}
		time.Sleep(5 * time.Millisecond)
	}
	client := func(uid int) string {
		py := `import socket,sys
s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1])
d=b""
try:
    s.sendall(b"nft_ruleset\n")
    while True:
        b=s.recv(64)
        if not b: break
        d+=b
except OSError:
    pass
print("GOT[%s]" % d.decode().strip())`
		o, err := exec.Command("setpriv", fmt.Sprintf("--reuid=%d", uid), fmt.Sprintf("--regid=%d", uid), "--clear-groups", "python3", "-c", py, path).CombinedOutput() //nolint:gosec // fixed test client
		if err != nil {
			t.Fatalf("client %d: %v %s", uid, err, o)
		}
		s := string(o)
		return s[strings.Index(s, "GOT[")+4 : strings.LastIndex(s, "]")]
	}
	for _, uid := range []int{0, 64991, 998} {
		if got := client(uid); got != "" {
			t.Fatalf("peer uid %d got %q", uid, got)
		}
	}
	if got := client(runnerUID); got != "ok\nserved" {
		t.Fatalf("the runner's uid got %q", got)
	}
}
