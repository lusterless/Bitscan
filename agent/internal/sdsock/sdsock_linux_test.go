// TP-M10-10 (tester-m10): systemd socket activation and the peer check,
// REQ-235 (1), (2), (5), (6); TS §3.7 L281–L283; #130 (j). The listening
// socket is passed to a child copy of this test binary as fd 3, with
// LISTEN_PID set to the child's own pid by an exec wrapper (as systemd
// does). Peers with other uids are run through setpriv. Runs as root in WSL.
package sdsock

import (
	"bytes"
	"errors"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io"
	"io/fs"
	"log/slog"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

// TestSdsockChild is the child side; it does nothing unless SDSOCK_MODE is set.
func TestSdsockChild(t *testing.T) {
	mode := os.Getenv("SDSOCK_MODE")
	if mode == "" {
		return
	}
	uid, _ := strconv.ParseUint(os.Getenv("SDSOCK_UID"), 10, 32)
	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	l, err := FromSystemd(uint32(uid), log)
	if err != nil {
		fmt.Println("REFUSED:", err)
		os.Exit(1)
	}
	switch mode {
	case "accept":
		fmt.Println("READY")
		c, err := l.Accept()
		if err != nil {
			fmt.Println("ACCEPT-ERR", err)
			os.Exit(4)
		}
		_, _ = c.Write([]byte("ok"))
		_ = c.Close()
		fmt.Println("SERVED")
		os.Exit(0)
	case "fdinfo":
		for _, fd := range []string{"3", "4", "5"} {
			b, err := os.ReadFile("/proc/self/fdinfo/" + fd) //nolint:gosec // fixed fd numbers
			if err != nil {
				fmt.Println("FD", fd, "missing")
				continue
			}
			for _, line := range strings.Split(string(b), "\n") {
				if v, ok := strings.CutPrefix(line, "flags:"); ok {
					f, _ := strconv.ParseUint(strings.TrimSpace(v), 8, 64)
					fmt.Printf("FD %s cloexec=%v\n", fd, f&unix.O_CLOEXEC != 0)
				}
			}
		}
		// Every fd above 2 of this process.
		ents, _ := os.ReadDir("/proc/self/fd")
		for _, e := range ents {
			n, _ := strconv.Atoi(e.Name())
			if n <= 2 {
				continue
			}
			fl, err := unix.FcntlInt(uintptr(n), unix.F_GETFD, 0)
			if err == nil && fl&unix.FD_CLOEXEC == 0 {
				fmt.Println("NOCLOEXEC", n)
			}
		}
		out, _ := exec.Command("/bin/sh", "-c", "ls /proc/$$/fd").Output()
		fmt.Printf("CHILDFDS %s\n", strings.Join(strings.Fields(string(out)), ","))
		os.Exit(0)
	}
	os.Exit(5)
}

// lockedBuf is a bytes.Buffer safe to read while exec writes into it.
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

type child struct {
	cmd *exec.Cmd
	out *lockedBuf
	err *lockedBuf
}

// startChild runs this test binary as the child, fds as fd 3, 4, …;
// pidExpr is what LISTEN_PID is set to in the wrapper ("$$" = the child).
func startChild(t *testing.T, mode, uid, pidExpr, listenFDs string, fds ...*os.File) *child {
	t.Helper()
	script := `LISTEN_PID=` + pidExpr + ` exec "$0" -test.run '^TestSdsockChild$' -test.count=1`
	if listenFDs == "unset" {
		script = `LISTEN_PID=` + pidExpr + ` exec env -u LISTEN_FDS "$0" -test.run '^TestSdsockChild$' -test.count=1`
	}
	cmd := exec.Command("/bin/sh", "-c", script, os.Args[0]) //nolint:gosec // the test binary itself
	cmd.Env = append(os.Environ(), "SDSOCK_MODE="+mode, "SDSOCK_UID="+uid)
	if listenFDs != "unset" {
		cmd.Env = append(cmd.Env, "LISTEN_FDS="+listenFDs)
	}
	cmd.ExtraFiles = fds
	c := &child{cmd: cmd, out: &lockedBuf{}, err: &lockedBuf{}}
	cmd.Stdout, cmd.Stderr = c.out, c.err
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = cmd.Process.Kill(); _ = cmd.Wait() })
	return c
}

func (c *child) wait(t *testing.T, d time.Duration) int {
	t.Helper()
	done := make(chan error, 1)
	go func() { done <- c.cmd.Wait() }()
	select {
	case <-done:
		return c.cmd.ProcessState.ExitCode()
	case <-time.After(d):
		_ = c.cmd.Process.Kill()
		t.Fatalf("child did not exit in %v; out %q err %q", d, c.out, c.err)
	}
	return -1
}

func listener(t *testing.T) (string, *os.File) {
	t.Helper()
	dir, err := os.MkdirTemp("", "sdsock-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	if err := os.Chmod(dir, 0o755); err != nil { //nolint:gosec // peers of other uids must reach the socket
		t.Fatal(err)
	}
	path := filepath.Join(dir, "s.sock")
	ln, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	if err := os.Chmod(path, 0o777); err != nil { //nolint:gosec // test socket reachable by any test uid
		t.Fatal(err)
	}
	f, err := ln.(*net.UnixListener).File()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = f.Close() })
	return path, f
}

func waitReady(t *testing.T, c *child) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for !strings.Contains(c.out.String(), "READY") {
		if time.Now().After(deadline) {
			t.Fatalf("child not ready: out %q err %q", c.out, c.err)
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// connectAs connects as uid:gid through setpriv and python3, sends a canary,
// and returns what the server sent back before closing.
func connectAs(t *testing.T, path string, uid, gid int) string {
	t.Helper()
	py := `import socket,sys
s=socket.socket(socket.AF_UNIX)
s.connect(sys.argv[1])
try:
    s.sendall(b"M10CANARY-PEER")
except OSError:
    pass
data=b""
try:
    while True:
        b=s.recv(64)
        if not b: break
        data+=b
except OSError:
    pass
print("GOT[%s]" % data.decode())`
	args := []string{fmt.Sprintf("--reuid=%d", uid), fmt.Sprintf("--regid=%d", gid), "--clear-groups", "python3", "-c", py, path}
	out, err := exec.Command("setpriv", args...).CombinedOutput() //nolint:gosec // fixed test client
	if err != nil {
		t.Fatalf("client as %d:%d: %v %s", uid, gid, err, out)
	}
	s := string(out)
	i, j := strings.Index(s, "GOT["), strings.LastIndex(s, "]")
	if i < 0 || j < i {
		t.Fatalf("client output %q", s)
	}
	return s[i+4 : j]
}

const otherUID, otherGID = 64999, 64999

// CHK-M10-117, -118: REQ-235 (1) the expected uid is served; any other uid
// (0 included) is closed unread with one log line naming the uid; a peer
// with the right gid but another uid is refused (CHK-M10-321).
//
// Root-only (PR #18 CI fix): the peers run as other uids through setpriv.
// Like M4's named euid skips, a non-root run skips it by name; agent.yml's
// root step runs it under sudo and is red unless it passed there.
func TestPeerCheck(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("named skip: needs root to run peers as other uids (setpriv); this row runs in agent.yml's root step and in WSL as root")
	}
	t.Run("expected uid served", func(t *testing.T) {
		path, f := listener(t)
		c := startChild(t, "accept", strconv.Itoa(otherUID), "$$", "1", f)
		waitReady(t, c)
		if got := connectAs(t, path, otherUID, otherGID); got != "ok" {
			t.Fatalf("served %q", got)
		}
		if code := c.wait(t, 10*time.Second); code != 0 || !strings.Contains(c.out.String(), "SERVED") {
			t.Fatalf("exit %d out %q", code, c.out)
		}
	})
	t.Run("root and other uids refused, then the right one served", func(t *testing.T) {
		path, f := listener(t)
		c := startChild(t, "accept", strconv.Itoa(otherUID), "$$", "1", f)
		waitReady(t, c)
		for _, who := range [][2]int{{0, 0}, {64998, 64998}, {64998, otherGID}} {
			if got := connectAs(t, path, who[0], who[1]); got != "" {
				t.Fatalf("peer %v got %q", who, got)
			}
		}
		if got := connectAs(t, path, otherUID, otherGID); got != "ok" {
			t.Fatalf("right peer after refusals got %q", got)
		}
		c.wait(t, 10*time.Second)
		lines := strings.Split(strings.TrimSpace(c.err.String()), "\n")
		if len(lines) != 3 {
			t.Fatalf("%d log lines for 3 refused peers: %q", len(lines), c.err)
		}
		for i, uid := range []string{"uid=0", "uid=64998", "uid=64998"} {
			if !strings.Contains(lines[i], uid) || strings.Contains(lines[i], "CANARY") {
				t.Fatalf("log line %d %q (want %s, no payload)", i, lines[i], uid)
			}
		}
	})
	t.Run("expected uid 0 serves root only", func(t *testing.T) {
		path, f := listener(t)
		c := startChild(t, "accept", "0", "$$", "1", f)
		waitReady(t, c)
		if got := connectAs(t, path, otherUID, 0); got != "" { // gid 0 but uid not 0
			t.Fatalf("uid %d with gid 0 got %q (gid compared?)", otherUID, got)
		}
		if got := connectAs(t, path, 0, 0); got != "ok" {
			t.Fatalf("root got %q", got)
		}
		c.wait(t, 10*time.Second)
	})
}

// CHK-M10-119: REQ-235 (2) start-up refused for every bad LISTEN_* or fd 3.
func TestFromSystemdRefusals(t *testing.T) {
	_, good := listener(t)
	regular, err := os.CreateTemp(t.TempDir(), "reg")
	if err != nil {
		t.Fatal(err)
	}
	dg, err := net.ListenUnixgram("unixgram", &net.UnixAddr{Name: filepath.Join(t.TempDir(), "d.sock"), Net: "unixgram"})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = dg.Close() }()
	dgf, _ := dg.File()
	sfd, err := syscall.Socket(syscall.AF_UNIX, syscall.SOCK_STREAM, 0)
	if err != nil {
		t.Fatal(err)
	}
	notListening := os.NewFile(uintptr(sfd), "stream")
	defer func() { _ = notListening.Close() }()
	tcp, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tcp.Close() }()
	tcpf, _ := tcp.(*net.TCPListener).File()
	cases := []struct {
		name, pid, fds string
		files          []*os.File
		word           string
	}{
		{"LISTEN_PID missing", "", "1", []*os.File{good}, "LISTEN_PID"},
		{"LISTEN_PID foreign", "1", "1", []*os.File{good}, "LISTEN_PID"},
		{"LISTEN_PID parent", "$PPID", "1", []*os.File{good}, "LISTEN_PID"},
		{"LISTEN_FDS 0", "$$", "0", []*os.File{good}, "LISTEN_FDS"},
		{"LISTEN_FDS 2", "$$", "2", []*os.File{good, good}, "LISTEN_FDS"},
		{"LISTEN_FDS unset", "$$", "unset", []*os.File{good}, "LISTEN_FDS"},
		{"fd 3 a regular file", "$$", "1", []*os.File{regular}, "fd 3"},
		{"fd 3 a datagram socket", "$$", "1", []*os.File{dgf}, "fd 3"},
		{"fd 3 a non-listening stream socket", "$$", "1", []*os.File{notListening}, "fd 3"},
		{"fd 3 a TCP listener", "$$", "1", []*os.File{tcpf}, "fd 3"},
		{"no fd 3 at all", "$$", "1", nil, "fd 3"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			ch := startChild(t, "accept", "0", c.pid, c.fds, c.files...)
			code := ch.wait(t, 10*time.Second)
			out := ch.out.String()
			if code != 1 || !strings.Contains(out, "REFUSED:") || !strings.Contains(out, c.word) || strings.Contains(out, "READY") {
				t.Fatalf("exit %d out %q", code, out)
			}
		})
	}
}

// CHK-M10-120: REQ-235 (5) fd 3 and every other inherited fd above 2 carry
// O_CLOEXEC after FromSystemd; a child exec'd afterwards has only 0, 1, 2
// (lead's ruling "TASK-217 fd 3 handling": assert fdinfo/3 as written).
func TestCloexecLinux(t *testing.T) {
	_, f := listener(t)
	extra1, _ := os.CreateTemp(t.TempDir(), "x1")
	extra2, _ := os.CreateTemp(t.TempDir(), "x2")
	c := startChild(t, "fdinfo", "0", "$$", "1", f, extra1, extra2)
	if code := c.wait(t, 10*time.Second); code != 0 {
		t.Fatalf("exit %d out %q err %q", code, c.out, c.err)
	}
	out := c.out.String()
	for _, fd := range []string{"3", "4", "5"} {
		if !strings.Contains(out, "FD "+fd+" cloexec=true") {
			t.Errorf("fd %s not close-on-exec: %q", fd, out)
		}
	}
	if strings.Contains(out, "NOCLOEXEC") {
		t.Errorf("a descriptor above 2 lacks O_CLOEXEC: %q", out)
	}
	if !strings.Contains(out, "CHILDFDS 0,1,2\n") {
		t.Errorf("a child exec'd after FromSystemd sees more than 0, 1, 2: %q", out)
	}
}

// CHK-M10-121: LookupUID without CGO.
func TestLookupUID(t *testing.T) {
	if uid, err := LookupUID("root"); err != nil || uid != 0 {
		t.Fatalf("root: %d %v", uid, err)
	}
	if _, err := LookupUID("no-such-user-m10"); err == nil {
		t.Fatal("unknown user found")
	}
	t.Logf("RECORDED: bitscan-runner → %v", func() string { u, err := LookupUID("bitscan-runner"); return fmt.Sprint(u, err) }())
}

// CHK-M10-122: REQ-235 (6) static: the only net.FileListener in non-test
// agent code is in internal/sdsock/listen_linux.go; no non-test file calls
// net.Listen*, syscall.Socket/Bind/Listen or unix.Socket/Bind/Listen.
func TestNoOtherListenerStatic(t *testing.T) {
	root := filepath.Join("..", "..")
	var fl []string
	err := filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return err
		}
		f, err := parser.ParseFile(token.NewFileSet(), p, nil, 0)
		if err != nil {
			return err
		}
		ast.Inspect(f, func(n ast.Node) bool {
			sel, ok := n.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			x, ok := sel.X.(*ast.Ident)
			if !ok {
				return true
			}
			call := x.Name + "." + sel.Sel.Name
			switch {
			case call == "net.FileListener":
				fl = append(fl, filepath.ToSlash(p))
			case x.Name == "net" && strings.HasPrefix(sel.Sel.Name, "Listen"),
				(x.Name == "syscall" || x.Name == "unix") && (sel.Sel.Name == "Socket" || sel.Sel.Name == "Bind" || sel.Sel.Name == "Listen"):
				t.Errorf("%s calls %s", p, call)
			}
			return true
		})
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(fl) != 1 || !strings.HasSuffix(fl[0], "internal/sdsock/listen_linux.go") {
		t.Fatalf("net.FileListener in %v", fl)
	}
	_ = errors.New
	_ = io.EOF
}
